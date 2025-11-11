import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread
import folium # ¡Necesario para mapas interactivos!
from streamlit_folium import folium_static # Función de Streamlit para renderizar Folium
from streamlit.components.v1 import html # Necesario para renderizar componentes HTML/JS
import requests # ¡NUEVO! Necesario para hacer llamadas a APIs externas (como Praxys)

# Importa la lógica y constantes del módulo vecino (Asegúrate que se llama 'routing_logic.py')
from Routing_logic3 import COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN

# =============================================================================
# CONFIGURACIÓN INICIAL, ZONA HORARIA Y PERSISTENCIA DE DATOS (GOOGLE SHEETS)
# =============================================================================

st.set_page_config(page_title="Optimizador Bimodal de Rutas", layout="wide")

# --- ZONA HORARIA ARGENTINA (GMT-3) ---
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires") # Define la zona horaria de Buenos Aires

# Ocultar menú de Streamlit y footer
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# Encabezados en el orden de Google Sheets
COLUMNS = ["Fecha", "Hora", "Lotes_ingresados", "Lotes_CamionA", "Lotes_CamionB", "KmRecorridos_CamionA", "KmRecorridos_CamionB"]


# --- Funciones Auxiliares para Navegación y Mapas ---

def generate_gmaps_link(stops_order, full_route=True):
    """
    Genera enlaces de Google Maps.
    Si full_route=True, usa el formato /dir/ para ruta completa (con waypoints).
    Si full_route=False, usa el formato /search/?query= para iniciar navegación al destino final.
    """
    if not stops_order:
        return '#'

    # COORDENADAS_ORIGEN es (lon, lat). GMaps requiere lat,lon.
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    
    # 1. ENLACE DE RUTA COMPLETA (DIR: Para previsualización)
    if full_route:
        
        # Origen (lat,lon)
        route_parts = [f"{lat_orig},{lon_orig}"] 
        
        # Puntos intermedios (Paradas optimizadas)
        for stop_lote in stops_order:
            if stop_lote in COORDENADAS_LOTES:
                lon, lat = COORDENADAS_LOTES[stop_lote]
                route_parts.append(f"{lat},{lon}") # lat,lon

        # Destino final (Volver al Ingenio)
        route_parts.append(f"{lat_orig},{lon_orig}")

        # Une las partes con '/' para la URL de Google Maps directions (dir/Start/Waypoint1/Waypoint2/End)
        return "https://www.google.com/maps/dir/" + "/".join(route_parts)

    # 2. ENLACE DE NAVEGACIÓN SIMPLE (SEARCH/QUERY: Para acción inmediata al último destino)
    else:
        # Obtiene el último punto de parada optimizada
        last_stop_lote = stops_order[-1]
        if last_stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[last_stop_lote]
            # Formato de búsqueda que suele activar la navegación más fácilmente:
            return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        return '#'

def generate_waze_link(stops_order):
    """
    Genera un enlace de Waze para navegar al primer destino de la ruta.
    """
    if not stops_order:
        return '#'

    first_stop_lote = stops_order[0]
    if first_stop_lote in COORDENADAS_LOTES:
        lon, lat = COORDENADAS_LOTES[first_stop_lote]
        # URL de Waze para navegar a una latitud, longitud específica
        return f"https://waze.com/ul?ll={lat},{lon}&navigate=yes"
    return '#'


def generate_csv_of_points(stops_order, route_name):
    """
    Genera un string CSV con el Lote, Latitud y Longitud de cada parada.
    """
    data = []
    # Incluimos el origen al inicio
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    data.append({'ID': 'INGENIO', 'LATITUD': lat_orig, 'LONGITUD': lon_orig, 'ORDEN': 0})
    
    # Incluimos el resto de las paradas
    for i, stop_lote in enumerate(stops_order):
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            data.append({'ID': stop_lote, 'LATITUD': lat, 'LONGITUD': lon, 'ORDEN': i + 1})
            
    df = pd.DataFrame(data)
    # Devolvemos el CSV como una cadena de texto, sin el índice de pandas
    return df.to_csv(index=False).encode('utf-8')

