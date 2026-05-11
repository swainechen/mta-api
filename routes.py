import pandas as pd

ROUTES_FILE = "subway_metadata/routes.txt"

# Ferry routes - these are displayed as "lines" similar to subway lines
FERRY_ROUTES = [
    {'route_id': 'AS', 'color': 'FF6B00', 'name': 'Astoria'},
    {'route_id': 'ER', 'color': '00839C', 'name': 'East River'},
    {'route_id': 'RES', 'color': '00A1E1', 'name': 'Rockaway East'},
    {'route_id': 'RS', 'color': '4E008E', 'name': 'Rockaway-Soundview'},
    {'route_id': 'RW', 'color': 'B218AA', 'name': 'Rockaway'},
    {'route_id': 'RWS', 'color': '00A1E1', 'name': 'Rockaway West'},
    {'route_id': 'SB', 'color': 'FFD100', 'name': 'South Brooklyn'},
    {'route_id': 'SG', 'color': 'D0006F', 'name': 'St. George'},
]


class Routes:
    def __init__(self):
        self.routes_df = pd.read_csv(ROUTES_FILE)
        self.routes = self.get_routes()

    def get_routes(self):
        routes = []
        self.routes_df = self.routes_df.fillna("grey")
        for row in self.routes_df.itertuples():
            routes.append({
                'route_id': row.route_id,
                'color': row.route_color,
                'name': row.route_long_name,
                'type': 'subway'
            })

        # Add ferry routes
        for ferry_route in FERRY_ROUTES:
            routes.append({
                'route_id': ferry_route['route_id'],
                'color': ferry_route['color'],
                'name': ferry_route['name'],
                'type': 'ferry'
            })

        return routes

    def get_route_color(self, route_id):
        """Get the color for a route_id, handling both subway and ferry."""
        # First check subway routes
        route_match = self.routes_df[self.routes_df['route_id'] == route_id]
        if not route_match.empty:
            return route_match.iloc[0]['route_color']

        # Then check ferry routes
        for ferry_route in FERRY_ROUTES:
            if ferry_route['route_id'] == route_id:
                return ferry_route['color']

        return 'grey'  # default
