from datetime import date, datetime
import pandas as pd

# Global caches
_ferry_trip_route_map = None
_ferry_stop_to_routes = None
_ferry_trip_metadata = None
_ferry_stop_times_by_trip = None
_ferry_stop_names = None

# Cache initialization status
_ferry_caches_initialized = False
_ferry_cache_init_time = None


def normalize_string(value):
    """Normalize raw string values from feed or CSV metadata."""
    if value is None:
        return None
    normalized = str(value).strip().strip('"')
    return normalized if normalized != '' else None


def initialize_ferry_caches():
    """Initialize all ferry metadata caches at once with proper error handling."""
    global _ferry_trip_route_map, _ferry_stop_to_routes, _ferry_trip_metadata
    global _ferry_stop_times_by_trip, _ferry_stop_names, _ferry_caches_initialized
    global _ferry_cache_init_time

    import logging
    logger = logging.getLogger('mta-api.utils')

    if _ferry_caches_initialized:
        return True

    try:
        # Initialize all caches
        get_ferry_trip_route_map()
        get_ferry_stop_to_routes()
        get_ferry_trip_metadata()
        get_ferry_stops_by_trip()
        get_ferry_stop_name_map()

        _ferry_caches_initialized = True
        _ferry_cache_init_time = datetime.now()
        logger.info("All ferry caches initialized successfully")
        return True
    except Exception as e:
        logger.error("Failed to initialize ferry caches: %s", str(e))
        # Set initialized flag to True even on failure to prevent repeated attempts
        _ferry_caches_initialized = True
        return False


def get_ferry_trip_route_map():
    """Build a mapping from trip_id to route_id for ferry routes."""
    global _ferry_trip_route_map
    if _ferry_trip_route_map is not None:
        return _ferry_trip_route_map

    import logging
    logger = logging.getLogger('mta-api.utils')

    try:
        trips_df = pd.read_csv('ferry_metadata/trips.txt', dtype=str)
        # Strip quotes and spacing added by raw static metadata files
        trips_df['trip_id'] = trips_df['trip_id'].str.strip('"').str.strip()
        trips_df['route_id'] = trips_df['route_id'].str.strip('"').str.strip()
        _ferry_trip_route_map = trips_df.set_index('trip_id')['route_id'].to_dict()
        logger.debug("Loaded %d trip-route mappings", len(_ferry_trip_route_map))
        return _ferry_trip_route_map
    except Exception as e:
        logger.error("Failed to load ferry trip-route map: %s", str(e))
        _ferry_trip_route_map = {}
        return _ferry_trip_route_map


def get_ferry_stop_to_routes():
    """Build a mapping from stop_id to set of route_ids for ferry routes."""
    global _ferry_stop_to_routes
    if _ferry_stop_to_routes is not None:
        return _ferry_stop_to_routes

    import logging
    logger = logging.getLogger('mta-api.utils')

    try:
        stop_times_df = pd.read_csv('ferry_metadata/stop_times.txt', dtype=str)
        trips_df = pd.read_csv('ferry_metadata/trips.txt', dtype=str)
        stop_times_df['stop_id'] = stop_times_df['stop_id'].str.strip('"').str.strip()
        stop_times_df['trip_id'] = stop_times_df['trip_id'].str.strip('"').str.strip()
        trips_df['trip_id'] = trips_df['trip_id'].str.strip('"').str.strip()
        trips_df['route_id'] = trips_df['route_id'].str.strip('"').str.strip()
        stop_times_with_trips = stop_times_df.merge(trips_df, on='trip_id')
        _ferry_stop_to_routes = stop_times_with_trips.groupby('stop_id')['route_id'].apply(set).to_dict()
        logger.debug("Loaded stop-to-routes mapping for %d stops", len(_ferry_stop_to_routes))
        return _ferry_stop_to_routes
    except Exception as e:
        logger.error("Failed to load ferry stop-to-routes map: %s", str(e))
        _ferry_stop_to_routes = {}
        return _ferry_stop_to_routes


def get_ferry_trip_metadata():
    """Build a mapping from trip_id to ferry trip metadata."""
    global _ferry_trip_metadata
    if _ferry_trip_metadata is not None:
        return _ferry_trip_metadata

    import logging
    logger = logging.getLogger('mta-api.utils')

    try:
        trips_df = pd.read_csv('ferry_metadata/trips.txt', dtype=str)
        trips_df['trip_id'] = trips_df['trip_id'].str.strip('"').str.strip()
        trips_df['direction_id'] = trips_df['direction_id'].str.strip('"').str.strip()
        trips_df['trip_headsign'] = trips_df['trip_headsign'].str.strip('"').str.strip()
        _ferry_trip_metadata = trips_df.set_index('trip_id')[['direction_id', 'trip_headsign']].to_dict('index')
        logger.debug("Loaded metadata for %d ferry trips", len(_ferry_trip_metadata))
        return _ferry_trip_metadata
    except Exception as e:
        logger.error("Failed to load ferry trip metadata: %s", str(e))
        _ferry_trip_metadata = {}
        return _ferry_trip_metadata


