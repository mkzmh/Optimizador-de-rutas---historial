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
# IMPORTACIONES
# =============================================================================
from Routing_logic3 import (
    COORDENADAS_LOTES, solve_route_optimization, VEHICLES, COORDENADAS_ORIGEN,
    generate_geojson_io_link, generate_geojson, COORDENADAS_LOTES_REVERSO
)

# =============================================================================
# CONFIGURACIÓN INICIAL Y ESTÉTICA CORPORATIVA
# =============================================================================

st.set_page_config(page_title="Sistema de Gestión Logística", layout="wide", page_icon="🚛")

# --- ZONA HORARIA ARGENTINA (GMT-3) ---
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# --- ESTILOS CSS PROFESIONALES ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Tarjetas de Métricas */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* Botones Primarios (Azul Corporativo) */
    div.stButton > button:first-child {
        background-color: #003366;
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.5rem 1rem;
    }
    div.stButton > button:first-child:hover {
        background-color: #002244;
    }
    
    /* Títulos */
    h1, h2, h3 {
        color: #2c3e50;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    </style>
    """, unsafe_allow_html=True)

# Encabezados en el orden de Google Sheets
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]


# =============================================================================
# 1. FUNCIÓN CORREGIDA: GENERAR LINK DE GOOGLE MAPS (OFICIAL)
# =============================================================================

def generate_gmaps_link(stops_order):
    """
    Genera un enlace de navegación DIRECTO de Google Maps.
    Usa la estructura oficial: https://www.google.com/maps/dir/Origen/Punto1/Punto2/Destino
    """
    if not stops_order:
        return '#'

    # COORDENADAS_ORIGEN es [lon, lat]. Maps necesita "lat,lon"
    lat_orig, lon_orig = COORDENADAS_ORIGEN[1], COORDENADAS_ORIGEN[0]
    
    # 1. Iniciar URL base
    url = f"https://www.google.com/maps/dir/{lat_orig},{lon_orig}"
    
    # 2. Añadir paradas intermedias
    for stop_lote in stops_order:
        if stop_lote in COORDENADAS_LOTES:
            # Recuperamos [lon, lat] del diccionario y lo invertimos para la URL
            lon, lat = COORDENADAS_LOTES[stop_lote]
            url += f"/{lat},{lon}"

    # 3. Añadir destino final (regreso)
    url += f"/{lat_orig},{lon_orig}"
    
    return url


# --- Funciones de Conexión y Persistencia (Google Sheets) ---

@st.cache_resource(ttl=3600)
def get_gspread_client():
    """Establece la conexión con Google Sheets."""
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

        gc = gspread.service_account_from_dict(credentials_dict)
        return gc
    except Exception as e:
        st.error(f"⚠️ Error de credenciales GSheets: {e}")
        return None

@st.cache_data(ttl=3600)
def get_history_data():
    """Lee el historial de Google Sheets."""
    client = get_gspread_client()
    if not client:
        return pd.DataFrame(columns=COLUMNS)

    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])

        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty or len(df.columns) < len(COLUMNS):
            return pd.DataFrame(columns=COLUMNS)
        return df

    except Exception as e:
        st.error(f"❌ Error al cargar datos: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    """Escribe una nueva ruta a Google Sheets."""
    client = get_gspread_client()
    if not client:
        st.warning("No hay conexión para guardar el historial.")
        return

    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])

        values_to_save = [new_route_data.get(col, "") for col in COLUMNS]
        worksheet.append_row(values_to_save)
        st.cache_data.clear()

    except Exception as e:
        st.error(f"❌ Error guardando: {e}")


# --- Funciones de Estadística ---

def calculate_statistics(df):
    """Calcula estadísticas diarias y mensuales."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M')

    def count_assigned_lotes(lotes_str):
        if not lotes_str or pd.isna(lotes_str) or str(lotes_str).strip() == '[]':
            return 0
        try:
            lotes_list = [l.strip() for l in str(lotes_str).strip('[]').replace("'", "").replace('"', '').replace(" ", "").split(',') if l.strip()]
            return len(lotes_list)
        except:
            return 0

    df['Total_Lotes_Asignados'] = df['Lotes_CamionA'].apply(count_assigned_lotes) + df['Lotes_CamionB'].apply(count_assigned_lotes)
    df['Km_CamionA'] = pd.to_numeric(df['Km_CamionA'], errors='coerce').fillna(0)
    df['Km_CamionB'] = pd.to_numeric(df['Km_CamionB'], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily_stats = df.groupby('Fecha').agg(
        Rutas_Total=('Fecha', 'count'),
        Lotes_Asignados_Total=('Total_Lotes_Asignados', 'sum'),
        Km_CamionA_Total=('Km_CamionA', 'sum'),
        Km_CamionB_Total=('Km_CamionB', 'sum'),
        Km_Total=('Km_Total', 'sum'),
    ).reset_index()
    daily_stats['Fecha_str'] = daily_stats['Fecha'].dt.strftime('%Y-%m-%d')
    
    monthly_stats = df.groupby('Mes').agg(
        Rutas_Total=('Fecha', 'count'),
        Lotes_Asignados_Total=('Total_Lotes_Asignados', 'sum'),
        Km_CamionA_Total=('Km_CamionA', 'sum'),
        Km_CamionB_Total=('Km_CamionB', 'sum'),
        Km_Total=('Km_Total', 'sum'),
    ).reset_index()
    monthly_stats['Mes_str'] = monthly_stats['Mes'].astype(str)

    return daily_stats, monthly_stats


# -------------------------------------------------------------------------
# INICIALIZACIÓN DE LA SESIÓN
# -------------------------------------------------------------------------

if 'historial_cargado' not in st.session_state:
    st.cache_data.clear()
    df_history = get_history_data()
    st.session_state.historial_rutas = df_history.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

# =============================================================================
# ESTRUCTURA DEL MENÚ LATERAL
# =============================================================================

with st.sidebar:
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.title("Menú Principal")
    page = st.radio("Módulos:", ["Planificación de Rutas", "Historial Operativo", "Dashboard de Estadísticas"])
    st.divider()
    st.info(f"Registros en base de datos: {len(st.session_state.historial_rutas)}")

# =============================================================================
# 1. PÁGINA: CALCULAR NUEVA RUTA
# =============================================================================

if page == "Planificación de Rutas":
    
    st.title("Sistema de Optimización Logística")
    st.markdown("#### Configuración de Despacho Diario")
    st.markdown("---")

    lotes_input = st.text_input(
        "Ingrese puntos de entrega (Códigos separados por coma):",
        placeholder="Ej: A05, B10, C95"
    )

    col_map, col_details = st.columns([2, 1])

    all_stops_to_visit = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    num_lotes = len(all_stops_to_visit)

    map_data_list = []
    map_data_list.append({'name': 'BASE (Ingenio)', 'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0], 'color': '#000000'})

    valid_stops_count = 0
    invalid_stops = [l for l in all_stops_to_visit if l not in COORDENADAS_LOTES]

    for lote in all_stops_to_visit:
        if lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[lote]
            map_data_list.append({'name': lote, 'lat': lat, 'lon': lon, 'color': '#0044FF'})
            valid_stops_count += 1

    map_data = pd.DataFrame(map_data_list)

    with col_map:
        if valid_stops_count > 0:
            st.markdown("###### Visualización de Puntos")
            st.map(map_data, latitude='lat', longitude='lon', size=20, color='color')
        else:
            st.info("Ingrese lotes para previsualizar.")

    with col_details:
        st.markdown("###### Estado")
        st.metric("Lotes Identificados", num_lotes)

        if invalid_stops:
            st.warning(f"Códigos no encontrados: {', '.join(invalid_stops)}")

        calculate_disabled = True
        if valid_stops_count > 0:
            calculate_disabled = False

    # -------------------------------------------------------------------------
    # BOTÓN DE CÁLCULO
    # -------------------------------------------------------------------------
    st.divider()

    if st.button("Ejecutar Optimización", type="primary", disabled=calculate_disabled, use_container_width=True):

        st.session_state.results = None
        current_time = datetime.now(ARG_TZ)
        
        with st.spinner('Procesando red logística y calculando rutas óptimas...'):
            try:
                valid_stops = [l for l in all_stops_to_visit if l in COORDENADAS_LOTES]
                
                # LLAMADA AL CEREBRO
                results = solve_route_optimization(valid_stops)

                if "error" in results:
                    st.error(f"Error en el proceso: {results['error']}")
                else:
                    # Generar Links Correctos de Google Maps
                    results['ruta_a']['gmaps_link'] = generate_gmaps_link(results['ruta_a']['orden_optimo'])
                    results['ruta_b']['gmaps_link'] = generate_gmaps_link(results['ruta_b']['orden_optimo'])

                    # Guardar en DB
                    new_route = {
                        "Fecha": current_time.strftime("%Y-%m-%d"),
                        "Hora": current_time.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(all_stops_to_visit),
                        "Lotes_CamionA": str(results['ruta_a']['lotes_asignados']),
                        "Lotes_CamionB": str(results['ruta_b']['lotes_asignados']),
                        "Km_CamionA": results['ruta_a']['distancia_km'],
                        "Km_CamionB": results['ruta_b']['distancia_km'],
                    }
                    new_route["Km Totales"] = new_route["Km_CamionA"] + new_route["Km_CamionB"]

                    save_new_route_to_sheet(new_route)

                    st.session_state.historial_rutas.append(new_route)
                    st.session_state.results = results
                    st.success("Planificación completada y registrada.")

            except Exception as e:
                st.session_state.results = None
                st.error(f"Error inesperado: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS
    # -------------------------------------------------------------------------

    if st.session_state.results:
        results = st.session_state.results

        st.markdown("### Resultados de la Planificación")
        
        res_a = results.get('ruta_a', {})
        res_b = results.get('ruta_b', {})

        col_a, col_b = st.columns(2)
        
        # --- UNIDAD A ---
        with col_a:
            with st.container(border=True):
                st.markdown(f"#### 🚛 {res_a.get('nombre', 'Unidad A')}")
                st.caption(f"Patente: {res_a.get('patente', 'N/A')}")
                
                if res_a.get('mensaje'):
                    st.info("Sin asignación.")
                else:
                    c1, c2 = st.columns(2)
                    c1.metric("Distancia", f"{res_a.get('distancia_km'):.2f} km")
                    c2.metric("Paradas", len(res_a.get('lotes_asignados', [])))
                    
                    st.markdown("**Secuencia de Entrega:**")
                    orden_str = " ➤ ".join(["Base"] + res_a.get('orden_optimo', []) + ["Base"])
                    st.code(orden_str, language="text")
                    
                    st.markdown("---")
                    # BOTONES DE ACCIÓN
                    link_geo = res_a.get('geojson_link', '#')
                    link_maps = res_a.get('gmaps_link', '#')
                    gpx_data = res_a.get('gpx_data', "")

                    b1, b2 = st.columns(2)
                    b1.link_button("🌐 Ver Mapa Web", link_geo, use_container_width=True)
                    b2.download_button("💾 Bajar GPX (OsmAnd)", data=gpx_data, file_name="Ruta_A.gpx", mime="application/gpx+xml", use_container_width=True)
                    
                    st.link_button("📍 Puntos en Google Maps", link_maps, use_container_width=True)
                
        # --- UNIDAD B ---
        with col_b:
            with st.container(border=True):
                st.markdown(f"#### 🚛 {res_b.get('nombre', 'Unidad B')}")
                st.caption(f"Patente: {res_b.get('patente', 'N/A')}")
                
                if res_b.get('mensaje'):
                    st.info("Sin asignación.")
                else:
                    c1, c2 = st.columns(2)
                    c1.metric("Distancia", f"{res_b.get('distancia_km'):.2f} km")
                    c2.metric("Paradas", len(res_b.get('lotes_asignados', [])))
                    
                    st.markdown("**Secuencia de Entrega:**")
                    orden_str = " ➤ ".join(["Base"] + res_b.get('orden_optimo', []) + ["Base"])
                    st.code(orden_str, language="text")
                    
                    st.markdown("---")
                    # BOTONES DE ACCIÓN
                    link_geo = res_b.get('geojson_link', '#')
                    link_maps = res_b.get('gmaps_link', '#')
                    gpx_data = res_b.get('gpx_data', "")

                    b1, b2 = st.columns(2)
                    b1.link_button("🌐 Ver Mapa Web", link_geo, use_container_width=True)
                    b2.download_button("💾 Bajar GPX (OsmAnd)", data=gpx_data, file_name="Ruta_B.gpx", mime="application/gpx+xml", use_container_width=True)
                    
                    st.link_button("📍 Puntos en Google Maps", link_maps, use_container_width=True)

# =============================================================================
# PÁGINAS SECUNDARIAS
# =============================================================================

elif page == "Historial Operativo":
    st.title("Registro Histórico")
    st.cache_data.clear()
    df_historial = get_history_data()
    if not df_historial.empty:
        st.dataframe(df_historial, use_container_width=True, hide_index=True)
    else:
        st.info("No hay registros disponibles.")
        
elif page == "Dashboard de Estadísticas":
    st.title("Indicadores de Gestión")
    st.cache_data.clear()
    df_historial = get_history_data()

    if not df_historial.empty:
        daily_stats, monthly_stats = calculate_statistics(df_historial)

        st.subheader("Desempeño Diario")
        if not daily_stats.empty:
            st.bar_chart(daily_stats, x='Fecha_str', y=['Km_CamionA_Total', 'Km_CamionB_Total'], color=['#003366', '#FF4B4B'])

        st.subheader("Consolidado Mensual")
        if not monthly_stats.empty:
            st.dataframe(monthly_stats, use_container_width=True)
    else:
        st.info("Se requieren datos para generar indicadores.")
