#!/usr/bin/env python3
"""Test confirmed working NOAA astrophysics endpoints."""

import httpx
from datetime import datetime

# Confirmed working endpoints
KP_INDEX_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
AURORA_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
SOLAR_WIND_URL = "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"
SOLAR_MAG_URL = "https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json"

def test_kp_index():
    """Test KP Index endpoint."""
    print("\n" + "=" * 60)
    print("Testing KP Index")
    print("=" * 60)
    try:
        response = httpx.get(KP_INDEX_URL, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Data points: {len(data)}")

            # Get latest reading
            if data and len(data) > 0:
                latest = data[-1]  # Last entry is most recent
                print(f"Latest reading: {latest}")
                print(f"KP Index: {latest.get('kp_index', 'N/A')}")
                print(f"Estimated KP: {latest.get('estimated_kp', 'N/A')}")
                print(f"Time tag: {latest.get('time_tag', 'N/A')}")
                return latest
    except Exception as e:
        print(f"Error: {e}")
    return None

def test_aurora():
    """Test Aurora endpoint."""
    print("\n" + "=" * 60)
    print("Testing Aurora Data")
    print("=" * 60)
    try:
        response = httpx.get(AURORA_URL, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Keys: {list(data.keys())}")
            print(f"Observation Time: {data.get('Observation Time', 'N/A')}")
            print(f"Forecast Time: {data.get('Forecast Time', 'N/A')}")
            print(f"Data Format: {data.get('Data Format', 'N/A')}")

            coords = data.get('coordinates', [])
            print(f"Coordinate points: {len(coords)}")

            if coords:
                # Find maximum aurora visibility
                max_aurora = max([c[2] for c in coords if len(c) > 2])
                print(f"Maximum aurora visibility: {max_aurora} (0-12 scale)")

                # Show a few sample coordinates
                print(f"Sample coordinates: {coords[:5]}")
            return data
    except Exception as e:
        print(f"Error: {e}")
    return None

def test_solar_wind():
    """Test Solar Wind endpoint."""
    print("\n" + "=" * 60)
    print("Testing Solar Wind Data")
    print("=" * 60)
    try:
        response = httpx.get(SOLAR_WIND_URL, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Data points: {len(data)}")

            if data:
                latest = data[-1]  # Last entry is most recent
                print(f"Latest reading: {latest}")
                print(f"Time tag: {latest.get('time_tag', 'N/A')}")
                print(f"Speed: {latest.get('proton_speed', 'N/A')} km/s")
                print(f"Density: {latest.get('proton_density', 'N/A')} p/cm³")
                print(f"Temperature: {latest.get('proton_temperature', 'N/A')} K")
                print(f"Source: {latest.get('source', 'N/A')}")
                return latest
    except Exception as e:
        print(f"Error: {e}")
    return None

def test_solar_mag():
    """Test Solar Magnetic Field endpoint."""
    print("\n" + "=" * 60)
    print("Testing Solar Magnetic Field Data")
    print("=" * 60)
    try:
        response = httpx.get(SOLAR_MAG_URL, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Data points: {len(data)}")

            if data:
                latest = data[-1]  # Last entry is most recent
                print(f"Latest reading: {latest}")
                print(f"Time tag: {latest.get('time_tag', 'N/A')}")
                print(f"Bt (total field): {latest.get('bt', 'N/A')} nT")
                print(f"Bz_gsm: {latest.get('bz_gsm', 'N/A')} nT")
                print(f"Bx_gsm: {latest.get('bx_gsm', 'N/A')} nT")
                print(f"By_gsm: {latest.get('by_gsm', 'N/A')} nT")
                print(f"Source: {latest.get('source', 'N/A')}")
                return latest
    except Exception as e:
        print(f"Error: {e}")
    return None

if __name__ == "__main__":
    print(f"Testing NOAA Astrophysics Data Endpoints - {datetime.now().isoformat()}")

    kp_data = test_kp_index()
    aurora_data = test_aurora()
    solar_wind = test_solar_wind()
    solar_mag = test_solar_mag()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"KP Index: {'✓ WORKING' if kp_data else '✗ FAILED'}")
    print(f"Aurora: {'✓ WORKING' if aurora_data else '✗ FAILED'}")
    print(f"Solar Wind: {'✓ WORKING' if solar_wind else '✗ FAILED'}")
    print(f"Solar Magnetic Field: {'✓ WORKING' if solar_mag else '✗ FAILED'}")