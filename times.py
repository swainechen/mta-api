import time
from itertools import chain

from feed_parser import FeedParser
from utils import (
    get_updates,
    get_route_id,
    get_source,
    infer_ferry_route_from_stop,
    get_ferry_direction,
    get_ferry_next_stop,
    get_ferry_trip_headsign,
    get_ferry_stops_by_trip,
    get_ferry_subroute,
    get_ferry_stop_name_map
)
from stations import Stations

MAX_TIME_DIFFERENCE = 1800


class Times:
    def __init__(self):
        self.feed_parser = FeedParser()
        self.feed = self.feed_parser.feed
        self.ferry_feed = self.feed_parser.ferry_feed
        self.train_times = self.get_times()
        self.ferry_times = self.get_ferry_times()

    def process_update(self, entity, update, times, source='subway'):
        """Process a single update and add to times list."""
        time_difference = self.get_time_difference(update)
        stop_id_raw = update['stopId']

        # For subway: strip N/S suffix; for ferry: use stop_id as-is
        if source == 'subway' and stop_id_raw[-1] in ('N', 'S'):
            stopId = stop_id_raw[:-1]
        else:
            stopId = stop_id_raw

        if time_difference is not None and time_difference > 0 and time_difference < MAX_TIME_DIFFERENCE:
            # Add direction to route id
            # Direction is the last character 'N' or 'S' at the end of the stop Id
            route_id = get_route_id(entity)

            # For ferry feeds without route_id, infer from stop_id
            if source == 'ferry' and route_id is None:
                route_id = infer_ferry_route_from_stop(entity)

            if source == 'subway':
                direction = stop_id_raw[-1]
                next_stop = None
                terminal = None
            else:
                direction = get_ferry_direction(entity) or 'N'
                terminal = get_ferry_trip_headsign(entity)

                # Try to expand a single ferry update into predicted times for downstream stops
                trip = entity.get('tripUpdate', {}).get('trip', {})
                trip_id = trip.get('tripId')
                if trip_id:
                    stops_by_trip = get_ferry_stops_by_trip().get(trip_id)
                else:
                    stops_by_trip = None

                if stops_by_trip:
                    # Find current stop index
                    current_index = None
                    for idx, s in enumerate(stops_by_trip):
                        if s.get('stop_id') == stopId:
                            current_index = idx
                            break

                    if current_index is not None:
                        current_arrival = stops_by_trip[current_index].get('arrival_seconds') or 0
                        stop_name_map = get_ferry_stop_name_map()
                        # For current and downstream stops, compute predicted time using scheduled offsets
                        # Determine if there's a more specific subroute (ERA/ERB)
                        subroute = get_ferry_subroute(entity)

                        for j in range(current_index, len(stops_by_trip)):
                            s_entry = stops_by_trip[j]
                            delta = (s_entry.get('arrival_seconds') or 0) - current_arrival
                            predicted = time_difference + delta
                            if predicted is not None and predicted > 0 and predicted < MAX_TIME_DIFFERENCE:
                                next_stop_name = None
                                if j + 1 < len(stops_by_trip):
                                    next_stop_id = stops_by_trip[j + 1].get('stop_id')
                                    next_stop_name = stop_name_map.get(next_stop_id)
                                display_route = subroute if subroute is not None else route_id

                                times.append({
                                    'stop_id': s_entry.get('stop_id'),
                                    'route_id': display_route,
                                    'direction': direction,
                                    'time': predicted,
                                    'source': source,
                                    'next_stop': next_stop_name,
                                    'terminal': terminal
                                })
                    else:
                        # Fall back to adding only the current stop if mapping not found
                        next_stop = get_ferry_next_stop(entity, stopId)
                        times.append({
                            'stop_id': stopId,
                            'route_id': route_id,
                            'direction': direction,
                            'time': time_difference,
                            'source': source,
                            'next_stop': next_stop,
                            'terminal': terminal
                        })
                else:
                    # No trip stop metadata available; add only the current stop
                    next_stop = get_ferry_next_stop(entity, stopId)
                    times.append({
                        'stop_id': stopId,
                        'route_id': route_id,
                        'direction': direction,
                        'time': time_difference,
                        'source': source,
                        'next_stop': next_stop,
                        'terminal': terminal
                    })
        return times

    def process_entity(self, entity, times, source='subway'):
        """Process a single entity (trip update)."""
        if isinstance(entity, dict) and 'tripUpdate' in entity.keys() and "stopTimeUpdate" in entity['tripUpdate'].keys():
            updates = get_updates(entity)
            for update in updates:
                times = self.process_update(entity, update, times, source)
        return times

    def get_times(self):
        """Get all subway arrival times."""
        times = []
        for entity in self.feed:
            times = self.process_entity(entity, times, 'subway')
        station_times = self.get_station_times(times, 'subway')
        return station_times

    def get_ferry_times(self):
        """Get all ferry arrival times."""
        times = []
        for entity in self.ferry_feed:
            times = self.process_entity(entity, times, 'ferry')
        station_times = self.get_station_times(times, 'ferry')
        return station_times

    def get_all_times(self):
        """Get all times (subway + ferry) combined."""
        return self.train_times + self.ferry_times

    def get_station_times(self, times, source='subway'):
        """Group times by station for a given source."""
        station_times = []
        # Filter stations by source
        stations = [s for s in Stations().stations if s.get('source') == source]
        for station in stations:
            stations_dict = {'station_id': station['station_id'], 'trains': []}
            for stopId in station['stop_ids']:
                stop_times = list(filter(lambda time: time['stop_id'] == stopId, times))
                for time in stop_times:
                    stations_dict['trains'].append(time)
            stations_dict['trains'] = sorted(stations_dict['trains'], key=lambda i: i['time'])
            station_times.append(stations_dict)
        return station_times

    @staticmethod
    def get_time_difference(update):
        """Return time difference between current time and train/ferry arrival/departure time in seconds."""
        if "arrival" in update.keys() and "time" in update["arrival"].keys():
            # Time in GTFS feed is in POSIX
            return float(update["arrival"]["time"]) - time.time()
        elif "departure" in update.keys() and "time" in update["departure"].keys():
            return float(update["departure"]["time"]) - time.time()
        else:
            return None
