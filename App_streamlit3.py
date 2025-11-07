import streamlit as st
import pandas as pd
from datetime import datetime # Importación actualizada para usar la hora
import pytz # ¡NUEVO! Importamos pytz para manejo de zonas horarias
import os
import time
import json
import io # Importado para manejar streams de bytes (necesario para la descarga)
import gspread # Necesario para la conexión a Google Sheets
from base64 import b64encode # Necesario para codificar el archivo de descarga

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
# ¡ATENCIÓN! Se agregó "Hora" después de "Fecha"
COLUMNS = ["Fecha", "Hora", "Lotes_ingresados", "Lotes_CamionA", "Lotes_CamionB", "KmRecorridos_CamionA", "KmRecorridos_CamionB"]


# --- Funciones Auxiliares para Navegación y Descarga ---

def generate_gmaps_link(stops_order):
    """
    Genera un enlace de Google Maps para una ruta de paradas múltiples.
    """
    if not stops_order:
        return '#'

    lon_orig, lat_orig = COORDENADAS_ORIGEN
    origin_coord = f"{lat_orig},{lon_orig}"
    
    origin_param = f"origin={origin_coord}"
    destination_param = f"destination={origin_coord}"
    
    waypoints_list = []
    for stop_lote in stops_order:
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            waypoints_list.append(f"{lat},{lon}")

    waypoints_param = ""
    if waypoints_list:
        waypoints_param = f"waypoints={'|'.join(waypoints_list)}"

    base_url = "https://www.google.com/maps/dir/?api=1"

    params = [origin_param, destination_param]
    if waypoints_param:
        params.append(waypoints_param)
        
    full_url = f"{base_url}&{'&'.join(params)}&travelmode=driving"
    return full_url


def convert_geojson_to_gpx(geojson_data):
    """
    Convierte la data de GeoJSON (la ruta optimizada) a formato GPX.
    
    NOTA: Dado que Streamlit no permite usar librerías complejas como OGR o gpxpy
    para conversión, esta función genera un GPX BÁSICO que solo contiene el track 
    (la línea de la ruta). Esto es suficiente para OsmAnd para 'Seguir Recorrido'.
    """
    if not geojson_data or not geojson_data.get('features'):
        return None

    # Asumimos que la primera FeatureCollection contiene el LineString de la ruta
    # Extraer el LineString de la ruta (coordenadas)
    route_coords = []
    for feature in geojson_data['features']:
        if feature.get('geometry', {}).get('type') == 'LineString':
            route_coords = feature['geometry']['coordinates']
            break
        elif feature.get('geometry', {}).get('type') == 'FeatureCollection' and 'features' in feature['geometry']:
             for sub_feature in feature['geometry']['features']:
                 if sub_feature.get('geometry', {}).get('type') == 'LineString':
                    route_coords = sub_feature['geometry']['coordinates']
                    break
             if route_coords:
                 break
        
    if not route_coords:
        return None

    gpx_content = io.StringIO()
    gpx_content.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    gpx_content.write('<gpx version="1.1" creator="Optimizator" xmlns="http://www.topografix.com/GPX/1/1">\n')
    gpx_content.write('  <trk>\n')
    gpx_content.write('    <name>Ruta Optimizada</name>\n')
    gpx_content.write('    <trkseg>\n')

    # Escribir los puntos de la ruta (trkpt)
    for lon, lat in route_coords:
        gpx_content.write(f'      <trkpt lat="{lat}" lon="{lon}"></trkpt>\n')

    gpx_content.write('    </trkseg>\n')
    gpx_content.write('  </trk>\n')
    gpx_content.write('</gpx>\n')

    return gpx_content.getvalue().encode('utf-8')


def generate_gpx_download_link(gpx_data, filename, link_text):
    """Genera un enlace de descarga directa usando base64 (Solución Streamlit)."""
    if gpx_data is None:
        return f'<p style="color:red;">Error: Datos GPX no disponibles para {filename}</p>'
    
    b64_gpx = b64encode(gpx_data).decode()
    
    # URL de datos codificados para la descarga
    href = f'<a href="data:application/gpx+xml;base64,{b64_gpx}" download="{filename}" style="background-color: #38761d; color: white; padding: 10px 20px; text-align: center; text-decoration: none; display: inline-block; border-radius: 5px;">{link_text}</a>'
    return href


