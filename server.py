"""FastAPI Backend for AccessGrid Digital Twin.

Exposes REST endpoints for the modern React frontend.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from shapely import wkt
from shapely.geometry import LineString

from src.ai import (
    ask_copilot,
    explain_interventions,
    generate_incident_action_plan,
    summarize_closure,
)
from src.config import (
    CENTRE_LAT,
    CENTRE_LON,
    DATA_DIR,
    DEFAULT_THRESHOLD_MIN,
    POP_RASTER_PATH,
)
from src.engine import (
    DISASTER_PRESETS,
    Network,
    add_facility_to_closure,
    closure_impact,
    corridor_road,
    coverage,
    facility_node_for_road,
    get_preset_edges,
    hospital_surge_analysis,
    intervention_outcome,
    interventions,
    named_roads,
    road_edges,
    travel_time_bands,
)
from src.nl import parse_scenario

app = FastAPI(title="AccessGrid API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global network load
NET = Network.load()
EDGE_INDEX: Dict[tuple[int, int], list[list[float]]] = {}

# Pre-extract road geometries
for u, v, data in NET.graph.edges(data=True):
    coords = []
    if data.get("geometry"):
        try:
            geom = wkt.loads(data["geometry"])
            if geom.geom_type == "LineString":
                coords = [[float(c[1]), float(c[0])] for c in geom.coords]
        except Exception:
            coords = []
    if not coords:
        a, b = NET.graph.nodes[u], NET.graph.nodes[v]
        coords = [[float(a["y"]), float(a["x"])], [float(b["y"]), float(b["x"])]]
    key = (min(int(u), int(v)), max(int(u), int(v)))
    EDGE_INDEX[key] = coords


def _edge_coords(u: int, v: int) -> list[list[float]]:
    key = (min(int(u), int(v)), max(int(u), int(v)))
    return EDGE_INDEX.get(key, [])


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class SimulateRequest(BaseModel):
    scenario: str = "closure"  # "closure", "facility", "corridor"
    road: Optional[str] = None
    preset_id: Optional[str] = None
    closed_edges: Optional[List[List[int]]] = None
    threshold: float = 15.0


class CopilotRequest(BaseModel):
    query: str
    chat_history: List[Dict[str, str]] = []
    impact: Optional[Dict[str, Any]] = None
    candidates: Optional[List[Dict[str, Any]]] = None


class IAPRequest(BaseModel):
    impact: Dict[str, Any]
    candidates: Optional[List[Dict[str, Any]]] = None


class NLRequest(BaseModel):
    query: str


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/overview")
def get_overview(threshold: float = Query(DEFAULT_THRESHOLD_MIN)):
    snap = coverage(NET, threshold)
    bands = travel_time_bands(NET, snap.get("node_time", {}))

    # Hospitals list with coordinates
    hospitals_data = []
    for h in snap["hospitals"]:
        row = NET.hospitals[NET.hospitals["osm_id"].astype(str) == str(h["osm_id"])]
        if row.empty:
            continue
        g = row.iloc[0].geometry
        lon, lat = (g.x, g.y) if g.geom_type == "Point" else (g.centroid.x, g.centroid.y)
        hospitals_data.append({
            "osm_id": str(h["osm_id"]),
            "name": h["name"],
            "node_id": int(h["node_id"]),
            "type": h.get("type", "Hospital"),
            "capacity": int(h.get("capacity", 100)),
            "service_pop": int(h["service_pop"]),
            "covered_pop": int(h["covered_pop"]),
            "lat": float(lat),
            "lng": float(lon),
        })

    # Sampled nodes for isochrone map
    nodes_sample = []
    nodes_list = list(NET.graph.nodes)
    step = max(1, len(nodes_list) // 1800)
    for n in nodes_list[::step]:
        t = snap["node_time"].get(n, float("inf"))
        d = NET.graph.nodes[n]
        nodes_sample.append({
            "id": int(n),
            "lat": float(d["y"]),
            "lng": float(d["x"]),
            "time": float(t) if t != float("inf") else 999.0,
            "pop": int(NET.population.get(n, 0)),
        })

    # Riskiest corridors
    crit_path = DATA_DIR / "criticality.csv"
    riskiest = []
    if crit_path.exists():
        crit_df = pd.read_csv(crit_path)
        crit_df = crit_df[crit_df["score"].notna()].sort_values("score", ascending=False).head(30)
        for _, row in crit_df.iterrows():
            u, v = int(row["u"]), int(row["v"])
            coords = _edge_coords(u, v)
            if coords:
                riskiest.append({
                    "u": u,
                    "v": v,
                    "score": float(row["score"]),
                    "affected": int(row.get("pop_affected", 0)),
                    "lost": int(row.get("pop_lost", 0)),
                    "coords": coords,
                })

    return {
        "centre": {"lat": CENTRE_LAT, "lng": CENTRE_LON},
        "total_pop": int(snap["total_pop"]),
        "covered_pop": int(snap["covered_pop"]),
        "coverage_pct": float(snap["coverage_pct"]),
        "avg_access_min": float(snap["avg_access_min"]),
        "threshold": float(threshold),
        "bands": bands,
        "hospitals": hospitals_data,
        "isochrone_sample": nodes_sample,
        "riskiest_corridors": riskiest,
        "is_synthetic": POP_RASTER_PATH is None,
    }


@app.get("/api/presets")
def get_presets():
    res = {}
    for pid, pdata in DISASTER_PRESETS.items():
        edges = get_preset_edges(NET, pid)
        res[pid] = {
            "id": pid,
            "title": pdata["title"],
            "description": pdata["description"],
            "roads": pdata["roads"],
            "icon": pdata["icon"],
            "segments_count": len(edges),
        }
    return res


@app.get("/api/roads")
def get_roads():
    return named_roads(NET.graph)


@app.post("/api/simulate")
def run_simulation(req: SimulateRequest):
    baseline = coverage(NET, req.threshold)
    closed_edges: list[tuple[int, int]] = []
    scenario_title = req.road or "Custom Scenario"

    if req.preset_id and req.preset_id in DISASTER_PRESETS:
        closed_edges = get_preset_edges(NET, req.preset_id)
        scenario_title = DISASTER_PRESETS[req.preset_id]["title"]
    elif req.closed_edges:
        closed_edges = [(min(int(u), int(v)), max(int(u), int(v))) for u, v in req.closed_edges]
    elif req.road and req.scenario == "closure":
        closed_edges = road_edges(NET.graph, req.road)

    impact: Optional[Dict[str, Any]] = None
    candidates: list[dict] = []
    boost_coords: list[list[list[float]]] = []
    facility_coord: Optional[dict] = None

    if req.scenario == "facility" and req.road:
        fn = facility_node_for_road(NET, req.road)
        if fn is not None:
            impact = add_facility_to_closure(NET, fn, closed_edges, req.threshold, baseline)
            d = NET.graph.nodes[fn]
            facility_coord = {"lat": float(d["y"]), "lng": float(d["x"]), "node_id": fn}
    elif req.scenario == "corridor" and req.road:
        impact = corridor_road(NET, req.road, 0.7, req.threshold, closed_edges, baseline)
        for u, v in road_edges(NET.graph, req.road):
            c = _edge_coords(u, v)
            if c:
                boost_coords.append(c)
    else:
        if closed_edges:
            impact = closure_impact(NET, closed_edges, req.threshold, baseline)
            candidates = interventions(NET, closed_edges, req.threshold, baseline)
            for cand in candidates:
                cand_boost = []
                for item in cand.get("boost_edges", []):
                    u, v = item[0], item[1]
                    c = _edge_coords(u, v)
                    if c:
                        cand_boost.append(c)
                cand["boost_geometries"] = cand_boost

                cand_closed = []
                for u, v in cand.get("remove_edges", []):
                    c = _edge_coords(u, v)
                    if c:
                        cand_closed.append(c)
                cand["closed_geometries"] = cand_closed
        else:
            impact = None

    if impact is None:
        return {
            "status": "baseline",
            "scenario": req.scenario,
            "baseline": baseline,
        }

    # Hospital Surge Analysis
    surge = hospital_surge_analysis(NET, baseline, impact)

    # Geometry for closed edges
    closed_geoms = []
    for u, v in impact.get("closed_edges", []):
        c = _edge_coords(u, v)
        if c:
            closed_geoms.append(c)

    # Sample updated node times for live isochrone view
    sample_times = []
    nodes_list = list(NET.graph.nodes)
    step = max(1, len(nodes_list) // 1800)
    time_map = impact.get("time_to_hospital", baseline["node_time"])
    for n in nodes_list[::step]:
        t = time_map.get(n, float("inf"))
        d = NET.graph.nodes[n]
        sample_times.append({
            "id": int(n),
            "lat": float(d["y"]),
            "lng": float(d["x"]),
            "time": float(t) if t != float("inf") else 999.0,
            "pop": int(NET.population.get(n, 0)),
        })

    # AI Briefing
    briefing = summarize_closure(impact, NET, candidates)

    return {
        "status": "disrupted",
        "scenario": req.scenario,
        "scenario_title": scenario_title,
        "threshold": req.threshold,
        "pop_affected": impact.get("pop_affected", 0),
        "pop_lost_coverage": impact.get("pop_lost_coverage", 0),
        "pop_worsened": impact.get("pop_worsened", 0),
        "avg_access_before": impact.get("avg_access_before", 0.0),
        "avg_access_after": impact.get("avg_access_after", 0.0),
        "debt_pop_minutes": impact.get("debt_pop_minutes", 0.0),
        "per_capita_debt_min": impact.get("per_capita_debt_min", 0.0),
        "equity": impact.get("equity", {}),
        "surge": surge,
        "candidates": candidates,
        "briefing": briefing,
        "closed_geometries": closed_geoms,
        "boost_geometries": boost_coords,
        "facility_coord": facility_coord,
        "isochrone_sample": sample_times,
    }


@app.post("/api/copilot")
def copilot_chat(req: CopilotRequest):
    res = ask_copilot(req.query, req.chat_history, req.impact, NET, req.candidates)
    return res


@app.post("/api/iap")
def generate_iap(req: IAPRequest):
    report = generate_incident_action_plan(req.impact, NET, req.candidates)
    return {"report": report}


@app.post("/api/nl")
def parse_natural_language(req: NLRequest):
    intent = parse_scenario(req.query, NET)
    return intent


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
