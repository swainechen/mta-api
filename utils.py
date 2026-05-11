from datetime import date
import pandas as pd

# Global caches
_ferry_trip_route_map = None
_ferry_stop_to_routes = None


def get_ferry_trip_route_map():
    """Build a mapping from trip_id to route_id for ferry routes."""
    global _ferry_trip_route_map
    if _ferry_trip_route_map is not None:
        return _ferry_trip_route_map

    trips_df = pd.read_csv('ferry_metadata/trips.txt', dtype={'trip_id': str, 'route_id': str})
    _ferry_trip_route_map = trips_df.set_index('trip_id')['route_id'].to_dict()
    return _ferry_trip_route_map


def get_ferry_stop_to_routes():
    """Build a mapping from stop_id to set of route_ids for ferry routes."""
    global _ferry_stop_to_routes
    if _ferry_stop_to_routes is not None:
        return _ferry_stop_to_routes

    stop_times_df = pd.read_csv('ferry_metadata/stop_times.txt', dtype={'stop_id': str, 'trip_id': str})
    trips_df = pd.read_csv('ferry_metadata/trips.txt', dtype={'trip_id': str, 'route_id': str})
    stop_times_with_trips = stop_times_df.merge(trips_df, on='trip_id')
    _ferry_stop_to_routes = stop_times_with_trips.groupby('stop_id')['route_id'].apply(set).to_dict()
    return _ferry_stop_to_routes


def get_route_id(entity):
    """Get route id from an entity, handling both subway and ferry feeds."""
    if "tripUpdate" in entity and "trip" in entity["tripUpdate"]:
        route_id = entity["tripUpdate"]["trip"].get("routeId")
        if route_id:
            return route_id

        # For ferry feeds, tripId may not have routeId - need to look it up
        trip_id = entity["tripUpdate"]["trip"].get("tripId")
        if trip_id:
            ferry_map = get_ferry_trip_route_map()
            return ferry_map.get(trip_id)

    return None


def get_updates(entity):
    """Get stop time updates from an entity."""
    if "tripUpdate" in entity and "stopTimeUpdate" in entity["tripUpdate"]:
        return entity["tripUpdate"]["stopTimeUpdate"]
    return []


def get_vehicle_label(entity):
    """Get vehicle label/ID from an entity."""
    if "tripUpdate" in entity and "vehicle" in entity["tripUpdate"]:
        return entity["tripUpdate"]["vehicle"]["label"]
    return None


def get_source(entity):
    """Determine if an entity is from subway or ferry feed based on route_id prefix."""
    route_id = get_route_id(entity)
    if route_id is None:
        return None

    # Ferry routes: AS, ER, RES, RS, RW, RWS, SB, SG
    ferry_routes = ['AS', 'ER', 'RES', 'RS', 'RW', 'RWS', 'SB', 'SG']
    if route_id in ferry_routes:
        return 'ferry'

    # Also check trip IDs for ferries (trip IDs like 1113, 1114, etc. often indicate ferries)
    if "tripUpdate" in entity and "trip" in entity["tripUpdate"]:
        trip_id = entity["tripUpdate"]["trip"].get("tripId", "")
        if trip_id and trip_id.isdigit() and len(trip_id) >= 4:
            # Ferry trip IDs typically start with 11, 12, 13, 14, 15, 16, 17
            first_two = int(trip_id[:2])
            if 11 <= first_two <= 17:
                return 'ferry'

    return 'subway'


def infer_ferry_route_from_stop(entity):
    """
    Infer ferry route from stop_id when routeId is not available in feed.
    The ferry feed doesn't include route_id, but we can infer from stop_id.
    """
    updates = get_updates(entity)
    if not updates:
        return None

    # Get the first stop_id from updates
    stop_id = updates[0].get('stopId', '')
    if not stop_id:
        return None

    stop_to_routes = get_ferry_stop_to_routes()
    routes = stop_to_routes.get(stop_id, set())

    # Return the first route if there are multiple
    if routes:
        return list(routes)[0]

    return None