# --- Funciones de Conexión y Persistencia (Google Sheets) ---
# (Las funciones de GSheets son las mismas)
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
    st.title("🚚 Optimizator")
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
                results = solve_route_optimization(all_stops_to_visit)

                if "error" in results:
                    st.error(f"❌ Error en la API de Ruteo: {results['error']}")
                else:
                    # ✅ GENERACIÓN DE ENLACES DE NAVEGACIÓN Y GPX
                    results['ruta_a']['gmaps_link'] = generate_gmaps_link(results['ruta_a']['orden_optimo'])
                    results['ruta_b']['gmaps_link'] = generate_gmaps_link(results['ruta_b']['orden_optimo'])
                    
                    # Generar los datos GPX y guardarlos en el estado de sesión
                    results['ruta_a']['gpx_data'] = convert_geojson_to_gpx(results['ruta_a'].get('geojson_data', {}))
                    results['ruta_b']['gpx_data'] = convert_geojson_to_gpx(results['ruta_b'].get('geojson_data', {}))


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
    # 2. REPORTE DE RESULTADOS UNIFICADO (ENFOQUE: SECUENCIA Y UN SOLO LINK)
    # -------------------------------------------------------------------------

    if st.session_state.results:
        results = st.session_state.results

        st.divider()
        st.header("Análisis de Rutas Generadas")
        st.metric("Distancia Interna de Agrupación (Minimización)", f"{results['agrupacion_distancia_km']} km")
        st.divider()
        
        st.markdown("**Elija la opción de navegación. Recuerde: Precisión vs. Sencillez.**")

        res_a = results.get('ruta_a', {})
        res_b = results.get('ruta_b', {})

        col_a, col_b = st.columns(2)

        def display_route_final(res, col_container, camion_label, ruta_key):
            """Función auxiliar para mostrar los detalles de la ruta final para el jefe/chofer."""
            with col_container:
                st.subheader(f"{camion_label}: {res.get('patente', 'N/A')}")
                
                # Resumen de Métricas
                with st.container(border=True):
                    st.markdown(f"**Total Lotes:** {len(res.get('lotes_asignados', []))}")
                    st.markdown(f"**Distancia Mínima Calculada (GraphHopper):** **{res.get('distancia_km', 'N/A')} km**")
                
                st.markdown("---")
                st.markdown("**🚛 Secuencia de Paradas Óptima:**")
                
                # Mostrar la secuencia de paradas claramente
                orden_display = f"INGENIO → {' → '.join(res.get('orden_optimo', []))} → INGENIO"
                st.code(orden_display, language='text')

                st.markdown("---")
                
                # --- OPCIÓN 1: PRECISION (OsmAnd/GPX) - DESCARGA DIRECTA ---
                st.markdown("#### Opción 1: PRECISION (Ruta Exacta)")
                
                # Generar el enlace de descarga directa GPX
                gpx_link_html = generate_gpx_download_link(
                    res.get('gpx_data'), 
                    f"Ruta_{ruta_key}_{datetime.now().strftime('%Y%m%d')}.gpx",
                    "💾 1 CLIC: Descargar Ruta GPX (OsmAnd)"
                )
                st.markdown(gpx_link_html, unsafe_allow_html=True)
                
                st.caption(f"""
                    **Recomendado para KM exactos.** En el móvil, el proceso es simple: 
                    
                    1. 🖱️ **Haga clic** en el botón de descarga verde. El archivo **.gpx** se guardará en su móvil.
                    2. 📲 **Abra el archivo .gpx descargado** y elija **Compartir/Abrir con OsmAnd** para iniciar el recorrido de **{res.get('distancia_km', 'N/A')} km**.
                """)
                
                st.markdown("---")
                
                # --- OPCIÓN 2: SENCILEZ (Google Maps) ---
                st.markdown("#### Opción 2: SENCILEZ (Un Clic de Navegación)")
                st.link_button(
                    "🗺️ Abrir Ruta COMPLETA en Google Maps", 
                    res.get('gmaps_link', '#'), 
                    type="primary"
                )
                st.caption(f"""
                    **Ideal para choferes.** Navegación simple por voz. **ADVERTENCIA:** Google Maps 
                    recalcula la ruta, por lo que la distancia real navegada será 
                    diferente a la optimizada.
                """)
                
        # Mostrar acciones para Camión A
        display_route_final(res_a, col_a, "🚛 Camión 1", "A")
        
        # Mostrar acciones para Camión B
        display_route_final(res_b, col_b, "🚚 Camión 2", "B")

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
