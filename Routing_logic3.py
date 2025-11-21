import requests
import json
from urllib.parse import quote
from math import radians, sin, cos, sqrt, atan2
import random
import time

# =============================================================================
# 1. CONFIGURACIÓN BASE Y COORDENADAS
# =============================================================================

API_KEY = "2ce810e0-dc57-4aa4-8099-bf0e33ec48e9"
# Nota: Agregué ch.disable=true para que GraphHopper no falle si los puntos están fuera de la red vial (campo)
URL_ROUTE = f"https://graphhopper.com/api/1/route?key={API_KEY}" 
HEADERS = {'Content-Type': 'application/json'}

# COORDENADAS DEL INGENIO (Inicio y Fin)
COORDENADAS_ORIGEN = [-64.245138888888889, -23.260327777777778]

VEHICLES = {
    "AF820AB": {"name": "Camión 1 (Ruta A)"},
    "AE898TW": {"name": "Camión 2 (Ruta B)"},
}

# Diccionario de coordenadas (Tu diccionario original completo)
COORDENADAS_LOTES = {
"A01_1": [-64.254233333333332, -23.255027777777777], "A01_2": [-64.26275833333334, -23.24804166666667], "A05": [-64.25640277777778, -23.247030555555558],
"A05_2": [-64.254025, -23.249480555555557], "A06_1": [-64.246711111111111, -23.245766666666668], "A06_2": [-64.246180555555554, -23.247272222222222],
"A07_1": [-64.24048611111111, -23.244858333333333], "A07_2": [-64.24014722222222, -23.246097222222222], "A08_1": [-64.212313888888886, -23.247027777777777],
"A08_2": [-64.20845833333334, -23.243086111111111], "A08_3": [-64.203083333333339, -23.239622222222224], "A09_1": [-64.229127777777776, -23.249513888888888],
"A09_2": [-64.231513888888884, -23.247052777777778], "A09_3": [-64.231916666666663, -23.243977777777779], "A09_4": [-64.233241666666672, -23.240794444444447],
"A09_5": [-64.23063333333333, -23.239572222222222], "A10": [-64.211733333333342, -23.258305555555555], "A11": [-64.218877777777777, -23.262127777777778],
"A12": [-64.212088888888886, -23.26871388888889], "A13": [-64.231938888888891, -23.259661111111111], "A14": [-64.22719722222223, -23.265916666666666],
"A17_1": [-64.238605555555552, -23.263994444444446], "A17_2": [-64.241294444444449, -23.259813888888889], "A17_3": [-64.243452777777776, -23.26175],
"A18_1": [-64.232875, -23.271013888888888], "A18_2": [-64.228877777777782, -23.2743], "A21_1": [-64.223297222222229, -23.272861111111109],
"A21_2": [-64.218630555555563, -23.27889722222222], "A22": [-64.217616666666672, -23.272988888888889], "A26_1": [-64.22711944444444, -23.27965],
"A26_2": [-64.221427777777777, -23.279033333333331], "A26_3": [-64.218847222222223, -23.283241666666665], "A26_4": [-64.222840555555564, -23.288533333333334],
"A69_1": [-64.281747222222222, -23.27563056], "A69_2": [-64.283708333333337, -23.271686111111109], "A69_3": [-64.277205555555554, -23.276138888888887],
"A41": [-64.402366666666666, -23.251111111111111], "A45_1": [-64.264541666666673, -23.25691388888889], "A45_2": [-64.2589611111111, -23.259097222222223],
"A45_3": [-64.2605, -23.26198611111111], "A45_4": [-64.255836111111108, -23.261841666666665], "A49_1": [-64.252302777777771, -23.263213888888888],
"A49_2": [-64.253686111111108, -23.265316666666667], "A49_3": [-64.255547222222219, -23.266352777777779], "A50": [-64.247672222222221, -23.270552777777777],
"A51": [-64.241583333333338, -23.276441666666667], "A29_1": [-64.238097222222223, -23.282166666666665], "A29_2": [-64.23720833333332, -23.284733333333335],
"A30": [-64.229411111111119, -23.290780555555557], "A33_1": [-64.243513888888884, -23.288263888888892], "A33_2": [-64.237407777777776, -23.290283333333335],
"A55": [-64.249113888888886, -23.282652777777777], "A54": [-64.256119444444451, -23.275861111111109], "A53": [-64.260413888888891, -23.270105555555556],
"A61": [-64.264930555555551, -23.265855555555557], "A62_1": [-64.270480555555551, -23.259369444444445], "A62_2": [-64.270394444444449, -23.254227777777778],
"A65": [-64.273291666666665, -23.268458333333331], "A66": [-64.2765611111111, -23.272052777777777], "A74_1": [-64.272405555555551, -23.281619444444445],
"A74_2":[-64.269047222222227, -23.280011111111111], "A73_1": [-64.263908333333333, -23.278022222222223], "A73_2": [-64.258861111111116, -23.283611111111114],
"B05": [-64.27883611, -23.25469167], "B06": [-64.28556111, -23.25046944], "B07_1": [-64.28989167, -23.244875], "B07_2": [-64.29418611, -23.24563333],
"B10": [-64.29096667, -23.25751944], "B09_1": [-64.28218611, -23.25921944], "B09_2": [-64.28712778, -23.26185833], "B09_3": [-64.2837, -23.26375833],
"B22_1": [-64.29549167, -23.26170556], "B22_2": [-64.29766389, -23.26524167], "B21": [-64.28976667, -23.26921111], "B25_1": [-64.28971111, -23.27639444],
"B25_2": [-64.29582778, -23.27570278], "B26": [-64.30286389, -23.27183611], "B29_1": [-64.31462778, -23.27323333], "B29_2": [-64.30697778, -23.27561944],
"B02": [-64.29092778, -23.22938056], "B03_1": [-64.29450278, -23.21945833], "B03_2": [-64.29607222, -23.21335], "B03_3": [-64.29896667, -23.21808056],
"B01": [-64.28866389, -23.23769722], "B11_1": [-64.29810556, -23.25266944], "B11_2": [-64.29301111, -23.25046944], "B23_1": [-64.30458056, -23.262025],
"B23_2": [-64.30686389, -23.25935833], "B23_3": [-64.30243056, -23.25775278], "B27": [-64.30988333, -23.26800833], "B43": [-64.29583056, -23.22983056],
"B42": [-64.30395278, -23.22773056], "B45_1": [-64.30093333, -23.24017778], "B45_2": [-64.29969722, -23.23788056], "B45_3": [-64.29517222, -23.23766944],
"B46_1": [-64.30943056, -23.23384444], "B46_2": [-64.30601944, -23.23236944], "B51_1": [-64.31641944, -23.24205], "B51_2": [-64.31470556, -23.23896389],
"B51_3": [-64.31318889, -23.23779722], "B50_1": [-64.31118889, -23.24491111], "B50_2": [-64.30850833, -23.24146111], "B50_3": [-64.30610833, -23.24105278],
"B49_1": [-64.30613889, -23.251], "B49_2": [-64.30483333, -23.24885278], "B49_3": [-64.30315556, -23.24665556], "B49_4": [-64.30136389, -23.24470556],
"B62": [-64.32173056, -23.25151944], "B61": [-64.31205, -23.25574444], "B66": [-64.32609444, -23.25722222], "B65_1": [-64.31492222, -23.26458889],
"B65_2": [-64.31813333, -23.261925], "B70_1": [-64.33281944, -23.26483056], "B70_2": [-64.33033889, -23.26101667], "B69": [-64.32278333, -23.26843889],
"B73": [-64.337975, -23.26780556]
# ... (Asumo que el resto de tus coordenadas están aquí)
}
COORDENADAS_LOTES_REVERSO = {tuple(v): k for k, v in COORDENADAS_LOTES.items()}

