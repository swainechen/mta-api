import csv
import os
import time
import threading
import requests
from google.transit import gtfs_realtime_pb2
from google.protobuf.json_format import MessageToDict

class TransitEngine:
    def __init__(self, metadata):
        self.meta = metadata
        self.lock = threading.Lock()
        
        # Thread-safe dual storage buckets matching your API endpoints
        self.train_times_cache = []
        self.ferry_times_cache = []
        
        self.subway_urls = {
            'ACE': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace',
            'BDFM': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm',
            'G': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g',
            'JZ': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz',
            'NQRW': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw',
            'L': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l',
            '1234567': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs',
            'SIR': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si',
        }
        self.ferry_url = "http://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"

    def fetch_entities(self, url, headers=None):
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(res.content)
                return MessageToDict(feed).get('entity', [])
        except Exception as e:
            print(f"Error fetching feed {url}: {e}")
        return []

    def start_background_loop(self, interval=30):
        def loop():
            while True:
                try:
                    self.refresh()
                except Exception as e:
                    print(f"Error in processing loop cycle: {e}")
                time.sleep(interval)
        
        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def refresh(self):
        now = time.time()
        subway_headers = {"x-api-key": os.getenv("MTA_API_KEY", "")}
        
        # 1. Fetch live buffers from the web
        raw_subway = []
        for url in self.subway_urls.values():
            raw_subway.extend(self.fetch_entities(url, subway_headers))
            
        raw_ferry = self.fetch_entities(self.ferry_url)

        processed_subway_updates = []
        processed_ferry_updates = []

        # 2. Parse Subway Entities
        for entity in raw_subway:
            tu = entity.get('tripUpdate', {})
            if not tu or 'stopTimeUpdate' not in tu:
                continue
            trip = tu.get('trip', {})
            trip_id = str(trip.get('tripId')).strip()
            route_id = trip.get('routeId') or self.meta.trips.get(trip_id, {}).get('route_id', 'UNK')
            
            for update in tu['stopTimeUpdate']:
                raw_stop_id = str(update.get('stopId')).strip()
                if not raw_stop_id: continue
                
                # Isolate platform suffix letters
                stop_id = raw_stop_id[:-1] if raw_stop_id[-1] in ('N', 'S') else raw_stop_id
                raw_dir = raw_stop_id[-1] if raw_stop_id[-1] in ('N', 'S') else 'N'
                direction = 'Uptown' if raw_dir == 'N' else 'Downtown'
                
                tgt_time = update.get('arrival', {}).get('time') or update.get('departure', {}).get('time')
                if tgt_time:
                    diff = float(tgt_time) - now
                    if 0 < diff < 1800:  # Only look up arrivals inside a 30 minute window
                        processed_subway_updates.append({
                            'stop_id': stop_id,
                            'route_id': route_id,
                            'direction': direction,
                            'time': diff,
                            'source': 'subway',
                            'next_stop': None,
                            'terminal': direction  # Just "Uptown" or "Downtown" - frontend will abbreviate
                        })

