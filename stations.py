import pandas as pd
from collections import defaultdict

# Configuration for data sources
DATA_SOURCES = {
    'subway': {
        'stops_file': 'subway_metadata/stops.txt',
        'routes_file': 'subway_metadata/routes.txt',
        'stop_times_file': 'subway_metadata/stop_times.txt',
        'trips_file': 'subway_metadata/trips.txt',
        'transfers_file': 'subway_metadata/transfers.txt',
        'agency_id': '1',
    },
    'ferry': {
        'stops_file': 'ferry_metadata/stops.txt',
        'routes_file': 'ferry_metadata/routes.txt',
        'stop_times_file': 'ferry_metadata/stop_times.txt',
        'trips_file': 'ferry_metadata/trips.txt',
        'transfers_file': None,
        'agency_id': '1',
    }
}


class Stations:
    """Unified station loader for subway and ferry."""

    # Class-level cache for stop_to_routes to avoid recomputing
    _stop_to_routes = None
    _combined_stops_df = None
    _combined_routes_df = None

    def __init__(self):
        self.stations = self.get_stations()

    @classmethod
    def get_combined_stops_df(cls):
        """Load and combine stops from both subway and ferry."""
        if cls._combined_stops_df is not None:
            return cls._combined_stops_df

        dfs = []
        for source, config in DATA_SOURCES.items():
            stops_df = pd.read_csv(config['stops_file'], dtype={'stop_id': str})
            stops_df['source'] = source
            dfs.append(stops_df)

        cls._combined_stops_df = pd.concat(dfs, ignore_index=True)
        return cls._combined_stops_df

    @classmethod
    def get_combined_routes_df(cls):
        """Load and combine routes from both subway and ferry."""
        if cls._combined_routes_df is not None:
            return cls._combined_routes_df

        dfs = []
        for source, config in DATA_SOURCES.items():
            routes_df = pd.read_csv(config['routes_file'], dtype={'route_id': str})
            routes_df['source'] = source
            dfs.append(routes_df)

        cls._combined_routes_df = pd.concat(dfs, ignore_index=True)
        return cls._combined_routes_df

    @classmethod
    def get_stop_to_routes(cls):
        """Build a mapping from stop_id (base, without N/S) to set of route_ids that serve it."""
        if cls._stop_to_routes is not None:
            return cls._stop_to_routes

        # Load only needed columns from both sources
        stop_times_dfs = []
        trips_dfs = []

        for source, config in DATA_SOURCES.items():
            stop_times_df = pd.read_csv(
                config['stop_times_file'],
                usecols=['trip_id', 'stop_id'],
                dtype={'stop_id': str, 'trip_id': str}
            )
            stop_times_df['source'] = source
            stop_times_dfs.append(stop_times_df)

            trips_df = pd.read_csv(
                config['trips_file'],
                usecols=['trip_id', 'route_id'],
                dtype={'route_id': str, 'trip_id': str}
            )
            trips_df['source'] = source
            trips_dfs.append(trips_df)

        stop_times_df = pd.concat(stop_times_dfs, ignore_index=True)
        trips_df = pd.concat(trips_dfs, ignore_index=True)

        # Strip N/S suffix from stop_id before merge to reduce data size
        stop_times_df['base_stop_id'] = stop_times_df['stop_id'].str[:-1].where(
            stop_times_df['stop_id'].str[-1].isin(['N', 'S']),
            stop_times_df['stop_id']
        )

        # Join stop_times with trips to get route_id for each stop
        stop_times_with_trips = stop_times_df.merge(trips_df, on='trip_id')

        # Use groupby for efficient aggregation
        stop_to_routes = stop_times_with_trips.groupby('base_stop_id')['route_id'].apply(set).to_dict()

        cls._stop_to_routes = stop_to_routes
        return cls._stop_to_routes

    @classmethod
    def format_routes(cls, routes):
        """Format a set of route_ids as a sorted string like '2345ACJZ'."""
        # Collapse express lines: remove 'X' suffix from routes ending with 'X'
        processed_routes = set()
        for r in routes:
            if r.endswith('X'):
                processed_routes.add(r[:-1])
            else:
                processed_routes.add(r)

        # Sort numerics first, then alphabetics
        numeric = sorted([r for r in processed_routes if r.isdigit()])
        alpha = sorted([r for r in processed_routes if not r.isdigit()])
        return ''.join(numeric + alpha)

    def get_parent_stations(self, source):
        """Get parent stations for a given source."""
        stops_df = self.get_combined_stops_df()
        return stops_df[stops_df['source'] == source][stops_df['source'] == source]['stop_id'].unique()

    def get_stations(self):
        """Build stations from both subway and ferry data."""
        # Get parent stations from subway (with transfers)
        subway_stops_df = self.get_combined_stops_df()
        subway_stations = self._build_subway_stations(subway_stops_df)

        # Get stations from ferry (no transfers, each stop is its own station)
        ferry_stations = self._build_ferry_stations(subway_stops_df, len(subway_stations))

        return subway_stations + ferry_stations

    def _build_subway_stations(self, stops_df):
        """Build subway stations with transfer support."""
        # Filter subway stops
        subway_df = stops_df[stops_df['source'] == 'subway']

        # Get parent stations (location_type=1)
        parent_stations = subway_df[subway_df['location_type'] == 1]['stop_id'].unique()

        # Load transfers for subway
        transfers_df = pd.read_csv(DATA_SOURCES['subway']['transfers_file'], dtype={'from_stop_id': str, 'to_stop_id': str})

        # Build transfer graph to find connected parent stations
        transfer_pairs = set()
        for _, row in transfers_df.iterrows():
            from_stop = str(row['from_stop_id'])
            to_stop = str(row['to_stop_id'])
            if from_stop in parent_stations and to_stop in parent_stations:
                transfer_pairs.add((from_stop, to_stop))

        # Union-Find to group connected parent stations
        parent_map = {p: p for p in parent_stations}
        def find(x):
            if parent_map[x] != x:
                parent_map[x] = find(parent_map[x])
            return parent_map[x]
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent_map[px] = py

        for from_stop, to_stop in transfer_pairs:
            union(from_stop, to_stop)

        # Group parent stations by their root
        groups = {}
        for p in parent_stations:
            root = find(p)
            if root not in groups:
                groups[root] = []
            groups[root].append(p)

        # Build stop_id to routes mapping (cached at class level)
        stop_to_routes = self.get_stop_to_routes()

        # Build stations from groups
        stations = []
        for count, (root, parent_ids) in enumerate(groups.items()):
            all_stop_ids = []
            all_routes = set()
            station_name = None
            for parent_id in parent_ids:
                parent_rows = subway_df[
                    (subway_df['parent_station'] == parent_id) |
                    (subway_df['stop_id'] == parent_id)
                ]
                if station_name is None:
                    station_name = parent_rows.iloc[0].stop_name
                for _, row in parent_rows.iterrows():
                    stopId = row.stop_id
                    if stopId[-1] not in ("N", "S"):
                        all_stop_ids.append(stopId)
                        # Add routes for this stop
                        if stopId in stop_to_routes:
                            all_routes.update(stop_to_routes[stopId])

            station_name_with_routes = f"{station_name} ({self.format_routes(all_routes)})"
            stations.append({
                'station_id': f'S-{count}',
                'name': station_name_with_routes,
                'stop_ids': all_stop_ids,
                'source': 'subway'
            })

        return stations

    def _build_ferry_stations(self, stops_df, start_id=0):
        """Build ferry stations - each ferry stop is its own station."""
        ferry_df = stops_df[stops_df['source'] == 'ferry']

        # Load ferry stop times to get routes for each stop
        stop_times_df = pd.read_csv(
            DATA_SOURCES['ferry']['stop_times_file'],
            usecols=['trip_id', 'stop_id'],
            dtype={'stop_id': str, 'trip_id': str}
        )
        trips_df = pd.read_csv(
            DATA_SOURCES['ferry']['trips_file'],
            usecols=['trip_id', 'route_id'],
            dtype={'route_id': str, 'trip_id': str}
        )
        stop_times_with_trips = stop_times_df.merge(trips_df, on='trip_id')

        # Group by stop_id to get routes
        stop_to_routes = stop_times_with_trips.groupby('stop_id')['route_id'].apply(set).to_dict()

        # Each ferry stop is its own station
        stations = []
        for idx, (_, row) in enumerate(ferry_df.iterrows()):
            stop_id = row.stop_id
            all_routes = stop_to_routes.get(stop_id, set())
            station_name = row.stop_name

            station_name_with_routes = f"{station_name} ({self.format_routes(all_routes)})"

            stations.append({
                'station_id': f'F-{idx}',
                'name': station_name_with_routes,
                'stop_ids': [stop_id],
                'source': 'ferry'
            })

        return stations
