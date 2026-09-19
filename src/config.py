"""Central configuration for AccessGrid. Values come from .env when present."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

GRAPHML_PATH = DATA_DIR / "city.graphml"
HOSPITALS_PATH = DATA_DIR / "hospitals.geojson"
POP_PATH = DATA_DIR / "pop_by_node.csv"
CRITICALITY_PATH = DATA_DIR / "criticality.csv"

CENTRE_LAT = float(os.getenv("CENTRE_LAT", "30.71"))
CENTRE_LON = float(os.getenv("CENTRE_LON", "76.75"))
RADIUS_KM = float(os.getenv("RADIUS_KM", "8.0"))

POP_RASTER = os.getenv("POP_RASTER", "")
if POP_RASTER:
    POP_RASTER_PATH = Path(POP_RASTER)
else:
    POP_RASTER_PATH = None

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

DEFAULT_THRESHOLD_MIN = float(os.getenv("DEFAULT_THRESHOLD_MIN", "15"))

DEFAULT_SPEED_KPH = 40.0

# Overpass endpoint. The default overpass-api.de is blocked on some networks;
# www.overpass-api.de runs behind Cloudflare and is reachable more widely.
OVERPASS_ENDPOINT = os.getenv("OVERPASS_ENDPOINT", "https://www.overpass-api.de/api/interpreter")
OVERFASS_ENDPOINTS_FALLBACK = [
    "https://www.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]