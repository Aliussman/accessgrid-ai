"""Tests for the closure briefing (template fallback path)."""
import math

import pytest

import src.ai as ai
from src.engine import INF

from .conftest import make_small_net


def make_impact():
    return {
        "threshold": 10.0,
        "closed_edges": [(3, 5)],
        "pop_affected": 50,
        "pop_lost_coverage": 50,
        "pop_worsened": 0,
        "baseline_covered_pop": 150,
        "coverage_pct": 60.0,
        "pop_added_minutes": {5: float("inf")},
        "lost_nodes": [5],
        "hospitals_lost": {"h1": 50},
    }


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.setattr(ai, "GEMINI_API_KEY", "")


def test_template_fallback_without_key():
    net = make_small_net()
    res = ai.summarize_closure(make_impact(), net)
    assert res["provider"] == "template"
    assert res["text"]


def test_template_contains_key_numbers():
    net = make_small_net()
    text = ai.summarize_closure(make_impact(), net)["text"]
    assert "50" in text                        # affected / lost population
    assert "Hospital One" in text              # named hospital absorbing loss
    assert "10" in text                        # threshold in minutes


def test_build_context_quotes_facts():
    net = make_small_net()
    ctx = ai._build_context(make_impact(), net)
    assert "Population affected by closure: 50" in ctx
    assert "LOST coverage" in ctx
    assert "Hospital One" in ctx


def test_template_respects_lengths():
    net = make_small_net()
    # edge (3,5) has length 2000 m -> 2.0 km in the fact sheet
    ctx = ai._build_context(make_impact(), net)
    assert "2.0 km total" in ctx


def test_gemini_error_falls_back(monkeypatch):
    monkeypatch.setattr(ai, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(ai, "_gemini_summary", lambda ctx: None)
    net = make_small_net()
    res = ai.summarize_closure(make_impact(), net)
    assert res["provider"] == "template"


# --------------------------------------------------------------------------
# interventions-aware briefings
# --------------------------------------------------------------------------
def _make_candidates():
    return [
        {"name": "Reopen all closed segments",
         "population_restored": 50, "population_recovered": 50,
         "avg_time_saved_min": 2.0, "accessibility_recovery_pct": 100.0,
         "score": 100.0},
        {"name": "Reopen segment 3-5",
         "population_restored": 50, "population_recovered": 50,
         "avg_time_saved_min": 2.0, "accessibility_recovery_pct": 100.0,
         "score": 90.0},
    ]


def test_template_summary_includes_interventions():
    net = make_small_net()
    res = ai.summarize_closure(make_impact(), net, _make_candidates())
    assert res["provider"] == "template"
    assert "Reopen all closed segments" in res["text"]


def test_ask_copilot_offline_fallback():
    net = make_small_net()
    impact = make_impact()
    candidates = _make_candidates()
    
    # Test debt query
    res = ai.ask_copilot("What is the accessibility debt?", [], impact, net, candidates)
    assert res["provider"] == "template"
    assert "accessibility debt" in res["text"].lower()

    # Test hospital query
    res_h = ai.ask_copilot("Which hospital is affected?", [], impact, net, candidates)
    assert res_h["provider"] == "template"
    assert "hospital" in res_h["text"].lower()

    # Test intervention query
    res_i = ai.ask_copilot("Which intervention helps most?", [], impact, net, candidates)
    assert res_i["provider"] == "template"
    assert "Reopen all closed segments" in res_i["text"]


def test_generate_incident_action_plan():
    net = make_small_net()
    impact = make_impact()
    candidates = _make_candidates()
    
    report = ai.generate_incident_action_plan(impact, net, candidates)
    assert "# 📋 INCIDENT ACTION PLAN (IAP)" in report
    assert "Executive Situational Overview" in report
    assert "50" in report
    assert "Reopen all closed segments" in report



def test_explain_interventions_empty():
    net = make_small_net()
    res = ai.explain_interventions(make_impact(), [], net)
    assert res["provider"] == "template"
    assert "No interventions were tested." in res["text"]