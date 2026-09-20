import pytest
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_overview_endpoint():
    response = client.get("/api/overview?threshold=15")
    assert response.status_code == 200
    data = response.json()
    assert "total_pop" in data
    assert "hospitals" in data
    assert len(data["hospitals"]) > 0
    assert "bands" in data

def test_presets_endpoint():
    response = client.get("/api/presets")
    assert response.status_code == 200
    data = response.json()
    assert "monsoon_flood" in data
    assert data["monsoon_flood"]["title"]

def test_simulate_preset():
    response = client.post("/api/simulate", json={"scenario": "closure", "preset_id": "monsoon_flood", "threshold": 15.0})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disrupted"
    assert "pop_affected" in data
    assert "surge" in data
    assert "candidates" in data

def test_copilot_chat():
    response = client.post("/api/copilot", json={"query": "What is the accessibility debt?", "chat_history": []})
    assert response.status_code == 200
    data = response.json()
    assert "text" in data

def test_iap_export():
    sim_res = client.post("/api/simulate", json={"scenario": "closure", "preset_id": "monsoon_flood", "threshold": 15.0}).json()
    response = client.post("/api/iap", json={"impact": sim_res, "candidates": sim_res.get("candidates", [])})
    assert response.status_code == 200
    data = response.json()
    assert "report" in data
    assert "# 📋 INCIDENT ACTION PLAN" in data["report"]


def test_destinations_endpoint():
    response = client.get("/api/destinations?category=all")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 20
    categories = {d.get("category") for d in data}
    assert "hospital" in categories

    # Test school filter
    resp_schools = client.get("/api/destinations?category=school")
    assert resp_schools.status_code == 200
    schools_data = resp_schools.json()
    assert len(schools_data) > 0
    assert all(d["category"] == "school" for d in schools_data)

    # Test market filter
    resp_markets = client.get("/api/destinations?category=market")
    assert resp_markets.status_code == 200
    markets_data = resp_markets.json()
    assert len(markets_data) > 0
    assert all(d["category"] == "market" for d in markets_data)


def test_route_endpoint():
    response = client.post("/api/route", json={
        "origin_lat": 30.720,
        "origin_lng": 76.760,
        "category": "hospital",
        "road": "Dakshin Marg"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "baseline_time_min" in data
    assert "detour_time_min" in data
    assert "baseline_route" in data
    assert "detour_route" in data
    assert "destination" in data


def test_resolve_nodes_endpoint():
    # Test resolve nodes via coordinates (e.g. coordinates in Chandigarh metro)
    response = client.post("/api/resolve-nodes", json={
        "lat1": 30.7333,
        "lng1": 76.7794,
        "lat2": 30.7400,
        "lng2": 76.7850
    })
    assert response.status_code == 200
    data = response.json()
    assert "node_a" in data
    assert "node_b" in data
    assert "closed_edges" in data
    assert len(data["closed_edges"]) > 0
    assert "coordinates" in data
    assert data["edge_count"] > 0

    # Test simulate with resolved closed_edges
    sim_resp = client.post("/api/simulate", json={
        "scenario": "closure",
        "closed_edges": data["closed_edges"],
        "threshold": 15.0
    })
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert sim_data["status"] == "disrupted"
    assert "pop_affected" in sim_data
    assert "surge" in sim_data
    assert "alternative_route" in sim_data


