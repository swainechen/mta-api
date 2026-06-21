import csv
import os

class TransitMetadata:
    def __init__(self, data_dir=None):
        self.trips = {}              # trip_id -> {route_id, direction_id, headsign}
        self.stop_names = {}         # stop_id -> stop_name
        self.stops_by_trip = {}      # trip_id -> list of {'stop_id', 'arrival_seconds'}
        self.merged_station_map = {} # raw_stop_id -> master_parent_id
        self.station_names = {}      # master_parent_id -> unified_combined_name
        
        # Default to the 'static_metadata' folder in the current directory
        if data_dir is None:
            self.base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static_metadata')
        else:
            self.base_dir = data_dir
            
        # Point to the active symlinks managed by the metadata_updater.py
        self.subway_dir = os.path.join(self.base_dir, 'subway_active')
        self.ferry_dir = os.path.join(self.base_dir, 'ferry_active')
        
        self.directories = {
            'subway': self.subway_dir,
            'ferry': self.ferry_dir
        }
        
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
        for feed_type, folder_path in self.directories.items():
            path = os.path.join(folder_path, 'trips.txt')
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
        for feed_type, folder_path in self.directories.items():
            path = os.path.join(folder_path, 'stops.txt')
            if os.path.exists(path):
                with open(path, mode='r', encoding='utf-8-sig') as f:
                    for row in csv.DictReader(f):
                        sid = self._clean(row.get('stop_id'))
                        loc_type = row.get('location_type', '0')
                        name = self._clean(row.get('stop_name'))
                        if sid:
                            # This ensures BOTH subway and ferry IDs populate self.stop_names
                            self.stop_names[sid] = name
                            
                            # KEEP THIS: Only add subway stops to the tracking list for Union-Find matrix processing
                            if feed_type == 'subway' and loc_type == '1':
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
                
        transfers_path = os.path.join(self.subway_dir, 'transfers.txt')
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
        ferry_stops_path = os.path.join(self.ferry_dir, 'stops.txt')
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
        ferry_stop_times = os.path.join(self.ferry_dir, 'stop_times.txt')
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

    def update_trip_id(trip_id, route_id, direction_id, headsign):
        if trip_id in self.trips:
            self.trips[trip_id] = {
                'route_id': self._clean(route_id),
                'direction_id': self._clean(direction_id, '0'),
                'headsign': self._clean(headsign, ''),
            }
