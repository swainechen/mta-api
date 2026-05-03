import pandas as pd

STOPS_FILE = "subway_metadata/stops.csv"
STATIONS_FILE = "subway_metadata/Stations.csv"

class Stations:
  def __init__(self):
    self.stops_file = STOPS_FILE
    self.stops_df = pd.read_csv(STOPS_FILE)
    self.stations_file = STATIONS_FILE
    self.stations_df = pd.read_csv(STATIONS_FILE)
    self.routes_per_station = self.get_routes_per_station()
    self.stations = self.get_stations()

  def get_routes_per_station(self):
    routes_per_station = {}
    for row in self.stations_df.itertuples():
      name = str(row._6)  # Stop Name
      routes = row._8  # Daytime Routes
      if pd.isna(routes):
        continue
      routes_list = str(routes).split()
      if name not in routes_per_station:
        routes_per_station[name] = set()
      routes_per_station[name].update(routes_list)
    return routes_per_station

  def get_stations(self):
    stops = {}
    # each station is indexed by location
    stations = []
    for row in self.stops_df.itertuples():
      stations.append(str(row.stop_name))   
    stations = list(set(stations))

    count = 0
    for station in stations:
      # Filter out express routes (ending with X)
      filtered_routes = [r for r in self.routes_per_station.get(station, []) if not r.endswith('X')]
      route_str = ' '.join(sorted(filtered_routes)) if filtered_routes else ''
      display_name = f"{station} ({route_str})" if route_str else station
      
      stops[count] = {'station_id': count, 'name': display_name, 'stop_ids': []}
      name_found = False
      for row in self.stops_df.itertuples():
        if  str(row.stop_name) == station:
          if name_found == False:
            stops[count]['name'] = display_name
            name_found = True
          stopId = row.stop_id
          if stopId[-1] == "N" or stopId[-1] == "S":
            continue
          else:
            stops[count]['stop_ids'].append(stopId)
      count += 1
    stops2 = []
    for count in stops.keys():
      stops2.append(stops[count])
    return stops2






  

 