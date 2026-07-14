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
        # 1. Handle compound identifiers (e.g., 'subway-138' or 'ferry-138')
        if station_id_clean.startswith('subway-'):
            clean_id = station_id_clean.replace('subway-', '')
            matched_station = next((s for s in transit_engine.train_times_cache if s['station_id'] == clean_id), None)
            if matched_station:
                return jsonify([matched_station])

        elif station_id_clean.startswith('ferry-'):
            clean_id = station_id_clean.replace('ferry-', '')
            matched_station = next((s for s in transit_engine.ferry_times_cache if s['station_id'] == clean_id), None)
            if matched_station:
                return jsonify([matched_station])

        # 2. Fallback for raw numeric IDs or legacy lookups
        combined = transit_engine.train_times_cache + transit_engine.ferry_times_cache

        # Look for a pure, direct cache identifier match
        matched_station = next((s for s in combined if s['station_id'] == station_id_clean), None)

        # Try matching against the suffix of the complex key (e.g. matching '87' to 'FERRY-STATION-87')
        if not matched_station:
            matched_station = next((s for s in combined if s['station_id'].endswith(f"-{station_id_clean}")), None)

        # Dynamic reverse lookup: If the frontend sends a full master ID string, match it by suffix
        if not matched_station:
            matched_station = next((s for s in combined if station_id_clean.endswith(f"-{s['station_id']}")), None)

        if matched_station:
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

            # Build line label for display in dropdown
            # e.g., "G" or "123/456/ACE/JZ"
            lines_dict = s.get('lines', {})
            source = s.get('source', 'subway')
            if lines_dict:
                line_labels = sorted(lines_dict.keys())
                line_label = '/'.join(line_labels)
            else:
                line_label = None

            station_list.append({
                # 1. Keep this compound string key unique to keep the React option keys happy
                'station_id': f"{s.get('source', 'subway')}-{s['station_id']}",
                # 2. Hand over the clean, raw identifier string the tracking loops expect
                'raw_id': raw_id,
                'name': s['name'],
                'source': s.get('source', 'subway'),
                'line_label': line_label
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
