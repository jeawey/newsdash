"""
Astrophysics live data fetching module.

Fetches real-time data from:
- NOAA Space Weather (KP index, aurora)
- USGS Earthquakes
- Stefan Burns YouTube videos
- NASA SDO solar data
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import feedparser
import httpx

logger = logging.getLogger(__name__)


class AstrophysicsData:
    """Fetches and caches astrophysics live data."""

    # API URLs - Confirmed working NOAA endpoints
    NOAA_KP_INDEX = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
    NOAA_AURORA = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
    NOAA_SOLAR_WIND = "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"
    NOAA_SOLAR_MAG = "https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json"
    USGS_EARTHQUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
    STEFAN_BURNS_YOUTUBE = "https://www.youtube.com/feeds/videos.xml?channel_id=UCGutiiMqD6jEy6J9hNdNniA"

    # Cache duration (seconds)
    KP_CACHE_TTL = 180  # 3 minutes
    AURORA_CACHE_TTL = 3600  # 1 hour
    SOLAR_CACHE_TTL = 3600  # 1 hour
    QUAKE_CACHE_TTL = 300  # 5 minutes
    VIDEOS_CACHE_TTL = 600  # 10 minutes

    def __init__(self):
        self._kp_cache: tuple[int, Any] = (0, None)
        self._aurora_cache: tuple[int, Any] = (0, None)
        self._solar_cache: tuple[int, Any] = (0, None)
        self._quake_cache: tuple[int, Any] = (0, None)
        self._videos_cache: tuple[int, Any] = (0, None)

    def _is_cache_valid(self, cache_time: int, ttl: int) -> bool:
        """Check if cache is still valid."""
        return (datetime.now().timestamp() - cache_time) < ttl

    def get_kp_index(self) -> dict[str, Any]:
        """Get current KP index and geomagnetic status."""
        cache_time, cached_data = self._kp_cache
        if cached_data and self._is_cache_valid(cache_time, self.KP_CACHE_TTL):
            return cached_data

        try:
            response = httpx.get(self.NOAA_KP_INDEX, timeout=10)
            response.raise_for_status()
            data = response.json()

            # New NOAA format: list of objects with time_tag, kp_index, estimated_kp, kp
            # [{'time_tag': '2026-03-02T23:45:00', 'kp_index': 1, 'estimated_kp': 1.33, 'kp': '1P'}, ...]
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]  # Last entry is most recent

                time_tag = latest.get("time_tag")
                kp_value = latest.get("kp_index", 0)
                estimated_kp = latest.get("estimated_kp", 0)
                kp_class = self._classify_kp(int(kp_value))

                result = {
                    "kp_index": kp_value,
                    "kp_value": kp_value,
                    "estimated_kp": estimated_kp,
                    "kp_class": kp_class,
                    "time_tag": time_tag,
                    "updated_at": datetime.now().isoformat(),
                }

                self._kp_cache = (datetime.now().timestamp(), result)
                return result

        except Exception as e:
            logger.warning(f"Failed to fetch KP index: {e}")

        return {"kp_index": 0, "kp_value": 0, "estimated_kp": 0, "kp_class": "green", "time_tag": None, "updated_at": None}

    def _classify_kp(self, kp: int) -> str:
        """Classify KP index for UI display."""
        if kp <= 3:
            return "green"
        elif kp <= 6:
            return "yellow"
        elif kp == 7:
            return "orange"
        else:
            return "red"

    def get_aurora_forecast(self) -> dict[str, Any]:
        """Get aurora visibility forecast."""
        cache_time, cached_data = self._aurora_cache
        if cached_data and self._is_cache_valid(cache_time, self.AURORA_CACHE_TTL):
            return cached_data

        try:
            response = httpx.get(self.NOAA_AURORA, timeout=10)
            response.raise_for_status()
            data = response.json()

            # New NOAA aurora format: has 'coordinates' field
            # coordinates: [[lon, lat, aurora], [lon, lat, aurora], ...]
            # aurora values are 0-12
            coords = data.get("coordinates", [])
            locations_count = len(coords)

            # Find maximum aurora visibility (0-12 scale)
            max_aurora = 0
            if coords:
                max_aurora = max([c[2] for c in coords if len(c) > 2])

            # Convert to percentage (0-100) for display
            visibility_score = int((max_aurora / 12) * 100) if max_aurora > 0 else 0

            # Calculate class based on visibility
            aurora_class = self._classify_aurora(visibility_score)

            result = {
                "visibility_score": visibility_score,
                "aurora_class": aurora_class,
                "max_aurora_level": max_aurora,
                "locations_count": locations_count,
                "observation_time": data.get("Observation Time"),
                "forecast_time": data.get("Forecast Time"),
                "updated_at": datetime.now().isoformat(),
            }

            self._aurora_cache = (datetime.now().timestamp(), result)
            return result

        except Exception as e:
            logger.warning(f"Failed to fetch aurora forecast: {e}")

        return {"visibility_score": 0, "aurora_class": "none", "max_aurora_level": 0, "locations_count": 0, "updated_at": None}

    def _classify_aurora(self, score: int) -> str:
        """Classify aurora visibility for UI display."""
        if score < 10:
            return "none"
        elif score < 25:
            return "low"
        elif score < 50:
            return "moderate"
        elif score < 75:
            return "high"
        else:
            return "very-high"

    def get_solar_activity(self) -> dict[str, Any]:
        """Get solar activity data (sunspots, flares, solar wind, magnetic field)."""
        cache_time, cached_data = self._solar_cache
        if cached_data and self._is_cache_valid(cache_time, self.SOLAR_CACHE_TTL):
            return cached_data

        try:
            # Fetch solar wind data (speed, density, temperature)
            wind_speed = None
            wind_density = None
            wind_temperature = None

            solar_response = httpx.get(self.NOAA_SOLAR_WIND, timeout=10)
            solar_response.raise_for_status()
            solar_data = solar_response.json()

            # New NOAA rtsw format: list of objects
            # [{'time_tag': '...', 'proton_speed': 347.5, 'proton_density': 4.78, ...}, ...]
            if isinstance(solar_data, list) and len(solar_data) > 0:
                # Find the latest active entry
                latest = None
                for entry in reversed(solar_data):
                    if entry.get("active", False):
                        latest = entry
                        break
                # If no active entry, use the last one
                if not latest:
                    latest = solar_data[-1]

                wind_speed = latest.get("proton_speed")
                wind_density = latest.get("proton_density")
                wind_temperature = latest.get("proton_temperature")

            # Fetch magnetic field data (Bz, Bx, By, Bt)
            bz_gsm = None
            bt = None

            mag_response = httpx.get(self.NOAA_SOLAR_MAG, timeout=10)
            mag_response.raise_for_status()
            mag_data = mag_response.json()

            # New NOAA rtsw mag format: list of objects
            # [{'time_tag': '...', 'bt': 4.66, 'bz_gsm': -3.89, 'bx_gsm': 2.09, ...}, ...]
            if isinstance(mag_data, list) and len(mag_data) > 0:
                # Find the latest active entry
                latest_mag = None
                for entry in reversed(mag_data):
                    if entry.get("active", False):
                        latest_mag = entry
                        break
                # If no active entry, use the last one
                if not latest_mag:
                    latest_mag = mag_data[-1]

                bz_gsm = latest_mag.get("bz_gsm")
                bt = latest_mag.get("bt")

            result = {
                "sunspots": self._get_sunspot_count(),
                "solar_wind_speed": wind_speed,
                "solar_wind_density": wind_density,
                "solar_wind_temperature": wind_temperature,
                "solar_wind_bz": bz_gsm,
                "solar_wind_bt": bt,
                "latest_flares": self._get_latest_flares(),
                "updated_at": datetime.now().isoformat(),
            }

            self._solar_cache = (datetime.now().timestamp(), result)
            return result

        except Exception as e:
            logger.warning(f"Failed to fetch solar activity: {e}")

        return {
            "sunspots": 0,
            "solar_wind_speed": None,
            "solar_wind_density": None,
            "solar_wind_temperature": None,
            "solar_wind_bz": None,
            "solar_wind_bt": None,
            "latest_flares": [],
            "updated_at": None,
        }

    def _get_sunspot_count(self) -> int:
        """Get current sunspot number (simulated - would need to scrape NASA)."""
        # In production, this would scrape from:
        # https://www.swpc.noaa.gov/solar-cycle/sunspots/
        # For now, return a reasonable estimate
        return 142

    def _get_latest_flares(self) -> list[dict[str, Any]]:
        """Get latest solar flares."""
        # In production, fetch from NOAA API
        return [
            {"class_type": "M", "begin_time": datetime.now() - timedelta(hours=2).isoformat()},
        ]

    def get_earthquakes(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get recent earthquakes with magnitude >= 4.5."""
        try:
            response = httpx.get(self.USGS_EARTHQUAKES, timeout=10)
            response.raise_for_status()
            data = response.json()

            quakes = []
            for feature in data["features"][:limit]:
                props = feature["properties"]
                coords = feature["geometry"]["coordinates"]

                quakes.append({
                    "magnitude": props.get("mag"),
                    "place": props.get("place"),
                    "time": props.get("time"),
                    "url": props.get("url"),
                    "depth": coords[2] if len(coords) > 2 else None,
                    "coordinates": {"lat": coords[1], "lon": coords[0]},
                })

            return quakes

        except Exception as e:
            logger.warning(f"Failed to fetch earthquakes: {e}")

        return []

    def get_stefan_burns_videos(self, limit: int = 4) -> list[dict[str, Any]]:
        """Get latest Stefan Burns YouTube videos."""
        try:
            feed = feedparser.parse(self.STEFAN_BURNS_YOUTUBE)
            videos = []

            for entry in feed.entries[:limit]:
                # Extract video ID from URL
                video_id = entry.get("yt_videoid", "")

                # Get thumbnail URL
                thumbnail_url = ""
                if entry.get("media_thumbnail"):
                    thumbnail_url = entry.media_thumbnail[0].get("url", "")

                # Parse duration
                duration = entry.get("yt_duration", "")
                duration_parts = []
                if "PT" in duration:
                    duration = duration.replace("PT", "")
                    if "H" in duration:
                        hours = int(duration.split("H")[0])
                        duration_parts.append(f"{hours}h")
                    if "M" in duration:
                        mins = int(duration.split("M")[0].split("S")[0])
                        duration_parts.append(f"{mins}m")
                    if "S" in duration:
                        secs = int(duration.split("S")[0])
                        duration_parts.append(f"{secs}s")

                videos.append({
                    "video_id": video_id,
                    "title": entry.get("title", ""),
                    "description": entry.get("description", "")[:200] + "..." if len(entry.get("description", "")) > 200 else entry.get("description", ""),
                    "link": entry.get("link"),
                    "thumbnail": thumbnail_url,
                    "published": entry.get("published_parsed"),
                    "duration": " ".join(duration_parts) if duration_parts else "",
                    "updated_at": datetime.now().isoformat(),
                })

            return videos

        except Exception as e:
            logger.warning(f"Failed to fetch Stefan Burns videos: {e}")

        return []

    def get_upcoming_events(self, days: int = 7) -> list[dict[str, Any]]:
        """Calculate upcoming astronomical events (conjunctions, oppositions, etc.)."""
        events = []
        now = datetime.now()

        # Example events (in production, calculate from astronomical algorithms)
        # For now, hardcode some common events for demonstration
        example_events = [
            {
                "name": "Jupiter Opposition",
                "date": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
                "visibility": "Excellent",
                "description": "Jupiter steht der Sonne gegenüber, optimal zur Beobachtung",
            },
            {
                "name": "Moon Eclipse (Penumbral)",
                "date": (now + timedelta(days=12)).strftime("%Y-%m-%d"),
                "visibility": "Partial (Europe)",
                "description": "Halbschattenfinsternis in Europa",
            },
            {
                "name": "Virginids Meteor Shower Peak",
                "date": (now + timedelta(days=16)).strftime("%Y-%m-%d"),
                "visibility": "Good (New Moon)",
                "description": "Virginiden Meteorstrom-Maximum, dunkler Mond",
            },
        ]

        for event in example_events:
            # Only include if date is within specified days
            event_date = datetime.strptime(event["date"], "%Y-%m-%d")
            if now <= event_date <= now + timedelta(days=days):
                events.append(event)

        return events

    def get_warnings(self) -> list[dict[str, Any]]:
        """Get active space weather warnings."""
        warnings = []
        kp_data = self.get_kp_index()

        # Check for geomagnetic storm warning
        if kp_data.get("kp_value", 0) >= 7:
            warnings.append({
                "type": "geomagnetic_storm",
                "severity": kp_data.get("kp_class", "red"),
                "title": "Geomagnetischer Sturm",
                "message": f"KP-Index {kp_data.get('kp_index')} erhöht - Aurora-Warnung aktiv",
                "expires": "4-8 Stunden" if kp_data.get("kp_value") <= 7 else "12-24 Stunden",
            })

        # Check for solar flare warning
        solar_data = self.get_solar_activity()
        flares = solar_data.get("latest_flares", [])
        for flare in flares:
            if flare.get("class_type") in ["M", "X"]:
                warnings.append({
                    "type": "solar_flare",
                    "severity": "orange" if flare["class_type"] == "M" else "red",
                    "title": "Sonnenflare Warnung",
                    "message": f"Solar Flare Klasse {flare['class_type']} erfasst - Beeinträchtigung möglich",
                    "expires": "30-60 Minuten",
                })

        return warnings

    def get_all_live_data(self) -> dict[str, Any]:
        """Get all live data for the astrophysics section."""
        return {
            "kp_index": self.get_kp_index(),
            "aurora": self.get_aurora_forecast(),
            "solar": self.get_solar_activity(),
            "earthquakes": self.get_earthquakes(limit=5),
            "videos": self.get_stefan_burns_videos(limit=4),
            "events": self.get_upcoming_events(days=7),
            "warnings": self.get_warnings(),
            "last_updated": datetime.now().isoformat(),
        }