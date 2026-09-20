"""Tests for the AccessGrid pathing engine."""
import math

import pytest

from src.engine import (
    closure_impact,
    closure_impact_many,
    close_road,
    coverage,
    intervention_outcome,
    interventions,
    named_roads,
    nearest_hospitals,
    road_edges,
    route_edge_usage,
)


# --------------------------------------------------------------------------
# nearest_hospitals
# --------------------------------------------------------------------------
def test_nearest_hospitals_basic(small_net):
    time, hospital = nearest_hospitals(
        small_net.graph, [int(n) for n in small_net.hospitals["node_id"]]
    )
    assert time[0] == 0.0 and time[3] == 0.0
    assert hospital[0] == 0 and hospital[3] == 3
    # node 1: 3 min to hospital 0 vs 8 to hospital 3
    assert time[1] == 3.0 and hospital[1] == 0
    # node 2: 5 min to hospital 3 vs 7 to hospital 0
    assert time[2] == 5.0 and hospital[2] == 3
    # node 4 is disconnected
    assert time.get(4, math.inf) == math.inf and hospital.get(4) is None


def test_nearest_hospitals_prev_consistent(small_net):
    time, hospital, prev = nearest_hospitals(
        small_net.graph, [0, 3], return_prev=True
    )
    for n, h in hospital.items():
        # walk the tree to the hospital; distance must be consistent
        cur = n
        dist = 0.0
        while cur != h:
            cur = prev.get(cur)
            assert cur is not None
            dist += 1.0
        assert dist <= time[n] + 1e-9


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------
def test_coverage_counts(small_net):
    snap = coverage(small_net, threshold=10.0)
    assert snap["total_pop"] == 250
    # reachable nodes 0,1,2,3,5 (pop 150); node 4 (100) never covered
    assert snap["covered_pop"] == 150
    assert snap["coverage_pct"] == 60.0
    assert len(snap["hospitals"]) == 2


def test_coverage_threshold_bounds(small_net):
    snap = coverage(small_net, threshold=5.0)
    # node 2 at exactly 5.0 is covered; node 5 at 2.0 covered; node 1 at 3.0
    # covered; node 0,3 covered.
    assert snap["covered_pop"] == 150  # unchanged, everyone within 5 min
    snap2 = coverage(small_net, threshold=4.0)
    # node 2 (5.0) now uncovered -> its pop 30 drops out
    assert snap2["covered_pop"] == 120


# --------------------------------------------------------------------------
# closure impact
# --------------------------------------------------------------------------
def test_closure_isolates_leaf(small_net):
    imp = closure_impact(small_net, [(3, 5)], threshold=10.0)
    assert imp["lost_nodes"] == [5]
    assert imp["pop_lost_coverage"] == 50
    assert imp["pop_affected"] == 50
    assert imp["hospitals_lost"].get("h1") == 50


def test_closure_delays_but_serves(small_net):
    # closing (1,0) forces node 1 to hospital One: 1->3 = 8 min instead of 3.
    # With a 20 min threshold it is delayed but still served.
    imp = closure_impact(small_net, [(1, 0)], threshold=20.0)
    assert imp["pop_lost_coverage"] == 0
    assert imp["pop_worsened"] == 20  # node 1 only (pop 20)
    assert imp["pop_affected"] == 20
    assert imp["pop_added_minutes"][1] == pytest.approx(5.0)  # 8 - 3


def test_closure_delays_past_threshold_loses(small_net):
    # same closure but a 7 min threshold: node 1 (now 8 min) loses coverage
    imp = closure_impact(small_net, [(1, 0)], threshold=7.0)
    assert imp["pop_lost_coverage"] == 20
    assert (1 in imp["lost_nodes"]) is False  # still reachable, just late


def test_closure_unknown_edges_noop(small_net):
    imp = closure_impact(small_net, [(99, 100)], threshold=10.0)
    assert imp["pop_affected"] == 0
    assert imp["pop_lost_coverage"] == 0
    assert imp["pop_added_minutes"] == {}


def test_closure_many_matches_individual(small_net):
    single = closure_impact(small_net, [(3, 5)], threshold=10.0)
    many = closure_impact_many(small_net, [(3, 5)], threshold=10.0)
    assert len(many) == 1
    imp = many[0]
    for key in ("pop_affected", "pop_lost_coverage", "pop_worsened"):
        assert imp[key] == single[key]


