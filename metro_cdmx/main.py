import os
from metro_simulation import MetroAutomata
import folium
from shapely.geometry import MultiLineString
from flask import Flask, send_file, jsonify
import json
import numpy as np
import threading
from config import SHAPEFILE_PATH, AFLUENCIA_PATH, MAP_OUTPUT_PATH, SIMULATION_INTERVAL
from history import HistoryLogger
import socket
import time

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return super().default(obj)

app = Flask(__name__)
app.json_encoder = CustomJSONEncoder
automata = None
history_logger = HistoryLogger()

def create_map():
    output_path = MAP_OUTPUT_PATH
    shp_path = SHAPEFILE_PATH
    afluencia_path = AFLUENCIA_PATH
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
            print(f"Archivo anterior eliminado: {output_path}")
        except Exception as e:
            print(f"No se pudo eliminar el archivo anterior: {e}")
    print(f"Buscando archivo shapefile en: {shp_path}")
    print(f"Buscando archivo de afluencia en: {afluencia_path}")
    if not os.path.exists(shp_path):
        print(f"Error: No se encuentra el archivo shapefile en {shp_path}")
        print("Archivos disponibles en stcmetro_shp:")
        shp_dir = os.path.dirname(shp_path)
        if os.path.exists(shp_dir):
            print(os.listdir(shp_dir))
        return
    if not os.path.exists(afluencia_path):
        print(f"Error: No se encuentra el archivo de afluencia en {afluencia_path}")
        return
    automata = MetroAutomata(shp_path, afluencia_path)
    results = automata.run_simulation(steps=10)
    automata.metro_network = automata.metro_network.to_crs(epsg=4326)
    m = folium.Map(
        location=[19.432608, -99.133208],
        zoom_start=11,
        tiles=None,
        control_scale=True
    )
    tile_claro = folium.TileLayer('cartodbpositron', name='Claro', control=True)
    tile_oscuro = folium.TileLayer('cartodbdark_matter', name='Oscuro', control=True)
    tile_claro.add_to(m)
    tile_oscuro.add_to(m)
    folium.LayerControl(position='bottomright', collapsed=False).add_to(m)
    linea_colores = {
        '1': '#FF1493', '2': '#0000FF', '3': '#808000',
        '4': '#00FFFF', '5': '#FFD700', '6': '#FF0000',
        '7': '#FFA500', '8': '#008000', '9': '#8B4513',
        '12': '#FFD700',
        'A': '#800080', 'B': '#696969'
    }
    def color_por_afluencia(afluencia, base_color):
        if afluencia < 1500:
            return "#2ecc40"
        elif afluencia < 3500:
            return "#ffd700"
        else:
            return "#ff4136"
    for _, row in automata.metro_network.iterrows():
        geom = row.geometry
        linea = str(row['LINEA'])
        color = linea_colores.get(linea, 'gray')
        if isinstance(geom, MultiLineString):
            for line in geom.geoms:
                x, y = line.xy
                coords = list(zip(y, x))
                folium.PolyLine(
                    coords,
                    weight=6,
                    color=color,
                    opacity=0.9,
                    popup=f"<b>Línea {linea}</b>"
                ).add_to(m)
                folium.PolyLine(
                    coords,
                    weight=4,
                    color='white',
                    opacity=0.7,
                    className=f'flow-line-{linea}'
                ).add_to(m)
    for station_id, station in automata.stations.items():
        coords = station['coords']
        current = station['current_people']
        nombre = station.get('nombre', station_id)
        linea = station['linea']
        color_borde = linea_colores.get(linea, 'gray')
        if current < 1500:
            estatus = "Baja"
        elif current < 3500:
            estatus = "Media"
        else:
            estatus = "Saturada"
        folium.CircleMarker(
            location=[coords[1], coords[0]],
            radius=12,
            color=color_borde,
            weight=3,
            fill=True,
            fill_color=color_borde,
            fill_opacity=0.85,
            popup=folium.Popup(f'''
                <div class="station-label" id="label-{station_id}" style="
                    background: rgba(255,255,255,0.97); border-radius: 10px; padding: 7px 14px; min-width: 120px;
                    box-shadow: 0 1px 6px rgba(0,0,0,0.10); font-size: 15px; font-family: Arial;">
                    <div style="font-weight:bold; color:{color_borde};">{nombre}</div>
                    <div><b>Línea:</b> {linea}</div>
                    <div><b>Afluencia:</b> <span class="afluencia-label" id="afluencia-{station_id}">{current:,}</span></div>
                    <div><b>Capacidad:</b> {station['capacity']:,}</div>
                    <div><b>Estatus:</b> <span class="estatus-label" id="estatus-{station_id}">{estatus}</span></div>
                </div>
            ''', max_width=300),
            tooltip=f"{nombre}",
            parse_html=True,
            attributes={
                'data-line': linea,
                'data-station-id': station_id
            }
        ).add_to(m)
    for station_id, station in automata.stations.items():
        linea = station['linea']
        color = linea_colores.get(linea, 'gray')
        for neighbor_id in automata.get_connected_stations(station_id):
            if neighbor_id in automata.stations:
                station_coords = station['coords']
                neighbor_coords = automata.stations[neighbor_id]['coords']
                folium.PolyLine(
                    locations=[[station_coords[1], station_coords[0]], 
                               [neighbor_coords[1], neighbor_coords[0]]],
                    weight=3,
                    color=color,
                    opacity=0.7,
                    dash_array='10, 15',
                    className=f'connection-line-animated line-{linea}'
                ).add_to(m)
    time_control = r"""
    <style>
        .control-panel {
            position: absolute;
            top: 16px;
            right: 16px;
            z-index: 9999;
            min-width: 900px;
            max-width: 1200px;
            background: rgba(255,255,255,0.97);
            border-radius: 16px;
            box-shadow: 0 2px 18px rgba(0,0,0,0.18);
            padding: 28px 32px 24px 32px;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        .main-btn {
            background: #0074D9;
            color: white;
            border: none;
            padding: 11px 26px;
            border-radius: 7px;
            cursor: pointer;
            font-size: 18px;
            margin: 2px 14px 2px 0;
            transition: background 0.2s;
        }
        .main-btn:hover { background: #005fa3; }
        .panel-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
        }
        .legend {
            margin: 18px 0 10px 0;
            padding: 14px 20px;
            background: #f7f7f7;
            border-radius: 10px;
            font-size: 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.07);
        }
        .legend .color-box {
            display: inline-block;
            width: 20px;
            height: 20px;
            margin-right: 10px;
            border-radius: 5px;
            vertical-align: middle;
        }
        .filter-panel {
            margin: 12px 0 18px 0;
            display: flex;
            align-items: center;
        }
        .filter-panel label {
            margin-right: 12px;
            font-size: 16px;
        }
        .filter-panel select {
            padding: 8px 16px;
            border-radius: 6px;
            border: 1px solid #bbb;
            font-size: 16px;
        }
        #afluenciaChart {
            margin-top: 22px;
            background: #fff;
            border-radius: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.07);
        }
        .panel-section {
            margin-bottom: 22px;
        }
    </style>
    <div class='control-panel' id='controlPanel'>
        <button id='togglePanelBtn' style='position:absolute;top:10px;right:10px;z-index:10001;background:#eee;border:none;border-radius:50%;width:36px;height:36px;font-size:22px;cursor:pointer;' title='Ocultar/Mostrar panel'>−</button>
        <div id='panelContent'>
        <div class='panel-row panel-section'>
            <button onclick='toggleAnimation()' class='main-btn'><span id='playPauseIcon'>▶️</span> <span id='playPauseText'>Play</span></button>
            <span id='status' style='font-weight:bold;'>Desconectado</span>
            <span id='info' style='font-size:15px;'>Actualización: <span id='countdown'>30</span>s</span>
        </div>
        <div class='panel-section filter-panel'>
            <label for='lineFilter'><b>Filtrar por línea:</b></label>
            <select id='lineFilter' onchange='filterByLine()'>
                <option value='all'>Todas</option>
                <option value='1'>Línea 1</option>
                <option value='2'>Línea 2</option>
                <option value='3'>Línea 3</option>
                <option value='4'>Línea 4</option>
                <option value='5'>Línea 5</option>
                <option value='6'>Línea 6</option>
                <option value='7'>Línea 7</option>
                <option value='8'>Línea 8</option>
                <option value='9'>Línea 9</option>
                <option value='12'>Línea 12</option>
                <option value='A'>Línea A</option>
                <option value='B'>Línea B</option>
            </select>
            <button onclick='resetFilter()' class='main-btn' style='margin-left:16px;'>Reset</button>
        </div>
        <div class='panel-section legend'>
            <div><span class='color-box' style='background:#2ecc40'></span> Baja afluencia (&lt; 1500)</div>
            <div><span class='color-box' style='background:#ffd700'></span> Media afluencia (1500 - 3499)</div>
            <div><span class='color-box' style='background:#ff4136'></span> Alta afluencia (&ge; 3500)</div>
        </div>
        <div class='panel-section' style='margin-bottom:0;'>
            <b style='font-size:18px;'>Afluencia total por línea (últimos 20 registros):</b>
            <canvas id='afluenciaChart' width='1100' height='400'></canvas>
        </div>
        </div>
    </div>
    <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
    <script>
        let isDark = false;
        let leafletMap = null;
        let tileClaro = null, tileOscuro = null;
        function getLeafletMap() {
            if (leafletMap) return leafletMap;
            for (let key in window) {
                if (window[key] && window[key].setView && window[key].addLayer && window[key].eachLayer) {
                    leafletMap = window[key];
                    break;
                }
            }
            return leafletMap;
        }
        function getBaseTiles() {
            const map = getLeafletMap();
            tileClaro = null; tileOscuro = null;
            map.eachLayer(function(layer) {
                if(layer.options && layer.options.name === 'Claro') tileClaro = layer;
                if(layer.options && layer.options.name === 'Oscuro') tileOscuro = layer;
            });
            // Si no existen, buscar en _layers
            if (!tileClaro || !tileOscuro) {
                for (let k in map._layers) {
                    let l = map._layers[k];
                    if(l.options && l.options.name === 'Claro') tileClaro = l;
                    if(l.options && l.options.name === 'Oscuro') tileOscuro = l;
                }
            }
        }
        function setMapBaseLayer(dark) {
            const map = getLeafletMap();
            getBaseTiles();
            if (!map || !tileClaro || !tileOscuro) return;
            if (dark) {
                if (map.hasLayer(tileClaro)) map.removeLayer(tileClaro);
                if (!map.hasLayer(tileOscuro)) map.addLayer(tileOscuro);
            } else {
                if (map.hasLayer(tileOscuro)) map.removeLayer(tileOscuro);
                if (!map.hasLayer(tileClaro)) map.addLayer(tileClaro);
            }
        }
        // Forzar modo claro al cargar
        window.addEventListener('load', function() {
            setTimeout(() => {
                setMapBaseLayer(false);
                isDark = false;
                const panel = document.getElementById('controlPanel');
                panel.style.background = 'rgba(255,255,255,0.97)';
                panel.style.color = 'black';
                document.body.classList.remove('dark-mode');
            }, 800);
        });
        let isPlaying = false;
        let countdownInterval;
        let countdown = 30;
        // Colores por línea para la gráfica
        const lineaColores = {
            '1': '#FF1493', '2': '#0000FF', '3': '#808000',
            '4': '#00FFFF', '5': '#FFD700', '6': '#FF0000',
            '7': '#FFA500', '8': '#008000', '9': '#8B4513',
            '12': '#FFD700',
            'A': '#800080', 'B': '#696969'
        };
        // Inicializar estructura de datos para la gráfica multiserie
        let chart;
        let chartData = {
            labels: [],
            datasets: Object.keys(lineaColores).map(linea => ({
                label: 'Línea ' + linea,
                data: [],
                borderColor: lineaColores[linea],
                backgroundColor: lineaColores[linea] + '33',
                fill: false,
                tension: 0.3
            }))
        };

        function colorPorAfluencia(afluencia) {
            if (afluencia < 1500) return "#2ecc40";
            if (afluencia < 3500) return "#ffd700";
            return "#ff4136";
        }

        let stationIdList = [];
        fetch('/station_ids')
            .then(response => response.json())
            .then(ids => { stationIdList = ids; });

        function updateStations() {
            fetch('/events')
                .then(response => response.json())
                .then(data => {
                    Object.entries(data).forEach(([stationId, people]) => {
                        document.querySelectorAll('span[id="afluencia-' + stationId + '"]').forEach(span => {
                            span.textContent = people.toLocaleString();
                        });
                        document.querySelectorAll('span[id="estatus-' + stationId + '"]').forEach(span => {
                            if (people < 1500) {
                                span.textContent = 'Baja';
                            } else if (people < 3500) {
                                span.textContent = 'Media';
                            } else {
                                span.textContent = 'Saturada';
                            }
                        });
                    });
                })
                .catch(console.error);
        }
        function updateCountdown() {
            document.getElementById('countdown').textContent = countdown;
            countdown--;
            if (countdown < 0) {
                countdown = 30;
                updateStations(); // Siempre actualizar, sin importar isPlaying
            }
        }
        function toggleAnimation() {
            isPlaying = !isPlaying;
            const statusEl = document.getElementById('status');
            const playPauseIcon = document.getElementById('playPauseIcon');
            const playPauseText = document.getElementById('playPauseText');
            if (isPlaying) {
                statusEl.textContent = 'Simulación en curso';
                countdownInterval = setInterval(updateCountdown, 1000);
                updateStations();
                playPauseIcon.textContent = '⏸️';
                playPauseText.textContent = 'Pause';
            } else {
                statusEl.textContent = 'Simulación detenida';
                clearInterval(countdownInterval);
                playPauseIcon.textContent = '▶️';
                playPauseText.textContent = 'Play';
            }
        }
        function filterByLine() {
            const selected = document.getElementById('lineFilter').value;
            // Ocultar todos los círculos primero
            document.querySelectorAll('svg.leaflet-zoom-animated circle').forEach(marker => {
                marker.style.display = 'none';
            });
            // Mostrar solo los círculos de la línea seleccionada, o todos si es 'all'
            document.querySelectorAll('svg.leaflet-zoom-animated circle').forEach(marker => {
                const markerLine = marker.getAttribute('data-line');
                if (selected === 'all' || markerLine === selected) {
                    marker.style.display = '';
                }
            });
            // Ocultar todas las líneas primero
            document.querySelectorAll('.leaflet-interactive').forEach(line => {
                line.style.display = 'none';
            });
            // Mostrar solo las líneas de la línea seleccionada, o todas si es 'all'
            document.querySelectorAll('.leaflet-interactive').forEach(line => {
                let classes = line.getAttribute('class') || '';
                if (selected === 'all') {
                    line.style.display = '';
                } else if (classes.includes('line-' + selected)) {
                    line.style.display = '';
                } else if (!classes.match(/line-\w+/)) {
                    // Siempre mostrar las líneas blancas
                    line.style.display = '';
                }
            });
            updateChart();
        }
        function resetFilter() {
            document.getElementById('lineFilter').value = 'all';
            filterByLine();
        }
        function updateChart() {
            const selected = document.getElementById('lineFilter').value;
            fetch('/history')
                .then(response => response.json())
                .then(historial => {
                    if (!Array.isArray(historial) || historial.length === 0) return;
                    const ultimos = historial.slice(-20);
                    const labels = ultimos.map(row => row.timestamp ? row.timestamp.split(' ')[1] : '');
                    if (selected === 'all') {
                        const lineas = Object.keys(lineaColores);
                        let datosPorLinea = {};
                        lineas.forEach(l => datosPorLinea[l] = []);
                        ultimos.forEach(row => {
                            lineas.forEach(l => {
                                let suma = 0;
                                Object.entries(row).forEach(([k, v]) => {
                                    if (k.startsWith('L'+l+'_')) suma += parseInt(v);
                                });
                                datosPorLinea[l].push(suma);
                            });
                        });
                        chartData.labels = labels;
                        chartData.datasets.forEach(ds => {
                            const linea = ds.label.replace('Línea ', '');
                            ds.data = datosPorLinea[linea];
                        });
                        chartData.datasets.forEach(ds => ds.hidden = false);
                    } else {
                        let datosLinea = [];
                        ultimos.forEach(row => {
                            let suma = 0;
                            Object.entries(row).forEach(([k, v]) => {
                                if (k.startsWith('L'+selected+'_')) suma += parseInt(v);
                            });
                            datosLinea.push(suma);
                        });
                        chartData.labels = labels;
                        chartData.datasets.forEach(ds => {
                            if (ds.label === 'Línea ' + selected) {
                                ds.data = datosLinea;
                                ds.hidden = false;
                            } else {
                                ds.data = [];
                                ds.hidden = true;
                            }
                        });
                    }
                    if (chart) {
                        chart.update();
                    } else {
                        const ctx = document.getElementById('afluenciaChart').getContext('2d');
                        chart = new Chart(ctx, {
                            type: 'line',
                            data: chartData,
                            options: {
                                responsive: true,
                                plugins: { legend: { display: false } },
                                scales: { y: { beginAtZero: true } }
                            }
                        });
                    }
                });
        }
        document.getElementById('lineFilter').addEventListener('change', updateChart);
        setInterval(updateChart, 3000);
        document.getElementById('togglePanelBtn').addEventListener('click', function() {
            const content = document.getElementById('panelContent');
            if (content.style.display === 'none') {
                content.style.display = '';
                this.textContent = '−';
            } else {
                content.style.display = 'none';
                this.textContent = '+';
            }
        });
        // Eliminar cualquier listener de popupopen para que NO actualice al abrir el popup
        // Solo actualizar afluencia y estatus con updateStations (cada ciclo de simulación)
        // Iniciar el temporizador de actualización al cargar la página
        setInterval(updateCountdown, 1000);
        // Asegurar que todos los círculos tengan el atributo data-line correcto al cargar el mapa
        window.addEventListener('load', function() {
            setTimeout(() => {
                fetch('/station_coords')
                  .then(r => r.json())
                  .then(stationCoords => {
                    // Obtener el mapa Leaflet
                    const map = getLeafletMap();
                    // Obtener el bounding box del mapa para transformar coordenadas a pixeles
                    const bounds = map.getBounds();
                    const topLeft = map.latLngToLayerPoint(bounds.getNorthWest());
                    const bottomRight = map.latLngToLayerPoint(bounds.getSouthEast());
                    // Emparejar círculos SVG con estaciones por posición
                    document.querySelectorAll('svg.leaflet-zoom-animated circle').forEach(marker => {
                        // Obtener posición del círculo en pixeles
                        const cx = parseFloat(marker.getAttribute('cx'));
                        const cy = parseFloat(marker.getAttribute('cy'));
                        let minDist = 999999;
                        let bestId = null;
                        Object.entries(stationCoords).forEach(([sid, info]) => {
                            // Convertir lat/lon a punto en pixeles
                            const latlng = L.latLng(info.coords[1], info.coords[0]);
                            const point = map.latLngToLayerPoint(latlng);
                            const dx = point.x - cx;
                            const dy = point.y - cy;
                            const dist = Math.sqrt(dx*dx + dy*dy);
                            if (dist < minDist) {
                                minDist = dist;
                                bestId = sid;
                            }
                        });
                        // Si la distancia es razonable (menos de 10 pixeles), asignar data-line
                        if (bestId && minDist < 10) {
                            marker.setAttribute('data-line', stationCoords[bestId].linea);
                            marker.setAttribute('data-station-id', bestId);
                        }
                    });
                  });
            }, 1200); // Espera a que el mapa y los círculos estén renderizados
        });
    </script>
    """
    m.get_root().html.add_child(folium.Element(time_control))
    m.save(output_path)
    print(f"Nuevo mapa interactivo guardado en: {output_path}")
    return output_path

