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
    # Link corregido para Google Maps
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
            "auth_provider_x509_cert_url": "https://www.googleapis.com/official/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['gsheets_client_email']}",
            "universe_domain": "googleapis.com"
        }
        return gspread.service_account_from_dict(credentials_dict)
    except Exception as e:
        st.error(f"❌ Error de configuración de credenciales: {e}")
        return None

@st.cache_data(ttl=60)
def get_history_data():
    client = get_gspread_client()
    if not client:
        return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        return df
    except Exception as e:
        st.error(f"❌ Error al leer Google Sheets: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        values_to_save = [str(new_route_data.get(col, "")) for col in COLUMNS]
        worksheet.append_row(values_to_save)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")

# =============================================================================
# LÓGICA DE ESTADÍSTICAS
# =============================================================================

def calculate_statistics(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    df = df.copy()
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M').astype(str)

    df['Km_CamionA'] = pd.to_numeric(df['Km_CamionA'], errors='coerce').fillna(0)
    df['Km_CamionB'] = pd.to_numeric(df['Km_CamionB'], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily = df.groupby(df['Fecha'].dt.date).agg(
        Rutas=('Fecha', 'count'),
        Km_Total=('Km_Total', 'sum')
    ).reset_index()

    monthly = df.groupby('Mes').agg(
        Rutas=('Fecha', 'count'),
        Km_Total=('Km_Total', 'sum')
    ).reset_index()

    return daily, monthly

# =============================================================================
# NAVEGACIÓN Y SESIÓN
# =============================================================================

if 'results' not in st.session_state:
    st.session_state.results = None

df_history = get_history_data()

st.sidebar.title("🚚 Optimizador Bimodal")
page = st.sidebar.radio("Ir a:", ["Calcular Nueva Ruta", "Historial", "Estadísticas"])

# =============================================================================
# PÁGINA: CALCULAR RUTA
# =============================================================================

if page == "Calcular Nueva Ruta":
    st.header("📍 Cálculo de Ruta Optimizada")
    
    lotes_input = st.multiselect("Seleccione los Lotes:", options=list(COORDENADAS_LOTES.keys()))
    
    if st.button("Calcular Optimización"):
        if not lotes_input:
            st.warning("Seleccione al menos un lote.")
        else:
            with st.spinner("Calculando mejor ruta..."):
                res = solve_route_optimization(lotes_input)
                st.session_state.results = res
                
                # Guardar en GSHEETS
                ahora = datetime.now(ARG_TZ)
                nueva_fila = {
                    "Fecha": ahora.strftime("%Y-%m-%d"),
                    "Hora": ahora.strftime("%H:%M:%S"),
                    "LotesIngresados": ", ".join(lotes_input),
                    "Lotes_CamionA": str(res['CamionA']['route']),
                    "Lotes_CamionB": str(res['CamionB']['route']),
                    "Km_CamionA": res['CamionA']['distance'],
                    "Km_CamionB": res['CamionB']['distance']
                }
                save_new_route_to_sheet(nueva_fila)
                st.success("Ruta calculada y guardada en el historial.")

    if st.session_state.results:
        res = st.session_state.results
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🚛 Camión A (Pesado)")
            st.write(f"**Distancia:** {res['CamionA']['distance']:.2f} km")
            st.write(f"**Orden:** {res['CamionA']['route']}")
            st.link_button("Ver en Google Maps", generate_gmaps_link(res['CamionA']['route']))
            
        with col2:
            st.subheader("🚛 Camión B (Liviano)")
            st.write(f"**Distancia:** {res['CamionB']['distance']:.2f} km")
            st.write(f"**Orden:** {res['CamionB']['route']}")
            st.link_button("Ver en Google Maps", generate_gmaps_link(res['CamionB']['route']))

# =============================================================================
# PÁGINA: HISTORIAL
# =============================================================================

elif page == "Historial":
    st.header("📋 Historial de Rutas")
    if not df_history.empty:
        st.dataframe(df_history.sort_values(by=["Fecha", "Hora"], ascending=False), use_container_width=True)
    else:
        st.info("No hay datos registrados aún.")

# =============================================================================
# PÁGINA: ESTADÍSTICAS
# =============================================================================

elif page == "Estadísticas":
    st.header("📊 Análisis de Operación")
    if not df_history.empty:
        daily_stats, monthly_stats = calculate_statistics(df_history)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Km Recorridos", f"{df_history['Km_CamionA'].astype(float).sum() + df_history['Km_CamionB'].astype(float).sum():.1f} km")
        with col2:
            st.metric("Total Rutas", len(df_history))
            
        st.subheader("Km por Día")
        st.bar_chart(daily_stats.set_index('Fecha')['Km_Total'])
        
        st.subheader("Resumen Mensual")
        st.table(monthly_stats)
    else:
        st.info("Sin datos para generar estadísticas.")

st.sidebar.divider()
st.sidebar.caption(f"Última actualización: {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")
