import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread

# =============================================================================
# IMPORTACIONES DE LÓGICA
# =============================================================================
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
st.set_page_config(
    page_title="Sistema de Gestión Logística",
    layout="wide",
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

COLUMNS = [
    "Fecha", "Hora", "LotesIngresados",
    "Lotes_CamionA", "Lotes_CamionB",
    "Km_CamionA", "Km_CamionB", "Km Totales"
]

# =============================================================================
# GOOGLE SHEETS
# =============================================================================
@st.cache_resource(ttl=3600)
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
    return gspread.service_account_from_dict(credentials_dict)


@st.cache_data(ttl=300)
def get_history_data():
    client = get_gspread_client()
    sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
    ws = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
    return pd.DataFrame(ws.get_all_records())


def save_new_route_to_sheet(data):
    client = get_gspread_client()
    sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
    ws = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
    ws.append_row([data.get(c, "") for c in COLUMNS])
    st.cache_data.clear()  # fuerza recarga real

# =============================================================================
# HISTORIAL (FUENTE ÚNICA)
# =============================================================================
df_hist = get_history_data()
st.session_state.historial_rutas = df_hist.to_dict("records")

# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.image(
        "https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png",
        use_container_width=True
    )
    page = st.radio("Módulos", ["Planificación Operativa", "Historial", "Estadísticas"])
    st.caption(f"Registros Totales: {len(st.session_state.historial_rutas)}")

# =============================================================================
# PLANIFICACIÓN
# =============================================================================
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")

    lotes_input = st.text_input("Ingreso de Lotes")
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

    if invalid_stops:
        st.warning(f"Lotes no encontrados: {', '.join(invalid_stops)}")

    if st.button("Calcular optimización", type="primary", disabled=not valid_stops):
        with st.spinner("Calculando..."):
            results = solve_route_optimization(valid_stops)

            if "error" in results:
                st.error(results["error"])
            else:
                now = datetime.now(ARG_TZ)
                ra, rb = results["ruta_a"], results["ruta_b"]

                new_entry = {
                    "Fecha": now.strftime("%Y-%m-%d"),
                    "Hora": now.strftime("%H:%M:%S"),
                    "LotesIngresados": ", ".join(valid_stops),
                    "Lotes_CamionA": str(ra.get("lotes_asignados", [])),
                    "Lotes_CamionB": str(rb.get("lotes_asignados", [])),
                    "Km_CamionA": ra.get("distancia_km", 0),
                    "Km_CamionB": rb.get("distancia_km", 0),
                    "Km Totales": ra.get("distancia_km", 0) + rb.get("distancia_km", 0)
                }

                save_new_route_to_sheet(new_entry)

                # 🔄 recargar historial real
                df_hist = get_history_data()
                st.session_state.historial_rutas = df_hist.to_dict("records")

                st.success("Ruta guardada correctamente.")

# =============================================================================
# HISTORIAL
# =============================================================================
elif page == "Historial":
    st.title("Historial de Operaciones")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if df.empty:
        st.info("No hay registros.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

# =============================================================================
# ESTADÍSTICAS
# =============================================================================
elif page == "Estadísticas":
    st.title("Indicadores")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if df.empty:
        st.info("No hay datos para mostrar.")
    else:
        st.bar_chart(df["Km Totales"])