# =============================================================================
# 2. FUNCIONES AUXILIARES DE CÁLCULO
# =============================================================================

def distancia_euclidiana(coord1, coord2):
    # Usamos distancia euclidiana simple para el clustering (más rápido que Haversine para esto)
    return sqrt((coord1[0] - coord2[0])**2 + (coord1[1] - coord2[1])**2)

def agrupar_lotes_k_means(lotes_nombres):
    """
    Agrupa los lotes en 2 clusters basados en cercanía espacial usando K-Means simplificado.
    """
    if len(lotes_nombres) < 2:
        return lotes_nombres, []
        
    # Obtener coordenadas
    puntos = [COORDENADAS_LOTES[lote] for lote in lotes_nombres]
    
    # 1. Inicialización: Elegir 2 centroides iniciales (usamos los dos lotes más alejados entre sí para empezar bien)
    max_dist = -1
    c1, c2 = puntos[0], puntos[1]
    for i in range(len(puntos)):
        for j in range(i + 1, len(puntos)):
            d = distancia_euclidiana(puntos[i], puntos[j])
            if d > max_dist:
                max_dist = d
                c1, c2 = puntos[i], puntos[j]
    
    centroides = [c1, c2]
    grupos_indices = [[], []]
    
    # 2. Iterar para ajustar los grupos (10 iteraciones es suficiente para convergencia en este caso)
    for _ in range(10):
        grupos_indices = [[], []]
        
        # Asignar cada punto al centroide más cercano
        for i, p in enumerate(puntos):
            dist0 = distancia_euclidiana(p, centroides[0])
            dist1 = distancia_euclidiana(p, centroides[1])
            if dist0 < dist1:
                grupos_indices[0].append(i)
            else:
                grupos_indices[1].append(i)
        
        # Recalcular centroides (promedio de las coordenadas del grupo)
        nuevos_centroides = []
        for indices in grupos_indices:
            if not indices: # Evitar grupos vacíos
                nuevos_centroides.append(centroides[0]) 
                continue
            sum_x = sum(puntos[i][0] for i in indices)
            sum_y = sum(puntos[i][1] for i in indices)
            nuevos_centroides.append([sum_x / len(indices), sum_y / len(indices)])
        
        centroides = nuevos_centroides

    # 3. Convertir índices de vuelta a nombres de lotes
    grupo_a = [lotes_nombres[i] for i in grupos_indices[0]]
    grupo_b = [lotes_nombres[i] for i in grupos_indices[1]]
    
    return grupo_a, grupo_b

