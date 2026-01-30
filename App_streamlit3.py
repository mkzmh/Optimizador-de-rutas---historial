import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN, 
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

# =============================================================================
# CONFIGURACIÓN INICIAL
# =============================================================================

st.set_page_config(page_title="Optimizador Bimodal de Rutas", layout="wide")
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB"]

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def generate_gmaps_link(stops_order):
    if not stops_order:
        return '#'
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    route_parts = [f"{lat_orig},{lon_orig}"]
    for stop_lote in stops_order:
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            route_parts.append(f"{lat},{lon}")
    route_parts.append(f"{lat_orig},{lon_orig}")
    return f"https://www.google.com/maps/dir/{lat_orig},{lon_orig}/" + "/".join(route_parts[1:])

# =============================================================================
# GOOGLE SHEETS
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
    except KeyError as e:
        st.error(f"⚠️ Falta clave en Streamlit Secrets: {e}")
        return None
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        return None

@st.cache_data(ttl=3600)
def get_history_data():
    client = get_gspread_client()
    if not client:
        return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception as e:
        st.error(f"❌ Error al leer Google Sheets: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client:
        st.warning("No se pudo guardar la ruta: fallo de conexión.")
        return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        values_to_save = [new_route_data[col] for col in COLUMNS]
        worksheet.append_row(values_to_save)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error al guardar en Google Sheets: {e}")

# =============================================================================
# ESTADÍSTICAS
# =============================================================================

def calculate_statistics(df):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df['Fecha'] = pd.to_datetime(df['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M')

    def count_assigned_lotes(lotes_str):
        if not lotes_str or pd.isna(lotes_str) or lotes_str.strip() in ['[]', '']:
            return 0
        try:
            lotes_list = [l.strip() for l in lotes_str.strip('[]').replace("'", "").replace('"', '').replace(" ", "").split(',') if l.strip()]
            return len(lotes_list)
        except:
            return 0

    df['Total_Lotes_Ingresados'] = df['LotesIngresados'].apply(lambda x: len([l.strip() for l in str(x).split(',') if l.strip()]))
    df['Lotes_CamionA_Count'] = df['Lotes_CamionA'].apply(count_assigned_lotes)
    df['Lotes_CamionB_Count'] = df['Lotes_CamionB'].apply(count_assigned_lotes)
    df['Total_Lotes_Asignados'] = df['Lotes_CamionA_Count'] + df['Lotes_CamionB_Count']
    df['Km_CamionA'] = pd.to_numeric(df['Km_CamionA'], errors='coerce').fillna(0)
    df['Km_CamionB'] = pd.to_numeric(df['Km_CamionB'], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

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

# =============================================================================
# SESIÓN
# =============================================================================

if 'historial_cargado' not in st.session_state:
    st.cache_data.clear()
    df_history = get_history_data()
    st.session_state.historial_rutas = df_history.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

# =============================================================================
# MENÚ LATERAL
# =============================================================================

st.sidebar.title("Menú Principal")
page = st.sidebar.radio(
    "Seleccione una opción:",
    ["Calcular Nueva Ruta", "Historial", "Estadísticas"]
)
st.sidebar.divider()
st.sidebar.info(f"Rutas Guardadas: {len(st.session_state.historial_rutas)}")

# =============================================================================
# EL RESTO DEL CÓDIGO (principal, historial, estadísticas) queda igual que tu versión original
# =============================================================================

            )
        st.divider()
        st.caption("Nota: Los KM Totales/Promedio se calculan usando la suma de las distancias optimizadas de cada camión.")