def generate_gpx_of_route(stops_order, route_name):
    """
    Genera un string GPX (XML) con los puntos de la ruta como un Track Segment.
    """
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    
    # Inicia el contenido GPX (header)
    gpx_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    gpx_content += '<gpx version="1.1" creator="Optimizator App" xmlns="http://www.topografix.com/GPX/1/1">\n'
    gpx_content += f'<trk><name>{route_name}</name><trkseg>\n'

    # Punto de Origen (Ingenio)
    gpx_content += f'<trkpt lat="{lat_orig}" lon="{lon_orig}"><name>INGENIO (Origen)</name></trkpt>\n'
    
    # Puntos de Parada optimizados
    for i, stop_lote in enumerate(stops_order):
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            gpx_content += f'<trkpt lat="{lat}" lon="{lon}"><name>{stop_lote}</name></trkpt>\n'
            
    # Punto de Destino Final (Regreso al Ingenio)
    gpx_content += f'<trkpt lat="{lat_orig}" lon="{lon_orig}"><name>INGENIO (Final)</name></trkpt>\n'
    
    # Cierra el contenido GPX
    gpx_content += '</trkseg></trk>\n'
    gpx_content += '</gpx>'
    
    return gpx_content.encode('utf-8')

def fetch_praxys_location(camion_id):
    """
    [FUNCIÓN CONCEPTUAL] Intenta obtener la última ubicación de Praxys API.
    
    **¡ADVERTENCIA!** Debe reemplazar la URL, el token y el formato de la respuesta.
    """
    
    # 1. Obtener ID del vehículo (Patente, IMEI, etc.)
    # Aquí usaríamos VEHICLES[camion_id] si tuviéramos un mapeo de patentes a ID de Praxys.
    # Usaremos un placeholder que usted debe reemplazar.
    VEHICLE_TRACKING_ID = "12345" # <--- REEMPLAZAR con el ID de rastreo real del camión A o B
    
    # 2. Configurar el endpoint y la autenticación
    # Deberías guardar tu API Key y URL en Streamlit Secrets.
    API_URL = "https://api.praxys.com/v1/vehicles" # <--- REEMPLAZAR por la URL real de Praxys
    HEADERS = {
        "Authorization": f"Bearer {st.secrets.get('PRAXYS_API_TOKEN', 'YOUR_TOKEN_HERE')}",
        "Content-Type": "application/json"
    }
    
    # 3. Construir la URL de la consulta (ejemplo: filtrando por ID)
    full_url = f"{API_URL}?id={VEHICLE_TRACKING_ID}" # <--- REEMPLAZAR con el parámetro de consulta correcto

    try:
        response = requests.get(full_url, headers=HEADERS, timeout=5)
        response.raise_for_status() # Lanza error si la respuesta es 4xx o 5xx
        data = response.json()
        
        # 4. PARSEAR LA RESPUESTA
        # El formato de respuesta depende 100% de Praxys. Debe inspeccionar el JSON.
        
        # Ejemplo: asumiendo que la respuesta es una lista y tomamos el primer resultado
        if data and isinstance(data, list) and data[0]:
            # REEMPLAZAR con las claves correctas de latitud y longitud en el JSON de Praxys
            lat = data[0].get('latitude') 
            lon = data[0].get('longitude')
            
            if lat is not None and lon is not None:
                return float(lat), float(lon)
                
        st.warning(f"Praxys API devolvió datos, pero no se pudo parsear lat/lon para Camión {camion_id}.")
        return None, None

    except requests.exceptions.RequestException as e:
        st.error(f"Error de conexión con Praxys API para Camión {camion_id}: {e}")
        return None, None
    except Exception as e:
        st.error(f"Error inesperado al procesar la respuesta de Praxys: {e}")
        return None, None


