import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread
from Routing_logic3 import (
COORDENADAS_LOTES, 
solve_route_optimization, 
VEHICLES, 
COORDENADAS_ORIGEN, 
generate_geojson_io_link, 
generate_geojson, 
COORDENADAS_LOTES_REVERSO
)

# CONFIGURACIÓN
st.set_page_config(page_title="Optimizador Bimodal", layout="wide")
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB"]

# GOOGLE SHEETS
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
st.error(f"Error: {e}")
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
return df
except Exception as e:
st.error(f"Error: {e}")
return pd.DataFrame(columns=COLUMNS)

# NAVEGACIÓN
if 'historial_rutas' not in st.session_state:
df_init = get_history_data()
st.session_state.historial_rutas = df_init.to_dict('records')

st.sidebar.title("Menú")
page = st.sidebar.radio("Ir a:", ["Calcular", "Historial"])

if page == "Calcular":
st.header("Optimización")
lotes = st.multiselect("Lotes:", list(COORDENADAS_LOTES.keys()))
if st.button("Optimizar"):
st.write("Calculando...")
# Aquí va tu lógica de solve_route_optimization

elif page == "Historial":
st.header("Historial")
st.table(st.session_state.historial_rutas)
