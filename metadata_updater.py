#!/usr/bin/env python3
import os
import shutil
import hashlib
import tempfile
import zipfile
import logging
from datetime import datetime, timezone
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Configuration
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static_metadata'))

# File to track last update date (in NYC time)
LAST_UPDATE_FILE = os.path.join(DATA_DIR, '.last_update_date.txt')
FEEDS = {
    'ferry': 'https://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx',
    'subway': 'https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip'
}
REQUIRED_FILES = ['trips.txt', 'stops.txt', 'routes.txt']
MIN_TRIP_ROWS = 50  # Sanity check to ensure trips.txt isn't completely empty/corrupted
RETAIN_VERSIONS = 3 # Number of old versions to keep for fallback

class MetadataUpdater:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def _get_hash(self, file_path):
        """Calculate SHA-256 hash of a file to check if it actually changed."""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def download_feed(self, name, url):
        """Download the zip file to a temporary file."""
        logging.info(f"[{name}] Downloading feed from {url}...")
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            fd, temp_path = tempfile.mkstemp(suffix='.zip')
            with os.fdopen(fd, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logging.info(f"[{name}] Download complete.")
            return temp_path
        except Exception as e:
            logging.error(f"[{name}] Download failed: {e}")
            return None

    def validate_and_extract(self, name, zip_path, extract_dir):
        """Extract and ensure the feed isn't corrupted."""
        logging.info(f"[{name}] Validating and extracting...")
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_dir)
            
            # 1. Check if required files exist
            for req_file in REQUIRED_FILES:
                if not os.path.exists(os.path.join(extract_dir, req_file)):
                    logging.error(f"[{name}] Validation failed: Missing {req_file}")
                    return False
            
            # 2. Row count sanity check on trips.txt
            trips_path = os.path.join(extract_dir, 'trips.txt')
            with open(trips_path, 'r') as f:
                row_count = sum(1 for _ in f)
                if row_count < MIN_TRIP_ROWS:
                    logging.error(f"[{name}] Validation failed: trips.txt has only {row_count} rows.")
                    return False
                    
            logging.info(f"[{name}] Feed is valid.")
            return True
        except zipfile.BadZipFile:
            logging.error(f"[{name}] Validation failed: Downloaded file is not a valid zip archive.")
            return False
        except Exception as e:
            logging.error(f"[{name}] Extraction error: {e}")
            return False

    def swap_symlink(self, name, new_target_dir):
        """Perform an atomic symlink swap so the API has zero downtime."""
        symlink_path = os.path.join(self.data_dir, f"{name}_active")
        temp_symlink = os.path.join(self.data_dir, f"{name}_active_tmp")
        
        # Create a new temp symlink
        os.symlink(new_target_dir, temp_symlink)
        # Atomically replace the old symlink with the new one
        os.rename(temp_symlink, symlink_path)
        logging.info(f"[{name}] Symlink updated to point to {os.path.basename(new_target_dir)}")

    def _get_nyc_date(self):
        """Get current date in NYC (America/New_York) timezone."""
        now_utc = datetime.now(timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            nyc_time = now_utc.astimezone(ZoneInfo('America/New_York'))
        except ImportError:
            # Python < 3.9: use a 4-hour offset (EDT) which is correct for half the year
            # or simply fall back to UTC date if zoneinfo isn't available
            import pytz
            nyc_time = now_utc.astimezone(pytz.timezone("America/New_York"))
        return nyc_time.date()

    def _has_updated_today(self):
        """Check if metadata has already been updated today (in NYC time)."""
        try:
            if not os.path.exists(LAST_UPDATE_FILE):
                return False
            with open(LAST_UPDATE_FILE, 'r') as f:
                last_date = f.read().strip()
                if last_date:
                    return last_date == str(self._get_nyc_date())
            return False
        except Exception as e:
            logging.warning(f"Error checking last update date: {e}")
            return False

    def _record_update_today(self):
        """Record that an update has been run today."""
        try:
            with open(LAST_UPDATE_FILE, 'w') as f:
                f.write(str(self._get_nyc_date()))
        except Exception as e:
            logging.warning(f"Error recording update date: {e}")

    def cleanup_old_versions(self, name):
        """Delete old timestamped directories to prevent disk bloat."""
        all_dirs = [d for d in os.listdir(self.data_dir) if d.startswith(f"{name}_20") and os.path.isdir(os.path.join(self.data_dir, d))]
        all_dirs.sort() # Oldest first
        
        if len(all_dirs) > RETAIN_VERSIONS:
            dirs_to_delete = all_dirs[:-RETAIN_VERSIONS]
            for d in dirs_to_delete:
                dir_path = os.path.join(self.data_dir, d)
                shutil.rmtree(dir_path)
                logging.info(f"[{name}] Cleaned up old version: {d}")

    def update_feed(self, name, url):
        """Main orchestration method for a single feed."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        target_dir_name = f"{name}_{timestamp}"
        target_dir = os.path.join(self.data_dir, target_dir_name)
        
        zip_path = self.download_feed(name, url)
        if not zip_path:
            return

        with tempfile.TemporaryDirectory() as temp_extract_dir:
            if self.validate_and_extract(name, zip_path, temp_extract_dir):
                # Move from temp to final versioned directory
                shutil.move(temp_extract_dir, target_dir)
                self.swap_symlink(name, target_dir)
                self.cleanup_old_versions(name)
            else:
                logging.warning(f"[{name}] Update aborted due to validation failure. Retaining current active feed.")

        # Clean up the downloaded zip file
        if os.path.exists(zip_path):
            os.remove(zip_path)

    def run_all(self):
        """Run the update cycle, but only if today's update hasn't been done yet (NYC time)."""
        # Check if we've already updated today (in NYC time)
        if self._has_updated_today():
            logging.info("Metadata update already run today (NYC time). Skipping update.")
            return

        logging.info("Starting GTFS Metadata Update Cycle...")
        for name, url in FEEDS.items():
            self.update_feed(name, url)
        logging.info("Update Cycle Complete.")

        # Record that we've updated today
        self._record_update_today()

if __name__ == "__main__":
    updater = MetadataUpdater(DATA_DIR)
    updater.run_all()