# 3. Parse Ferry Entities
        for entity in raw_ferry:
            tu = entity.get('tripUpdate', {})
            if not tu or 'stopTimeUpdate' not in tu: 
                continue
                
            trip = tu.get('trip', {})
            trip_id = str(trip.get('tripId')).strip()
            
            meta = self.meta.trips.get(trip_id, {})
            route_id = trip.get('routeId') or meta.get('route_id')
            
            # Keep ferry line route variants clean (ERA / ERB)
            headsign_clean = meta.get('headsign', '').replace(" ", "").upper()
            if "ERA" in headsign_clean: route_id = "ERA"
            elif "ERB" in headsign_clean: route_id = "ERB"
            if not route_id: route_id = "ER"

            direction_id = meta.get('direction_id', '0')
            direction_symbol = 'I' if str(direction_id) == '1' else 'O'
            terminal_name = meta.get('headsign', 'Unknown')

            # Look up immediate down-line stops to calculate next landing names dynamically
            updates_list = tu['stopTimeUpdate']

            for idx, update in enumerate(updates_list):
                stop_id = str(update.get('stopId')).strip()
                
                # Capture the explicit time target calculated by the transit authority server
                tgt_time = update.get('arrival', {}).get('time') or update.get('departure', {}).get('time')
                if not tgt_time: 
                    continue
                
                # Math matches your verified accurate system clock safely now
                time_diff = float(tgt_time) - now
                
                # Filter down to arrivals within a defensive 45-minute horizon window
                if 0 <= time_diff < 2700:
                    next_stop_name = None
                    
                    # Look ahead exactly one index position in the live feed to capture the true next landing
                    if idx + 1 < len(updates_list):
                        next_sid = updates_list[idx + 1].get('stopId')
                        next_stop_name = self.meta.stop_names.get(next_sid)

                    # Dynamic display destination mapping
                    display_destination = next_stop_name if next_stop_name else terminal_name
                    
                    processed_ferry_updates.append({
                        'stop_id': stop_id,
                        'route_id': route_id,
                        'direction': direction_symbol,
                        'time': time_diff, # Clean real-time difference directly from feed
                        'source': 'ferry',
                        'next_stop': next_stop_name,
                        'terminal': display_destination
                    })

        # 4. Group data matrices using Union-Find mapping tables
        new_train_times = self._group_by_station(processed_subway_updates, 'subway_metadata/stops.txt', 'subway')
        new_ferry_times = self._group_by_station(processed_ferry_updates, 'ferry_metadata/stops.txt', 'ferry')

        # 5. Atomic thread cache swap
        with self.lock:
            self.train_times_cache = new_train_times
            self.ferry_times_cache = new_ferry_times

    def _group_by_station(self, updates, stops_file, source_type):
        grouped_dict = {}
        
        # Grid sorting maps for layout partitions
        subway_line_groups = {
            '123': ['1', '2', '3'],
            '456': ['4', '5', '6'],
            'ACE': ['A', 'C', 'E'],
            'BDFM': ['B', 'D', 'F', 'M'],
            'NQRW': ['N', 'Q', 'R', 'W'],
            'JZ': ['J', 'Z'],
            'L': ['L'],
            'G': ['G'],
            'SIR': ['SI']
        }

        # Initialize placeholder buckets for EVERY station to keep frontend selectors fully populated
        for master_id, name in self.meta.station_names.items():
            is_ferry_station = master_id.startswith("FERRY-")
            if (source_type == 'subway' and not is_ferry_station) or (source_type == 'ferry' and is_ferry_station):
                grouped_dict[master_id] = {
                    'station_id': master_id,
                    'name': name,
                    'source': source_type,
                    'all_updates': []
                }

        # Route platform-specific codes under master unified complexes via Union-Find maps
        for u in updates:
            raw_sid = u['stop_id']
            master_id = self.meta.merged_station_map.get(raw_sid)
            
            if master_id in grouped_dict:
                u['time'] = int(round(u['time']))
                grouped_dict[master_id]['all_updates'].append(u)

        # Build horizontal family partitions
        final_list = []
        for master_id, sdata in grouped_dict.items():
            matched_updates = sorted(sdata['all_updates'], key=lambda x: x['time'])
            lines_split = {}

            if source_type == 'subway':
                for label, routes in subway_line_groups.items():
                    line_trains = [t for t in matched_updates if t['route_id'] in routes]
                    if line_trains:
                        lines_split[label] = line_trains
                
                assigned = [r for sub in subway_line_groups.values() for r in sub]
                misc = [t for t in matched_updates if t['route_id'] not in assigned]
                if misc:
                    lines_split['Other'] = misc
            else:
                lines_split['Ferry'] = matched_updates

            # FIX: Strip the internal prefix naming rules out so the API returns clean IDs (like '229')
            clean_api_id = master_id.split('-')[-1]

            final_list.append({
                'station_id': clean_api_id, # Returns clean ID strings matching CSS selectors
                'name': sdata['name'],
                'source': source_type,
                'lines': lines_split,
                'trains': matched_updates
            })

        return final_list
