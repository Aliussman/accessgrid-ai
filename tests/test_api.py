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


def test_resolve_link_endpoint():
    # Test resolve link connector via coordinates in Chandigarh metro (~1 km)
    response = client.post("/api/resolve-link", json={
        "lat1": 30.7333,
        "lng1": 76.7794,
        "lat2": 30.7400,
        "lng2": 76.7850,
        "speed_kmh": 30.0,
    })
    assert response.status_code == 200
    data = response.json()
    assert "node_a" in data
    assert "node_b" in data
    assert "distance_m" in data
    assert data["distance_m"] <= 3000.0
    assert "travel_time_min" in data
    assert data["speed_kmh"] == 30.0
    assert len(data["coordinates"]) == 2
    assert "route_comparison" in data

    # Test simulate with added link
    sim_resp = client.post("/api/simulate", json={
        "scenario": "link",
        "added_link": {
            "node_a": data["node_a"],
            "node_b": data["node_b"],
            "speed_kmh": 30.0,
        },
        "threshold": 15.0
    })
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert sim_data["status"] == "disrupted"
    assert "added_link_info" in sim_data
    assert sim_data["added_link_info"]["node_a"] == data["node_a"]
    assert "route_comparison" in sim_data["added_link_info"]
    assert "destination_impact" in sim_data["added_link_info"]
    assert "added_link_geometry" in sim_data
    assert len(sim_data["added_link_geometry"]) == 2


def test_resolve_link_validation_errors():
    # 1. Reject if points are too far apart (> 3 km)
    response = client.post("/api/resolve-link", json={
        "lat1": 30.7000,
        "lng1": 76.7000,
        "lat2": 30.8000,
        "lng2": 76.8000,
        "speed_kmh": 30.0,
    })
    assert response.status_code == 400
    assert "3 km limit" in response.json()["detail"]

    # 2. Reject if points snap to the exact same node
    response_same = client.post("/api/resolve-link", json={
        "lat1": 30.7333,
        "lng1": 76.7794,
        "lat2": 30.7333,
        "lng2": 76.7794,
    })
    assert response_same.status_code == 400
    assert "same network node" in response_same.json()["detail"]


