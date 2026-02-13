import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread
from Routing_logic3 import (
COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN, 
generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

st.set_page_config(page_title="Optimizador Bimodal de Rutas", layout="wide")
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB"]

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
st.error(f"❌ Error de conexión con Google: {e}")
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
st.error(f"❌ Error al guardar en Sheets: {e}")

if 'historial_rutas' not in st.session_state:
df_init = get_history_data()
st.session_state.historial_rutas = df_init.to_dict('records')

st.sidebar.title("Menú Principal")
page = st.sidebar.radio("Seleccione una opción:", ["Calcular Nueva Ruta", "Historial", "Estadísticas"])

if page == "Calcular Nueva Ruta":
st.header("📍 Optimizador Bimodal de Rutas")
lotes_disponibles = list(COORDENADAS_LOTES.keys())
lotes_seleccionados = st.multiselect("Seleccione los lotes para la ruta:", options=lotes_disponibles)

if st.button("Optimizar y Guardar"):
if not lotes_seleccionados:
st.warning("Debe seleccionar al menos un lote.")
else:
with st.spinner("Calculando rutas óptimas..."):
results = solve_route_optimization(lotes_seleccionados)
now = datetime.now(ARG_TZ)
new_data = {
"Fecha": now.strftime("%Y-%m-%d"),
"Hora": now.strftime("%H:%M:%S"),
"LotesIngresados": ", ".join(lotes_seleccionados),
"Lotes_CamionA": str(results['vehicle_routes'].get('Camion_A', [])),
"Lotes_CamionB": str(results['vehicle_routes'].get('Camion_B', [])),
"Km_CamionA": round(results['distances'].get('Camion_A', 0), 2),
"Km_CamionB": round(results['distances'].get('Camion_B', 0), 2)
}
save_new_route_to_sheet(new_data)
st.session_state.historial_rutas.append(new_data)
st.success("Ruta optimizada y enviada a Google Sheets.")
c1, c2 = st.columns(2)
c1.info(f"**Camión A:** {new_data['Km_CamionA']} km")
c2.success(f"**Camión B:** {new_data['Km_CamionB']} km")

elif page == "Historial":
st.header("📋 Historial de Rutas Guardadas")
df_h = pd.DataFrame(st.session_state.historial_rutas)

if not df_h.empty:
st.dataframe(df_h.iloc[::-1], use_container_width=True)
if st.button("Actualizar Datos"):
st.cache_data.clear()
st.rerun()
else:
st.info("No hay registros en el historial.")

elif page == "Estadísticas":
st.header("📊 Análisis de Rendimiento")
df_h = pd.DataFrame(st.session_state.historial_rutas)

if not df_h.empty:
df_h['Km_Total'] = pd.to_numeric(df_h['Km_CamionA']) + pd.to_numeric(df_h['Km_CamionB'])
m1, m2, m3 = st.columns(3)
m1.metric("Total Kilómetros", f"{df_h['Km_Total'].sum():.1f} km")
m2.metric("Promedio por Ruta", f"{df_h['Km_Total'].mean():.1f} km")
m3.metric("Cant. de Viajes", len(df_h))
st.divider()
st.subheader("Kilómetros por Viaje (Tendencia)")
st.line_chart(df_h['Km_Total'])
st.caption("Nota: Los KM Totales se calculan sumando las distancias de ambos camiones por cada operación.")
else:
st.warning("Sin datos para generar estadísticas.")
