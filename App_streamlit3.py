import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread

# =============================================================================
# 1. IMPORTACIONES
# =============================================================================
try:
    from Routing_logic3 import (
        COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
        generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
    )
except ImportError:
    st.error("Error: No se encontró 'Routing_logic3.py'. Asegúrate de que el archivo esté en la misma carpeta.")

# =============================================================================
# 2. CONFIGURACIÓN E INTERFAZ
# =============================================================================
st.set_page_config(
    page_title="Sistema de Gestión Logística", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# CSS PROFESIONAL
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 8px; }
    div.stButton > button[kind="primary"] { background-color: #003366 !important; color: white !important; width: 100%; border-radius: 6px; }
    div.stButton > button[kind="secondary"] { width: 100%; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e0e0e0; }
    </style>
    """, unsafe_allow_html=True)

# =============================================================================
# 3. CONEXIÓN BASE DE DATOS (CORREGIDA Y ROBUSTA)
# =============================================================================

@st.cache_resource(ttl=3600)
def get_gspread_client():
    try:
        # Limpieza profunda de la clave para evitar errores de formato JSON
        pk = st.secrets["gsheets_private_key"].strip()
        if "\\n" in pk:
            pk = pk.replace("\\n", "\n")

        credentials_dict = {
            "type": "service_account",
            "project_id": st.secrets["gsheets_project_id"],
            "private_key_id": st.secrets["gsheets_private_key_id"],
            "private_key": pk,
            "client_email": st.secrets["gsheets_client_email"],
            "client_id": st.secrets["gsheets_client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['gsheets_client_email']}",
            "universe_domain": "googleapis.com"
        }
        return gspread.service_account_from_dict(credentials_dict)
    except Exception as e:
        st.error(f"Error de autenticación con Google: {e}")
        return None

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        
        # Mapeo exacto de columnas para asegurar el orden en el Excel
        row_values = [new_route_data.get(col, "") for col in COLUMNS]
        
        worksheet.append_row(row_values)
        st.toast("✅ Datos guardados en la nube", icon="💾")
        st.cache_data.clear() # Limpiar caché para ver el historial nuevo
    except Exception as e:
        st.error(f"Error registrando en Google Sheets: {e}")

@st.cache_data(ttl=600)
def get_history_data():
    client = get_gspread_client()
    if not client: return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame(columns=COLUMNS)

# =============================================================================
# 4. FUNCIONES AUXILIARES
# =============================================================================

def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    origin_str = f"{lat_orig},{lon_orig}"
    
    waypoints = []
    for lote in stops_order_names:
        if lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[lote]
            waypoints.append(f"{lat},{lon}")
            
    base_url = "https://www.google.com/maps/dir/"
    route_path = "/".join([origin_str] + waypoints + [origin_str])
    return base_url + route_path

def calculate_statistics(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M')
    
    def safe_count(x):
        try:
            s = str(x).replace('[','').replace(']','').replace("'", "")
            return len([i for i in s.split(',') if i.strip()])
        except: return 0

    df['Total_Lotes'] = df['Lotes_CamionA'].apply(safe_count) + df['Lotes_CamionB'].apply(safe_count)
    for col in ['Km_CamionA', 'Km_CamionB']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily = df.groupby('Fecha').agg({'Fecha':'count', 'Total_Lotes':'sum', 'Km_Total':'sum'}).rename(columns={'Fecha':'Rutas'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    
    monthly = df.groupby('Mes').agg({'Fecha':'count', 'Km_Total':'sum'}).rename(columns={'Fecha':'Rutas'}).reset_index()
    monthly['Mes_str'] = monthly['Mes'].astype(str)
    return daily, monthly

# =============================================================================
# 5. NAVEGACIÓN Y SESSION STATE
# =============================================================================

if 'historial_cargado' not in st.session_state:
    df_hist = get_history_data()
    st.session_state.historial_rutas = df_hist.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.markdown("### Panel de Control")
    page = st.radio("Módulos", ["Planificación Operativa", "Historial", "Estadísticas"])
    
    st.markdown("---")
    # Botón de Test de Conexión
    if st.button("🔄 Test Conexión Sheets", use_container_width=True):
        c = get_gspread_client()
        if c:
            try:
                sh = c.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
                st.success(f"Conectado a:\n{sh.title}")
            except Exception as e:
                st.error(f"Error al abrir: {e}")
        else:
            st.error("Fallo de autenticación")
    
    st.caption(f"Registros en memoria: **{len(st.session_state.historial_rutas)}**")

# =============================================================================
# PÁGINA 1: PLANIFICACIÓN OPERATIVA
# =============================================================================
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    st.markdown("##### Planificación y división óptima de carga")
    
    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ej: A05, B10, C95")
    
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

    c1, c2 = st.columns(2)
    c1.metric("Lotes Identificados", len(valid_stops))
    c2.metric("No Encontrados", len(invalid_stops), delta_color="inverse") 

    if invalid_stops:
        st.warning(f"⚠️ No reconocidos: {', '.join(invalid_stops)}")

    if valid_stops:
        with st.expander("🗺️ Ver Mapa de Lotes"):
            map_data = [{'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0], 'name': 'INGENIO', 'color':'#000000'}]
            for l in valid_stops:
                coords = COORDENADAS_LOTES[l]
                map_data.append({'lat': coords[1], 'lon': coords[0], 'name': l, 'color':'#0044ff'})
            st.map(pd.DataFrame(map_data), size=20, color='color')

    st.markdown("---")
    if st.button("Calcular Optimización y Guardar", type="primary", disabled=len(valid_stops)==0):
        with st.spinner("Calculando rutas óptimas..."):
            try:
                results = solve_route_optimization(valid_stops)
                st.session_state.results = results

                if "error" not in results:
                    now = datetime.now(ARG_TZ)
                    ra, rb = results.get('ruta_a', {}), results.get('ruta_b', {})
                    
                    new_entry = {
                        "Fecha": now.strftime("%Y-%m-%d"),
                        "Hora": now.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(valid_stops),
                        "Lotes_CamionA": str(ra.get('lotes_asignados', [])),
                        "Lotes_CamionB": str(rb.get('lotes_asignados', [])),
                        "Km_CamionA": ra.get('distancia_km', 0),
                        "Km_CamionB": rb.get('distancia_km', 0),
                        "Km Totales": ra.get('distancia_km', 0) + rb.get('distancia_km', 0)
                    }
                    save_new_route_to_sheet(new_entry)
                    st.session_state.historial_rutas.append(new_entry)
                    st.success("Planificación completada y guardada exitosamente.")
            except Exception as e:
                st.error(f"Error crítico en cálculo: {e}")

    # Mostrar Resultados si existen
    if st.session_state.results and "error" not in st.session_state.results:
        res = st.session_state.results
        st.markdown("### Resultados")
        col_a, col_b = st.columns(2)
        
        for i, key in enumerate(['ruta_a', 'ruta_b']):
            r = res.get(key, {})
            with [col_a, col_b][i]:
                with st.container(border=True):
                    st.markdown(f"#### {'🚛 Camión 1' if i==0 else '🚚 Camión 2'}: {r.get('patente')}")
                    if r.get('mensaje'):
                        st.info("Sin lotes asignados.")
                    else:
                        m1, m2 = st.columns(2)
                        m1.metric("Distancia", f"{r.get('distancia_km')} km")
                        m2.metric("Lotes", len(r.get('lotes_asignados', [])))
                        st.code(" ➤ ".join(["Ingenio"] + r.get('orden_optimo', []) + ["Ingenio"]))
                        st.link_button("📍 Iniciar Ruta (Maps)", generate_gmaps_link(r.get('orden_optimo', [])), type="primary")

# =============================================================================
# PÁGINA 2: HISTORIAL
# =============================================================================
elif page == "Historial":
    st.title("Historial de Operaciones")
    if st.button("🔄 Refrescar desde la nube"):
        st.cache_data.clear()
        st.session_state.historial_rutas = get_history_data().to_dict('records')
        st.rerun()

    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No hay registros previos.")

# =============================================================================
# PÁGINA 3: ESTADÍSTICAS
# =============================================================================
elif page == "Estadísticas":
    st.title("Indicadores de Desempeño")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        day, month = calculate_statistics(df)
        st.subheader("Uso Diario (Km)")
        st.bar_chart(day, x='Fecha_str', y='Km_Total')
        st.subheader("Consolidado Mensual")
        st.dataframe(month, use_container_width=True, hide_index=True)
    else:
        st.info("Faltan datos operativos.")
