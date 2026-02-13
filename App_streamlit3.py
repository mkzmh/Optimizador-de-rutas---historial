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
    return f"https://www.google.com/maps/dir/" + "/".join(route_parts)

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
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

@st.cache_data(ttl=3600)
def get_history_data():
    client = get_gspread_client()
    if not client: return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        for col in COLUMNS:
            if col not in df.columns: df[col] = ""
        return df
    except Exception as e:
        st.error(f"❌ Error al leer historial: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        values_to_save = [new_route_data.get(col, "") for col in COLUMNS]
        worksheet.append_row(values_to_save)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")

# =============================================================================
# ESTADÍSTICAS
# =============================================================================

def calculate_statistics(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    df = df.copy()
    df['Fecha'] = pd.to_datetime(df['Fecha'])
    df['Km_CamionA'] = pd.to_numeric(df['Km_CamionA'], errors='coerce').fillna(0)
    df['Km_CamionB'] = pd.to_numeric(df['Km_CamionB'], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']
    
    daily_stats = df.groupby('Fecha').agg(
        Rutas_Total=('Fecha', 'count'),
        Km_Total=('Km_Total', 'sum')
    ).reset_index()
    
    return daily_stats, df

# =============================================================================
# SESIÓN Y NAVEGACIÓN
# =============================================================================

if 'historial_rutas' not in st.session_state:
    df_init = get_history_data()
    st.session_state.historial_rutas = df_init.to_dict('records')

st.sidebar.title("Menú Principal")
page = st.sidebar.radio("Seleccione una opción:", ["Calcular Nueva Ruta", "Historial", "Estadísticas"])

# =============================================================================
# PÁGINAS
# =============================================================================

if page == "Calcular Nueva Ruta":
    st.header("📍 Optimizador de Rutas")
    
    lotes_seleccionados = st.multiselect("Selecciona los lotes a visitar:", options=list(COORDENADAS_LOTES.keys()))
    
    if st.button("Optimizar Ruta"):
        if not lotes_seleccionados:
            st.warning("Por favor, selecciona al menos un lote.")
        else:
            with st.spinner("Calculando mejor ruta..."):
                # Llamada a tu lógica importada
                results = solve_route_optimization(lotes_seleccionados)
                
                now = datetime.now(ARG_TZ)
                new_data = {
                    "Fecha": now.strftime("%Y-%m-%d"),
                    "Hora": now.strftime("%H:%M:%S"),
                    "LotesIngresados": str(lotes_seleccionados),
                    "Lotes_CamionA": str(results['vehicle_routes'].get('Camion_A', [])),
                    "Lotes_CamionB": str(results['vehicle_routes'].get('Camion_B', [])),
                    "Km_CamionA": results['distances'].get('Camion_A', 0),
                    "Km_CamionB": results['distances'].get('Camion_B', 0)
                }
                
                save_new_route_to_sheet(new_data)
                st.session_state.historial_rutas.append(new_data)
                st.success("Ruta calculada y guardada con éxito.")
                st.json(results)

elif page == "Historial":
    st.header("📋 Historial de Rutas")
    df_h = pd.DataFrame(st.session_state.historial_rutas)
    if not df_h.empty:
        st.dataframe(df_h, use_container_width=True)
    else:
        st.info("No hay rutas registradas.")

elif page == "Estadísticas":
    st.header("📊 Estadísticas de Operación")
    df_h = pd.DataFrame(st.session_state.historial_rutas)
    
    if not df_h.empty:
        daily, full_df = calculate_statistics(df_h)
        col1, col2 = st.columns(2)
        col1.metric("Total KM Recorridos", f"{full_df['Km_Total'].sum():.2f}")
        col2.metric("Total Rutas", len(full_df))
        
        st.line_chart(daily.set_index('Fecha')['Km_Total'])
        
        st.divider()
        st.caption("Nota: Los KM Totales/Promedio se calculan usando la suma de las distancias optimizadas de cada camión.")
    else:
        st.warning("No hay datos para mostrar estadísticas.")
