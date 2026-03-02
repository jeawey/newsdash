#!/usr/bin/env python3
"""Test various NOAA SWPC API endpoints to find working ones."""

import httpx

# Various NOAA SWPC endpoints to try
KP_ENDPOINTS = [
    "https://services.swpc.noaa.gov/json/planetary-k-index.json",
    "https://services.swpc.noaa.gov/json/planetary-k-index-3-hour.json",
    "https://services.swpc.noaa.gov/json/noaa-indices.json",
    "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
    "https://services.swpc.noaa.gov/text/3-day-geomag-forecast.txt",
]

AURORA_ENDPOINTS = [
    "https://services.swpc.noaa.gov/json/ovation-aurora-now.json",
    "https://services.swpc.noaa.gov/json/ovation_aurora_forecast.json",
    "https://services.swpc.noaa.gov/products/aurora-nowcast-map.json",
]

SOLAR_WIND_ENDPOINTS = [
    "https://services.swpc.noaa.gov/json/solar-wind.json",
    "https://services.swpc.noaa.gov/json/solar-wind-plasma-2-hour.json",
    "https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json",
    "https://services.swpc.noaa.gov/json/ace-magnetometer.json",
]

def test_endpoints(name, endpoints):
    print(f"\n=== Testing {name} ===")
    for url in endpoints:
        try:
            print(f"\nTrying: {url}")
            response = httpx.get(url, timeout=10)
            print(f"  Status: {response.status_code}")
            if response.status_code == 200:
                print(f"  ✓ WORKS!")
                # Try to show sample data
                try:
                    if "json" in response.headers.get("content-type", ""):
                        data = response.json()
                        print(f"  Data type: {type(data)}")
                        if isinstance(data, list):
                            print(f"  Array length: {len(data)}")
                            if len(data) > 0:
                                print(f"  Sample: {data[0] if len(data) == 1 else data[:2]}")
                        elif isinstance(data, dict):
                            print(f"  Keys: {list(data.keys())[:5]}")
                            print(f"  Sample: {dict(list(data.items())[:3])}")
                    else:
                        # Text response
                        print(f"  Response (first 200 chars): {response.text[:200]}")
                except Exception as e:
                    print(f"  Error parsing response: {e}")
            else:
                print(f"  ✗ Failed")
        except Exception as e:
            print(f"  ✗ Error: {e}")

if __name__ == "__main__":
    test_endpoints("KP Index", KP_ENDPOINTS)
    test_endpoints("Aurora", AURORA_ENDPOINTS)
    test_endpoints("Solar Wind", SOLAR_WIND_ENDPOINTS)