def get_live_location_for_camion(camion_id):
    """
    Determina si usar la simulación o la conexión real a Praxys.
    """
    
    # Si desea usar la conexión REAL, descomente estas líneas:
    # live_lat, live_lon = fetch_praxys_location(camion_id)
    # if live_lat is not None and live_lon is not None:
    #     return live_lat, live_lon
    
    # --------------------------------------------------------------------------
    # CÓDIGO DE SIMULACIÓN (Mantenido como fallback o si la conexión real falla)
    # --------------------------------------------------------------------------
    
    if camion_id == 'A':
        if 'camion_a_step' not in st.session_state:
            st.session_state.camion_a_step = 0
            
        # Simula el movimiento aumentando la latitud y longitud ligeramente
        lon_orig, lat_orig = COORDENADAS_ORIGEN
        
        # Simula un movimiento diagonal simple partiendo del origen
        lat = lat_orig + (st.session_state.camion_a_step * 0.0001)
        lon = lon_orig + (st.session_state.camion_a_step * 0.0001)
        
        # Incrementa el paso para el próximo ciclo
        st.session_state.camion_a_step = (st.session_state.camion_a_step + 1) % 100 # Resetea después de 100 pasos
        
        return lat, lon
    
    # Si no hay rastreo activo, devuelve una posición estática para B
    if camion_id == 'B':
        if 'camion_b_step' not in st.session_state:
            st.session_state.camion_b_step = 0
        
        lon_orig, lat_orig = COORDENADAS_ORIGEN
        
        # Simula un movimiento diferente para B
        lat = lat_orig - (st.session_state.camion_b_step * 0.00005)
        lon = lon_orig + (st.session_state.camion_b_step * 0.0001)
        
        st.session_state.camion_b_step = (st.session_state.camion_b_step + 1) % 100
        
        return lat, lon 

    return None, None

def render_interactive_route_map(route_results, route_name, live_lat=None, live_lon=None):
    """
    Crea y renderiza un mapa interactivo (Folium) con la línea de la ruta, marcadores y
    la ubicación en vivo del camión.
    """
    # Usamos el punto de origen como centro inicial
    center_lat, center_lon = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    
    # Crea el mapa base
    m = folium.Map(location=[center_lat, center_lon], zoom_start=11)
    
    # 1. Dibuja la línea de la ruta (si GeoJSON está disponible)
    geojson_data = route_results.get('geojson')
    if geojson_data:
        try:
            # Añade la geometría de la ruta al mapa
            folium.GeoJson(
                geojson_data,
                name=f'{route_name} - Ruta Optimizada',
                style_function=lambda x: {'color': '#FF0000', 'weight': 5, 'opacity': 0.7}
            ).add_to(m)
        except Exception as e:
            # Desactivado para evitar errores si el GeoJSON es incorrecto
            pass

    # 2. Añade los marcadores de las paradas (Ingenio + Lotes)
    stops_order = route_results.get('orden_optimo', [])
    
    # Marcador de Origen
    folium.Marker(
        [center_lat, center_lon],
        popup='Ingenio (Origen/Destino)',
        icon=folium.Icon(color='green', icon='home', prefix='fa')
    ).add_to(m)

    # Marcadores de Paradas
    for i, stop_lote in enumerate(stops_order):
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            # Usamos un círculo para los lotes para diferenciarlos del camión
            folium.CircleMarker(
                [lat, lon],
                radius=8,
                color='blue',
                fill=True,
                fill_color='#007bff',
                popup=f'Parada {i+1}: {stop_lote}'
            ).add_to(m)
            
            # Etiqueta con el número de orden
            folium.map.Marker(
                [lat, lon],
                icon=folium.DivIcon(
                    icon_size=(20,20),
                    icon_anchor=(0,0),
                    html=f'<div style="font-size: 12pt; font-weight: bold; color: white; background-color: #007bff; border-radius: 50%; width: 20px; height: 20px; text-align: center; line-height: 20px;">{i+1}</div>',
                    )
            ).add_to(m)
            
    # 3. Marcador de Posición en Vivo (REAL)
    if live_lat is not None and live_lon is not None:
        folium.Marker(
            [live_lat, live_lon],
            popup=f'{route_name} - Ubicación Actual',
            tooltip='Ubicación Actual (LIVE)',
            icon=folium.Icon(color='red', icon='truck', prefix='fa')
        ).add_to(m)
        
    # Ajusta el zoom para que se vean todos los elementos
    m.fit_bounds(m.get_bounds())
    
    # Renderiza el mapa en Streamlit
    folium_static(m, width=900, height=500)
    
    # Muestra el orden de la ruta
    st.markdown(f"**Orden de Entrega:** Ingenio → {' → '.join(stops_order)} → Ingenio")


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
            "private_key": st.secrets["gsheets_private_key"],
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

        # Validación: si el DF está vacío o las columnas no coinciden con las 7 esperadas, se usa el DF vacío.
        if df.empty or len(df.columns) < len(COLUMNS):
            return pd.DataFrame(columns=COLUMNS)
        return df

    except Exception as e:
        # Puede fallar si la hoja no está compartida
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
        # El orden es crucial: [Fecha, Hora, Lotes_ingresados, ...]
        values_to_save = [new_route_data[col] for col in COLUMNS]

        # Añade la fila al final de la hoja
        worksheet.append_row(values_to_save)

        # Invalida la caché para que la próxima lectura traiga el dato nuevo
        st.cache_data.clear()

    except Exception as e:
        st.error(f"❌ Error al guardar datos en Google Sheets. Verifique que la Fila 1 tenga 7 columnas: {e}")


