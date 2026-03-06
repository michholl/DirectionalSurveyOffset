"""
Pre-computation engine for Lateral Well Offset Analysis.

Loads DS.csv, computes Cartesian coordinates, identifies lateral wells,
finds perpendicular plane intersections, computes gunbarrel offsets,
and caches everything to disk.

Usage:
    python precompute.py            # Full pre-computation
    python precompute.py --force    # Force re-computation even if cache exists
"""

import hashlib
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CSV_PATH = os.path.join(os.path.dirname(__file__), "DS.csv")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache.json")
HASH_PATH = os.path.join(os.path.dirname(__file__), ".csv_hash")

FT_PER_DEG = 364_567.2          # approximate feet per degree of latitude
SURFACE_RADIUS_FT = 10_000.0    # Haversine proximity filter
EARTH_RADIUS_FT = 20_902_231.0  # mean Earth radius in feet
MIN_LATERAL_LENGTH_FT = 1_000.0
INC_THRESHOLD_DEG = 90.0
AZIMUTH_TOLERANCE_DEG = 25.0
VERTICAL_WELL_INC_MAX = 5.0     # wells with max INC below this are excluded


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def file_sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def haversine_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in feet."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_FT * math.asin(math.sqrt(a))


def vector_avg_azimuth(azimuths_deg: np.ndarray) -> float:
    """Circular (vector) mean of azimuths in degrees. Returns 0-360."""
    rads = np.radians(azimuths_deg)
    s = np.sum(np.sin(rads))
    c = np.sum(np.cos(rads))
    avg = math.degrees(math.atan2(s, c)) % 360
    return avg


def azimuth_within(azi1: float, azi2: float, tol: float) -> bool:
    """True if azi1 is within ±tol degrees of azi2 OR of azi2+180 (reverse)."""
    diff = (azi1 - azi2 + 180) % 360 - 180  # signed shortest angle
    if abs(diff) <= tol:
        return True
    diff_rev = (azi1 - (azi2 + 180) + 180) % 360 - 180
    return abs(diff_rev) <= tol


# ---------------------------------------------------------------------------
# Main pre-computation
# ---------------------------------------------------------------------------

