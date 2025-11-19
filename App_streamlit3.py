import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread

# =============================================================================
# 1. IMPORTACIONES LÓGICAS
# =============================================================================
from Routing_logic3 import (
    COORDENADAS_LOTES, 
    solve_route_optimization, 
    VEHICLES, 
    COORDENADAS_ORIGEN
)

# =============================================================================
# 2. CONFIGURACIÓN CORPORATIVA
# =============================================================================

st.set_page_config(
    page_title="Sistema de Gestión Logística", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# --- ESTILOS CSS CORPORATIVOS (Clean & Professional) ---
st.markdown("""
    <style>
    /* Ocultar elementos default de Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Estilo de Tarjetas de Métricas */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 5px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    
    /* Títulos más sobrios */
    h1 {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-weight: 600;
        color: #2c3e50;
        font-size: 2.2rem;
        padding-bottom: 10px;
        border-bottom: 1px solid #eee;
    }
    h3 {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #34495e;
        font-weight: 500;
    }
    
    /* Botones Primarios estilo Enterprise */
    div.stButton > button:first-child {
        background-color: #003366;
        color: white;
        border-radius: 4px;
        border: none;
        padding: 10px 24px;
        font-weight: 500;
    }
    div.stButton > button:first-child:hover {
        background-color: #002244;
        border: none;
    }
    
    /* Ajuste de contenedores */
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
        gap: 1rem;
    }
    </style>
    """, unsafe_allow_html=True)

COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# =============================================================================
# 3. FUNCIONES AUXILIARES
# =============================================================================

def generate_gmaps_link(stops_order_names):
    if not stops_order_names: return '#'
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    route_parts = [f"{lat_orig},{lon_orig}"] 
    for lote_nombre in stops_order_names:
        if lote_nombre in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[lote_nombre]
            route_parts.append(f"{lat},{lon}")
    route_parts.append(f"{lat_orig},{lon_orig}")
    return f"https://www.google.com/maps/dir/" + "/".join(route_parts)

# =============================================================================
# 4. CONEXIÓN GOOGLE SHEETS
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
    except Exception:
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
        st.error(f"Error de registro en base de datos: {e}")

@st.cache_data(ttl=3600)
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
# 5. LÓGICA DE ESTADÍSTICAS
# =============================================================================

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
    for col in ['Km_CamionA', 'Km_CamionB', 'Km Totales']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    daily = df.groupby('Fecha').agg({'Fecha':'count', 'Total_Asignados':'sum', 'Km Totales':'sum'}).rename(columns={'Fecha':'Operaciones'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    
    monthly = df.groupby('Mes').agg({'Fecha':'count', 'Total_Asignados':'sum', 'Km Totales':'sum'}).rename(columns={'Fecha':'Operaciones'}).reset_index()
    monthly['Mes_str'] = monthly['Mes'].astype(str)
    return daily, monthly

# =============================================================================
# 6. NAVEGACIÓN Y SESIÓN
# =============================================================================

if 'historial_cargado' not in st.session_state:
    st.cache_data.clear()
    df_hist = get_history_data()
    st.session_state.historial_rutas = df_hist.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

# --- SIDEBAR CORPORATIVO ---
with st.sidebar:
    # Logo más pequeño y limpio
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.markdown("### Panel de Control")
    page = st.radio("Módulos", ["Planificación Operativa", "Registro Histórico", "Indicadores de Gestión"])
    
    st.markdown("---")
    st.caption(f"Base de Datos: **Conectada**")
    st.caption(f"Registros Totales: **{len(st.session_state.historial_rutas)}**")
    st.caption("v3.1.0 - Enterprise Edition")

# =============================================================================
# PÁGINA 1: PLANIFICACIÓN (CALCULAR)
# =============================================================================

if page == "Planificación Operativa":
    st.title("Sistema de Optimización Logística")
    st.markdown("#### Configuración de Despacho Diario")
    
    # Input estilizado
    with st.container():
        lotes_input = st.text_input("Puntos de Entrega (Códigos de Lote)", placeholder="Ingrese códigos separados por coma (Ej: A05, B10, C95)")
    
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

    # Panel de Estado
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Lotes Identificados", len(valid_stops))
    c2.metric("Lotes Desconocidos", len(invalid_stops), delta_color="inverse")
    
    if invalid_stops:
        c3.warning(f"Verificar códigos: {', '.join(invalid_stops)}")

    # Mapa de Previsualización (Solo si hay datos)
    if valid_stops:
        with st.expander("🗺️ Visualizar Ubicación de Lotes", expanded=False):
            map_data = [{'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0], 'name': 'BASE OPERATIVA', 'color':'#000000'}]
            for l in valid_stops:
                coords = COORDENADAS_LOTES[l]
                map_data.append({'lat': coords[1], 'lon': coords[0], 'name': l, 'color':'#0044ff'})
            st.map(pd.DataFrame(map_data), size=20, color='color')

    st.markdown("---")
    
    # Botón Principal
    col_btn, col_space = st.columns([1, 4])
    with col_btn:
        calculate = st.button("Ejecutar Optimización", type="primary", disabled=len(valid_stops)==0, use_container_width=True)

    if calculate:
        with st.spinner("Procesando red logística y calculando rutas óptimas..."):
            try:
                results = solve_route_optimization(valid_stops)
                st.session_state.results = results

                if "error" not in results:
                    now = datetime.now(ARG_TZ)
                    ra = results.get('ruta_a', {})
                    rb = results.get('ruta_b', {})
                    
                    new_entry = {
                        "Fecha": now.strftime("%Y-%m-%d"),
                        "Hora": now.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(valid_stops),
                        "Lotes_CamionA": str(ra.get('lotes_asignados', [])),
                        "Lotes_CamionB": str(rb.get('lotes_asignados', [])),
                        "Km_CamionA": ra.get('distancia_km', 0),
                        "Km_CamionB": rb.get('distancia_km', 0),
                    }
                    new_entry["Km Totales"] = new_entry["Km_CamionA"] + new_entry["Km_CamionB"]
                    
                    save_new_route_to_sheet(new_entry)
                    st.session_state.historial_rutas.append(new_entry)
                    st.success("Planificación completada y registrada exitosamente.")

            except Exception as e:
                st.error(f"Error crítico en el proceso: {e}")

    # --- RESULTADOS ---
    if st.session_state.results:
        res = st.session_state.results
        
        if "error" in res:
            st.error(res['error'])
        else:
            st.markdown("### Resultados de la Planificación")
            
            # Contenedor de resultados
            col_a, col_b = st.columns(2)
            
            # UNIDAD A
            with col_a:
                ra = res.get('ruta_a', {})
                with st.container(border=True):
                    st.markdown(f"#### {ra.get('nombre', 'Unidad A')}")
                    st.markdown(f"**Patente:** {ra.get('patente', 'N/A')}")
                    
                    if ra.get('mensaje'):
                        st.info("Sin asignación de carga.")
                    else:
                        kpi1, kpi2 = st.columns(2)
                        kpi1.metric("Distancia Est.", f"{ra.get('distancia_km',0)} km")
                        kpi2.metric("Paradas", len(ra.get('lotes_asignados', [])))
                        
                        st.markdown("**Secuencia Operativa:**")
                        seq_str = " ➤ ".join(["Base"] + ra.get('orden_optimo', []) + ["Base"])
                        st.caption(seq_str)
                        
                        # Acciones
                        st.markdown("##### Exportar Datos")
                        gpx_data = ra.get('gpx_data', "")
                        link_maps = generate_gmaps_link(ra.get('orden_optimo', []))
                        
                        b1, b2 = st.columns(2)
                        b1.download_button("💾 Archivo GPS (.gpx)", data=gpx_data, file_name="Ruta_A.gpx", mime="application/gpx+xml", use_container_width=True)
                        b2.link_button("🌐 Visualizar Web", ra.get('geojson_link', '#'), use_container_width=True)
                        st.link_button("📍 Puntos de Referencia (Google Maps)", link_maps, use_container_width=True)

            # UNIDAD B
            with col_b:
                rb = res.get('ruta_b', {})
                with st.container(border=True):
                    st.markdown(f"#### {rb.get('nombre', 'Unidad B')}")
                    st.markdown(f"**Patente:** {rb.get('patente', 'N/A')}")
                    
                    if rb.get('mensaje'):
                        st.info("Sin asignación de carga.")
                    else:
                        kpi1, kpi2 = st.columns(2)
                        kpi1.metric("Distancia Est.", f"{rb.get('distancia_km',0)} km")
                        kpi2.metric("Paradas", len(rb.get('lotes_asignados', [])))
                        
                        st.markdown("**Secuencia Operativa:**")
                        seq_str = " ➤ ".join(["Base"] + rb.get('orden_optimo', []) + ["Base"])
                        st.caption(seq_str)
                        
                        # Acciones
                        st.markdown("##### Exportar Datos")
                        gpx_data = rb.get('gpx_data', "")
                        link_maps = generate_gmaps_link(rb.get('orden_optimo', []))
                        
                        b1, b2 = st.columns(2)
                        b1.download_button("💾 Archivo GPS (.gpx)", data=gpx_data, file_name="Ruta_B.gpx", mime="application/gpx+xml", use_container_width=True)
                        b2.link_button("🌐 Visualizar Web", rb.get('geojson_link', '#'), use_container_width=True)
                        st.link_button("📍 Puntos de Referencia (Google Maps)", link_maps, use_container_width=True)

        with st.expander("Ver logs del sistema"):
            st.json(res)

# =============================================================================
# PÁGINA 2: HISTORIAL
# =============================================================================
elif page == "Registro Histórico":
    st.title("Registro Histórico de Operaciones")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        st.dataframe(
            df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Km_CamionA": st.column_config.NumberColumn("Km Unidad A", format="%.2f"),
                "Km_CamionB": st.column_config.NumberColumn("Km Unidad B", format="%.2f"),
                "Km Totales": st.column_config.NumberColumn("Km Totales", format="%.2f"),
            }
        )
    else:
        st.info("No se encontraron registros previos.")

# =============================================================================
# PÁGINA 3: ESTADÍSTICAS
# =============================================================================
elif page == "Indicadores de Gestión":
    st.title("Indicadores Clave de Desempeño (KPIs)")
    df = pd.DataFrame(st.session_state.historial_rutas)
    
    if not df.empty:
        day, month = calculate_statistics(df)
        
        st.subheader("Desempeño Diario")
        st.bar_chart(day, x='Fecha_str', y='Km_Dia', color="#003366")
        
        st.subheader("Consolidado Mensual")
        st.dataframe(
            month, 
            use_container_width=True,
            column_config={
                "Km_Mes": st.column_config.NumberColumn("Km Totales", format="%.2f"),
                "Mes_str": "Período"
            }
        )
    else:
        st.info("Se requieren datos operativos para generar los indicadores.")