def make_api_request(points_list):
    # Configuración para camión (car o truck según disponibilidad) y evitar errores de puntos fuera de ruta
    URL_ROUTE_FINAL = f"{URL_ROUTE}&ch.disable=true" 
    
    request_body = {
        "points": points_list,
        "vehicle": "car", # Si graphhopper free permite 'truck' úsalo, sino 'car'
        "locale": "es",
        "instructions": False,
        "points_encoded": False,
        "optimize": "true" # ESTO HACE LA MAGIA DEL ORDEN
    }
    try:
        response = requests.post(URL_ROUTE_FINAL, headers=HEADERS, data=json.dumps(request_body))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error API: {e}")
        return None

def generate_geojson(route_name, points_sequence, path_coordinates, total_distance_km, vehicle_id):
    features = []
    num_points = len(points_sequence)
    color_map = {"AF820AB": "#0080FF", "AE898TW": "#FF4500"}
    line_color = color_map.get(vehicle_id, "#000000")
    
    for i in range(num_points):
        coords = points_sequence[i]
        is_origin = (i == 0)
        is_destination = (i == num_points - 1)
        
        lote_name = "Ingenio"
        if not is_origin and not is_destination:
            # Buscamos el nombre del lote por coordenada
            lote_name = "Lote Desconocido"
            for name, original_coords in COORDENADAS_LOTES.items():
                # Comparamos con un pequeño margen de error por decimales
                if abs(original_coords[0] - coords[0]) < 0.00001 and abs(original_coords[1] - coords[1]) < 0.00001:
                    lote_name = name
                    break
        
        point_type = "PARADA"
        color = line_color
        symbol = str(i)
        
        if is_origin:
            point_type = "SALIDA (Ingenio)"
            color = "#008000" # Verde
            symbol = "rocket"
        elif is_destination:
            point_type = "LLEGADA (Ingenio)"
            color = "#FF0000" # Rojo
            symbol = "lodging"
            
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "name": f"{i} - {lote_name}",
                "description": point_type,
                "marker-color": color,
                "marker-symbol": symbol,
                "vehicle": vehicle_id
            }
        })
        
    features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": path_coordinates},
        "properties": {
            "name": f"{route_name} ({total_distance_km} km)",
            "stroke": line_color,
            "stroke-width": 4
        }
    })
    return {"type": "FeatureCollection", "features": features}