def precompute(force: bool = False):
    t_total = time.time()

    # ------------------------------------------------------------------
    # 0. Check cache freshness
    # ------------------------------------------------------------------
    if not force and os.path.exists(CACHE_PATH) and os.path.exists(HASH_PATH):
        with open(HASH_PATH) as f:
            cached_hash = f.read().strip()
        current_hash = file_sha256(CSV_PATH)
        if cached_hash == current_hash:
            print("✓ Cache is up-to-date (CSV unchanged). Skipping pre-computation.")
            return
        print("CSV has changed — re-computing...")
    else:
        if force:
            print("Force flag set — re-computing...")
        else:
            print("No cache found — computing from scratch...")

    # ------------------------------------------------------------------
    # 1. Load CSV
    # ------------------------------------------------------------------
    print("\n[1/6] Loading DS.csv...")
    t0 = time.time()
    df = pd.read_csv(CSV_PATH, low_memory=False)
    print(f"       {len(df):,} rows, {df['UWI'].nunique():,} wells  ({time.time()-t0:.1f}s)")

    # Validate units
    bad_uom = df[df["Uom"] != "FT"]
    if len(bad_uom) > 0:
        print(f"  ⚠ Dropping {len(bad_uom)} rows with Uom != FT")
        df = df[df["Uom"] == "FT"].copy()

    # Convert UWI to string
    df["UWI"] = df["UWI"].astype(str)

    # ------------------------------------------------------------------
    # 2. Compute Cartesian coordinates for every station
    # ------------------------------------------------------------------
    print("\n[2/6] Computing Cartesian coordinates...")
    t0 = time.time()

    # Absolute lat/lon per station
    df["station_lat"] = df["SufaceLatitude"] + df["DeltaLatitude"]
    df["station_lon"] = df["SurfaceLongitude"] + df["DeltaLongitude"]

    # Origin = centroid of all surface locations (kept for metadata/cache only)
    surface_locs = df.groupby("UWI").first()[["SufaceLatitude", "SurfaceLongitude"]]
    origin_lat = surface_locs["SufaceLatitude"].mean()
    origin_lon = surface_locs["SurfaceLongitude"].mean()

    # z coordinate only — x/y are computed per-pair at query time using the
    # lateral midpoint as the local projection origin (see step 5).
    df["z"] = df["TVDSS"]

    print(f"       Origin (metadata): ({origin_lat:.6f}, {origin_lon:.6f})  ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # 3. Identify lateral wells
    # ------------------------------------------------------------------
    print("\n[3/6] Identifying lateral wells...")
    t0 = time.time()

    # Build per-well data structures
    wells = {}  # UWI -> dict of arrays
    for uwi, grp in df.groupby("UWI"):
        grp = grp.sort_values("MeasuredDepth")
        wells[uwi] = {
            "md": grp["MeasuredDepth"].values,
            "inc": grp["Inclination"].values,
            "azi": grp["Azimuth"].values,
            # No pre-projected x/y — coordinates are computed on-demand per pair
            # using the lateral midpoint as the local projection origin.
            "z": grp["z"].values,
            "station_lat": grp["station_lat"].values,
            "station_lon": grp["station_lon"].values,
            "surface_lat": grp["SufaceLatitude"].iloc[0],
            "surface_lon": grp["SurfaceLongitude"].iloc[0],
        }

    laterals = {}  # UWI -> lateral info
    for uwi, w in wells.items():
        max_inc = np.max(w["inc"])
        if max_inc <= INC_THRESHOLD_DEG:
            continue

        # Find first station where INC > 90°
        lateral_mask = w["inc"] > INC_THRESHOLD_DEG
        first_lat_idx = np.argmax(lateral_mask)
        md_start = w["md"][first_lat_idx]
        md_end = w["md"][-1]
        lateral_length = md_end - md_start

        if lateral_length < MIN_LATERAL_LENGTH_FT:
            continue

        # Midpoint station: closest actual station to MD midpoint
        md_mid_target = (md_start + md_end) / 2.0
        mid_idx = np.argmin(np.abs(w["md"] - md_mid_target))

        # Vector-averaged azimuth along lateral section stations
        lat_azimuths = w["azi"][first_lat_idx:]
        avg_azi = vector_avg_azimuth(lat_azimuths)

        laterals[uwi] = {
            "midpoint_idx": int(mid_idx),
            # midpoint_x/y removed — computed fresh per-pair in step 5
            "midpoint_z": float(w["z"][mid_idx]),
            "midpoint_md": float(w["md"][mid_idx]),
            "midpoint_lat": float(w["station_lat"][mid_idx]),
            "midpoint_lon": float(w["station_lon"][mid_idx]),
            "avg_azimuth": float(avg_azi),
            "lateral_length": float(lateral_length),
            "surface_lat": float(w["surface_lat"]),
            "surface_lon": float(w["surface_lon"]),
            "max_inc": float(max_inc),
        }

    print(f"       {len(laterals)} lateral wells identified  ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # 4. Build location caches & per-well metadata for filtering
    # ------------------------------------------------------------------
    print("\n[4/6] Building location caches...")
    t0 = time.time()

    surface_cache = {}  # UWI -> (lat, lon)  — still needed for GeoJSON
    well_bbox = {}      # UWI -> (lat_min, lat_max, lon_min, lon_max) in degrees
    for uwi, w in wells.items():
        surface_cache[uwi] = (w["surface_lat"], w["surface_lon"])
        well_bbox[uwi] = (
            float(np.min(w["station_lat"])), float(np.max(w["station_lat"])),
            float(np.min(w["station_lon"])), float(np.max(w["station_lon"])),
        )

    # Also compute per-well average azimuth & max inclination for filtering.
    # Use lateral-section azimuth (INC > 90°) when available so that build-
    # section azimuths don't skew the filter for offset wells whose surface
    # pad is far from the lateral.
    well_meta = {}
    for uwi, w in wells.items():
        max_inc = float(np.max(w["inc"]))
        if max_inc >= VERTICAL_WELL_INC_MAX:
            lat_mask = w["inc"] > INC_THRESHOLD_DEG
            if np.any(lat_mask):
                avg_azi = vector_avg_azimuth(w["azi"][lat_mask])
            elif np.any(w["inc"] > 10):
                avg_azi = vector_avg_azimuth(w["azi"][w["inc"] > 10])
            else:
                avg_azi = 0.0
        else:
            avg_azi = None  # vertical well — will be excluded
        well_meta[uwi] = {"max_inc": max_inc, "avg_azi": avg_azi}

    print(f"       {len(surface_cache)} well locations cached  ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # 5. For each lateral: find nearby wells, filter, intersect, compute offsets
    # ------------------------------------------------------------------
    print("\n[5/6] Computing gunbarrel offsets for all laterals...")
    t0 = time.time()

    results = {}
    total = len(laterals)
    progress_interval = max(1, total // 20)

    for i, (lat_uwi, lat_info) in enumerate(laterals.items()):
        if (i + 1) % progress_interval == 0 or i == 0:
            pct = (i + 1) / total * 100
            print(f"       [{i+1}/{total}] ({pct:.0f}%) processing {lat_uwi}...")

        avg_azi = lat_info["avg_azimuth"]
        mlat = lat_info["midpoint_lat"]
        mlon = lat_info["midpoint_lon"]
        mz   = lat_info["midpoint_z"]

        # Local projection anchored at the lateral's midpoint.
        # cos_mid corrects east-west degrees→feet at this specific latitude.
        cos_mid = math.cos(math.radians(mlat))

        # In this local frame the midpoint is always (0, 0, mz).
        mx = 0.0
        my = 0.0

        # Plane normal: direction of average azimuth (horizontal)
        azi_rad = math.radians(avg_azi)
        nx = math.sin(azi_rad)
        ny = math.cos(azi_rad)
        # Plane equation: nx*(x-mx) + ny*(y-my) = 0  →  nx*x + ny*y = 0

        # Right vector (looking from toe toward heel = reverse azimuth)
        # look_dir = (-sin(A), -cos(A), 0)
        # right = look_dir × (0,0,-1) = (-cos(A), sin(A), 0)
        rx = -math.cos(azi_rad)
        ry = math.sin(azi_rad)

        # Strike line segment endpoints in Cartesian (±SURFACE_RADIUS_FT from midpoint)
        # midpoint is (0,0) in local frame
        s1x = rx * SURFACE_RADIUS_FT
        s1y = ry * SURFACE_RADIUS_FT
        s2x = -rx * SURFACE_RADIUS_FT
        s2y = -ry * SURFACE_RADIUS_FT

        # Bounding box of the strike line in degrees (for well_bbox filter)
        STRIKE_BUFFER_FT = 500.0
        strike_buf_lat_deg = (SURFACE_RADIUS_FT + STRIKE_BUFFER_FT) / FT_PER_DEG
        strike_buf_lon_deg = (SURFACE_RADIUS_FT + STRIKE_BUFFER_FT) / (FT_PER_DEG * cos_mid)
        strike_lat_min = mlat - strike_buf_lat_deg
        strike_lat_max = mlat + strike_buf_lat_deg
        strike_lon_min = mlon - strike_buf_lon_deg
        strike_lon_max = mlon + strike_buf_lon_deg

        offsets = []

        for off_uwi in wells:
            if off_uwi == lat_uwi:
                continue

            # (a) Bounding-box overlap: does the well's station footprint (degrees)
            #     overlap the strike line's geographic bounding box?
            bb = well_bbox[off_uwi]  # (lat_min, lat_max, lon_min, lon_max)
            if bb[1] < strike_lat_min or bb[0] > strike_lat_max:
                continue  # no lat overlap
            if bb[3] < strike_lon_min or bb[2] > strike_lon_max:
                continue  # no lon overlap

            # (b) Exclude vertical wells (max INC < 5°)
            meta = well_meta[off_uwi]
            if meta["avg_azi"] is None:
                continue  # vertical well

            # (c) Azimuth compatibility: ±25° of target or reverse
            if not azimuth_within(meta["avg_azi"], avg_azi, AZIMUTH_TOLERANCE_DEG):
                continue

            # (d) Project offset well stations into the lateral's local frame.
            # Using cos_mid for both wells gives <0.1% error for wells within
            # 20 miles of each other (typical offset well distance).
            ow = wells[off_uwi]
            ox = (ow["station_lon"] - mlon) * cos_mid * FT_PER_DEG
            oy = (ow["station_lat"] - mlat) * FT_PER_DEG
            oz = ow["z"]
            omd = ow["md"]

            # Find plane intersection — signed distance per station
            # (mx=0, my=0 in local frame, so: signed_d = nx*ox + ny*oy)
            signed_d = nx * ox + ny * oy

            # Find sign changes
            crossings = []
            for j in range(len(signed_d) - 1):
                if signed_d[j] * signed_d[j + 1] < 0:
                    # Snap to nearest station
                    if abs(signed_d[j]) <= abs(signed_d[j + 1]):
                        snap_idx = j
                    else:
                        snap_idx = j + 1
                    crossings.append(snap_idx)

            if not crossings:
                continue

            # Pick closest crossing to midpoint M (which is at origin 0,0 in local frame)
            best_idx = None
            best_dist3d = float("inf")
            for idx in crossings:
                dx = ox[idx]          # mx = 0
                dy = oy[idx]          # my = 0
                dz = oz[idx] - mz
                d3d = math.sqrt(dx * dx + dy * dy + dz * dz)
                if d3d < best_dist3d:
                    best_dist3d = d3d
                    best_idx = idx

            # (e) Compute gunbarrel offsets
            # dP = Q - M; M is at origin so dP = Q
            qx, qy, qz = float(ox[best_idx]), float(oy[best_idx]), float(oz[best_idx])
            dpx, dpy, dpz = qx, qy, qz - mz

            x_gun = rx * dpx + ry * dpy          # right · dP
            y_gun = -(dpz)                         # positive up (shallower TVDSS)

            # Skip if intersection is beyond the strike line extent
            if abs(x_gun) > SURFACE_RADIUS_FT:
                continue
            dist_h = abs(x_gun)
            dist_v = abs(dpz)
            dist_3d = math.sqrt(dpx ** 2 + dpy ** 2 + dpz ** 2)

            offsets.append({
                "uwi": off_uwi,
                "x_gunbarrel": round(x_gun, 2),
                "y_gunbarrel": round(y_gun, 2),
                "distance_horizontal": round(dist_h, 2),
                "distance_vertical": round(dist_v, 2),
                "distance_3d": round(dist_3d, 2),
                "md_intersection": round(float(omd[best_idx]), 2),
                "intersection_lat": round(float(ow["station_lat"][best_idx]), 7),
                "intersection_lon": round(float(ow["station_lon"][best_idx]), 7),
            })

        results[lat_uwi] = {
            "midpoint": {
                # x/y are always 0 in the local frame (midpoint IS the origin);
                # geographic position is fully captured by lat/lon.
                "x": 0.0,
                "y": 0.0,
                "z": round(mz, 2),
                "md": round(lat_info["midpoint_md"], 2),
                "lat": mlat,
                "lon": mlon,
            },
            "avg_azimuth": round(avg_azi, 2),
            "lateral_length": round(lat_info["lateral_length"], 2),
            "surface_lat": lat_info["surface_lat"],
            "surface_lon": lat_info["surface_lon"],
            "offset_count": len(offsets),
            "offsets": offsets,
            # Strike line endpoints: line perpendicular to azimuth through midpoint.
            # Uses the lateral's own midpoint latitude for the cosine scale —
            # accurate regardless of where the dataset's centroid falls.
            "strike_line": {
                "lat1": round(mlat + (ry * SURFACE_RADIUS_FT) / FT_PER_DEG, 7),
                "lon1": round(mlon + (rx * SURFACE_RADIUS_FT) / (FT_PER_DEG * cos_mid), 7),
                "lat2": round(mlat - (ry * SURFACE_RADIUS_FT) / FT_PER_DEG, 7),
                "lon2": round(mlon - (rx * SURFACE_RADIUS_FT) / (FT_PER_DEG * cos_mid), 7),
            },
        }

    elapsed = time.time() - t0
    total_offsets = sum(r["offset_count"] for r in results.values())
    laterals_with_offsets = sum(1 for r in results.values() if r["offset_count"] > 0)
    print(f"       Done: {total_offsets:,} total offset points across {laterals_with_offsets} laterals  ({elapsed:.1f}s)")

    # ------------------------------------------------------------------
    # 6. Build GeoJSON for map & save cache
    # ------------------------------------------------------------------
    print("\n[6/6] Saving cache...")
    t0 = time.time()

    # GeoJSON for all wells (surface locations + well paths for laterals)
    features = []
    for uwi, (slat, slon) in surface_cache.items():
        is_lateral = uwi in laterals
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(slon), float(slat)]},
            "properties": {
                "uwi": uwi,
                "is_lateral": is_lateral,
                "offset_count": results[uwi]["offset_count"] if is_lateral else None,
                "kind": "surface",
            },
        })

    # Add well path polylines for ALL wells (laterals + non-laterals)
    # Downsample long wells to keep GeoJSON manageable
    MAX_PATH_PTS = 80
    for uwi, w in wells.items():
        lats = w["station_lat"]
        lons = w["station_lon"]
        n = len(lats)
        if n < 2:
            continue
        # Downsample if needed
        if n > MAX_PATH_PTS:
            indices = np.linspace(0, n - 1, MAX_PATH_PTS, dtype=int)
        else:
            indices = np.arange(n)
        coords = [[round(float(lons[i]), 7), round(float(lats[i]), 7)] for i in indices]
        is_lateral = uwi in laterals
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "uwi": uwi,
                "is_lateral": is_lateral,
                "kind": "path",
            },
        })

    # Add midpoint markers for laterals
    for uwi, lat_info in laterals.items():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [
                lat_info["midpoint_lon"], lat_info["midpoint_lat"]
            ]},
            "properties": {
                "uwi": uwi,
                "is_lateral": True,
                "kind": "midpoint",
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}

    # Full cache object
    cache = {
        "metadata": {
            "csv_rows": len(df),
            "total_wells": len(wells),
            "lateral_count": len(laterals),
            "total_offset_points": total_offsets,
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
        },
        "laterals": results,
        "geojson": geojson,
    }

    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)

    # Save CSV hash
    csv_hash = file_sha256(CSV_PATH)
    with open(HASH_PATH, "w") as f:
        f.write(csv_hash)

    cache_size_mb = os.path.getsize(CACHE_PATH) / (1024 * 1024)
    print(f"       Cache saved: {CACHE_PATH} ({cache_size_mb:.1f} MB)  ({time.time()-t0:.1f}s)")

    total_elapsed = time.time() - t_total
    print(f"\n✅ Pre-computation complete in {total_elapsed:.1f}s")
    print(f"   {len(laterals)} laterals, {total_offsets:,} offset points cached")
    print(f"   {laterals_with_offsets} laterals have at least one offset well")

    # Print some stats
    offset_counts = [r["offset_count"] for r in results.values()]
    if offset_counts:
        print(f"\n   Offset well count per lateral:")
        print(f"     Min:    {min(offset_counts)}")
        print(f"     Median: {sorted(offset_counts)[len(offset_counts)//2]}")
        print(f"     Max:    {max(offset_counts)}")
        print(f"     Mean:   {sum(offset_counts)/len(offset_counts):.1f}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    precompute(force=force)