def get_ferry_stop_name_map():
    """Build a mapping from ferry stop_id to stop_name."""
    global _ferry_stop_names
    if _ferry_stop_names is not None:
        return _ferry_stop_names

    import logging
    logger = logging.getLogger('mta-api.utils')

    try:
        stops_df = pd.read_csv('ferry_metadata/stops.txt', dtype=str)
        stops_df['stop_id'] = stops_df['stop_id'].str.strip('"').str.strip()
        stops_df['stop_name'] = stops_df['stop_name'].str.strip('"').str.strip()
        _ferry_stop_names = stops_df.set_index('stop_id')['stop_name'].to_dict()
        logger.debug("Loaded names for %d ferry stops", len(_ferry_stop_names))
        return _ferry_stop_names
    except Exception as e:
        logger.error("Failed to load ferry stop names: %s", str(e))
        _ferry_stop_names = {}
        return _ferry_stop_names


def get_ferry_stops_by_trip():
    """Build an ordered stop sequence for each ferry trip."""
    global _ferry_stop_times_by_trip
    if _ferry_stop_times_by_trip is not None:
        return _ferry_stop_times_by_trip

    import logging
    logger = logging.getLogger('mta-api.utils')

    try:
        stop_times_df = pd.read_csv(
            'ferry_metadata/stop_times.txt',
            usecols=['trip_id', 'stop_id', 'stop_sequence', 'arrival_time', 'departure_time'],
            dtype=str
        )
        stop_times_df['trip_id'] = stop_times_df['trip_id'].str.strip('"').str.strip()
        stop_times_df['stop_id'] = stop_times_df['stop_id'].str.strip('"').str.strip()
        # Parse stop_sequence and arrival_time into numeric values
        stop_times_df['stop_sequence'] = stop_times_df['stop_sequence'].astype(int)

        def _time_to_seconds(t):
            try:
                parts = t.split(':')
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                return h * 3600 + m * 60 + s
            except Exception:
                return None

        stop_times_df['arrival_seconds'] = stop_times_df['arrival_time'].apply(_time_to_seconds)
        stop_times_df['departure_seconds'] = stop_times_df['departure_time'].apply(_time_to_seconds)
        sorted_times = stop_times_df.sort_values(['trip_id', 'stop_sequence'])
        # Include both arrival_seconds and departure_seconds so callers can compute offsets between stops
        _ferry_stop_times_by_trip = sorted_times.groupby('trip_id').apply(
            lambda df: df[['stop_id', 'stop_sequence', 'arrival_seconds', 'departure_seconds']].to_dict('records')
        ).to_dict()
        logger.debug("Loaded stop sequences for %d ferry trips", len(_ferry_stop_times_by_trip))
        return _ferry_stop_times_by_trip
    except Exception as e:
        logger.error("Failed to load ferry stops by trip: %s", str(e))
        _ferry_stop_times_by_trip = {}
        return _ferry_stop_times_by_trip


def get_ferry_direction_id(entity):
    """Get ferry direction_id from the feed entity or ferry trip metadata."""
    if 'tripUpdate' in entity and 'trip' in entity['tripUpdate']:
        trip = entity['tripUpdate']['trip']
        direction_id = trip.get('directionId') or trip.get('direction_id')
        if direction_id in ('0', '1'):
            return str(direction_id)
        trip_id = trip.get('tripId')
        if trip_id:
            metadata = get_ferry_trip_metadata()
            trip_meta = metadata.get(normalize_string(trip_id))
            if trip_meta:
                return trip_meta.get('direction_id')
    return None


def get_ferry_direction(entity):
    """Map ferry direction_id to ferry direction symbols for the app."""
    direction_id = get_ferry_direction_id(entity)
    if direction_id == '1':
        return 'I'
    if direction_id == '0':
        return 'O'
    return None


def get_ferry_trip_headsign(entity):
    """Get a ferry trip headsign from the feed entity or metadata."""
    if 'tripUpdate' in entity and 'trip' in entity['tripUpdate']:
        trip = entity['tripUpdate']['trip']
        headsign = trip.get('tripHeadsign') or trip.get('trip_headsign')
        if headsign:
            return headsign
        trip_id = trip.get('tripId')
        if trip_id:
            metadata = get_ferry_trip_metadata()
            trip_meta = metadata.get(normalize_string(trip_id))
            if trip_meta:
                return trip_meta.get('trip_headsign')
    return None


