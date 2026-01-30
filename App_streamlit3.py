import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread

# =============================================================================
# 1. IMPORTACIONES DE LÓGICA DE RUTAS
# =============================================================================
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

# =============================================================================
# 2. CONFIGURACIÓN INTERFAZ
# =============================================================================
st.set_page_config(
    page_title="Sistema de Gestión Logística", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Columnas de Google Sheets
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# =============================================================================
# 3. FUNCIONES AUXILIARES
# =============================================================================
def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    origin_str = f"{lat_orig},{lon_orig}"
    
    waypoints = []
    for lote_nombre in stops_order_names:
        if lote_nombre in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[lote_nombre]
            waypoints.append(f"{lat},{lon}")
            
    base_url = "https://www.google.com/maps/dir/"
    route_path = "/".join([origin_str] + waypoints + [origin_str])
    return base_url + route_path

# =============================================================================
# 4. CONEXIÓN GOOGLE SHEETS (SIN CACHE)
# =============================================================================
def get_gspread_client():
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
    try:
        return gspread.service_account_from_dict(credentials_dict)
    except Exception as e:
        st.error(f"No se pudo crear cliente gspread: {e}")
        return None

def get_history_data():
    client = get_gspread_client()
    if not client: return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"No se pudo cargar historial: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client:
        st.error("Cliente de Google Sheets no disponible")
        return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        row_values = [new_route_data.get(col, "") for col in COLUMNS]
        worksheet.append_row(row_values)
        st.session_state.historial_rutas.append(new_route_data)
        st.success("✅ Planificación completada y guardada en Google Sheets")
    except Exception as e:
        st.error(f"Error guardando en Sheets: {e}")

# =============================================================================
# 5. ESTADÍSTICAS
# =============================================================================
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

    if 'Lotes_CamionA' not in df.columns: df['Lotes_CamionA'] = ""
    if 'Lotes_CamionB' not in df.columns: df['Lotes_CamionB'] = ""

    df['Total_Asignados'] = df['Lotes_CamionA'].apply(safe_count) + df['Lotes_CamionB'].apply(safe_count)

    for col in ['Km_CamionA', 'Km_CamionB']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily = df.groupby('Fecha').agg({
        'Fecha':'count',
        'Total_Asignados':'sum',
        'Km_CamionA':'sum',
        'Km_CamionB':'sum',
        'Km_Total':'sum'
    }).rename(columns={'Fecha':'Rutas_Total', 'Total_Asignados':'Lotes_Asignados_Total', 'Km_CamionA':'Km_CamionA_Total', 'Km_CamionB':'Km_CamionB_Total', 'Km_Total':'Km_Total'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    daily['Km_Promedio_Ruta'] = daily['Km_Total'] / daily['Rutas_Total']

    monthly = df.groupby('Mes').agg({
        'Fecha':'count',
        'Total_Asignados':'sum',
        'Km_CamionA':'sum',
        'Km_CamionB':'sum',
        'Km_Total':'sum'
    }).rename(columns={'Fecha':'Rutas_Total', 'Total_Asignados':'Lotes_Asignados_Total', 'Km_CamionA':'Km_CamionA_Total', 'Km_CamionB':'Km_CamionB_Total', 'Km_Total':'Km_Total'}).reset_index()
    monthly['Mes_str'] = monthly['Mes'].astype(str)
    monthly['Km_Promedio_Ruta'] = monthly['Km_Total'] / monthly['Rutas_Total']
    return daily, monthly

# =============================================================================
# 6. INICIALIZACIÓN SESSION_STATE
# =============================================================================
if 'historial_rutas' not in st.session_state:
    st.session_state.historial_rutas = get_history_data().to_dict('records')
if 'results' not in st.session_state:
    st.session_state.results = None

# =============================================================================
# 7. INTERFAZ
# =============================================================================
with st.sidebar:
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.markdown("### Panel de Control")
    page = st.radio("Módulos", ["Planificación Operativa", "Historial", "Estadísticas"])
    st.markdown("---")
    st.caption(f"Registros Totales: **{len(st.session_state.historial_rutas)}**")

# ================= PÁGINA 1: PLANIFICACIÓN =================
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    st.markdown("##### Planificación y división óptima de lotes para vehículos de entrega")
    st.markdown("---")

    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ingrese códigos separados por coma (Ej: A05, B10, C95)")
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

    c1, c2 = st.columns(2)
    c1.metric("Lotes Identificados", len(valid_stops))
    c2.metric("Lotes No Encontrados", len(invalid_stops), delta_color="inverse")
    if invalid_stops:
        st.warning(f"⚠️ **Atención:** No reconoce estos códigos: {', '.join(invalid_stops)}")

    if valid_stops:
        with st.expander("🗺️ Ver Mapa de Lotes", expanded=False):
            map_data = [{'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0], 'name': 'INGENIO', 'color':'#000000'}]
            for l in valid_stops:
                coords = COORDENADAS_LOTES[l]
                map_data.append({'lat': coords[1], 'lon': coords[0], 'name': l, 'color':'#0044ff'})
            st.map(pd.DataFrame(map_data), size=20, color='color')

    col_btn, _ = st.columns([1,3])
    with col_btn:
        calculate = st.button("Calcular optimización", type="primary", disabled=len(valid_stops)==0, use_container_width=True)

    if calculate:
        with st.spinner("Calculando distribución óptima de carga..."):
            try:
                results = solve_route_optimization(valid_stops)
                st.session_state.results = results
                if "error" not in results:
                    now = datetime.now(ARG_TZ)
                    ra = results.get('ruta_a', {})
                    rb = results.get('ruta_b', {})

                    km_a = ra.get('distancia_km', 0)
                    km_b = rb.get('distancia_km', 0)

                    new_entry = {
                        "Fecha": now.strftime("%Y-%m-%d"),
                        "Hora": now.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(valid_stops),
                        "Lotes_CamionA": str(ra.get('lotes_asignados', [])),
                        "Lotes_CamionB": str(rb.get('lotes_asignados', [])),
                        "Km_CamionA": km_a,
                        "Km_CamionB": km_b,
                        "Km Totales": km_a + km_b
                    }
                    save_new_route_to_sheet(new_entry)
            except Exception as e:
                st.error(f"Error crítico: {e}")

# ================= PÁGINA 2: HISTORIAL =================
elif page == "Historial":
    st.title("Historial de Operaciones")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No se encontraron registros previos.")

# ================= PÁGINA 3: ESTADÍSTICAS =================
elif page == "Estadísticas":
    st.title("Indicadores de Desempeño")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        day, month = calculate_statistics(df)
        st.subheader("Desempeño Diario")
        if not day.empty:
            st.dataframe(day, use_container_width=True)
        st.subheader("Consolidado Mensual")
        if not month.empty:
            st.dataframe(month, use_container_width=True)
    else:
        st.info("Se requieren datos operativos para generar los indicadores.")
