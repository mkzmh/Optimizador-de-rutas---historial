import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread
from urllib.parse import quote

# =============================================================================
# 1. IMPORTACIONES (Se mantienen igual)
# =============================================================================
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

# =============================================================================
# 2. CONFIGURACIÓN E INTERFAZ (Tu estructura original)
# =============================================================================
st.set_page_config(
    page_title="Sistema de Gestión Logística", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Mantenemos tu CSS original
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    div.stButton > button[kind="primary"], a[kind="primary"] { background-color: #003366 !important; border: 1px solid #003366 !important; color: #ffffff !important; font-weight: 600 !important; border-radius: 6px !important; text-align: center !important; text-decoration: none !important; width: 100% !important; }
    div.stButton > button[kind="secondary"], a[kind="secondary"] { background-color: #ffffff !important; color: #003366 !important; border: 1px solid #dce1e6 !important; width: 100% !important; text-align: center !important; text-decoration: none !important; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e0e0e0; }
    </style>
    """, unsafe_allow_html=True)

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# =============================================================================
# 3. CONEXIÓN BASE DE DATOS (AQUÍ ESTÁ LA CORRECCIÓN)
# =============================================================================

@st.cache_resource(ttl=3600)
def get_gspread_client():
    try:
        # Limpieza automática de la clave para que no falle por espacios en Secrets
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
        st.error(f"Error de autenticación: {e}")
        return None

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        
        # Mapeo manual para asegurar que cada dato vaya a su columna correcta
        row_values = [new_route_data.get(col, "") for col in COLUMNS]
        
        worksheet.append_row(row_values)
        st.toast("✅ Sincronizado con Google Sheets")
        st.cache_data.clear()
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
    except Exception as e:
        # Esto te avisará si el historial no carga por culpa del nombre de la hoja
        st.sidebar.warning(f"No se pudo cargar historial: {e}")
        return pd.DataFrame(columns=COLUMNS)

# =============================================================================
# 4. FUNCIONES AUXILIARES (Tus funciones originales)
# =============================================================================

def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    origin_str = f"{lat_orig},{lon_orig}"
    waypoints = [f"{COORDENADAS_LOTES[l][1]},{COORDENADAS_LOTES[l][0]}" for l in stops_order_names if l in COORDENADAS_LOTES]
    route_path = "/".join([origin_str] + waypoints + [origin_str])
    return "https://www.google.com/maps/dir//" + route_path

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

    df['Total_Asignados'] = df['Lotes_CamionA'].apply(safe_count) + df['Lotes_CamionB'].apply(safe_count)
    for col in ['Km_CamionA', 'Km_CamionB']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily = df.groupby('Fecha').agg({'Fecha':'count', 'Total_Asignados':'sum', 'Km_CamionA':'sum', 'Km_CamionB':'sum', 'Km_Total':'sum'}).rename(columns={'Fecha':'Rutas_Total', 'Total_Asignados':'Lotes_Asignados_Total', 'Km_CamionA':'Km_CamionA_Total', 'Km_CamionB':'Km_CamionB_Total', 'Km_Total':'Km_Total'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    return daily, df.groupby('Mes').agg({'Km_Total':'sum'}).reset_index()

# =============================================================================
# 6. NAVEGACIÓN (Tu estructura original)
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
    # Botón extra de seguridad para que pruebes la conexión sin romper nada
    if st.button("🔄 Refrescar Excel"):
        st.cache_data.clear()
        st.rerun()

# --- EL RESTO DE TU LÓGICA DE PÁGINAS SIGUE IGUAL (Planificación, Historial, Estadísticas) ---
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ej: A05, B10, C95")
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    
    col_btn, _ = st.columns([1, 3])
    with col_btn:
        calculate = st.button("Calcular optimización", type="primary", disabled=len(valid_stops)==0)

    if calculate:
        with st.spinner("Calculando..."):
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
                st.success("Guardado en Google Sheets.")

    # (Muestra de resultados igual a tu original)
    if st.session_state.results and "error" not in st.session_state.results:
        res = st.session_state.results
        c_a, c_b = st.columns(2)
        with c_a:
            r = res.get('ruta_a', {})
            st.metric("Camión 1 - Km", r.get('distancia_km', 0))
            st.link_button("📍 Maps Camión 1", generate_gmaps_link(r.get('orden_optimo', [])), type="primary")
        with c_b:
            r = res.get('ruta_b', {})
            st.metric("Camión 2 - Km", r.get('distancia_km', 0))
            st.link_button("📍 Maps Camión 2", generate_gmaps_link(r.get('orden_optimo', [])), type="primary")

elif page == "Historial":
    st.title("Historial de Operaciones")
    df = pd.DataFrame(st.session_state.historial_rutas)
    st.dataframe(df, use_container_width=True, hide_index=True)

elif page == "Estadísticas":
    st.title("Indicadores de Desempeño")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        day, month = calculate_statistics(df)
        st.bar_chart(day, x='Fecha_str', y='Km_Total')
