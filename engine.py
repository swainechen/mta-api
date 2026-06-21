import datetime as dt
import os
import time
import threading
import subprocess
import requests
import zoneinfo
from google.transit import gtfs_realtime_pb2
from google.protobuf.json_format import MessageToDict

class TransitEngine:
    def __init__(self, metadata):
        self.meta = metadata
        self.lock = threading.Lock()
        
        self.train_times_cache = []
        self.ferry_times_cache = []
        
        # --- Update Hook State ---
        self.missed_trips = 0
        self.last_update_time = 0
        self.UPDATE_COOLDOWN = 6 * 3600  # 6 hours debounce
        self.meta_dir = getattr(self.meta, 'base_dir', './static_metadata')
        
        try:
            self._last_ferry_link = os.readlink(os.path.join(self.meta_dir, 'ferry_active'))
        except OSError:
            self._last_ferry_link = None
        
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

    @staticmethod
    def clean(val):
        return str(val).replace('"', '').strip() if val else ""

    @staticmethod
    def get_route_family_from_terminal(final_stop_id):
        sid = TransitEngine.clean(final_stop_id)
        if sid in ["89", "90", "112", "113", "25"]: return "AS"
        elif sid in ["111", "17", "24", "115"]: return "SB"
        elif sid in ["23", "137", "138", "136", "141"]: return "SG"
        elif sid in ["16", "62", "118", "88", "142"]: return "RS"
        else: return "ER"

    def _record_missed_trip(self):
        """Hook to trigger the external metadata updater if static data goes stale."""
        print(f"Missed trips: {self.missed_trips}")
        self.missed_trips += 1
        if self.missed_trips >= 5:
            now = time.time()
            if now - self.last_update_time > self.UPDATE_COOLDOWN:
                print("Missed trip threshold reached. Triggering background metadata update...")
                self.last_update_time = now
                self.missed_trips = 0
                
                updater_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata_updater.py")
                if os.path.exists(updater_script):
                    subprocess.Popen(["python3", updater_script])
                else:
                    print(f"Could not find updater script at {updater_script}")

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
        # ====================================================================
        # 0. Hot-Reload Hook (Check for Symlink Swaps)
        # ====================================================================
        try:
            ferry_link_path = os.path.join(self.meta_dir, 'ferry_active')
            if os.path.islink(ferry_link_path):
                current_ferry_link = os.readlink(ferry_link_path)
                if self._last_ferry_link and current_ferry_link != self._last_ferry_link:
                    print(f"New symlink detected ({current_ferry_link}). Hot-reloading metadata...")
                    new_meta = self.meta.__class__(self.meta_dir)
                    with self.lock:
                        self.meta = new_meta
                        self._last_ferry_link = current_ferry_link
                elif not self._last_ferry_link:
                    self._last_ferry_link = current_ferry_link
        except Exception as e:
            print(f"Hot-reload check failed: {e}")

        now = time.time()
        subway_headers = {"x-api-key": os.getenv("MTA_API_KEY", "")}
        
        raw_subway = []
        for url in self.subway_urls.values():
            raw_subway.extend(self.fetch_entities(url, subway_headers))
            
        raw_ferry = self.fetch_entities(self.ferry_url)

        processed_subway_updates = []
        processed_ferry_updates = []

        # ====================================================================
        # 1. Parse Subway Entities
        # ====================================================================
        with self.lock:
            for entity in raw_subway:
                tu = entity.get('tripUpdate', {})
                if not tu or 'stopTimeUpdate' not in tu:
                    continue
                trip = tu.get('trip', {})
                feed_trip_id = str(trip.get('tripId')).strip()

                # The GTFS-RT feed uses shorter tripIds than the static data.
                # Static data might have format "L0S1-1-1094-S02_123800_1..N15R"
                # while feed provides "123800_1..N15R". Check for suffix match.
                trip_info = self.meta.trips.get(feed_trip_id)
                static_trip_id = None
                num_matches = 0
                best_match = None
                last_match = None
                if not trip_info:
                    for static_trip_id_inner, ti in self.meta.trips.items():
                        if static_trip_id_inner.endswith(feed_trip_id):
                            # Try matching by suffix
                            trip_info = ti
                            static_trip_id = static_trip_id_inner
                            break
                        else:
                            # RT feed has 129600_SI..S and trips.txt has
                            # - SIR-FA2017-SI017-Weekday-08_129600_SI..S03R
                            # - SIR-SP2026-SI017-Saturday-00_129600_SI..S03R
                            # - SIR-SP2026-SI017-Sunday-00_129600_SI..S03R
                            two_fields = static_trip_id_inner.split(
                                "_", maxsplit=1
                            )
                            if (
                                len(two_fields) > 1 and
                                two_fields[1].startswith(feed_trip_id)
                            ):
                                num_matches += 1
                                last_match = static_trip_id_inner
                                dow_maybe = two_fields[0].split("-")[-2]
                                today_dow = dt.datetime.now(tz=zoneinfo.ZoneInfo("America/New_York")).weekday()
                                if (
                                    dow_maybe == "Saturday" and today_dow == 5
                                ) or (
                                    dow_maybe == "Sunday" and today_dow == 6
                                ) or (
                                    dow_maybe == "Weekday" and today_dow <= 4
                                ):
                                    best_match = static_trip_id_inner
                    if best_match:
                        static_trip_id = best_match
                    elif last_match:
                        static_trip_id = last_match
                if not static_trip_id:
                    # This just isn't an issue for the subway feed since the
                    # RT feed has the full set of stations that train is going
                    # to visit, so we don't record missing stations
                    continue

                route_id = trip.get('routeId') or (trip_info.get('route_id') if trip_info else 'UNK')
                
                # The feed usually gives the full set of stops
                # Because we want the terminus in every upate, we end up
                # traversing two times here...
                max_ts = 0
                rt_feed_terminus = None
                for update in tu["stopTimeUpdate"]:
                    arr_ts = update.get("arrival", {}).get("time")
                    if arr_ts:
                        arr_ts_numeric = float(arr_ts)
                        if arr_ts_numeric > max_ts:
                            max_ts = arr_ts_numeric
                            update_stopid = update.get("stopId")
                            if update_stopid and update_stopid in self.meta.stop_names:
                                rt_feed_terminus = self.meta.stop_names[update_stopid]

                for update in tu['stopTimeUpdate']:
                    raw_stop_id = str(update.get('stopId')).strip()
                    if not raw_stop_id: continue
                    
                    stop_id = raw_stop_id[:-1] if raw_stop_id[-1] in ('N', 'S') else raw_stop_id
                    raw_dir = raw_stop_id[-1] if raw_stop_id[-1] in ('N', 'S') else 'N'
                    direction = 'Uptown' if raw_dir == 'N' else 'Downtown'
                    
                    arr_ts = update.get('arrival', {}).get('time')
                    dep_ts = update.get('departure', {}).get('time')
                    sort_time = arr_ts or dep_ts
                    
                    if sort_time:
                        diff = float(sort_time) - now
                        if 0 < diff < 1800:
                            arr_diff = float(arr_ts) - now if arr_ts else None
                            dep_diff = float(dep_ts) - now if dep_ts else None
                            
                            # Get the actual terminal station from trip headsign
                            headsign = trip_info.get('headsign', '') if trip_info else ''
                            terminal = rt_feed_terminus if rt_feed_terminus else headsign if headsign else direction

                            processed_subway_updates.append({
                                'stop_id': stop_id,
                                'route_id': route_id,
                                'direction': direction,
                                'time': diff,
                                'time_seconds': int(round(diff)),
                                'arrival_time_seconds': int(round(arr_diff)) if arr_diff is not None else None,
                                'departure_time_seconds': int(round(dep_diff)) if dep_diff is not None else None,
                                'source': 'subway',
                                'next_stop': None,
                                'terminal': terminal,
                                'static_trip_id': static_trip_id,
                                'feed_trip_id': feed_trip_id,
                            })

            # ====================================================================
            # 2. Parse Ferry Entities (O(1) Direct Lookup)
            # ====================================================================
            for entity in raw_ferry:
                tu = entity.get('tripUpdate', {})
                if not tu or 'stopTimeUpdate' not in tu:
                    continue
                
                trip_id = self.clean(tu.get('trip', {}).get('tripId', ''))
                vehicle_id = self.clean(tu.get('vehicle', {}).get('id', 'N/A'))
                vehicle_label = self.clean(tu.get('vehicle', {}).get('label', 'N/A'))
                updates_list = tu.get('stopTimeUpdate', [])
                
                live_remaining_stops = [self.clean(u.get('stopId')) for u in updates_list if u.get('stopId')]
                if not live_remaining_stops:
                    continue
                
                live_dest = live_remaining_stops[-1]
                
                static_trip = self.meta.trips.get(trip_id)
                static_stops = []
                
                if static_trip:
                    route = static_trip.get('route_id', 'ER')
                    static_stops = self.meta.stops_by_trip.get(trip_id, [])
                    static_dest = static_stops[-1]['stop_id'] if static_stops else None
                    final_dest_id = live_dest if live_dest else static_dest
                else:
                    self._record_missed_trip()
                    route = self.get_route_family_from_terminal(live_dest)
                    final_dest_id = live_dest

                if route == "ER":
                    try:
                        trip_num = int(trip_id) if trip_id.isdigit() else 0
                        route_display = "ERA" if trip_num % 2 == 0 else "ERB"
                    except ValueError:
                        route_display = "ER"
                else:
                    route_display = route

                if route_display in ["RES", "ROCK"]:
                    route_display = "RS"
                    
                route_display = route_display.upper().strip()
                dest_name = self.meta.stop_names.get(str(final_dest_id), f"Stop {final_dest_id}")

                for idx, update in enumerate(updates_list):
                    stop_id = self.clean(update.get('stopId'))
                    
                    arr_ts = update.get('arrival', {}).get('time')
                    dep_ts = update.get('departure', {}).get('time')
                    sort_time = arr_ts or dep_ts
                    
                    if not sort_time:
                        continue
                    
                    time_diff = float(sort_time) - now
                    if 0 <= time_diff < 3900:
                        arr_diff = float(arr_ts) - now if arr_ts else None
                        dep_diff = float(dep_ts) - now if dep_ts else None
                        
                        next_stop_name = None
                        if idx + 1 < len(live_remaining_stops):
                            next_id = live_remaining_stops[idx+1]
                            next_stop_name = self.meta.stop_names.get(next_id, f"Stop {next_id}")
                        elif static_stops:
                            for stop_index, stop_entry in enumerate(static_stops):
                                if self.clean(stop_entry.get('stop_id')) == stop_id:
                                    if stop_index + 1 < len(static_stops):
                                        next_id = static_stops[stop_index + 1]['stop_id']
                                        next_stop_name = self.meta.stop_names.get(next_id, f"Stop {next_id}")
                                    break
                            
                        processed_ferry_updates.append({
                            'stop_id': stop_id,
                            'route_id': route_display,
                            'vehicle_id': vehicle_id,
                            'vehicle_label': vehicle_label,
                            'direction': 'O', 
                            'time': time_diff,
                            'time_seconds': int(round(time_diff)),
                            'arrival_time_seconds': int(round(arr_diff)) if arr_diff is not None else None,
                            'departure_time_seconds': int(round(dep_diff)) if dep_diff is not None else None,
                            'source': 'ferry',
                            'next_stop': next_stop_name,
                            'terminal': dest_name,
                            'static_trip_id': trip_id if static_trip else None,
                            'feed_trip_id': trip_id,
                        })

            # ====================================================================
            # 3. Group and Cache
            # ====================================================================
            new_train_times = self._group_by_station(processed_subway_updates, 'subway')
            new_ferry_times = self._group_by_station(processed_ferry_updates, 'ferry')

            self.train_times_cache = new_train_times
            self.ferry_times_cache = new_ferry_times

    def _group_by_station(self, updates, source_type):
        grouped_dict = {}
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

        for master_id, name in self.meta.station_names.items():
            is_ferry_station = master_id.startswith("FERRY-")
            if (source_type == 'subway' and not is_ferry_station) or (source_type == 'ferry' and is_ferry_station):
                grouped_dict[master_id] = {
                    'station_id': master_id,
                    'name': name,
                    'source': source_type,
                    'all_updates': []
                }

        for u in updates:
            raw_sid = u['stop_id']
            master_id = self.meta.merged_station_map.get(raw_sid)
            
            if master_id in grouped_dict:
                u['time'] = int(round(u['time']))
                grouped_dict[master_id]['all_updates'].append(u)

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
                for update in matched_updates:
                    r_id = update.get('route_id', 'Ferry').upper().strip()
                    if r_id not in lines_split:
                        lines_split[r_id] = []
                    lines_split[r_id].append(update)

            clean_api_id = master_id.split('-')[-1]

            final_list.append({
                'station_id': clean_api_id,
                'name': sdata['name'],
                'source': source_type,
                'lines': lines_split,
                'trains': matched_updates
            })

        return final_list
