#!/usr/bin/env python3
"""Test new astrophysics data sources."""

import httpx
import re

# KP Index sources
KP_SOURCES = [
    ("NOAA Planetary K-Index (product)", "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"),
    ("GFZ Potsdam KP Index", "https://kp.gfz-potsdam.de/app/json/Kp_index.json"),
    ("GFZ KP API", "https://www-app3.gfz-potsdam.de/kp_index/qplasma.json"),
    ("SpaceWeatherLive", "https://www.spaceweatherlive.com/api/v1/planetary-k-index"),
]

# Solar Wind sources
SOLAR_WIND_SOURCES = [
    ("NOAA Solar Wind Plasma", "https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json"),
    ("NOAA ACE Real-Time", "https://services.swpc.noaa.gov/json/ace-mag-7-day.json"),
]

# Aurora sources
AURORA_SOURCES = [
    ("NOAA Aurora 30-min", "https://services.swpc.noaa.gov/json/ovation_aurora_forecast.json"),
    ("NOAA WSA Enlil", "https://services.swpc.noaa.gov/json/wsa-enlil.json"),
]

def test_source(name, url):
    print(f"\n{name}")
    print(f"  URL: {url}")
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        print(f"  Status: {response.status_code}")

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            print(f"  Content-Type: {content_type}")

            if "json" in content_type:
                data = response.json()
                print(f"  Data type: {type(data)}")
                if isinstance(data, list):
                    print(f"  Array length: {len(data)}")
                    if len(data) > 0:
                        print(f"  First item: {data[0]}")
                        if len(data) > 1:
                            print(f"  Second item: {data[1]}")
                elif isinstance(data, dict):
                    print(f"  Keys: {list(data.keys())[:10]}")
                    print(f"  Sample: {dict(list(data.items())[:5])}")
            else:
                print(f"  Text preview: {response.text[:300]}")
            return True
        else:
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing KP Index Sources")
    print("=" * 60)
    for name, url in KP_SOURCES:
        test_source(name, url)

    print("\n" + "=" * 60)
    print("Testing Solar Wind Sources")
    print("=" * 60)
    for name, url in SOLAR_WIND_SOURCES:
        test_source(name, url)

    print("\n" + "=" * 60)
    print("Testing Aurora Sources")
    print("=" * 60)
    for name, url in AURORA_SOURCES:
        test_source(name, url)