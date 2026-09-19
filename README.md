# AccessGrid

Emergency-access digital twin for the Mohali / Chandigarh / Panchkula metro.
A planner closes road segments on a map; AccessGrid recomputes which
population still reaches a hospital within an emergency time budget and
summarises the impact, including an optional Gemini-generated briefing.

Built for a 24 h AI-for-Good hackathon (Urban Planning track).

## What it does

- **Coverage** — every graph node is assigned to its nearest hospital
  (multi-source Dijkstra on edge `travel_time`, minutes). A node is
  *covered* if that time is within a threshold (default 15 min).
- **Closure impact** — closed road segments re-route traffic; the engine
  reports population that *loses* all in-threshold access, is *delayed but
  served*, and which hospitals absorb the loss.
- **Before/after** — the Simulate tab shows average access time and covered
  population before vs after a disruption, plus the top "most affected zones"
  ranked by population × travel-time change (normalised 0-100).
- **Interventions** — the engine ranks ways to restore access: reopen all
  closed segments, reopen each high-usage segment alone, or run an emergency
  corridor (0.7× travel time) around the worst segment. Each candidate reports
  population restored, recovered, average time saved, and accessibility
  recovery %. Pick one to preview it on the map.
- **Scenarios** — close roads two ways: pick a named street from a dropdown
  (``RUN SIMULATION``) or draw a polyline over the map; segments near the line
  are closed automatically.
- **Natural-language input** — the sidebar parses planner sentences such as
  *"What happens if Dakshin Marg is closed during an emergency?"* and
  *"Which intervention helps the most?"* (deterministic, offline; fuzzy road
  matching via rapidfuzz).
- **Criticality** — precomputed per-edge risk (route usage + exact single-edge
  closure for top-150 edges, threshold 10 min at precompute time) shown as
  "Riskiest corridors".
- **What-if engine** — beyond road closure you can also test **"add an
  emergency facility"** (sites it on the most central junction of a chosen
  road and shows newly within-threshold residents + debt prevented) and
  **"emergency corridor"** (0.7× travel time along a chosen road, an
  emergency-only priority route).
- **Accessibility Debt (AD)** — every scenario reports its
  **pop-min accessibility debt** `AD = Σ P_i × (T_i,after − T_i,before)` and
  per-capita debt, so interventions can be compared as "how much plain
  accessibility did this restore".
- **Equity analysis** — population-group-aware: elderly / mobility-limited /
  low-car shares are read from `pop_by_node.csv`, and every impact breaks out
  the travel-time change and lost coverage per group, flagging when a
  disruption *disproportionately* affects a vulnerable group.
- **Interventions** — the engine ranks ways to restore access (reopen all,
  reopen each segment, or an emergency corridor), each reporting debt
  reduction to go with restored/recovered population.
- **AI briefing** — concise analyst-style closure summary and intervention
  recommendation from Google Gemini, with a deterministic template fallback
  when offline.
- Synthetic (formula-based) population and bed counts are clearly labelled
  and flagged in the UI when no real raster is configured, as are the
  vulnerability shares (synthetic, not census).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # optional: set GEMINI_API_KEY for AI briefings

python -m src.graph_build                     # build/refresh cached data
python -m scripts.precompute_criticality      # optional risk-layer scores
streamlit run app.py
```

`app.py` works fully offline (cached local extract + template briefings).
Run tests with `python -m pytest tests/`.

## Data files (`data/`)

| File | Contents |
| --- | --- |
| `city.graphml` | Drive network (largest component), `speed_kph`, `travel_time` (min) per edge |
| `hospitals.geojson` | OSM `amenity=hospital`, snapped to nearest node; `type`, synthetic `capacity` (beds) |
| `pop_by_node.csv` | `node_id, population` per graph node |
| `criticality.csv` | Edge risk scores (usage / affected / lost) |
| `mohali_extract.osm` | Local OSM extract that builds everything offline |

### Population

No population raster was configured, so `pop_by_node.csv` is **synthetic**
(Gaussian around the centre + road-degree bonus, rng seed 42). Set
`POP_RASTER=` in `.env` to a raster path to use real cell data instead.

### Network source

Network + hospitals come from a Geofabrik Northern Zone PBF converted by
`src/osmpbf_extract.py` (pure-Python PBF → OSM XML for osmnx), used because
Overpass mirrors were firewalled during development. With internet access
`graph_build` can use Overpass directly; it prefers the local extract when
present.

## Architecture

```
app.py                             Streamlit + Folium UI (4 tabs: Overview,
                                   Simulate, Impact, Interventions)
scripts/precompute_criticality.py  Edge-risk scoring -> criticality.csv
src/graph_build.py                 Data build/cache (graph, hospitals, pop)
src/engine.py                      Coverage, closure impact, interventions,
                                   named-road + road-edge helpers
src/nl.py                          Deterministic natural-language parser
src/ai.py                          Gemini briefing (template fallback)
src/osmpbf_extract.py              PBF bbox extractor for offline data
src/config.py                      .env-driven configuration
tests/                             pytest suite (engine + AI + NL)
```

## Config (`.env`)

- `CENTRE_LAT`, `CENTRE_LON`, `RADIUS_KM` — study area (default tri-city).
- `DEFAULT_THRESHOLD_MIN` — emergency coverage threshold (default 15).
- `POP_RASTER` — optional population raster; synthetic fallback if unset.
- `GEMINI_API_KEY`, `GEMINI_MODEL` — AI briefing.
- `OVERPASS_ENDPOINT` — fallback Overpass endpoint for graph downloads.