# --------------------------------------------------------------------------
# route usage
# --------------------------------------------------------------------------
def test_route_edge_usage_weighting(small_net):
    usage = route_edge_usage(small_net)
    # node 2's nearest route goes 2->3 (hospital): pop 30 on edge (2,3)
    assert usage[(2, 3)] == 30
    # node 1's nearest route goes 1->0 (hospital): pop 20 on edge (0,1)
    assert usage[(0, 1)] == 20
    # node 5's nearest route goes 5->3 (hospital): pop 50 on edge (3,5)
    assert usage[(3, 5)] == 50


# --------------------------------------------------------------------------
# named roads / NL-driven closures
# --------------------------------------------------------------------------
def test_named_roads(small_net):
    roads = named_roads(small_net.graph)
    names = [r["name"] for r in roads]
    assert "Main Road" in names and "High Street" in names and "Village Road" in names
    main = next(r for r in roads if r["name"] == "Main Road")
    assert main["segments"] == 2


def test_road_edges(small_net):
    edges = road_edges(small_net.graph, "Main Road")
    assert (0, 1) in edges and (1, 2) in edges and len(edges) == 2
    assert road_edges(small_net.graph, "Village Road") == [(3, 5)]
    assert road_edges(small_net.graph, "No Such Road") == []


def test_close_road_isolates_leaf(small_net):
    imp = close_road(small_net, "Village Road", threshold=10.0)
    assert imp["road_name"] == "Village Road"
    assert imp["closed_edges"] == [(3, 5)]
    assert imp["pop_lost_coverage"] == 50


def test_zone_impact_score_normalized(small_net):
    imp = closure_impact(small_net, [(3, 5)], threshold=10.0)
    score = imp["zone_impact_score"]
    assert set(score) == {5}
    assert score[5] == pytest.approx(100.0)
    # baseline closure of two unrelated edges has an empty score map
    imp2 = intervention_outcome(small_net, [], {
        "remove_edges": [], "boost_edges": []}, threshold=10.0)
    assert imp2["zone_impact_score"] == {}


# --------------------------------------------------------------------------
# interventions
# --------------------------------------------------------------------------
def test_interventions_restore_leaf(small_net):
    imp = closure_impact(small_net, [(3, 5)], threshold=10.0)
    cands = interventions(small_net, [(3, 5)], threshold=10.0)
    assert cands, "expected tactical candidates"
    assert cands[0]["population_restored"] == 50
    assert cands[0]["accessibility_recovery_pct"] == pytest.approx(100.0)


def test_interventions_noop_when_no_impact(small_net):
    cands = interventions(small_net, [(99, 100)], threshold=10.0)
    assert cands == []


def test_intervention_outcome(small_net):
    imp = closure_impact(small_net, [(3, 5)], threshold=10.0)
    cands = interventions(small_net, [(3, 5)], threshold=10.0)
    assert len(cands) > 0
    top_cand = cands[0]
    out = intervention_outcome(small_net, [(3, 5)], top_cand, threshold=10.0)
    assert out["pop_affected"] <= imp["pop_affected"]
    assert "debt_pop_minutes" in out


def test_intervention_scenario_specific(small_net):
    # Test monsoon flood preset produces tailored flood mitigation interventions
    flood_cands = interventions(small_net, [(0, 1), (1, 2)], threshold=10.0, preset_id="monsoon_flood")
    assert len(flood_cands) <= 3
    assert any("Dewatering" in c["name"] or "Flood" in c["category"] for c in flood_cands)

    # Test VIP lockdown preset produces security-tailored interventions
    vip_cands = interventions(small_net, [(0, 1), (1, 2)], threshold=10.0, preset_id="vip_lockdown")
    assert any("Gate" in c["name"] or "Security" in c["category"] or "Transit" in c["name"] for c in vip_cands)


# --------------------------------------------------------------------------
# integration on the real cached dataset
# --------------------------------------------------------------------------
def test_real_coverage_consistency(real_net):
    snap = coverage(real_net, threshold=10.0)
    assert snap["total_pop"] > 0
    assert 0.0 < snap["coverage_pct"] <= 100.0
    assert len(snap["hospitals"]) >= 10
    assert snap["covered_pop"] <= snap["total_pop"]

    # every hospital must show up in the per-hospital table
    assert len({h["osm_id"] for h in snap["hospitals"]}) == len(real_net.hospitals)


