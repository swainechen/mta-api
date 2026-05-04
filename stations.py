import pandas as pd
from collections import defaultdict

STOPS_FILE = "subway_metadata/stops.txt"
TRANSFERS_FILE = "subway_metadata/transfers.txt"
STOP_TIMES_FILE = "subway_metadata/stop_times.txt"
TRIPS_FILE = "subway_metadata/trips.txt"

class Stations:
  # Class-level cache for stop_to_routes to avoid recomputing
  _stop_to_routes = None

  def __init__(self):
    self.stops_file = STOPS_FILE
    self.stops_df = pd.read_csv(STOPS_FILE)
    self.transfers_df = pd.read_csv(TRANSFERS_FILE)
    self.stations = self.get_stations()

  @classmethod
  def get_stop_to_routes(cls):
    """Build a mapping from stop_id (base, without N/S) to set of route_ids that serve it."""
    if cls._stop_to_routes is not None:
      return cls._stop_to_routes

    # Load only needed columns
    stop_times_df = pd.read_csv(STOP_TIMES_FILE, usecols=['trip_id', 'stop_id'], dtype={'stop_id': str})
    trips_df = pd.read_csv(TRIPS_FILE, usecols=['trip_id', 'route_id'], dtype={'route_id': str})

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
    return stop_to_routes

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

  def get_stations(self):
    # Get parent stations (location_type=1)
    parent_stations = self.stops_df[self.stops_df['location_type'] == 1]['stop_id'].unique()

    # Build transfer graph to find connected parent stations
    # Transfers between parent stations indicate they're part of the same complex
    transfer_pairs = set()
    for _, row in self.transfers_df.iterrows():
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
        parent_rows = self.stops_df[
          (self.stops_df['parent_station'] == parent_id) |
          (self.stops_df['stop_id'] == parent_id)
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
        'station_id': count,
        'name': station_name_with_routes,
        'stop_ids': all_stop_ids
      })

    return stations






  

 
