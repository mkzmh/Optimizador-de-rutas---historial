import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import gspread

# =============================================================================
# 1. IMPORTACIONES DE LÓGICA EXTERNA
# =============================================================================
try:
    from Routing_logic3 import (
        COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
        generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
    )
except ImportError:
    st.error("❌ No se encontró 'Routing_logic3.py'. Verifica que el archivo esté en la misma carpeta.")

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

# CSS PROFESIONAL ORIGINAL
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    div.stButton > button[kind="primary"] { background-color: #003366 !important; color: white !important; font-weight: 600 !important; border-radius: 6px !important; width: 100% !important; }
    div.stButton > button[kind="secondary"] { width: 100% !important; color: #003366 !important; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e0e0e0; }
    </style>
    """, unsafe_allow_html=True)

# =============================================================================
# 3. CONEXIÓN BASE DE DATOS (CORREGIDA)
# =============================================================================

@st.cache_resource(ttl=3600)
def get_gspread_client():
    try:
        # Limpieza automática de la clave privada para evitar errores de JSON
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
        st.error(f"Error de credenciales: {e}")
        return None

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
        st.error(f"Error registrando en la nube: {e}")

@st.cache_data(ttl=600)
def get_history_data():
    client = get_gspread_client()
    if not client: return pd.DataFrame(columns=COLUMNS)
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame(columns=COLUMNS)

# =============================================================================
# 4. FUNCIONES AUXILIARES
# =============================================================================

def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    origin_str = f"{lat_orig},{lon_orig}"
    waypoints = [f"{COORDENADAS_LOTES[l][1]},{COORDENADAS_LOTES[l][0]}" for l in stops_order_names if l in COORDENADAS_LOTES]
    route_path = "/".join([origin_str] + waypoints + [origin_str])
    return f"https://www.google.com/maps/dir/{route_path}"

def calculate_statistics(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha'])
    
    def safe_count(x):
        try: return len([i for i in str(x).replace('[','').replace(']','').replace("'", "").split(',') if i.strip()])
        except: return 0

    df['Total_Lotes'] = df['Lotes_CamionA'].apply(safe_count) + df['Lotes_CamionB'].apply(safe_count)
    for col in ['Km_CamionA', 'Km_CamionB']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']
    
    daily = df.groupby('Fecha').agg({'Fecha':'count', 'Total_Lotes':'sum', 'Km_Total':'sum'}).rename(columns={'Fecha':'Rutas'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    return daily, df

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
    st.caption(f"Registros Totales: **{len(st.session_state.historial_rutas)}**")

# =============================================================================
# PÁGINA 1: PLANIFICACIÓN OPERATIVA
# =============================================================================
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    st.markdown("##### Planificación y división óptima de carga")
    
    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ej: A05, B10, C95")
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    
    c1, c2 = st.columns(2)
    c1.metric("Lotes Válidos", len(valid_stops))
    c2.metric("No Identificados", len(all_stops) - len(valid_stops), delta_color="inverse")

    if st.button("Calcular Optimización", type="primary", disabled=len(valid_stops)==0):
        with st.spinner("Calculando rutas óptimas..."):
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
                st.success("✅ Planificación completada y guardada.")

    if st.session_state.results and "error" not in st.session_state.results:
        res = st.session_state.results
        col_a, col_b = st.columns(2)
        for i, key in enumerate(['ruta_a', 'ruta_b']):
            r = res.get(key, {})
            with [col_a, col_b][i]:
                with st.container(border=True):
                    st.markdown(f"#### 🚛 Unidad {['1', '2'][i]}: {r.get('patente')}")
                    if not r.get('lotes_asignados'):
                        st.info("Sin asignación.")
                    else:
                        st.metric("Distancia", f"{r.get('distancia_km')} km")
                        st.code(" ➤ ".join(["Ingenio"] + r.get('orden_optimo', []) + ["Ingenio"]))
                        st.link_button("📍 Iniciar Ruta (Maps)", generate_gmaps_link(r.get('orden_optimo', [])), type="primary")

# =============================================================================
# PÁGINA 2: HISTORIAL
# =============================================================================
elif page == "Historial":
    st.title("Historial de Operaciones")
    if st.button("🔄 Refrescar Datos"):
        st.cache_data.clear()
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
        
        st.subheader("Desempeño Diario")
        if not day.empty:
            cols_show = {
                'Fecha_str': 'Fecha', 'Rutas_Total': 'Rutas', 'Lotes_Asignados_Total': 'Lotes Entregados',
                'Km_CamionA_Total': 'Km Unidad A', 'Km_CamionB_Total': 'Km Unidad B', 'Km_Total': 'Km Totales'
            }
            st.dataframe(day[list(cols_show.keys())].rename(columns=cols_show), use_container_width=True, hide_index=True)
            
            st.markdown("##### Kilómetros Totales Recorridos por Día")
            st.bar_chart(day, x='Fecha_str', y=['Km_CamionA_Total', 'Km_CamionB_Total'], color=['#003366', '#00A8E8'])
        
        st.subheader("Consolidado Mensual")
        if not month.empty:
            st.dataframe(
                month, 
                use_container_width=True,
                column_config={
                    "Km_Total": st.column_config.NumberColumn("Km Totales", format="%.2f"),
                    "Mes_str": "Período"
                }
            )
    else:
        st.info("Se requieren datos operativos para generar los indicadores.")
