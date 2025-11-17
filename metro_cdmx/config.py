import os

# Rutas de archivos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHAPEFILE_PATH = os.path.join(BASE_DIR, "stcmetro_shp", "stcmetro_shp", "STC_Metro_lineas_utm14n.shp")
AFLUENCIA_PATH = os.path.join(BASE_DIR, "data-2025-06-19.csv")
MAP_OUTPUT_PATH = os.path.join(BASE_DIR, "metro_simulation.html")

# Parámetros de simulación
def get_simulation_interval():
    try:
        return int(os.environ.get('SIMULATION_INTERVAL', 2))
    except Exception:
        return 2

SIMULATION_INTERVAL = get_simulation_interval()