def get_ferry_next_stop(entity, current_stop_id):
    """Get the next stop name for a ferry trip if available."""
    if current_stop_id is None:
        return None

    stop_name_map = get_ferry_stop_name_map()
    normalized_stop_id = normalize_string(current_stop_id)
    if not normalized_stop_id:
        return None

    def _find_next_stop(stops_by_trip):
        for index, stop_entry in enumerate(stops_by_trip):
            if normalize_string(stop_entry.get('stop_id')) == normalized_stop_id:
                if index + 1 < len(stops_by_trip):
                    next_stop_id = stops_by_trip[index + 1]['stop_id']
                    return stop_name_map.get(next_stop_id)
                break
        return None

    if 'tripUpdate' in entity and 'trip' in entity['tripUpdate']:
        trip_id = entity['tripUpdate']['trip'].get('tripId')
        if trip_id:
            stops_by_trip = get_ferry_stops_by_trip().get(normalize_string(trip_id))
            if stops_by_trip:
                next_stop = _find_next_stop(stops_by_trip)
                if next_stop:
                    return next_stop

    # Fallback: use stopSequence from the realtime update to infer the next stop
    updates = get_updates(entity)
    if updates:
        stop_sequence = updates[0].get('stopSequence') or updates[0].get('stop_sequence')
        try:
            stop_sequence = int(stop_sequence)
        except Exception:
            stop_sequence = None

        if stop_sequence is not None:
            for trip_stops in get_ferry_stops_by_trip().values():
                for index, stop_entry in enumerate(trip_stops):
                    if normalize_string(stop_entry.get('stop_id')) == normalized_stop_id and stop_entry.get('stop_sequence') == stop_sequence:
                        if index + 1 < len(trip_stops):
                            next_stop_id = trip_stops[index + 1]['stop_id']
                            return stop_name_map.get(next_stop_id)
                        break

    return None


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
            return ferry_map.get(normalize_string(trip_id))

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
    if not routes:
        return None

    if len(routes) == 1:
        return next(iter(routes))

    preferred = ['ERA', 'ERB', 'AS', 'SB', 'RS', 'RW', 'RWS', 'RES', 'SG', 'ER']
    for route in preferred:
        if route in routes:
            return route

    return sorted(routes)[0]


def get_ferry_subroute(entity):
    """Detect ferry subroute variant (e.g., ERA or ERB) from trip headsign or metadata.

    Returns a more specific route id like 'ERA' or 'ERB' when available, otherwise `None`.
    """
    import re

    def _extract_from_headsign(headsign):
        if not headsign:
            return None
        # Look for patterns like '(E R A)', 'E R A', 'ERA', 'ER A', 'ERB', etc.
        m = re.search(r'\(\s*E\s*R\s*([AB])\s*\)', headsign, re.I)
        if not m:
            m = re.search(r'\bER\s*([AB])\b', headsign, re.I)
        if m:
            return 'ER' + m.group(1).upper()
        # Additional patterns for more robust matching
        if 'ERA' in headsign.upper():
            return 'ERA'
        if 'ERB' in headsign.upper():
            return 'ERB'
        return None

    # First try the realtime trip headsign
    if 'tripUpdate' in entity and 'trip' in entity['tripUpdate']:
        trip = entity['tripUpdate']['trip']
        headsign = trip.get('tripHeadsign') or trip.get('trip_headsign')
        variant = _extract_from_headsign(headsign)
        if variant:
            return variant

        # Fall back to metadata for the tripId when realtime headsign is missing
        trip_id = trip.get('tripId')
        if trip_id:
            metadata = get_ferry_trip_metadata()
            trip_meta = metadata.get(normalize_string(trip_id))
            if trip_meta:
                variant = _extract_from_headsign(trip_meta.get('trip_headsign'))
                if variant:
                    return variant

    # Absolute variant fallback extraction if regex missed spaced notations
    trip_id = None
    if 'tripUpdate' in entity and 'trip' in entity['tripUpdate']:
        trip_id = entity['tripUpdate']['trip'].get('tripId')
    route_id = get_route_id(entity)

    # Enhanced logic: if route_id is ER, try to determine subroute from metadata
    if (route_id == 'ER' or route_id is None) and trip_id:
        metadata = get_ferry_trip_metadata()
        trip_meta = metadata.get(normalize_string(trip_id))
        if trip_meta:
            hs = trip_meta.get('trip_headsign', '')
            if hs:  # Only try extraction if headsign exists
                variant = _extract_from_headsign(hs)
                if variant:
                    return variant
                # Fallback pattern matching
                hs_clean = hs.replace(' ', '').upper()
                if 'ERA' in hs_clean:
                    return 'ERA'
                if 'ERB' in hs_clean:
                    return 'ERB'

    return None
