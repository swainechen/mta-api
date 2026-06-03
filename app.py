import time

from flask import Flask, jsonify
from flask_cors import CORS
from markupsafe import escape

from times import Times
from stations import Stations
from routes import Routes

# __name__ = name of current module
app = Flask(__name__)
CORS(app)


@app.route('/')
def homepage1():
    return 'Welcome to SubwayApi'


@app.route('/api/')
def homepage2():
    return 'Welcome to SubwayApi'


@app.route('/api/train_times/')
def train_times():
    """Get arrival times for all subway stations."""
    trains = Times().train_times
    return jsonify(trains)


@app.route('/api/ferry_times/')
def ferry_times():
    """Get arrival times for all ferry stations."""
    ferry = Times().ferry_times
    return jsonify(ferry)


@app.route('/api/times/')
def all_times():
    """Get arrival times for all stations (subway + ferry)."""
    times = Times().get_all_times()
    return jsonify(times)


@app.route('/api/train_times/<station_id>')
def nextTrains(station_id):
    """Get arrival times for a specific subway station."""
    times = Times().train_times
    station_route = list(filter(lambda station: station['station_id'] == station_id, times))
    return jsonify(station_route)


@app.route('/api/ferry_times/<station_id>')
def nextFerry(station_id):
    """Get arrival times for a specific ferry station, prioritizing next stops."""
    times = Times().ferry_times
    station_route_full = list(filter(lambda station: station['station_id'] == station_id, times))
    # Filter out entries that are marked as terminal, unless the list only contains one entry (i.e., the station IS the terminal point)
    station_route = [
        station for station in station_route_full
        if station['terminal'] == False or len(station_route_full) == 1
    ]
    return jsonify(station_route)


@app.route('/api/times/<station_id>')
def nextAll(station_id):
    """Get arrival times for a specific station (subway or ferry)."""
    times = Times().get_all_times()
    station_route = list(filter(lambda station: station['station_id'] == station_id, times))
    return jsonify(station_route)


@app.route('/api/stations/')
def stops():
    """Get all stations (subway + ferry)."""
    stations = Stations().stations
    return jsonify(stations)


@app.route('/api/routes/')
def routes():
    """Get all routes (subway + ferry)."""
    routes = Routes().routes
    return jsonify(routes)


if __name__ == "__main__":
    import bjoern
    bjoern.run(app, "0.0.0.0", 5280)
