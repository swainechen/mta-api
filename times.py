import time
from itertools import chain

from feed_parser import FeedParser
from utils import get_updates, get_route_id, get_source, infer_ferry_route_from_stop
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

            # For subway, get direction from stop_id; for ferry, direction is always 'N' (no direction)
            if source == 'subway':
                direction = stop_id_raw[-1]
            else:
                direction = 'N'  # Ferry doesn't have N/S suffix

            times.append({
                'stop_id': stopId,
                'route_id': route_id,
                'direction': direction,
                'time': time_difference,
                'source': source
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
