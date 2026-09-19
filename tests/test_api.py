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
