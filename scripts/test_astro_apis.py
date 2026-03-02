#!/usr/bin/env python3
"""Test astrophysics API endpoints."""

import httpx
import feedparser

# API URLs
NOAA_KP_INDEX = "https://services.swpc.noaa.gov/json/planetary-k-index.json"
NOAA_AURORA = "https://services.swpc.noaa.gov/json/ovation-aurora-now.json"
NOAA_SOLAR_WIND = "https://services.swpc.noaa.gov/json/solar-wind.json"
USGS_EARTHQUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
STEFAN_BURNS_YOUTUBE = "https://www.youtube.com/@StefanBurns/videos"
STEFAN_BURNS_YOUTUBE_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id=UC2Zp0hTbqQ9lI1cP0a0YJgA"

print("=== Testing NOAA KP Index ===")
try:
    response = httpx.get(NOAA_KP_INDEX, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Data points: {len(data)}")
        if data:
            print(f"Latest: {data[0]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Testing NOAA Aurora ===")
try:
    response = httpx.get(NOAA_AURORA, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Data points: {len(data)}")
        if data:
            print(f"First location visibility: {data[0].get('aurora_visibility', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Testing NOAA Solar Wind ===")
try:
    response = httpx.get(NOAA_SOLAR_WIND, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Data points: {len(data)}")
        if len(data) > 1:
            print(f"Latest speed: {data[1].get('speed', 'N/A')} km/s")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Testing USGS Earthquakes ===")
try:
    response = httpx.get(USGS_EARTHQUAKES, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        count = data.get("metadata", {}).get("count", 0)
        print(f"Earthquakes found: {count}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Testing Stefan Burns YouTube (web URL) ===")
try:
    response = httpx.get(STEFAN_BURNS_YOUTUBE, timeout=10, follow_redirects=True)
    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Testing Stefan Burns YouTube (RSS feed) ===")
try:
    feed = feedparser.parse(STEFAN_BURNS_YOUTUBE_RSS)
    print(f"Feed title: {feed.get('feed', {}).get('title', 'N/A')}")
    print(f"Entries: {len(feed.entries)}")
    if feed.entries:
        print(f"First video: {feed.entries[0].get('title', 'N/A')}")
        print(f"Video ID: {feed.entries[0].get('yt_videoid', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")