@app.route('/')
def home():
    return send_file('metro_simulation.html')

@app.route('/events')
def events():
    """Endpoint para obtener actualizaciones y almacenar en el historial"""
    if not automata:
        return jsonify({'error': 'Simulación no iniciada'})
    current_state = {
        station_id: int(people)
        for station_id, people in automata.get_current_state().items()
    }
    history_logger.log(current_state)
    return jsonify(current_state)

@app.route('/history')
def history():
    """Endpoint para consultar el historial de afluencia"""
    return jsonify(history_logger.read_all())

@app.route('/stats')
def stats():
    """Endpoint para consultar estadísticas globales de la simulación actual"""
    if not automata:
        return jsonify({'error': 'Simulación no iniciada'})
    state = automata.get_current_state()
    total_afluencia = sum(state.values())
    saturadas = sum(1 for v in state.values() if v >= 3500)
    min_afluencia = min(state.values()) if state else 0
    max_afluencia = max(state.values()) if state else 0
    return jsonify({
        'total_afluencia': total_afluencia,
        'estaciones_saturadas': saturadas,
        'min_afluencia': min_afluencia,
        'max_afluencia': max_afluencia,
        'num_estaciones': len(state)
    })

@app.route('/station_ids')
def station_ids():
    if not automata:
        return jsonify([])
    return jsonify(list(automata.stations.keys()))

