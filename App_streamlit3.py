import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread
from urllib.parse import quote

# Importa la lógica y constantes del módulo vecino
# Nota: Se asume que COORDENADAS_LOTES_REVERSO es accesible y mapea (lon, lat) -> Lote
from Routing_logic3 import COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN, COORDENADAS_LOTES_REVERSO

# =============================================================================
# CONFIGURACIÓN INICIAL, ZONA HORARIA Y PERSISTENCIA DE DATOS (GOOGLE SHEETS)
# =============================================================================

st.set_page_config(page_title="Optimizador Bimodal de Rutas", layout="wide")

# --- ZONA HORARIA ARGENTINA (GMT-3) ---
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Ocultar menú de Streamlit y footer
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# Encabezados en el orden de Google Sheets
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB"]


# --- Funciones Auxiliares para Navegación y GEOJSON ---

def generate_gmaps_link(stops_order):
    """
    Genera un enlace de Google Maps para una ruta con múltiples paradas.
    La ruta comienza en el origen (Ingenio) y regresa a él.
    """
    if not stops_order:
        return '#'

    # COORDENADAS_ORIGEN es (lon, lat). GMaps requiere lat,lon.
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    
    route_parts = [f"{lat_orig},{lon_orig}"] # Origen
    
    # Añadir paradas intermedias
    for stop_lote in stops_order:
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            route_parts.append(f"{lat},{lon}") # lat,lon

    # Añadir destino final (regreso al origen)
    route_parts.append(f"{lat_orig},{lon_orig}")

    # Une las partes con '/' para la URL de Google Maps directions
    return f"https://www.google.com/maps/dir/{lat_orig},{lon_orig}/" + "/".join(route_parts[1:])


def generate_geojson(route_name, points_sequence, path_coordinates, total_distance_km):
    """
    Genera el objeto GeoJSON incluyendo los puntos de parada y la traza de la ruta (LineString).
    """
    features = []
    num_points = len(points_sequence)
    
    # =========================================================================
    # 1. GENERAR EL FEATURE DE LA TRAZA (LINESTRING)
    # =========================================================================
    line_feature = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            # Las coordenadas deben ser una lista de [lon, lat]
            "coordinates": path_coordinates 
        },
        "properties": {
            "name": f"Traza Ruta {route_name} ({total_distance_km:.2f} km)",
            "stroke": "#0044FF" if route_name.endswith('A') else "#FF4B4B", # Azul para A, Rojo para B
            "stroke-width": 4,
            "stroke-opacity": 0.7
        }
    }
    features.append(line_feature) # Añadimos la traza primero

    # =========================================================================
    # 2. GENERAR LOS FEATURES DE LOS PUNTOS (POINT)
    # =========================================================================
    
    for i in range(num_points):
        coords = points_sequence[i] # Coordenadas del punto [lon, lat]
        
        # Intentamos obtener el nombre del lote usando el diccionario inverso
        # Usamos una tupla de dos decimales para una clave más robusta
        coord_key = (round(coords[0], 6), round(coords[1], 6))
        
        lote_name = "Ingenio"
        
        # Buscar el nombre del lote en el reverso, ignorando el origen/destino final
        if i > 0 and i < num_points - 1:
            # Buscar el lote correspondiente a esta coordenada.
            # Esto depende de cómo COORDENADAS_LOTES_REVERSO esté definido.
            # Si COORDENADAS_LOTES_REVERSO mapea (lon, lat) -> Lote:
            lote_name = COORDENADAS_LOTES_REVERSO.get(coord_key, "Lote Desconocido")
        
        # Lógica de color y símbolo
        point_type = "PARADA"
        color = "#ffa500" # Naranja para paradas intermedias
        symbol = str(i)
        
        if i == 0:
            point_type = "ORIGEN (Ingenio)"
            color = "#ff0000" # Rojo para origen
            symbol = "star"
        elif i == num_points - 1:
            point_type = "DESTINO FINAL (Ingenio)"
            color = "#008000" # Verde para destino
            symbol = "square"
        
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "name": f"{i} - {point_type} ({lote_name})",
                "marker-color": color,
                "marker-symbol": symbol,
                "order": i
            }
        })
    
    return {"type": "FeatureCollection", "features": features}


