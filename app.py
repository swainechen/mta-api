import os
from flask import Flask, jsonify
from flask_cors import CORS
from metadata import TransitMetadata
from engine import TransitEngine

app = Flask(__name__)
CORS(app)

meta_store = TransitMetadata()
transit_engine = TransitEngine(meta_store)

print("Seeding live transit cache arrays...")
transit_engine.refresh()
transit_engine.start_background_loop(interval=30)
print("Background cache loop running smoothly.")

@app.route('/')
@app.route('/api/')
def homepage():
    return 'Welcome to SubwayApi'

@app.route('/api/train_times/')
def train_times():
    with transit_engine.lock:
        return jsonify(transit_engine.train_times_cache)

@app.route('/api/ferry_times/')
def ferry_times():
    with transit_engine.lock:
        return jsonify(transit_engine.ferry_times_cache)

@app.route('/api/times/')
def all_times():
    with transit_engine.lock:
        return jsonify(transit_engine.train_times_cache + transit_engine.ferry_times_cache)

@app.route('/api/times/<station_id>')
def next_all(station_id):
    station_id_clean = str(station_id).strip()
    
    with transit_engine.lock:
        combined = transit_engine.train_times_cache + transit_engine.ferry_times_cache
        
        # 1. Look for a pure, direct cache identifier match
        matched_station = next((s for s in combined if s['station_id'] == station_id_clean), None)
        
        # 2. Try matching against the suffix of the complex key (e.g. matching '87' to 'FERRY-STATION-87')
        if not matched_station:
            matched_station = next((s for s in combined if s['station_id'].endswith(f"-{station_id_clean}")), None)
            
        # 3. Dynamic reverse lookup: If the frontend sends a full master ID string, match it by suffix
        if not matched_station:
            matched_station = next((s for s in combined if station_id_clean.endswith(f"-{s['station_id']}")), None)
            
        if matched_station:
            # Return wrapped inside an array block to ensure cross-version compatibility
            return jsonify([matched_station])
            
    # Fallback skeleton framework object safe containment
    station_name = meta_store.stop_names.get(station_id_clean, f"Station {station_id_clean}")
    return jsonify([{
        'station_id': station_id_clean,
        'name': station_name,
        'lines': {},
        'trains': [],
        'source': 'ferry' if station_id_clean.isdigit() and int(station_id_clean) < 200 else 'subway'
    }])

@app.route('/api/stations/')
def stops():
    with transit_engine.lock:
        combined = transit_engine.train_times_cache + transit_engine.ferry_times_cache
        
        station_list = []
        for s in combined:
            # Extract the pure structural master identifier from the complex string key
            # (e.g., converts 'SUBWAY-COMPLEX-229' -> '229' or 'FERRY-STATION-87' -> '87')
            raw_id = s['station_id'].split('-')[-1]
            
            station_list.append({
                # 1. Keep this compound string key unique to keep the React option keys happy
                'station_id': f"{s.get('source', 'subway')}-{s['station_id']}",
                # 2. Hand over the clean, raw identifier string the tracking loops expect
                'raw_id': raw_id,
                'name': s['name'],
                'source': s.get('source', 'subway')
            })
            
        return jsonify(station_list)

if __name__ == "__main__":
    try:
        import bjoern
        print("Starting production Bjoern server on port 5280...")
        bjoern.run(app, "0.0.0.0", 5280)
    except ImportError:
        print("Bjoern not found. Falling back to native Flask testing server...")
        app.run(host="127.0.0.1", port=5280, debug=False, use_reloader=False)
