import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import os
import time
import json
import gspread

# =============================================================================
# IMPORTACIONES DEL CEREBRO (ROUTING_LOGIC3)
# =============================================================================
# Nota: Ya no necesitamos importar las funciones de geojson aquí, 
# porque el archivo logic3 ya nos devuelve el link listo.
from Routing_logic3 import (
    COORDENADAS_LOTES, 
    solve_route_optimization, 
    VEHICLES, 
    COORDENADAS_ORIGEN
)

# =============================================================================
# CONFIGURACIÓN INICIAL
# =============================================================================

st.set_page_config(page_title="Optimizador Bimodal de Rutas", layout="wide")

# --- ZONA HORARIA ARGENTINA (GMT-3) ---
ARG_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Estilos CSS
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# Encabezados en el orden de Google Sheets
COLUMNS = ["Fecha", "Hora", "LotesIngresados", "Lotes_CamionA", "Lotes_CamionB", "Km_CamionA", "Km_CamionB", "Km Totales"]

# =============================================================================
# FUNCIONES AUXILIARES DE LA APP
# =============================================================================

def generate_gmaps_link(stops_order):
    """
    Genera un enlace de Google Maps para navegación visual (humana).
    NOTA: Google Maps recalculará la ruta por calles públicas.
    Sirve para guiar al chofer de un punto a otro, pero la distancia
    calculada por nuestro sistema (KML) es la que vale para el reporte.
    """
    if not stops_order:
        return '#'

    # COORDENADAS_ORIGEN es (lon, lat). GMaps requiere lat,lon.
    lon_orig, lat_orig = COORDENADAS_ORIGEN
    
    route_parts = [f"{lat_orig},{lon_orig}"] # Origen
    
    # Añadir paradas intermedias
    for stop_lote in stops_order:
        if stop_lote in COORDENADAS_LOTES:
            lon, lat = COORDENADAS_LOTES[stop_lote]
            route_parts.append(f"{lat},{lon}") # lat,lon

    # Añadir destino final (regreso al origen)
    route_parts.append(f"{lat_orig},{lon_orig}")

    # Une las partes con '/' para la URL de Google Maps directions
    # Usamos un formato universal de maps
    return f"https://www.google.com/maps/dir/" + "/".join(route_parts)