def generate_geojson_string(geojson_object):
    """
    Genera la cadena JSON legible de la ruta (ahora con LineString).
    """
    if not geojson_object:
        return None
        
    try:
        # Devuelve el texto JSON indentado para que el usuario pueda copiarlo
        return json.dumps(geojson_object, indent=2)
    except Exception:
        return 'Error de formato en el GeoJSON generado.'

def generate_geojson_io_link(geojson_object):
    """
    Genera el enlace GeoJSON.io codificando el objeto GeoJSON en la URL.
    """
    if not geojson_object or not geojson_object.get('features'):
        return "https://geojson.io/"
        
    try:
        # Compacta el JSON antes de la codificación para reducir la longitud de la URL
        geojson_string = json.dumps(geojson_object, separators=(',', ':'))
        # Usamos quote para codificar el GeoJSON de forma segura en la URL
        encoded_geojson = quote(geojson_string) 
        base_url = "https://geojson.io/#data=data:application/json,"
        return base_url + encoded_geojson
    except Exception:
        return "https://geojson.io/"


# --- Funciones de Conexión y Persistencia (Google Sheets) ---

@st.cache_resource(ttl=3600)
def get_gspread_client():
    """Establece la conexión con Google Sheets usando variables de secrets separadas."""
    try:
        # Crea el diccionario de credenciales a partir de los secrets individuales
        credentials_dict = {
            "type": "service_account",
            "project_id": st.secrets["gsheets_project_id"],
            "private_key_id": st.secrets["gsheets_private_key_id"],
            "private_key": st.secrets["gsheets_private_key"].replace('\\n', '\n'), # Manejo de saltos de línea en la clave
            "client_email": st.secrets["gsheets_client_email"],
            "client_id": st.secrets["gsheets_client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['gsheets_client_email']}",
            "universe_domain": "googleapis.com"
        }

        # Usa service_account_from_dict para autenticar
        gc = gspread.service_account_from_dict(credentials_dict)
        return gc
    except KeyError as e:
        st.error(f"⚠️ Error de Credenciales: Falta la clave '{e}' en Streamlit Secrets. El historial está desactivado.")
        return None
    except Exception as e:
        st.error(f"❌ Error fatal al inicializar la conexión con GSheets: {e}")
        return None

@st.cache_data(ttl=3600)
def get_history_data():
    """Lee el historial de Google Sheets."""
    client = get_gspread_client()
    if not client:
        return pd.DataFrame(columns=COLUMNS)

    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])

        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        # Validación estricta de las columnas requeridas
        required_cols = ["Fecha", "LotesIngresados", "Lotes_CamionA", "Km_CamionA"]
        if not all(col in df.columns for col in required_cols):
             missing_cols = [col for col in required_cols if col not in df.columns]
             st.warning(f"⚠️ Error en Historial: Faltan las columnas necesarias en Google Sheets. Faltan: {', '.join(missing_cols)}. Verifique la primera fila.")
             return pd.DataFrame(columns=COLUMNS)
        
        if df.empty or len(df.columns) < len(COLUMNS):
            return pd.DataFrame(columns=COLUMNS)
        return df

    except Exception as e:
        st.error(f"❌ Error al cargar datos de Google Sheets. Asegure permisos para {st.secrets['gsheets_client_email']}: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    """Escribe una nueva ruta a Google Sheets."""
    client = get_gspread_client()
    if not client:
        st.warning("No se pudo guardar la ruta por fallo de conexión a Google Sheets.")
        return

    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])

        # gspread necesita una lista de valores en el orden de las COLUMNS
        values_to_save = [new_route_data[col] for col in COLUMNS]

        # Añade la fila al final de la hoja
        worksheet.append_row(values_to_save)

        # Invalida la caché para que la próxima lectura traiga el dato nuevo
        st.cache_data.clear()

    except Exception as e:
        st.error(f"❌ Error al guardar datos en Google Sheets. Verifique que la Fila 1 tenga 7 columnas: {e}")


# --- Funciones de Estadística ---

def calculate_statistics(df):
    """Calcula estadísticas diarias y mensuales a partir del historial."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 1. Preparación de datos
    df['Fecha'] = pd.to_datetime(df['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M')

    def count_total_lotes_input(lotes_str):
        if not lotes_str or pd.isna(lotes_str):
            return 0
        return len([l.strip() for l in lotes_str.split(',') if l.strip()])

    def count_assigned_lotes(lotes_str):
        if not lotes_str or pd.isna(lotes_str) or lotes_str.strip() == '[]':
            return 0
        try:
            lotes_list = [l.strip() for l in lotes_str.strip('[]').replace("'", "").replace('"', '').replace(" ", "").split(',') if l.strip()]
            return len(lotes_list)
        except:
            return 0

    df['Total_Lotes_Ingresados'] = df['LotesIngresados'].apply(count_total_lotes_input)
    df['Lotes_CamionA_Count'] = df['Lotes_CamionA'].apply(count_assigned_lotes)
    df['Lotes_CamionB_Count'] = df['Lotes_CamionB'].apply(count_assigned_lotes)
    df['Total_Lotes_Asignados'] = df['Lotes_CamionA_Count'] + df['Lotes_CamionB_Count']
    # Aseguramos que las columnas de KM sean numéricas, si GSheets las ha interpretado como string
    df['Km_CamionA'] = pd.to_numeric(df['Km_CamionA'], errors='coerce').fillna(0)
    df['Km_CamionB'] = pd.to_numeric(df['Km_CamionB'], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']


    # 2. Agregación Diaria
    daily_stats = df.groupby('Fecha').agg(
        Rutas_Total=('Fecha', 'count'),
        Lotes_Ingresados_Total=('Total_Lotes_Ingresados', 'sum'),
        Lotes_Asignados_Total=('Total_Lotes_Asignados', 'sum'),
        Km_CamionA_Total=('Km_CamionA', 'sum'),
        Km_CamionB_Total=('Km_CamionB', 'sum'),
        Km_Total=('Km_Total', 'sum'),
    ).reset_index()
    daily_stats['Fecha_str'] = daily_stats['Fecha'].dt.strftime('%Y-%m-%d')
    daily_stats['Km_Promedio_Ruta'] = daily_stats['Km_Total'] / daily_stats['Rutas_Total']
    
    # 3. Agregación Mensual
    monthly_stats = df.groupby('Mes').agg(
        Rutas_Total=('Fecha', 'count'),
        Lotes_Ingresados_Total=('Total_Lotes_Ingresados', 'sum'),
        Lotes_Asignados_Total=('Total_Lotes_Asignados', 'sum'),
        Km_CamionA_Total=('Km_CamionA', 'sum'),
        Km_CamionB_Total=('Km_CamionB', 'sum'),
        Km_Total=('Km_Total', 'sum'),
    ).reset_index()
    monthly_stats['Mes_str'] = monthly_stats['Mes'].astype(str)
    monthly_stats['Km_Promedio_Ruta'] = monthly_stats['Km_Total'] / monthly_stats['Rutas_Total']

    return daily_stats, monthly_stats


# -------------------------------------------------------------------------
# INICIALIZACIÓN DE LA SESIÓN
# -------------------------------------------------------------------------

# Inicializar el estado de la sesión para guardar el historial PERMANENTE
if 'historial_cargado' not in st.session_state:
    st.cache_data.clear()
    df_history = get_history_data()
    st.session_state.historial_rutas = df_history.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

# =============================================================================
# ESTRUCTURA DEL MENÚ LATERAL Y NAVEGACIÓN
# =============================================================================

st.sidebar.title("Menú Principal")
page = st.sidebar.radio(
    "Seleccione una opción:",
    ["Calcular Nueva Ruta", "Historial", "Estadísticas"]
)
st.sidebar.divider()
st.sidebar.info(f"Rutas Guardadas: {len(st.session_state.historial_rutas)}")

# =============================================================================
# 1. PÁGINA: CALCULAR NUEVA RUTA (PÁGINA PRINCIPAL)
# =============================================================================

if page == "Calcular Nueva Ruta":
    
    # --- LOGO CENTRADO Y AJUSTES ---
    col_left, col_logo, col_right = st.columns([4, 4, 2]) 
    
    with col_logo:
        st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", 
                 width=450)
    
    # Títulos debajo del logo
    st.title("🚚 OPTIMIZATOR📍")
    st.caption("Planificación y división óptima de lotes para vehículos de entrega.")

    st.markdown("---")
    # ---------------------------------------------------

    st.header("Selección de Destinos")

    lotes_input = st.text_input(
        "Ingrese los lotes a visitar (separados por coma, ej: A05, B10, C95):",
        placeholder="A05, A10, B05, B10, C95, D01, K01"
    )

    col_map, col_details = st.columns([2, 1])

    all_stops_to_visit = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    num_lotes = len(all_stops_to_visit)

    # Lógica de pre-visualización y mapa...
    map_data_list = []
    map_data_list.append({'name': 'INGENIO (Origen)', 'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0]})

    valid_stops_count = 0
    invalid_stops = [l for l in all_stops_to_visit if l not in COORDENADAS_LOTES]

    for lote in all_stops_to_visit:
        if lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[lote]
            map_data_list.append({'name': lote, 'lat': lat, 'lon': lon})
            valid_stops_count += 1

    map_data = pd.DataFrame(map_data_list)

    with col_map:
        if valid_stops_count > 0:
            st.subheader(f"Mapa de {valid_stops_count} Destinos")
            # Calcula el centro del mapa para un zoom inicial adecuado
            center_lat = map_data['lat'].mean()
            center_lon = map_data['lon'].mean()
            
            st.map(map_data, 
                   latitude='lat', 
                   longitude='lon', 
                   color='#0044FF', 
                   size=10, 
                   zoom=10) # Zoom ajustado
        else:
            st.info("Ingrese lotes válidos para ver la previsualización del mapa.")

    with col_details:
        st.subheader("Estado de la Selección")
        st.metric("Total Lotes Ingresados", num_lotes)

        if invalid_stops:
            st.error(f"❌ {len(invalid_stops)} Lotes Inválidos: {', '.join(invalid_stops)}.")

        MIN_LOTES = 3
        MAX_LOTES = 7

        if valid_stops_count < MIN_LOTES or valid_stops_count > MAX_LOTES:
            st.warning(f"⚠️ Debe ingresar entre {MIN_LOTES} y {MAX_LOTES} lotes válidos. Ingresó {valid_stops_count}.")
            calculate_disabled = True
        elif valid_stops_count > 0:
            calculate_disabled = False
        else:
            calculate_disabled = True

    # -------------------------------------------------------------------------
    # 🛑 BOTÓN DE CÁLCULO Y LÓGICA
    # -------------------------------------------------------------------------
    st.divider()

    if st.button("🚀 Calcular Rutas Óptimas", key="calc_btn_main", type="primary", disabled=calculate_disabled):

        st.session_state.results = None
        current_time = datetime.now(ARG_TZ) 

        with st.spinner('Realizando cálculo óptimo y agrupando rutas'):
            try:
                # La lista de paradas a visitar debe ser solo la lista de lotes válidos
                valid_stops = [l for l in all_stops_to_visit if l in COORDENADAS_LOTES]
                
                # Ejecutar la lógica de ruteo
                results = solve_route_optimization(valid_stops)

                if "error" in results:
                    st.error(f"❌ Error en la API de Ruteo: {results['error']}")
                else:
                    # --- PREPARACIÓN DE DATOS PARA GEOJSON (SECUENCIA COMPLETA DE COORDENADAS) ---
                    # path_coordinates_a/b es la secuencia completa de [lon, lat] incluyendo Origen y Destino final (Ingenio)
                    path_coordinates_a = [COORDENADAS_ORIGEN] + [COORDENADAS_LOTES[l] for l in results['ruta_a']['orden_optimo']] + [COORDENADAS_ORIGEN]
                    path_coordinates_b = [COORDENADAS_ORIGEN] + [COORDENADAS_LOTES[l] for l in results['ruta_b']['orden_optimo']] + [COORDENADAS_ORIGEN]
                    
                    # 1. Generar Objeto GeoJSON (AHORA CON TRAZA)
                    geojson_a = generate_geojson("Camión A", path_coordinates_a, path_coordinates_a, results['ruta_a']['distancia_km'])
                    geojson_b = generate_geojson("Camión B", path_coordinates_b, path_coordinates_b, results['ruta_b']['distancia_km'])

                    # 2. Generar Enlaces GeoJSON.io (CODIFICADO)
                    results['ruta_a']['geojson_link'] = generate_geojson_io_link(geojson_a)
                    results['ruta_b']['geojson_link'] = generate_geojson_io_link(geojson_b)
                    
                    # 3. Generar Enlaces Google Maps
                    results['ruta_a']['gmaps_link'] = generate_gmaps_link(results['ruta_a']['orden_optimo'])
                    results['ruta_b']['gmaps_link'] = generate_gmaps_link(results['ruta_b']['orden_optimo'])

                    # ✅ CREA LA ESTRUCTURA DEL REGISTRO PARA GUARDADO EN SHEETS
                    new_route = {
                        "Fecha": current_time.strftime("%Y-%m-%d"),
                        "Hora": current_time.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(all_stops_to_visit),
                        "Lotes_CamionA": str(results['ruta_a']['lotes_asignados']),
                        "Lotes_CamionB": str(results['ruta_b']['lotes_asignados']),
                        "Km_CamionA": results['ruta_a']['distancia_km'],
                        "Km_CamionB": results['ruta_b']['distancia_km'],
                    }

                    # 🚀 GUARDA PERMANENTEMENTE EN GOOGLE SHEETS
                    save_new_route_to_sheet(new_route)

                    # ACTUALIZA EL ESTADO DE LA SESIÓN
                    st.session_state.historial_rutas.append(new_route)
                    st.session_state.results = results
                    st.success("✅ Cálculo finalizado y rutas optimizadas. Datos guardados permanentemente en Google Sheets.")

            except Exception as e:
                st.session_state.results = None
                st.error(f"❌ Ocurrió un error inesperado durante el ruteo: {e}")

    # -------------------------------------------------------------------------
    # 2. REPORTE DE RESULTADOS UNIFICADO
    # -------------------------------------------------------------------------

    if st.session_state.results:
        results = st.session_state.results

        st.divider()
        st.header("Análisis de Rutas Generadas")
        st.metric("Distancia Interna de Agrupación (Minimización)", f"{results['agrupacion_distancia_km']:.2f} km")
        st.divider()

        res_a = results.get('ruta_a', {})
        res_b = results.get('ruta_b', {})

        col_a, col_b = st.columns(2)
        
        with col_a:
            st.subheader(f"🚛 Camión 1: {res_a.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Total Lotes:** {len(res_a.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_a.get('distancia_km', 'N/A'):.2f} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_a.get('lotes_asignados', []))}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_a.get('orden_optimo', []))} → Ingenio")
                
                # Botón principal INICIAR RUTA
                st.markdown("---")
                st.link_button(
                    "🚀 INICIAR RUTA CAMIÓN A (GMaps)", 
                    res_a.get('gmaps_link', '#'),
                    type="primary", 
                    use_container_width=True
                )
                # Muestra el GEOJSON como enlace (reinsertado)
                st.link_button("🌐 Ver GeoJSON de Ruta A (Traza)", res_a.get('geojson_link', '#'), use_container_width=True)
                
        with col_b:
            st.subheader(f"🚚 Camión 2: {res_b.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Total Lotes:** {len(res_b.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_b.get('distancia_km', 'N/A'):.2f} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_b.get('lotes_asignados', []) )}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_b.get('orden_optimo', []))} → Ingenio")
                
                # Botón principal INICIAR RUTA
                st.markdown("---")
                st.link_button(
                    "🚀 INICIAR RUTA CAMIÓN B (GMaps)", 
                    res_b.get('gmaps_link', '#'),
                    type="primary", 
                    use_container_width=True
                )
                # Muestra el GEOJSON como enlace (reinsertado)
                st.link_button("🌐 Ver GeoJSON de Ruta B (Traza)", res_b.get('geojson_link', '#'), use_container_width=True)

    else:
        st.info("El reporte aparecerá aquí después de un cálculo exitoso.")


# =============================================================================
# 3. PÁGINA: HISTORIAL
# =============================================================================

elif page == "Historial":
    st.header("📋 Historial de Rutas Calculadas")

    df_historial = get_history_data()
    st.session_state.historial_rutas = df_historial.to_dict('records')

    if not df_historial.empty:
        st.subheader(f"Total de {len(df_historial)} Rutas Guardadas")

        st.dataframe(df_historial,
                      use_container_width=True,
                      column_config={
                          "Km_CamionA": st.column_config.NumberColumn("KM Camión A", format="%.2f km"),
                          "Km_CamionB": st.column_config.NumberColumn("KM Camión B", format="%.2f km"),
                          "Lotes_CamionA": "Lotes Camión A",
                          "Lotes_CamionB": "Lotes Camión B",
                          "Fecha": "Fecha",
                          "Hora": "Hora de Carga",
                          "LotesIngresados": "Lotes Ingresados"
                      })

    else:
        st.info("No hay rutas guardadas. Realice un cálculo en la página principal.")
        
# =============================================================================
# 4. PÁGINA: ESTADÍSTICAS
# =============================================================================

elif page == "Estadísticas":
    
    st.cache_data.clear()
    
    st.header("📊 Estadísticas de Ruteo")
    st.caption("Análisis diario y mensual de la actividad de optimización.")

    df_historial = get_history_data()

    if df_historial.empty:
        st.info("No hay datos en el historial para generar estadísticas.")
    else:
        daily_stats, monthly_stats = calculate_statistics(df_historial)

        # -----------------------------------------------------
        # Estadísticas Diarias
        # -----------------------------------------------------
        st.subheader("Resumen Diario")
        if not daily_stats.empty:
            
            columns_to_show = {
                'Fecha_str': 'Fecha',
                'Rutas_Total': 'Rutas Calculadas',
                'Lotes_Asignados_Total': 'Lotes Asignados',
                'Km_CamionA_Total': 'KM Camión A',
                'Km_CamionB_Total': 'KM Camión B',
                'Km_Total': 'KM Totales',
                'Km_Promedio_Ruta': 'KM Promedio por Ruta'
            }

            st.dataframe(
                daily_stats[list(columns_to_show.keys())].rename(columns=columns_to_show),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'KM Camión A': st.column_config.NumberColumn("KM Camión A", format="%.2f km"),
                    'KM Camión B': st.column_config.NumberColumn("KM Camión B", format="%.2f km"),
                    'KM Totales': st.column_config.NumberColumn("KM Totales", format="%.2f km"),
                    'KM Promedio por Ruta': st.column_config.NumberColumn("KM Promedio/Ruta", format="%.2f km"),
                }
            )
            
            st.markdown("##### Kilómetros Totales Recorridos por Día")
            st.bar_chart(
                daily_stats,
                x='Fecha_str',
                y=['Km_CamionA_Total', 'Km_CamionB_Total'],
                color=['#0044FF', '#FF4B4B']
            )

        # -----------------------------------------------------
        # Estadísticas Mensuales
        # -----------------------------------------------------
        st.subheader("Resumen Mensual")
        if not monthly_stats.empty:
            
            columns_to_show = {
                'Mes_str': 'Mes',
                'Rutas_Total': 'Rutas Calculadas',
                'Lotes_Asignados_Total': 'Lotes Asignados',
                'Km_CamionA_Total': 'KM Camión A',
                'Km_CamionB_Total': 'KM Camión B',
                'Km_Total': 'KM Totales',
                'Km_Promedio_Ruta': 'KM Promedio por Ruta'
            }

            st.dataframe(
                monthly_stats[list(columns_to_show.keys())].rename(columns=columns_to_show),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'KM Camión A': st.column_config.NumberColumn("KM Camión A", format="%.2f km"),
                    'KM Camión B': st.column_config.NumberColumn("KM Camión B", format="%.2f km"),
                    'KM Totales': st.column_config.NumberColumn("KM Totales", format="%.2f km"),
                    'KM Promedio por Ruta': st.column_config.NumberColumn("KM Promedio/Ruta", format="%.2f km"),
                }
            )
        st.divider()
        st.caption("Nota: Los KM Totales/Promedio se calculan usando la suma de las distancias optimizadas de cada camión.")