# -------------------------------------------------------------------------
# INICIALIZACIÓN DE LA SESIÓN
# -------------------------------------------------------------------------

# Inicializar el estado de la sesión para guardar el historial PERMANENTE
if 'historial_cargado' not in st.session_state:
    df_history = get_history_data() # Ahora carga de Google Sheets
    # Convertimos el DataFrame a lista de diccionarios para la sesión
    st.session_state.historial_rutas = df_history.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

# Inicializar estado para el rastreo en vivo simulado
if 'is_tracking_A' not in st.session_state:
    st.session_state.is_tracking_A = False
if 'is_tracking_B' not in st.session_state:
    st.session_state.is_tracking_B = False

# =============================================================================
# ESTRUCTURA DEL MENÚ LATERAL Y NAVEGACIÓN
# =============================================================================

st.sidebar.title("Menú Principal")
page = st.sidebar.radio(
    "Seleccione una opción:",
    ["Calcular Nueva Ruta", "Historial"]
)
st.sidebar.divider()
st.sidebar.info(f"Rutas Guardadas: {len(st.session_state.historial_rutas)}")

# =============================================================================
# 1. PÁGINA: CALCULAR NUEVA RUTA (PÁGINA PRINCIPAL)
# =============================================================================

if page == "Calcular Nueva Ruta":
    st.title("🚚 Optimizator📍")
    st.caption("Planificación y división óptima de lotes para vehículos de entrega.")

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
            st.map(map_data, latitude='lat', longitude='lon', color='#0044FF', size=10, zoom=10)
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
        # 👇 Captura la fecha y hora con la zona horaria argentina
        current_time = datetime.now(ARG_TZ) 

        with st.spinner('Realizando cálculo óptimo y agrupando rutas'):
            try:
                # Asumiendo que solve_route_optimization devuelve el GeoJSON en 'geojson'
                results = solve_route_optimization(all_stops_to_visit)

                if "error" in results:
                    st.error(f"❌ Error en la API de Ruteo: {results['error']}")
                else:
                    # ✅ GENERACIÓN DE ENLACES DE NAVEGACIÓN
                    # Ruta A
                    # Genera el enlace de ruta completa (con waypoints)
                    results['ruta_a']['gmaps_link_full'] = generate_gmaps_link(results['ruta_a']['orden_optimo'], full_route=True)
                    # Genera el enlace de inicio rápido (solo destino final)
                    results['ruta_a']['gmaps_link_simple'] = generate_gmaps_link(results['ruta_a']['orden_optimo'], full_route=False)
                    results['ruta_a']['waze_link'] = generate_waze_link(results['ruta_a']['orden_optimo']) 
                    
                    # Ruta B
                    # Genera el enlace de ruta completa (con waypoints)
                    results['ruta_b']['gmaps_link_full'] = generate_gmaps_link(results['ruta_b']['orden_optimo'], full_route=True)
                    # Genera el enlace de inicio rápido (solo destino final)
                    results['ruta_b']['gmaps_link_simple'] = generate_gmaps_link(results['ruta_b']['orden_optimo'], full_route=False)
                    results['ruta_b']['waze_link'] = generate_waze_link(results['ruta_b']['orden_optimo']) 

                    # ✅ CREA LA ESTRUCTURA DEL REGISTRO PARA GUARDADO EN SHEETS
                    new_route = {
                        "Fecha": current_time.strftime("%Y-%m-%d"),
                        "Hora": current_time.strftime("%H:%M:%S"), # << Usa la hora ya en la zona horaria correcta
                        "Lotes_ingresados": ", ".join(all_stops_to_visit),
                        "Lotes_CamionA": str(results['ruta_a']['lotes_asignados']), # Guardar como string
                        "Lotes_CamionB": str(results['ruta_b']['lotes_asignados']), # Guardar como string
                        "KmRecorridos_CamionA": results['ruta_a']['distancia_km'],
                        "KmRecorridos_CamionB": results['ruta_b']['distancia_km'],
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
    
    # --- Lógica de Bucle de Rastreo en Vivo ---
    
    # Si el rastreo está activo en cualquier camión, pausa por 3s y fuerza la recarga (rerun)
    if st.session_state.is_tracking_A or st.session_state.is_tracking_B:
        time.sleep(3)
        st.rerun()

    if st.session_state.results:
        results = st.session_state.results

        st.divider()
        st.header("Análisis de Rutas Generadas")
        st.metric("Distancia Interna de Agrupación (Minimización)", f"{results['agrupacion_distancia_km']} km")
        st.divider()

        res_a = results.get('ruta_a', {})
        res_b = results.get('ruta_b', {})

        # Creamos las pestañas de visualización
        tab_a, tab_b, tab_map = st.tabs(["🚛 Camión 1", "🚚 Camión 2", "🗺️ Vista de Despacho (Seguimiento)"])
        
        # ==============================================================
        # PESTAÑA 1: CAMIÓN 1 (Resultados y Enlaces)
        # ==============================================================
        with tab_a:
            st.subheader(f"🚛 Camión 1: {res_a.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Total Lotes:** {len(res_a.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_a.get('distancia_km', 'N/A')} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_a.get('lotes_asignados', []))}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_a.get('orden_optimo', []))} → Ingenio")
                
                st.markdown("---")
                st.write("**Iniciar Navegación (Ruta A):**")
                st.link_button("➡️ Iniciar Rápido (Destino Final) - Maps", res_a.get('gmaps_link_simple', '#'))
                st.link_button("🚕 Ruta en Waze (1ra Parada)", res_a.get('waze_link', '#'))
                st.link_button("🗺️ Ruta Completa (Vista Previa) - Maps", res_a.get('gmaps_link_full', '#'))
                
                st.markdown("---")
                st.write("**Descarga de Datos Geoespaciales:**")
                # Botón de descarga de GeoJSON (COMPACTO)
                if 'geojson' in res_a and res_a['geojson']:
                     st.download_button(
                         label="🌐 Descargar GeoJSON (Ruta A) - Compacto",
                         data=json.dumps(res_a['geojson'], separators=(',', ':')),
                         file_name="ruta_A_optimizada_compacta.geojson",
                         mime="application/json"
                     )
                else:
                    st.link_button("🌐 Enlace a GeoJSON de Ruta A (Si está hosteado)", res_a.get('geojson_link', '#'))

                # Botón de descarga de CSV
                csv_data_a = generate_csv_of_points(res_a.get('orden_optimo', []), "Ruta A")
                st.download_button(
                    label="📄 Descargar CSV de Puntos (Ruta A)",
                    data=csv_data_a,
                    file_name="puntos_ruta_A.csv",
                    mime="text/csv"
                )

                # Botón de descarga de GPX (Mejor para rutas completas en otras apps como OsmAnd)
                gpx_data_a = generate_gpx_of_route(res_a.get('orden_optimo', []), "Ruta A")
                st.download_button(
                    label="⬇️ Descargar GPX de Ruta (Ruta A)",
                    data=gpx_data_a,
                    file_name="ruta_A_optimizada.gpx",
                    mime="application/gpx+xml"
                )

        # ==============================================================
        # PESTAÑA 2: CAMIÓN 2 (Resultados y Enlaces)
        # ==============================================================
        with tab_b:
            st.subheader(f"🚚 Camión 2: {res_b.get('patente', 'N/A')}")
            with st.container(border=True):
                st.markdown(f"**Total Lotes:** {len(res_b.get('lotes_asignados', []))}")
                st.markdown(f"**Distancia Total (TSP):** **{res_b.get('distancia_km', 'N/A')} km**")
                st.markdown(f"**Lotes Asignados:** `{' → '.join(res_b.get('lotes_asignados', []))}`")
                st.info(f"**Orden Óptimo:** Ingenio → {' → '.join(res_b.get('orden_optimo', []))} → Ingenio")
                
                st.markdown("---")
                st.write("**Iniciar Navegación (Ruta B):**")
                st.link_button("➡️ Iniciar Rápido (Destino Final) - Maps", res_b.get('gmaps_link_simple', '#'))
                st.link_button("🚕 Ruta en Waze (1ra Parada)", res_b.get('waze_link', '#'))
                st.link_button("🗺️ Ruta Completa (Vista Previa) - Maps", res_b.get('gmaps_link_full', '#'))

                st.markdown("---")
                st.write("**Descarga de Datos Geoespaciales:**")
                # Botón de descarga de GeoJSON (COMPACTO)
                if 'geojson' in res_b and res_b['geojson']:
                     st.download_button(
                         label="🌐 Descargar GeoJSON (Ruta B) - Compacto",
                         data=json.dumps(res_b['geojson'], separators=(',', ':')),
                         file_name="ruta_B_optimizada_compacta.geojson",
                         mime="application/json"
                     )
                else:
                    st.link_button("🌐 Enlace a GeoJSON de Ruta B (Si está hosteado)", res_b.get('geojson_link', '#'))
                
                # Botón de descarga de CSV
                csv_data_b = generate_csv_of_points(res_b.get('orden_optimo', []), "Ruta B")
                st.download_button(
                    label="📄 Descargar CSV de Puntos (Ruta B)",
                    data=csv_data_b,
                    file_name="puntos_ruta_B.csv",
                    mime="text/csv"
                )

                # Botón de descarga de GPX (Mejor para rutas completas en otras apps como OsmAnd)
                gpx_data_b = generate_gpx_of_route(res_b.get('orden_optimo', []), "Ruta B")
                st.download_button(
                    label="⬇️ Descargar GPX de Ruta (Ruta B)",
                    data=gpx_data_b,
                    file_name="ruta_B_optimizada.gpx",
                    mime="application/gpx+xml"
                )

        # ==============================================================
        # PESTAÑA 3: VISTA INTERNA INTERACTIVA (Mapa con Folium)
        # ==============================================================
        with tab_map:
            st.header("Rutas Optimizadas - Vista de Despacho y Seguimiento")
            
            # --- Toggles de Rastreo ---
            st.markdown("### Control de Rastreo (Simulado)")
            
            col_track_a, col_track_b = st.columns(2)
            
            with col_track_a:
                if st.session_state.is_tracking_A:
                    st.button("🔴 Detener Rastreo Camión 1", 
                              on_click=lambda: st.session_state.update(is_tracking_A=False), 
                              type="secondary")
                    st.success("Rastreo de Camión 1 en vivo...")
                else:
                    st.button("🟢 Iniciar Rastreo Camión 1 (Simulación)", 
                              on_click=lambda: st.session_state.update(is_tracking_A=True), 
                              type="primary")
                    st.info("Rastreo de Camión 1 detenido.")
            
            with col_track_b:
                if st.session_state.is_tracking_B:
                    st.button("🔴 Detener Rastreo Camión 2", 
                              on_click=lambda: st.session_state.update(is_tracking_B=False), 
                              type="secondary")
                    st.success("Rastreo de Camión 2 en vivo...")
                else:
                    st.button("🟢 Iniciar Rastreo Camión 2 (Simulación)", 
                              on_click=lambda: st.session_state.update(is_tracking_B=True), 
                              type="primary")
                    st.info("Rastreo de Camión 2 detenido.")
            
            st.warning("""
                ⚠️ **IMPORTANTE:** Para que esto sea un seguimiento REAL de Praxys, la función `fetch_praxys_location`
                debe ser completada con la URL de la API de Praxys, su token de autenticación y la lógica para parsear el JSON de respuesta.
            """)

            # --- Mapas de Seguimiento ---
            
            # Obtiene ubicación real/simulada
            live_lat_a, live_lon_a = get_live_location_for_camion('A') if st.session_state.is_tracking_A else (None, None)
            live_lat_b, live_lon_b = get_live_location_for_camion('B') if st.session_state.is_tracking_B else (None, None)
            
            col_map_a, col_map_b = st.columns(2)

            with col_map_a:
                st.subheader("🚛 Ruta Camión 1")
                render_interactive_route_map(res_a, "Ruta Camión 1", live_lat=live_lat_a, live_lon=live_lon_a)

            with col_map_b:
                st.subheader("🚚 Ruta Camión 2")
                render_interactive_route_map(res_b, "Ruta Camión 2", live_lat=live_lat_b, live_lon=live_lon_b)

    else:
        st.info("El reporte aparecerá aquí después de un cálculo exitoso.")


# =============================================================================
# 3. PÁGINA: HISTORIAL
# =============================================================================

elif page == "Historial":
    st.header("📋 Historial de Rutas Calculadas")

    # Se recarga el historial de Google Sheets para garantizar que está actualizado
    df_historial = get_history_data()
    st.session_state.historial_rutas = df_historial.to_dict('records') # Sincroniza la sesión

    if not df_historial.empty:
        st.subheader(f"Total de {len(df_historial)} Rutas Guardadas")

        # Muestra el DF, usando los nombres amigables
        st.dataframe(df_historial,
                     use_container_width=True,
                     column_config={
                         "KmRecorridos_CamionA": st.column_config.NumberColumn("KM Camión A", format="%.2f km"),
                         "KmRecorridos_CamionB": st.column_config.NumberColumn("KM Camión B", format="%.2f km"),
                         "Lotes_CamionA": "Lotes Camión A",
                         "Lotes_CamionB": "Lotes Camión B",
                         "Fecha": "Fecha",
                         "Hora": "Hora de Carga", # Nombre visible en Streamlit
                         "Lotes_ingresados": "Lotes Ingresados"
                      })

    else:
        st.info("No hay rutas guardadas. Realice un cálculo en la página principal.")
