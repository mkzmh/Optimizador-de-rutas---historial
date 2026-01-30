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
# 2. CONFIGURACIÓN INICIAL
# =============================================================================
st.set_page_config(
    page_title="Sistema de Gestión Logística", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# Estilos Visuales
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 8px; }
    div.stButton > button[kind="primary"] { background-color: #003366 !important; color: white !important; width: 100%; border-radius: 6px; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e0e0e0; }
    </style>
    """, unsafe_allow_html=True)

# =============================================================================
# 3. CONEXIÓN A GOOGLE SHEETS (Sincronización Corregida)
# =============================================================================

@st.cache_resource(ttl=3600)
def get_gspread_client():
    try:
        # Limpieza de clave: maneja comillas triples y saltos de línea \\n
        pk = st.secrets["gsheets_private_key"].strip()
        if "\\n" in pk:
            pk = pk.replace("\\n", "\n")
        
        # Validar formato mínimo
        if "-----BEGIN PRIVATE KEY-----" not in pk:
            st.error("Error: La clave privada en Secrets no tiene el formato BEGIN/END.")
            return None

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
        st.error(f"Fallo de Autenticación: {e}")
        return None

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client: return
    try:
        # Conexión directa usando la URL de Secrets
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        
        # Crear la fila respetando el orden de COLUMNS
        row_values = [new_route_data.get(col, "") for col in COLUMNS]
        
        # Escribir en la hoja
        worksheet.append_row(row_values)
        st.toast("✅ Registro guardado en Google Sheets", icon="💾")
        
        # Limpiar caché para que el historial se actualice
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al escribir en Google Sheets: {e}. Revisa si el nombre de la hoja es '{st.secrets['SHEET_WORKSHEET']}'")

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
# 4. FUNCIONES DE APOYO
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
    df['Mes'] = df['Fecha'].dt.to_period('M')
    
    def safe_count(x):
        try: return len([i for i in str(x).replace('[','').replace(']','').replace("'", "").split(',') if i.strip()])
        except: return 0

    df['Total_Lotes'] = df['Lotes_CamionA'].apply(safe_count) + df['Lotes_CamionB'].apply(safe_count)
    for c in ['Km_CamionA', 'Km_CamionB']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['Km_Total'] = df['Km_CamionA'] + df['Km_CamionB']

    daily = df.groupby('Fecha').agg({'Fecha':'count', 'Total_Lotes':'sum', 'Km_Total':'sum'}).rename(columns={'Fecha':'Rutas'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')
    return daily, df.groupby('Mes').agg({'Fecha':'count', 'Km_Total':'sum'}).reset_index()

# =============================================================================
# 5. ESTRUCTURA DE LA APP Y NAVEGACIÓN
# =============================================================================

# Cargar historial inicial
if 'historial_cargado' not in st.session_state:
    df_hist = get_history_data()
    st.session_state.historial_rutas = df_hist.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
    st.markdown("### Navegación")
    page = st.radio("Módulos", ["Planificación Operativa", "Historial", "Estadísticas"])
    
    st.markdown("---")
    st.markdown("### 🛠 Herramientas")
    if st.button("🔄 Test Conexión Sheets"):
        c = get_gspread_client()
        if c:
            try:
                sh = c.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
                st.success(f"Conectado a:\n{sh.title}")
            except Exception as e:
                st.error(f"Error: {e}")
        else:
            st.error("Error de credenciales")

# -----------------------------------------------------------------------------
# PÁGINA: PLANIFICACIÓN
# -----------------------------------------------------------------------------
if page == "Planificación Operativa":
    st.title("Optimizador de Rutas")
    lotes_input = st.text_input("Ingreso de Lotes", placeholder="Ej: A05, B10, C95")
    
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    
    col1, col2 = st.columns(2)
    col1.metric("Lotes Válidos", len(valid_stops))
    col2.metric("No Identificados", len(all_stops) - len(valid_stops))

    if st.button("Optimizar y Registrar en Sheets", type="primary", disabled=not valid_stops):
        with st.spinner("Procesando distribución óptima..."):
            results = solve_route_optimization(valid_stops)
            st.session_state.results = results
            
            if "error" not in results:
                now = datetime.now(ARG_TZ)
                ra, rb = results.get('ruta_a', {}), results.get('ruta_b', {})
                
                # Datos para enviar a Sheets
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
                
                # GUARDADO EN LA NUBE
                save_new_route_to_sheet(new_entry)
                
                # Actualizar historial local
                st.session_state.historial_rutas.append(new_entry)
                st.success("✅ ¡Operación registrada exitosamente!")

    if st.session_state.results and "error" not in st.session_state.results:
        st.markdown("---")
        res = st.session_state.results
        ca, cb = st.columns(2)
        for i, key in enumerate(['ruta_a', 'ruta_b']):
            r = res.get(key, {})
            with [ca, cb][i]:
                with st.container(border=True):
                    st.subheader(f"🚛 Unidad {['1', '2'][i]}: {r.get('patente')}")
                    if not r.get('lotes_asignados'):
                        st.info("Sin lotes asignados.")
                    else:
                        st.metric("Kilómetros", f"{r.get('distancia_km')} km")
                        st.code(" ➤ ".join(["Ingenio"] + r.get('orden_optimo', []) + ["Ingenio"]))
                        st.link_button("📍 Abrir en Google Maps", generate_gmaps_link(r.get('orden_optimo', [])), type="primary")

# -----------------------------------------------------------------------------
# PÁGINA: HISTORIAL
# -----------------------------------------------------------------------------
elif page == "Historial":
    st.title("Historial de Rutas (Google Sheets)")
    
    if st.button("🔄 Refrescar desde la Nube"):
        st.cache_data.clear()
        df_hist = get_history_data()
        st.session_state.historial_rutas = df_hist.to_dict('records')
        st.rerun()

    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        st.dataframe(df.sort_values(by=['Fecha', 'Hora'], ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No se encontraron registros en Google Sheets.")

# -----------------------------------------------------------------------------
# PÁGINA: ESTADÍSTICAS
# -----------------------------------------------------------------------------
elif page == "Estadísticas":
    st.title("Indicadores Logísticos")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        daily, monthly = calculate_statistics(df)
        st.subheader("Kilómetros Totales por Día")
        st.bar_chart(daily, x='Fecha_str', y='Km_Total')
        st.subheader("Consolidado por Fecha")
        st.dataframe(daily, use_container_width=True, hide_index=True)
    else:
        st.info("Sin datos para mostrar estadísticas.")