def test_real_closure_on_bridge(real_net):
    imp = closure_impact(real_net, [], threshold=10.0)
    assert imp["pop_affected"] == 0  # closing nothing changes nothing


def test_real_zone_impact_and_interventions(real_net):
    # close the highest-usage single edge and check the pipeline end-to-end
    from src.engine import close_road, road_edges

    roads = named_roads(real_net.graph)
    assert roads, "expected at least one named road in the real dataset"
    road = next(r for r in roads if r["segments"] == max(
        r2["segments"] for r2 in roads))["name"]
    edges = road_edges(real_net.graph, road)
    imp = close_road(real_net, road, threshold=10.0)
    assert imp["closed_edges"] == edges
    assert "zone_impact_score" in imp
    cands = interventions(real_net, edges, threshold=10.0, max_segments=2, road_name=road)
    assert cands
    assert len(cands) <= 3
    assert cands[0]["name"]



# --------------------------------------------------------------------------
# Isochrones, Presets, and Hospital Surge tests
# --------------------------------------------------------------------------
def test_travel_time_bands(small_net):
    from src.engine import travel_time_bands
    # nodes 0,3 at 0 min; 5 at 2 min; 1 at 3 min; 2 at 5 min; 4 at inf
    times = {0: 0.0, 3: 0.0, 5: 2.0, 1: 3.0, 2: 5.0, 4: float("inf")}
    bands = travel_time_bands(small_net, times)
    assert "<5 min" in bands
    assert "5-10 min" in bands
    assert ">20 min / Isolated" in bands
    assert bands["<5 min"]["nodes"] == 4  # nodes 0, 3, 5, 1
    assert bands["5-10 min"]["nodes"] == 1  # node 2
    assert bands[">20 min / Isolated"]["nodes"] == 1  # node 4


def test_disaster_presets(small_net):
    from src.engine import DISASTER_PRESETS, get_preset_edges
    assert "monsoon_flood" in DISASTER_PRESETS
    edges = get_preset_edges(small_net, "monsoon_flood")
    assert isinstance(edges, list)


def test_hospital_surge_analysis(small_net):
    from src.engine import closure_impact, coverage, hospital_surge_analysis
    baseline = coverage(small_net, threshold=10.0)
    # isolate node 5 from hospital 3 (node 3)
    impact = closure_impact(small_net, [(3, 5)], threshold=10.0, baseline=baseline)
    surge = hospital_surge_analysis(small_net, baseline, impact)
    assert len(surge) == 2
    h1 = next(s for s in surge if s["name"] == "Hospital One")
    assert h1["delta_pop"] == -50


def test_load_destinations(small_net):
    from src.engine import load_destinations
    df = load_destinations()
    assert len(df) > 0
    assert "node_id" in df.columns
    assert "category" in df.columns


def test_compute_point_route(small_net):
    from src.engine import compute_point_route
    # Route from node 5 to destination hospitals (nodes 0, 3)
    res = compute_point_route(small_net, origin_node=5, dest_nodes=[0, 3])
    assert res["success"] is True
    assert res["baseline_time_min"] == 2.0
    assert res["is_diverted"] is False

    # Close edge (3, 5) -> must find alternative detour or report divergence
    res_divert = compute_point_route(small_net, origin_node=5, dest_nodes=[0, 3], closed_edges=[(3, 5)])
    assert res_divert["success"] is True
    assert res_divert["is_diverted"] is True


def test_find_edges_between_nodes(small_net):
    from src.engine import find_edges_between_nodes
    # Direct edge between 1 and 2
    edges_direct = find_edges_between_nodes(small_net, 1, 2)
    assert edges_direct == [(1, 2)]

    # Multi-hop path between 0 and 3 (0 -> 1 -> 2 -> 3)
    edges_path = find_edges_between_nodes(small_net, 0, 3)
    assert len(edges_path) >= 2
    assert (0, 1) in edges_path or (1, 2) in edges_path

    # Same node
    assert find_edges_between_nodes(small_net, 1, 1) == []

    # Disconnected node (node 4 is isolated)
    assert find_edges_between_nodes(small_net, 1, 4) == []