@app.route('/station_lines')
def station_lines():
    if not automata:
        return jsonify({})
    # Devuelve {station_id: linea}
    return jsonify({sid: s['linea'] for sid, s in automata.stations.items()})

@app.route('/station_coords')
def station_coords():
    if not automata:
        return jsonify({})
    # Devuelve {station_id: {'linea': ..., 'coords': [lon, lat]}}
    return jsonify({sid: {'linea': s['linea'], 'coords': [s['coords'][0], s['coords'][1]]} for sid, s in automata.stations.items()})

def simulation_loop():
    global automata
    while True:
        if automata:
            automata.step()
            # Guardar el estado current en el historial
            history_logger.log(automata.get_current_state())
        time.sleep(SIMULATION_INTERVAL)

def find_free_port(start_port=5000, max_tries=20):
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1
    raise RuntimeError('No free port found')

def main():
    global automata
    shp_path = SHAPEFILE_PATH
    afluencia_path = AFLUENCIA_PATH
    if not os.path.exists(shp_path):
        print(f"Error: No se encuentra el archivo shapefile en {shp_path}")
        return
    if not os.path.exists(afluencia_path):
        print(f"Error: No se encuentra el archivo de afluencia en {afluencia_path}")
        return
    automata = MetroAutomata(shp_path, afluencia_path)
    create_map()
    sim_thread = threading.Thread(target=simulation_loop, daemon=True)
    sim_thread.start()
    port = find_free_port(5000)
    print(f"Iniciando servidor en http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    main()