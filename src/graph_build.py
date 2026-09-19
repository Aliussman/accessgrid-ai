"""Build and cache the AccessGrid data files.

Downloads the road network for the study area, the hospital locations,
and the population per node. Writes:
  data/city.graphml      drive network with speed_kph and travel_time
  data/hospitals.geojson hospitals snapped to nearest node (name, lat, lon, node_id)
  data/pop_by_node.csv   node_id, population

Usage:  python -m src.graph_build
"""
from __future__ import annotations

import http.client
import socket
import ssl
import sys
import urllib.parse
import zlib
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from pyproj import Geod
from shapely.geometry import Point

from .config import (
    CENTRE_LAT,
    CENTRE_LON,
    DATA_DIR,
    DEFAULT_SPEED_KPH,
    GRAPHML_PATH,
    HOSPITALS_PATH,
    OVERFASS_ENDPOINTS_FALLBACK,
    POP_PATH,
    POP_RASTER_PATH,
    RADIUS_KM,
)

_GEOD = Geod(ellps="WGS84")


def km_to_m(km: float) -> float:
    return km * 1000.0


def _probe_overpass_ip(host: str, ip: str, path: str) -> bool:
    """POST a trivial query to (host pinned to ip) and report success."""
    body = urllib.parse.urlencode(
        {
            "data": (
                f"[out:json][timeout:10];"
                f"node({CENTRE_LAT:.4f},{CENTRE_LON:.4f},"
                f"{CENTRE_LAT + 0.001:.4f},{CENTRE_LON + 0.001:.4f});out 1;"
            )
        }
    )
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(ip, port=443, timeout=15, context=ctx)
        conn.request(
            "POST", path, body=body,
            headers={
                "Host": host,
                "User-Agent": "AccessGrid/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp = conn.getresponse()
        ok = resp.status == 200 and b"element" in resp.read(2000)
        conn.close()
        return ok
    except Exception:
        return False


def _pin_host_to_ip(hostname: str, ip: str) -> None:
    """Globally resolve hostname -> ip in socket.getaddrinfo."""
    original = socket.getaddrinfo

    def _getaddrinfo(*args, **kwargs):
        if hostname == next(iter(args), kwargs.get("host")):
            kwargs.pop("host", None)
            return original(ip, *args[1:], **kwargs)
        return original(*args, **kwargs)

    socket.getaddrinfo = _getaddrinfo


def try_overpass_endpoints() -> bool:
    """Point osmnx at a reachable Overpass endpoint; returns True if any works."""
    import osmnx._http as ox_http

    # osmnx pins DNS to whichever single IP gethostbyname returns, which may be
    # firewalled. We probe every candidate IP and pin to a working one instead.
    ox_http._config_dns = lambda url: None  # noqa: SLF001 - neutralise osmnx pinning
    for url in OVERFASS_ENDPOINTS_FALLBACK:
        parts = urllib.parse.urlparse(url)
        host, path = parts.hostname, parts.path
        root = url.rsplit("/interpreter", 1)[0]
        found = False
        try:
            _, _, addresses = socket.gethostbyname_ex(host)
        except socket.gaierror:
            addresses = []
        if addresses:
            for ip in addresses:
                if _probe_overpass_ip(host, ip, path):
                    print(f"Using Overpass endpoint: {root} (IP {ip})")
                    _pin_host_to_ip(host, ip)
                    ox.settings.overpass_url = root
                    ox.settings.http_user_agent = "AccessGrid/1.0"
                    found = True
                    break
        if not found:
            import requests

            try:
                r = requests.post(
                    url, data={"data": "[out:json][timeout:10];node(30.7,76.7,30.71,76.71);out 1;"},
                    timeout=15, headers={"User-Agent": "AccessGrid/1.0"},
                )
                if r.status_code == 200:
                    print(f"Using Overpass endpoint: {root} (hostname)")
                    ox.settings.overpass_url = root
                    ox.settings.http_user_agent = "AccessGrid/1.0"
                    found = True
            except Exception:
                continue
        if found:
            return True
    print("WARNING: all Overpass endpoints unreachable.")
    return False


def _finalize_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Undirected, largest SCC, speeds and travel-time edge attributes."""
    graph = ox.convert.to_undirected(graph)
    largest = max(nx.connected_components(graph), key=len)
    graph = graph.subgraph(largest).copy()  # largest (strong) component on undirected graph
    graph = ox.add_edge_speeds(graph, hwy_speeds=None, fallback=DEFAULT_SPEED_KPH)
    for _u, _v, key, data in graph.edges(keys=True, data=True):
        speed_kph = float(data.get("speed_kph", DEFAULT_SPEED_KPH)) or DEFAULT_SPEED_KPH
        length_m = float(data.get("length", 0.0))
        data["travel_time"] = length_m / (speed_kph * 1000.0 / 60.0)  # minutes
        data["speed_kph"] = float(speed_kph)
    return graph


def download_graph() -> nx.MultiDiGraph:
    """Build the drive network from the cached local extract if present,
    otherwise download it from Overpass. Both paths return a graph with
    speed_kph and travel_time (minutes) on every edge."""
    extract = DATA_DIR / "mohali_extract.osm"
    if extract.exists():
        print(f"Using cached local OSM extract: {extract.name}")
        graph = ox.graph_from_xml(str(extract), simplify=True, retain_all=True)
        print(f"Loaded {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges from XML")
        return _finalize_graph(graph)

    centre = (float(CENTRE_LAT), float(CENTRE_LON))
    dist_m = km_to_m(RADIUS_KM)

    if not try_overpass_endpoints():
        raise RuntimeError(
            "No Overpass endpoint reachable and no local extract found. "
            "Run scripts/build_from_geofabrik.py (or put mohali_extract.osm in data/)."
        )

    # Version-safe OSMnx call. graph_from_point's dist is metres in 2.x,
    # kilometres in 1.x. Detect the unit from the installed version.
    graph = None
    for unit, factor in (("m", 1.0), ("km", 1000.0)):
        try:
            if unit == "m":  # osmnx >= 2.0
                graph = ox.graph_from_point(centre, dist=dist_m, network_type="drive")
            else:  # osmnx < 2.0 fallback
                graph = ox.graph_from_point(centre, dist=dist_m / 1000.0, network_type="drive")
            break
        except (TypeError, KeyError):
            continue
    if graph is None:
        raise RuntimeError("Could not download the road graph. Check internet / OSMnx API.")

    return _finalize_graph(graph)


def save_graph(graph: nx.MultiDiGraph) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, filepath=str(GRAPHML_PATH))


def get_hospitals(graph: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    """Find OSM amenity=hospital features and snap each to its nearest node."""
    centre = (float(CENTRE_LAT), float(CENTRE_LON))
    dist_m = km_to_m(RADIUS_KM)

    extract = DATA_DIR / "mohali_extract.osm"
    try:
        if extract.exists():
            features = ox.features_from_xml(
                str(extract), tags={"amenity": "hospital"}
            )
        else:
            if not try_overpass_endpoints():
                raise RuntimeError("no reachable Overpass endpoint")
            features = ox.features_from_point(centre, tags={"amenity": "hospital"}, dist=dist_m)
    except Exception as exc:
        print(f"WARNING: hospital query failed ({exc}), writing an empty hospitals file.")
        empty = gpd.GeoDataFrame(
            {"name": [], "lat": [], "lon": [], "node_id": []},
            geometry=[],
            crs="EPSG:4326",
        )
        return empty

    if features.empty:
        print("WARNING: no hospital features found in this area.")
        return gpd.GeoDataFrame(
            {"name": [], "lat": [], "lon": [], "node_id": []},
            geometry=[],
            crs="EPSG:4326",
        )

    rows = []
    for i, (osm_id, feat) in enumerate(features.iterrows()):
        geom = feat.geometry
        if geom.is_empty or geom is None:
            continue
        point = geom.representative_point() if geom.geom_type != "Point" else geom
        raw_name = str(feat.get("name", "")).strip()
        if not raw_name or raw_name.lower() == "nan":
            raw_name = ""
        name = raw_name or f"Unnamed hospital {i + 1}"
        nearest = ox.nearest_nodes(graph, X=float(point.x), Y=float(point.y))
        # Rough facility type from OSM tags (healthcare > building > amenity).
        htype = str(feat.get("healthcare", "")).strip() or str(
            feat.get("building", "")
        ).strip() or "hospital"
        if htype.lower() in ("nan", "none", ""):
            htype = "Hospital"
        # Synthetic, deterministic bed capacity (0-1000) from the OSM id.
        # Not real data - used only for demonstration and clearly disclosed.
        beds = int(zlib.crc32(str(osm_id).encode("utf-8")) % 1001)
        rows.append({"osm_id": str(osm_id), "name": name, "lat": float(point.y),
                     "lon": float(point.x), "node_id": int(nearest),
                     "type": htype.capitalize(), "capacity": beds})

    j = gpd.GeoDataFrame(
        rows, geometry=[Point(r["lon"], r["lat"]) for r in rows], crs="EPSG:4326"
    )
    print(f"Found {len(j)} hospital features from OSM.")
    return j


def _population_from_raster(graph: nx.MultiDiGraph) -> pd.DataFrame:
    """Assign raster cell centroids to nearest nodes and sum population."""
    if POP_RASTER_PATH is None or not POP_RASTER_PATH.exists():
        raise FileNotFoundError(f"Raster not found: {POP_RASTER_PATH}")

    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.transform import xy

    xs = [float(graph.nodes[n]["x"]) for n in graph.nodes]
    ys = [float(graph.nodes[n]["y"]) for n in graph.nodes]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)

    with rasterio.open(str(POP_RASTER_PATH)) as src:
        window = from_bounds(min_x, min_y, max_x, max_y, transform=src.transform)
        band = src.read(1, window=window)
        transform = src.window_transform(window)

    n_steps = band.shape
    # Stride to keep cell count manageable for the graph query.
    stride = max(1, int(np.sqrt(band.size / 200_000)))
    if stride > 1:
        band = band[::stride, ::stride]
        transform = transform * transform.scale(stride, stride)

    py, px = np.nonzero(np.isfinite(band) & (band > 0))
    vals = band[py, px]
    lons, lats = xy(transform, py, px, offset="center")
    if len(lons) == 0:
        raise ValueError("Raster has no finite positive cells inside the study area.")
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)

    node_ids = ox.nearest_nodes(graph, X=lons, Y=lats)
    df = pd.DataFrame({"node_id": node_ids, "population": vals}).groupby(
        "node_id", as_index=False
    ).sum()
    return df


def _population_synthetic(graph: nx.MultiDiGraph) -> pd.DataFrame:
    """Clearly labelled synthetic population, so the UI can be built offline.

    Model: population rises near the city centre (Gaussian kernel) and
    junctions with more roads. It is NOT real survey / WorldPop data.
    """
    rng = np.random.default_rng(42)
    centre_lon, centre_lat = float(CENTRE_LON), float(CENTRE_LAT)

    rows = []
    for node, data in graph.nodes(data=True):
        lon, lat = float(data["x"]), float(data["y"])
        # Approx great-circle distance in km.
        _, _, dist_m = _GEOD.inv(centre_lon, centre_lat, lon, lat)
        d_km = abs(dist_m) / 1000.0
        degree = float(graph.degree(node))
        gaussian = np.exp(-((d_km / max(RADIUS_KM / 2.0, 1e-6)) ** 2) / 2.0)
        population = 15.0 + 420.0 * gaussian + 12.0 * degree
        population *= rng.uniform(0.7, 1.3)
        rows.append({"node_id": int(node), "population": float(population)})
    df = pd.DataFrame(rows)
    df["population"] = df["population"].round().astype(int)
    return df


def _vulnerability_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Synthetic, deterministic per-node vulnerability shares (0-1) used for
    equity analysis. NOT real census data; keyed by node_id so the file is
    stable across rebuilds."""
    out = df.copy()
    counts = {
        "elderly": (0.06, 0.30),
        "mobility": (0.05, 0.32),
        "lowcar": (0.18, 0.72),
    }
    for group, (lo, hi) in counts.items():
        draws = []
        for node in out["node_id"].astype(np.int64):
            rng = np.random.default_rng((int(node) + 11_000 * (group == "mobility")
                                         + 23_000 * (group == "lowcar")) % (2**32))
            draws.append(lo + rng.uniform() * (hi - lo))
        out[group] = np.round(np.clip(np.asarray(draws), 0.0, 1.0), 3)
    return out


def save_population(graph: nx.MultiDiGraph) -> None:
    """Write pop_by_node.csv (raster if available, else synthetic)."""
    synthetic = True
    try:
        df = _population_from_raster(graph)
        synthetic = False
        print(f"Population raster: {POP_RASTER_PATH} (real WorldPop-style cells).")
    except FileNotFoundError:
        df = _population_synthetic(graph)
        print("Population raster not configured -> USING SYNTHETIC POPULATION "
              "(clearly labelled, non-real).")
    except Exception as exc:  # noqa: BLE001 - surface but continue with synthetic
        df = _population_synthetic(graph)
        print(f"Population raster failed ({exc}) -> USING SYNTHETIC FALLBACK.")

    df = _vulnerability_shares(df)
    df.to_csv(POP_PATH, index=False)
    print(f"Population rows written to {POP_PATH.name}: {len(df)} nodes, "
          f"total {int(df['population'].sum()):,} (synthetic={synthetic}); "
          "added synthetic elderly/mobility/lowcar shares for equity analysis.")


def write_manifest() -> None:
    lines = [
        "AccessGrid cached data",
        f"Study area centre: {CENTRE_LAT}, {CENTRE_LON}  radius: {RADIUS_KM} km",
        "city.graphml       : drive network, largest SCC, speed_kph & travel_time(min)",
        "hospitals.geojson  : OSM amenity=hospital, snapped to nearest node;",
        "                    type (osm tag); capacity = SYNTHETIC beds (not real)",
        "pop_by_node.csv    : node_id, population + SYNTHETIC vulnerability shares",
        "                    (elderly/mobility/lowcar in [0,1], NOT real census)",
        f"population source  : {'POP_RASTER=' + str(POP_RASTER_PATH) if POP_RASTER_PATH else 'SYNTHETIC FALLBACK (not real data)'}",
    ]
    (DATA_DIR / "DATA_NOTES.txt").write_text("\n".join(lines) + "\n")


def main() -> None:
    print("Downloading road graph (first run needs internet, then cached)...")
    graph = download_graph()
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    print(f"Graph: {n_nodes} nodes, {n_edges} edges")

    save_graph(graph)
    print(f"Saved {GRAPHML_PATH.name}")

    hospitals = get_hospitals(graph)
    hospitals.to_file(str(HOSPITALS_PATH), driver="GeoJSON")
    print(f"Saved {HOSPITALS_PATH.name} with {len(hospitals)} hospitals")

    save_population(graph)
    write_manifest()

    total_pop = pd.read_csv(POP_PATH)["population"].sum()
    print("-" * 60)
    print(f"SUMMARY  nodes={n_nodes}  edges={n_edges}  "
          f"hospitals={len(hospitals)}  total_population={total_pop:,.0f}")


if __name__ == "__main__":
    sys.exit(main())