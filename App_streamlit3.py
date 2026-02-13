import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread
from urllib.parse import quote

# Importa la lógica y constantes del módulo vecino.
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO # Aseguramos las importaciones necesarias
)

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
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]


# --- Funciones Auxiliares para Navegación ---

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


# --- Funciones de Conexión y Persistencia (Google Sheets) ---

@st.cache_resource(ttl=3600)
def get_gspread_client():
    """Establece la conexión con Google Sheets usando variables de secrets separadas."""
    try:
        credentials_dict = {
            "type": "service_account",
            "project_id": st.secrets["gsheets_project_id"],
            "private_key_id": st.secrets["gsheets_private_key_id"],
            "private_key": st.secrets["gsheets_private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["gsheets_client_email"],
            "client_id": st.secrets["gsheets_client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['gsheets_client_email']}",
            "universe_domain": "googleapis.com"
        }

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

        values_to_save = [new_route_data[col] for col in COLUMNS]

        worksheet.append_row(values_to_save)

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
    
    col_left, col_logo, col_right = st.columns([4, 4, 2])
    
    with col_logo:
        st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png",
                 width=450)
    
    st.title("🚚 OPTIMIZATOR📍")
    st.caption("Planificación y división óptima de lotes para vehículos de entrega.")

    st.markdown("---")

    st.header("Selección de Destinos")

    col_input, col_info = st.columns([2, 1])

    with col_input:
        lotes_input = st.text_input(
            "Ingrese los lotes a visitar (separados por coma, ej: A05, B10, C95):",
            placeholder="A05, A10, B05, B10, C95, D01, K01"
        )
    
    with col_info:
        # Solo muestra la capacidad como dato informativo
        st.info("Capacidad Camión 1/2: 17,000 Litros")
        
    st.markdown("---")

    col_map, col_details = st.columns([2, 1])

    all_stops_to_visit = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    num_lotes = len(all_stops_to_visit)

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
            st.map(map_data,
                   latitude='lat',
                   longitude='lon',
                   color='#0044FF',
                   size=10,
                   zoom=10)
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
        
        with st.spinner('Realizando cálculo óptimo de secuencia'):
            try:
                valid_stops = [l for l in all_stops_to_visit if l in COORDENADAS_LOTES]
                
                # LLAMADA A LA FUNCIÓN SIMPLIFICADA (SIN ARGUMENTO max_capacity)
                results = solve_route_optimization(valid_stops)

                if "error" in results:
                    st.error(f"❌ Error en el cálculo: {results['error']}")
                else:
                    # 3. Generar Enlaces Google Maps (Se mantiene)
                    results['ruta_a']['gmaps_link'] = generate_gmaps_link(results['ruta_a']['orden_optimo'])
                    results['ruta_b']['gmaps_link'] = generate_gmaps_link(results['ruta_b']['orden_optimo'])

                    # CREA LA ESTRUCTURA DEL REGISTRO PARA GUARDADO EN SHEETS
                    new_route = {
                        "Fecha": current_time.strftime("%Y-%m-%d"),
                        "Hora": current_time.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(all_stops_to_visit),
                        "Lotes_CamionA": str(results['ruta_a']['lotes_asignados']),
                        "Lotes_CamionB": str(results['ruta_b']['lotes_asignados']), 
                        "Km_CamionA": results['ruta_a']['distancia_km'],
                        "Km_CamionB": results['ruta_b']['distancia_km'],
                    }
                    new_route["Km Totales"] = new_route["Km_CamionA"] + new_route["Km_CamionB"] # Agregado para coincidir con COLUMNS

                    save_new_route_to_sheet(new_route)

                    st.session_state.historial_rutas.append(new_route)
                    st.session_state.results = results
                    st.success("✅ Cálculo finalizado y ruta optimizada. Datos guardados permanentemente en Google Sheets.")

            except Exception as e:
                st.session_state.results = None
                st.error(f"❌ Ocurrió un error inesperado durante el ruteo: {e}")

    # -------------------------------------------------------------------------
    # 2. REPORTE DE RESULTADOS UNIFICADO
    # -------------------------------------------------------------------------

    if st.session_state.results:
        results = st.session_state.results

        # Obtener el valor de demanda de forma segura
        carga_a = results.get('ruta_a', {}).get('demanda_total', 'N/A')
        carga_b = results.get('ruta_b', {}).get('demanda_total', 'N/A')

        st.divider()
        st.header("Análisis de Rutas Generadas")
        st.metric("Distancia Interna de Agrupación (Minimización)", f"{results['agrupacion_distancia_km']:.2f} km")
        
        # MOSTRAR LA CARGA TOTAL (solo informativo)
        st.metric("Carga Total (A/B)", f"{carga_a} / {carga_b} litros", "Capacidad máx. de referencia: 17,000 litros")
        
        st.divider()

        res_a = results.get('ruta_a', {})
        res_b = results.get('ruta_b', {})

        col_a, col_b = st.columns(2)
        
        with col_a:
            st.subheader(f"🚛 Camión 1: {res_a.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Carga Total:** **{carga_a} litros**")
                st.markdown(f"**Total Lotes:** {len(res_a.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_a.get('distancia_km', 'N/A'):.2f} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_a.get('lotes_asignados', []))}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_a.get('orden_optimo', []))} → Ingenio")
                
                st.markdown("---")
                st.link_button(
                    "🚀 INICIAR RUTA CAMIÓN A",
                    res_a.get('gmaps_link', '#'),
                    type="primary",
                    use_container_width=True
                )
                st.link_button("🌐 Ver GeoJSON de Ruta A", res_a.get('geojson_link', '#'), use_container_width=True)
                
        with col_b:
            st.subheader(f"🚚 Camión 2: {res_b.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Carga Total:** **{carga_b} litros**")
                st.markdown(f"**Total Lotes:** {len(res_b.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_b.get('distancia_km', 'N/A'):.2f} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_b.get('lotes_asignados', []) )}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_b.get('orden_optimo', []))} → Ingenio")
                
                st.markdown("---")
                st.link_button(
                    "🚀 INICIAR RUTA CAMIÓN B",
                    res_b.get('gmaps_link', '#'),
                    type="primary",
                    use_container_width=True
                )
                st.link_button("🌐 Ver GeoJSON de Ruta B", res_b.get('geojson_link', '#'), use_container_width=True)
                
        # =============================================================================
        # SECCIÓN DE INSTRUCCIONES PASO A PASO (GUÍA DE DESPACHO)
        # =============================================================================
        st.divider()

        instructions_a = res_a.get('instrucciones', [])
        instructions_b = res_b.get('instrucciones', [])
        
        if instructions_a or instructions_b:
            st.header("📋 Indicaciones Detalladas para el Despacho")
            
            tab_a, tab_b = st.tabs([f"🚛 Camión 1 ({res_a.get('distancia_km', 'N/A'):.2f} km)", f"🚚 Camión 2 ({res_b.get('distancia_km', 'N/A'):.2f} km)"])

            with tab_a:
                if instructions_a:
                    st.subheader("Ruta A (Camión 1)")
                    for i, step in enumerate(instructions_a):
                        distance = f" ({round(step.get('distance', 0) / 1000, 2)} km)" if step.get('distance') else ""
                        st.markdown(f"**{i+1}.** {step.get('text')}{distance}")
                else:
                    st.info("No se asignaron lotes a esta ruta o la API no devolvió instrucciones.")

            with tab_b:
                if instructions_b:
                    st.subheader("Ruta B (Camión 2)")
                    for i, step in enumerate(instructions_b):
                        distance = f" ({round(step.get('distance', 0) / 1000, 2)} km)" if step.get('distance') else ""
                        st.markdown(f"**{i+1}.** {step.get('text')}{distance}")
                else:
                    st.info("No se asignaron lotes a esta ruta o la API no devolvió instrucciones.")
                

    else:
        st.info("El reporte aparecerá aquí después de un cálculo exitoso.")


# =============================================================================
# 3. PÁGINA: HISTORIAL
# =============================================================================

elif page == "Historial":
    st.header("📋 Historial de Rutas Calculadas")

    # Forzamos la recarga de datos al entrar a la página del historial
    st.cache_data.clear()
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
                         "LotesIngresados": "Lotes Ingresados",
                         "Km Totales": st.column_config.NumberColumn("KM Totales", format="%.2f km"),
                     })

    else:
        st.info("No hay rutas guardadas. Realice un cálculo en la página principal.")
        
# =============================================================================
# 4. PÁGINA: ESTADÍSTICAS
# =============================================================================

elif page == "Estadísticas":
    
    st.cache_data.clear() # Asegurar datos frescos
    
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
