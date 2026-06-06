import csv
import os

class TransitMetadata:
    def __init__(self):
        self.trips = {}             # trip_id -> {route_id, direction_id, headsign}
        self.stop_names = {}         # stop_id -> stop_name
        self.stops_by_trip = {}      # trip_id -> list of {'stop_id', 'arrival_seconds'}
        self.merged_station_map = {} # raw_stop_id -> master_parent_id
        self.station_names = {}      # master_parent_id -> unified_combined_name
        
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.load_all()

    def _clean(self, val):
        return str(val).strip('"').strip() if val else ""

    def _time_to_seconds(self, t_str):
        try:
            parts = t_str.split(':')
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            return None

    def load_all(self):
        # 1. Load Trips
        for folder in ['subway_metadata', 'ferry_metadata']:
            path = os.path.join(self.base_dir, folder, 'trips.txt')
            if os.path.exists(path):
                with open(path, mode='r', encoding='utf-8-sig') as f:
                    for row in csv.DictReader(f):
                        tid = self._clean(row.get('trip_id'))
                        if tid:
                            self.trips[tid] = {
                                'route_id': self._clean(row.get('route_id')),
                                'direction_id': self._clean(row.get('direction_id', '0')),
                                'headsign': self._clean(row.get('trip_headsign', ''))
                            }

        # 2. Load Raw Stop Names
        raw_subway_stops = {}
        for folder in ['subway_metadata', 'ferry_metadata']:
            path = os.path.join(self.base_dir, folder, 'stops.txt')
            if os.path.exists(path):
                with open(path, mode='r', encoding='utf-8-sig') as f:
                    for row in csv.DictReader(f):
                        sid = self._clean(row.get('stop_id'))
                        loc_type = row.get('location_type', '0')
                        name = self._clean(row.get('stop_name'))
                        if sid:
                            self.stop_names[sid] = name
                            if folder == 'subway_metadata' and loc_type == '1':
                                raw_subway_stops[sid] = name

        # 3. Union-Find Graph Assembly (Merges Subway Transfers)
        parent = {sid: sid for sid in raw_subway_stops}
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
            
        def union(x, y):
            root_x, root_y = find(x), find(y)
            if root_x != root_y:
                parent[root_x] = root_y

        transfers_path = os.path.join(self.base_dir, 'subway_metadata', 'transfers.txt')
        if os.path.exists(transfers_path):
            with open(transfers_path, mode='r', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    f_stop = self._clean(row.get('from_stop_id'))
                    t_stop = self._clean(row.get('to_stop_id'))
                    if f_stop in parent and t_stop in parent:
                        union(f_stop, t_stop)

        # 4. Map Raw IDs to Master Groups
        groups = {}
        for sid in raw_subway_stops:
            root = find(sid)
            if root not in groups:
                groups[root] = []
            groups[root].append(sid)

        # Build final optimized lookup tables
        for root, child_sids in groups.items():
            # Use the first valid stop name as the master complex label
            master_name = raw_subway_stops[child_sids[0]]
            master_id = f"SUBWAY-COMPLEX-{root}"
            
            self.station_names[master_id] = master_name
            for sid in child_sids:
                self.merged_station_map[sid] = master_id

        # Map Ferries directly as standalone stations
        ferry_stops_path = os.path.join(self.base_dir, 'ferry_metadata', 'stops.txt')
        if os.path.exists(ferry_stops_path):
            with open(ferry_stops_path, mode='r', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    sid = self._clean(row.get('stop_id'))
                    loc_type = row.get('location_type', '0')
                    if sid and loc_type in ('0', ''):
                        fid = f"FERRY-STATION-{sid}"
                        self.merged_station_map[sid] = fid
                        self.station_names[fid] = self.stop_names.get(sid, f"Ferry Landing {sid}")

        # 5. Load Ferry Stop Sequences
        ferry_stop_times = os.path.join(self.base_dir, 'ferry_metadata', 'stop_times.txt')
        if os.path.exists(ferry_stop_times):
            raw_sequences = {}
            with open(ferry_stop_times, mode='r', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    tid = self._clean(row.get('trip_id'))
                    sid = self._clean(row.get('stop_id'))
                    seq_str = self._clean(row.get('stop_sequence'))
                    arr_str = self._clean(row.get('arrival_time'))
                    
                    if tid and sid and seq_str and arr_str:
                        secs = self._time_to_seconds(arr_str)
                        if secs is not None:
                            if tid not in raw_sequences:
                                raw_sequences[tid] = []
                            raw_sequences[tid].append({
                                'stop_id': sid,
                                'stop_sequence': int(seq_str),
                                'arrival_seconds': secs
                            })
            
            for tid, stops in raw_sequences.items():
                self.stops_by_trip[tid] = sorted(stops, key=lambda x: x['stop_sequence'])
                
        print(f"Static Union-Find generation complete. Indexed {len(self.station_names)} unified complexes.")
