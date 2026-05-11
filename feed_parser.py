import os
import requests
from google.transit import gtfs_realtime_pb2
from google.protobuf.json_format import MessageToDict
from dotenv import load_dotenv
import os

load_dotenv()


def get_feed(url):
    """Get a single feed from a URL."""
    feed = gtfs_realtime_pb2.FeedMessage()
    headers = {"x-api-key": os.getenv("MTA_API_KEY")}
    response = requests.get(url, headers=headers)
    feed.ParseFromString(response.content)
    return MessageToDict(feed)

def get_ferry_feed():
    """Get a single feed from a URL."""
    url = "http://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"
    feed = gtfs_realtime_pb2.FeedMessage()
    response = requests.get(url)
    feed.ParseFromString(response.content)
    return MessageToDict(feed)


class FeedParser:
    """Parser for MTA feeds - both subway and ferry."""

    def __init__(self):
        self.urls_dict = {
            'ACE': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace',
            'BDFM': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm',
            'G': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g',
            'JZ': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz',
            'NQRW': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw',
            'L': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l',
            '1234567': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs',
            'SIR': 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si',
        }
        self.headers = {"x-api-key": os.getenv("MTA_API_KEY")}
        self.feed = self.combine_feeds()
        self.ferry_feed = self.get_ferry_feed()

    def get_feed(self, url):
        """Get a single feed from a URL."""
        return get_feed(url)

    def combine_feeds(self):
        """Combine all subway feeds into one list of entities."""
        feeds = []
        for url in self.urls_dict.values():
            feeds.append(self.get_feed(url)['entity'])
        # unpack 2d list
        feed = [j for sub in feeds for j in sub]
        return feed

    def get_ferry_feed(self):
        return get_ferry_feed().get('entity', [])
#        """Get ferry feed from local tripupdate file."""
#        ferry_entities = []
#        try:
#            with open('tripupdate', 'rb') as f:
#                feed = gtfs_realtime_pb2.FeedMessage()
#                feed.ParseFromString(f.read())
#                ferry_entities = MessageToDict(feed).get('entity', [])
#        except FileNotFoundError:
#            pass  # Ferry feed file not found, continue with empty
#        return ferry_entities

    def get_all_entities(self):
        """Get all entities from both subway and ferry feeds."""
        return self.feed + self.ferry_feed

    def get_ferry_entities(self):
        """Get only ferry entities."""
        return self.ferry_feed
