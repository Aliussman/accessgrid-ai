# AccessGrid AI — Emergency Access Digital Twin

Emergency-access digital twin and decision-support platform for the **Mohali / Chandigarh / Panchkula (Tri-City)** metropolitan area.

A planner or emergency responder simulates road closures, flood inundations, or security cordons; AccessGrid computes which population loses hospital access within the emergency time budget, measures **Accessibility Debt**, models **hospital capacity surge**, and ranks optimal recovery interventions with an interactive **Gemini AI Logistics Copilot** and one-click **Incident Action Plan (IAP)** export.

Built for the **AI-for-Good / Urban Planning Hackathon**.

---

## 🌟 Key Features

- **Multi-Source Dijkstra Routing** — Every graph node is assigned to its nearest hospital (minimum travel time over the drive network). A node is covered if reachable within the threshold (default 15 min).
- **Modern React + Leaflet Dark Mode UI** — Intuitive glassmorphic cockpit with floating telemetry HUD, glowing isochrone catchment rings, pulsing red closures, and hospital capacity markers.
- **Accessibility Debt (AD)** — Quantifies the societal cost of disruptions:
  $$\text{AD} = \sum P_i \times (T_{i, \text{after}} - T_{i, \text{before}})$$
  reported in population-minutes and per-capita debt to objectively rank interventions.
- **🏥 Hospital Surge & Capacity Strain** — Tracks patient displacement ($\Delta$) and overload warnings against hospital bed capacities (`🚨 Critical Surge`, `⚠️ Strained`, `⛔ Access Severed`, `✅ Stable`).
- **Demographic Equity & Vulnerability Tracking** — Evaluates delays across **Elderly (65+)**, **Mobility-Limited**, and **Low-Car** households, automatically flagging disproportionate impacts.
- **🌊 1-Click Multi-Hazard Presets** — *Monsoon Flash Flood (Underpass Inundation)*, *VIP Security Arterial Lockdown*, and *Industrial Hazmat Spill*.
- **🤖 AI Disaster Logistics Copilot** — Interactive multi-turn chat powered by Google GenAI (`gemini-3.6-flash`), with 100% offline deterministic fallback.
- **📋 One-Click Incident Action Plan (IAP) Export** — Generates official emergency response briefs ready for download as Markdown for SDRF, NDRF, and Traffic Police.

---

## 🚀 Quick Start

### 1. Backend Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # Set GEMINI_API_KEY=your_key in .env
python server.py              # Starts FastAPI backend on http://localhost:8000
```

### 2. Frontend Setup (React SPA)
In a separate terminal:
```bash
cd frontend
npm install
npm run dev                   # Starts React frontend on http://localhost:5173
```

### 3. Run Automated Tests
```bash
pytest tests/                 # Runs full suite (45 tests)
```

---

## 🏗️ Architecture

```
frontend/                          React 18 SPA (Vite, Leaflet, Lucide Icons, Glassmorphic CSS)
server.py                          FastAPI REST Backend (Endpoints for overview, simulate, presets, copilot, IAP)
src/engine.py                      Routing engine (Multi-source Dijkstra, isochrones, surge, interventions)
src/ai.py                          Gemini Copilot & Incident Action Plan generator (with template fallbacks)
src/nl.py                          Deterministic natural-language fuzzy intent parser (rapidfuzz)
src/graph_build.py                 Build/cache road network, hospitals, and population from OSM
data/                              Cached datasets (city.graphml, hospitals.geojson, pop_by_node.csv, criticality.csv)
tests/                             Comprehensive pytest suite (test_api.py, test_engine.py, test_ai.py, test_nl.py)
```

---

## ⚙️ Configuration (`.env`)

- `CENTRE_LAT`, `CENTRE_LON`, `RADIUS_KM` — Study area (default: 30.71, 76.75, 8.0 km).
- `DEFAULT_THRESHOLD_MIN` — Emergency coverage threshold (default: 15 min).
- `GEMINI_API_KEY` — Google GenAI API key for live AI briefings.
- `GEMINI_MODEL` — Active Gemini model (default: `gemini-3.6-flash`).
- `POP_RASTER` — Optional GeoTIFF raster path; synthetic fallback used if unset.