def generate_geojson_io_link(geojson_object):
    geojson_string = json.dumps(geojson_object, separators=(',', ':'))
    encoded_geojson = quote(geojson_string)
    return "https://geojson.io/#data=data:application/json," + encoded_geojson

# =============================================================================
# 3. FUNCIÓN PRINCIPAL
# =============================================================================

def solve_route_optimization(all_intermediate_stops):
    print(f"Procesando {len(all_intermediate_stops)} lotes...")
    
    # 1. AGRUPACIÓN POR CERCANÍA (K-MEANS)
    group_a_names, group_b_names = agrupar_lotes_k_means(all_intermediate_stops)
    
    print(f"Grupo A asignado: {len(group_a_names)} lotes")
    print(f"Grupo B asignado: {len(group_b_names)} lotes")
    
    VEHICLE_A_ID = "AF820AB"
    VEHICLE_B_ID = "AE898TW"
    results = {}

    # --- RUTA A (AF820AB) ---
    # AQUÍ SE DEFINE EL ORDEN: INGENIO -> LOTES -> INGENIO
    coords_A = [COORDENADAS_ORIGEN] + [COORDENADAS_LOTES[name] for name in group_a_names] + [COORDENADAS_ORIGEN]
    
    response_A = make_api_request(coords_A)
    if response_A:
        path_A = response_A['paths'][0]
        dist_A = round(path_A['distance'] / 1000, 2)
        order_A = path_A['points_order'] # Índices optimizados por GraphHopper
        
        # Reconstruir secuencia de nombres basada en el orden de la API
        names_input_A = ["Ingenio"] + group_a_names + ["Ingenio"]
        ordered_names_A = [names_input_A[i] for i in order_A]
        ordered_coords_A = [coords_A[i] for i in order_A]
        
        results["ruta_a"] = {
            "patente": VEHICLE_A_ID,
            "nombre": VEHICLES[VEHICLE_A_ID]['name'],
            "lotes": ordered_names_A[1:-1], # Excluimos Ingenio del listado de lotes
            "distancia_km": dist_A,
            "link_mapa": generate_geojson_io_link(generate_geojson("Ruta A", ordered_coords_A, path_A['points']['coordinates'], dist_A, VEHICLE_A_ID))
        }
    else:
        results["ruta_a"] = {"error": "Fallo API GraphHopper"}

    # Pequeña pausa para no saturar la API si es cuenta free
    time.sleep(2) 

    # --- RUTA B (AE898TW) ---
    coords_B = [COORDENADAS_ORIGEN] + [COORDENADAS_LOTES[name] for name in group_b_names] + [COORDENADAS_ORIGEN]
    
    response_B = make_api_request(coords_B)
    if response_B:
        path_B = response_B['paths'][0]
        dist_B = round(path_B['distance'] / 1000, 2)
        order_B = path_B['points_order']
        
        names_input_B = ["Ingenio"] + group_b_names + ["Ingenio"]
        ordered_names_B = [names_input_B[i] for i in order_B]
        ordered_coords_B = [coords_B[i] for i in order_B]
        
        results["ruta_b"] = {
            "patente": VEHICLE_B_ID,
            "nombre": VEHICLES[VEHICLE_B_ID]['name'],
            "lotes": ordered_names_B[1:-1],
            "distancia_km": dist_B,
            "link_mapa": generate_geojson_io_link(generate_geojson("Ruta B", ordered_coords_B, path_B['points']['coordinates'], dist_B, VEHICLE_B_ID))
        }
    else:
        results["ruta_b"] = {"error": "Fallo API GraphHopper"}

    return results

# =============================================================================
# EJECUCIÓN DE PRUEBA (Descomentar para probar)
# =============================================================================
# lotes_prueba = ["A01_1", "A01_2", "A05", "B05", "B06", "B10"] 
# print(json.dumps(solve_route_optimization(lotes_prueba), indent=2))