# =============================================================================
# CONEXIÓN GOOGLE SHEETS (MANTENIDA EXACTA)
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
        gc = gspread.service_account_from_dict(credentials_dict)
        return gc
    except Exception as e:
        st.error(f"❌ Error fatal al inicializar GSheets: {e}")
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
        if df.empty or len(df.columns) < len(COLUMNS): return pd.DataFrame(columns=COLUMNS)
        return df
    except Exception as e:
        st.error(f"❌ Error leyendo historial: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_new_route_to_sheet(new_route_data):
    client = get_gspread_client()
    if not client:
        st.warning("No se pudo guardar en GSheets (Error Cliente).")
        return

    try:
        sh = client.open_by_url(st.secrets["GOOGLE_SHEET_URL"])
        worksheet = sh.worksheet(st.secrets["SHEET_WORKSHEET"])
        values_to_save = [new_route_data[col] for col in COLUMNS]
        worksheet.append_row(values_to_save)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error guardando ruta: {e}")


# =============================================================================
# LÓGICA DE ESTADÍSTICAS
# =============================================================================

def calculate_statistics(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    df['Fecha'] = pd.to_datetime(df['Fecha'])
    df['Mes'] = df['Fecha'].dt.to_period('M')

    def count_lotes(x):
        try: return len(str(x).split(',')) if x else 0
        except: return 0

    def count_assigned(x):
        try: 
            clean = str(x).replace('[','').replace(']','').replace("'", "")
            return len([i for i in clean.split(',') if i.strip()])
        except: return 0

    df['Total_Ingresados'] = df['LotesIngresados'].apply(count_lotes)
    df['Total_Asignados'] = df['Lotes_CamionA'].apply(count_assigned) + df['Lotes_CamionB'].apply(count_assigned)
    
    # Convertir KM a numérico
    for col in ['Km_CamionA', 'Km_CamionB', 'Km Totales']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Agregación Diaria
    daily = df.groupby('Fecha').agg({
        'Fecha': 'count',
        'Total_Asignados': 'sum',
        'Km Totales': 'sum'
    }).rename(columns={'Fecha': 'Rutas', 'Km Totales': 'Km_Dia'}).reset_index()
    daily['Fecha_str'] = daily['Fecha'].dt.strftime('%Y-%m-%d')

    # Agregación Mensual
    monthly = df.groupby('Mes').agg({
        'Fecha': 'count',
        'Total_Asignados': 'sum',
        'Km Totales': 'sum'
    }).rename(columns={'Fecha': 'Rutas', 'Km Totales': 'Km_Mes'}).reset_index()
    monthly['Mes_str'] = monthly['Mes'].astype(str)

    return daily, monthly

# =============================================================================
# SESIÓN Y MENÚ
# =============================================================================

if 'historial_cargado' not in st.session_state:
    st.cache_data.clear()
    df_history = get_history_data()
    st.session_state.historial_rutas = df_history.to_dict('records')
    st.session_state.historial_cargado = True

if 'results' not in st.session_state:
    st.session_state.results = None

st.sidebar.image("https://raw.githubusercontent.com/mkzmh/Optimizator-historial/main/LOGO%20CN%20GRUPO%20COLOR%20(1).png", use_container_width=True)
st.sidebar.title("Menú")
page = st.sidebar.radio("Ir a:", ["Calcular Nueva Ruta", "Historial", "Estadísticas"])
st.sidebar.divider()
st.sidebar.info(f"💾 Rutas en Historial: {len(st.session_state.historial_rutas)}")


# =============================================================================
# PÁGINA 1: CALCULAR RUTA
# =============================================================================

if page == "Calcular Nueva Ruta":
    
    st.title("🚚 Optimizador de Rutas (Interno)")
    st.markdown("**Sistema Bimodal:** Usa mapa interno (KML) para cálculo exacto y Google Maps para navegación visual.")
    
    st.markdown("---")

    lotes_input = st.text_input(
        "📍 Ingrese Lotes (separados por coma):",
        placeholder="Ej: A05, B10, C95"
    )

    # Procesamiento de entrada
    all_stops = [l.strip().upper() for l in lotes_input.split(',') if l.strip()]
    valid_stops = [l for l in all_stops if l in COORDENADAS_LOTES]
    invalid_stops = [l for l in all_stops if l not in COORDENADAS_LOTES]

    # Columnas de info
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if valid_stops:
            map_data = [{'lat': COORDENADAS_ORIGEN[1], 'lon': COORDENADAS_ORIGEN[0], 'name': 'INGENIO'}]
            for l in valid_stops:
                coords = COORDENADAS_LOTES[l]
                map_data.append({'lat': coords[1], 'lon': coords[0], 'name': l})
            
            st.map(pd.DataFrame(map_data), size=20, color='#0044ff')
        else:
            st.info("Ingrese lotes válidos para visualizar el mapa.")

    with col2:
        st.metric("Lotes Válidos", len(valid_stops))
        if invalid_stops:
            st.error(f"Inválidos: {', '.join(invalid_stops)}")

    # BOTÓN DE CÁLCULO
    can_calculate = len(valid_stops) >= 1
    
    if st.button("🚀 Optimizar Recorrido", type="primary", disabled=not can_calculate):
        
        with st.spinner('Consultando Mapa KML y calculando rutas óptimas...'):
            try:
                # --- LLAMADA AL CEREBRO ---
                results = solve_route_optimization(valid_stops)

                if "error" in results:
                    st.error(results['error'])
                else:
                    # Generamos links visuales de GMaps (Para el chofer)
                    # Nota: routing_logic3 ya nos dio el orden óptimo
                    if 'ruta_a' in results and 'orden_optimo' in results['ruta_a']:
                        results['ruta_a']['gmaps_link'] = generate_gmaps_link(results['ruta_a']['orden_optimo'])
                    
                    if 'ruta_b' in results and 'orden_optimo' in results['ruta_b']:
                        results['ruta_b']['gmaps_link'] = generate_gmaps_link(results['ruta_b']['orden_optimo'])

                    # Guardar en Historial
                    current_time = datetime.now(ARG_TZ)
                    new_route = {
                        "Fecha": current_time.strftime("%Y-%m-%d"),
                        "Hora": current_time.strftime("%H:%M:%S"),
                        "LotesIngresados": ", ".join(all_stops),
                        "Lotes_CamionA": str(results.get('ruta_a', {}).get('lotes_asignados', [])),
                        "Lotes_CamionB": str(results.get('ruta_b', {}).get('lotes_asignados', [])),
                        "Km_CamionA": results.get('ruta_a', {}).get('distancia_km', 0),
                        "Km_CamionB": results.get('ruta_b', {}).get('distancia_km', 0),
                    }
                    new_route["Km Totales"] = new_route["Km_CamionA"] + new_route["Km_CamionB"]
                    
                    save_new_route_to_sheet(new_route)
                    st.session_state.historial_rutas.append(new_route)
                    st.session_state.results = results
                    st.success("✅ ¡Ruta Calculada y Guardada!")

            except Exception as e:
                st.error(f"Ocurrió un error inesperado: {e}")

    # MOSTRAR RESULTADOS
    if st.session_state.results:
        res = st.session_state.results
        st.divider()
        
        st.subheader("Resultados del Cálculo")
        
        col_a, col_b = st.columns(2)

        # RUTA A
        with col_a:
            ra = res.get('ruta_a', {})
            st.info(f"🚛 {ra.get('nombre', 'Camión A')}")
            if 'error' in ra:
                st.warning(ra['error'])
            elif 'mensaje' in ra:
                st.write(ra['mensaje'])
            else:
                st.write(f"**Distancia Real (Interna):** {ra['distancia_km']} km")
                st.write(f"**Paradas:** {len(ra['lotes_asignados'])}")
                st.code(" -> ".join(ra['orden_optimo']))
                
                # Botones de acción
                c1, c2 = st.columns(2)
                with c1:
                    st.link_button("🗺️ Ver Mapa Trazado", ra.get('geojson_link', '#'))
                with c2:
                    st.link_button("📍 Navegar (GMaps)", ra.get('gmaps_link', '#'))

        # RUTA B
        with col_b:
            rb = res.get('ruta_b', {})
            st.error(f"🚚 {rb.get('nombre', 'Camión B')}")
            if 'error' in rb:
                st.warning(rb['error'])
            elif 'mensaje' in rb:
                st.write(rb['mensaje'])
            else:
                st.write(f"**Distancia Real (Interna):** {rb['distancia_km']} km")
                st.write(f"**Paradas:** {len(rb['lotes_asignados'])}")
                st.code(" -> ".join(rb['orden_optimo']))
                
                # Botones de acción
                c1, c2 = st.columns(2)
                with c1:
                    st.link_button("🗺️ Ver Mapa Trazado", rb.get('geojson_link', '#'))
                with c2:
                    st.link_button("📍 Navegar (GMaps)", rb.get('gmaps_link', '#'))


# =============================================================================
# PÁGINA 2: HISTORIAL
# =============================================================================

elif page == "Historial":
    st.header("📋 Historial de Operaciones")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No hay registros aún.")

# =============================================================================
# PÁGINA 3: ESTADÍSTICAS
# =============================================================================

elif page == "Estadísticas":
    st.header("📊 Panel de Control")
    df = pd.DataFrame(st.session_state.historial_rutas)
    if not df.empty:
        d, m = calculate_statistics(df)
        
        st.subheader("Evolución Diaria")
        st.bar_chart(d, x='Fecha_str', y='Km_Dia')
        
        st.subheader("Datos Mensuales")
        st.dataframe(m, use_container_width=True)
    else:
        st.info("Se requieren datos para generar estadísticas.")
