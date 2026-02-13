import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread
from urllib.parse import quote

# =============================================================================
# 1. IMPORTACIONES DE LÓGICA (Asegúrate de que Routing_logic3.py esté presente)
# =============================================================================
try:
    from Routing_logic3 import (
        COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
        generate_geojson_io_link # Asegúrate de tener esta función en tu logic
    )
except ImportError:
    st.error("Error: No se encontró 'Routing_logic3.py'. Verifica que el archivo esté en la misma carpeta.")

# =============================================================================
# 2. CONFIGURACIÓN E INTERFAZ CORPORATIVA (CSS ACTUALIZADO)
# =============================================================================

st.set_page_config(
    page_title="Sistema de Gestión Logística | CN Grupo", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# CSS REFORZADO PARA VERSIONES ACTUALES DE STREAMLIT
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Fondo y Tarjetas */
    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e0e0e0 !important;
        padding: 15px !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
    }
    
    /* BOTONES PRIMARIOS (AZUL CN) */
    button[data-testid="baseButton-primary"] {
        background-color: #003366 !important;
        border: 1px solid #003366 !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        border-radius: 6px !important;
        width: 100% !important;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #002244 !important;
        border-color: #002244 !important;
    }

    /* BOTONES SECUNDARIOS */
    button[data-testid="baseButton-secondary"] {
        background-color: #ffffff !important;
        color: #003366 !important;
        border: 1px solid #dce1e6 !important;
        width: 100% !important;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #f8f9fa;
        border-right: 1px solid #e0e0e0;
    }
    </style>
    """, unsafe_allow_html=True)

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# =============================================================================
# 3. CONEXIÓN BASE DE DATOS (GOOGLE SHEETS)
# =============================================================================

@st.cache_resource(ttl=3600)
def get_gspread_client():
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
        return gspread.service_account_from_dict(credentials_dict)
    except: return None

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        row_values = [new_route_data.get(col, "") for col in COLUMNS]
        worksheet.append_row(row_values)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error registrando operación: {e}")

@st.cache_data(ttl=60)
def get_history_data():
    client = get_gspread_client()
    if not client: return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        return pd.DataFrame(worksheet.get_all_records())
    except: return pd.DataFrame(columns=COLUMNS)

# =============================================================================
# 4. FUNCIONES AUXILIARES
# =============================================================================

def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    origin = f"{lat_orig},{lon_orig}"
    waypoints = [f"{COORDENADAS_LOTES[l][1]},{COORDENADAS_LOTES[l][0]}" for l in stops_order_names if l in COORDENADAS_LOTES]
    return f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={origin}&waypoints={quote('|'.join(waypoints))}&travelmode=driving"

def calculate_stats(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha'])
    for col in ['Km_CamionA', 'Km_CamionB', 'Km Totales']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    daily = df.groupby(df['Fecha'].dt.date).agg({'Km Totales': 'sum', 'LotesIngresados': 'count'}).reset_index()
    df['Mes'] = df['Fecha'].dt.strftime('%Y-%m')
    monthly = df.groupby('Mes').agg({'Km Totales': 'sum', 'LotesIngresados': 'count'}).reset_index()
    return daily, monthly

# =============================================================================
# 5. NAVEGACIÓN Y PÁGINAS
# =============================================================================

with st.sidebar:
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.markdown("### Panel de Control")
    page = st.radio("Módulos", ["Planificación Operativa", "Historial", "Estadísticas"])

# --- PÁGINA 1: PLANIFICACIÓN ---
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ej: A05, B10, C95")
    
    if lotes_input:
        all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
        valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
        invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

        c1, c2 = st.columns(2)
        c1.metric("Lotes Identificados", len(valid_stops))
        c2.metric("Lotes No Encontrados", len(invalid_stops), delta=-len(invalid_stops) if invalid_stops else 0, delta_color="inverse")

        if valid_stops:
            with st.expander("🗺️ Ver Mapa de Lotes", expanded=True):
                map_data = pd.DataFrame([{'lat': COORDENADAS_LOTES[l][1], 'lon': COORDENADAS_LOTES[l][0], 'name': l} for l in valid_stops])
                st.map(map_data)

        if st.button("Calcular Optimización", type="primary", disabled=len(valid_stops)==0):
            res = solve_route_optimization(valid_stops)
            if "error" not in res:
                now = datetime.now(ARG_TZ)
                ra, rb = res.get('ruta_a', {}), res.get('ruta_b', {})
                
                # GUARDADO EN SHEETS
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
                st.success("¡Optimización completada y guardada!")

                # RESULTADOS POR CAMIÓN
                st.markdown("### Resultados de la Planificación")
                col_a, col_b = st.columns(2)
                
                for col, ruta, titulo in zip([col_a, col_b], [ra, rb], ["🚛 Camión 1 (Unidad A)", "🚚 Camión 2 (Unidad B)"]):
                    with col:
                        with st.container(border=True):
                            st.subheader(titulo)
                            if ruta.get('lotes_asignados'):
                                st.write(f"**Distancia:** {ruta['distancia_km']} km")
                                st.write(f"**Lotes:** {len(ruta['lotes_asignados'])}")
                                st.markdown("**Orden Óptimo:**")
                                st.code(" ➤ ".join(["Ingenio"] + ruta['orden_optimo'] + ["Ingenio"]))
                                
                                # BOTONES DE ACCIÓN
                                st.link_button("📍 Iniciar Ruta (Google Maps)", generate_gmaps_link(ruta['orden_optimo']), type="primary")
                                if 'geojson_link' in ruta:
                                    st.link_button("🌐 Ver Mapa Web (GeoJSON)", ruta['geojson_link'], type="secondary")
                            else:
                                st.info("Sin asignación de lotes para esta unidad.")

# --- PÁGINA 2: HISTORIAL ---
elif page == "Historial":
    st.title("Historial de Operaciones")
    df = get_history_data()
    if not df.empty:
        st.dataframe(df.sort_values(by=['Fecha', 'Hora'], ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No se encontraron registros previos.")

# --- PÁGINA 3: ESTADÍSTICAS ---
elif page == "Estadísticas":
    st.title("Indicadores de Desempeño")
    df = get_history_data()
    if not df.empty:
        daily, monthly = calculate_stats(df)
        st.subheader("Consolidado Mensual")
        st.table(monthly.rename(columns={'LotesIngresados': 'Total Cargas'}))
        
        st.subheader("Uso de Flota (Km por Día)")
        st.bar_chart(daily, x='Fecha', y='Km Totales', color="#003366")
    else:
        st.info("Sin datos para generar estadísticas.")
