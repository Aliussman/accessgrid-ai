"""AccessGrid pathing engine: hospital coverage and closure impact.

Core model:
  * Each node belongs to the nearest hospital (minimum travel time over the
    road graph). A node is *covered* when that nearest time <= threshold.
  * Closing road segment(s) re-routes traffic; we recompute nearest hospitals
    and measure the population whose access is lost or worsened.

All times use the edge attribute ``travel_time`` (minutes), set in
``graph_build``. Population comes from ``pop_by_node.csv``.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Optional

import geopandas as gpd
import networkx as nx
import pandas as pd
from .config import DATA_DIR, DEFAULT_THRESHOLD_MIN, DESTINATIONS_PATH, HOSPITALS_PATH, POP_PATH

INF = float("inf")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_graph() -> nx.MultiGraph:
    """Load the cached graph, normalising node labels to ints."""
    G = nx.read_graphml(str(DATA_DIR / "city.graphml"))
    if any(not isinstance(n, int) for n in G.nodes):
        G = nx.relabel_nodes(G, {n: int(n) for n in G.nodes})
    for u, v, data in G.edges(data=True):
        data["travel_time"] = float(data.get("travel_time", 0.0))
    return G


def load_destinations(data_dir=None, category: str = "all") -> gpd.GeoDataFrame:
    """Load points of interest (hospitals, schools, markets) with snapped graph node_ids."""
    path = DESTINATIONS_PATH if DESTINATIONS_PATH.exists() else HOSPITALS_PATH
    df = gpd.read_file(str(path))
    df["node_id"] = df["node_id"].astype(int)
    df["name"] = df["name"].astype(str)
    if "category" not in df.columns:
        df["category"] = "hospital"
    if "type" not in df.columns:
        df["type"] = "Facility"
    if "capacity" not in df.columns:
        df["capacity"] = 0
    df["capacity"] = df["capacity"].fillna(0).astype(int)
    df["type"] = df["type"].fillna("Facility").astype(str)
    df["category"] = df["category"].fillna("hospital").astype(str)

    if category != "all":
        df = df[df["category"] == category].copy()
    return df


def load_hospitals() -> gpd.GeoDataFrame:
    """Backwards-compatible loader for hospital amenities."""
    return load_destinations(category="hospital")


def load_population() -> dict[int, int]:
    df = pd.read_csv(POP_PATH)
    return dict(zip(df["node_id"].astype(int), df["population"].astype(int)))


def load_vulnerability() -> dict[int, dict[str, float]]:
    """Per-node vulnerability shares (elderly/mobility-limited/low-car
    households) read from pop_by_node.csv. Fuzzy either way is fine: the
    shares are SYNTHETIC and only used for relative equity analysis."""
    df = pd.read_csv(POP_PATH)
    vuln: dict[int, dict[str, float]] = {}
    for row in df.itertuples(index=False):
        node = int(row.node_id)
        vuln[node] = {
            group: float(getattr(row, group, 0.0) or 0.0)
            for group in ("elderly", "mobility", "lowcar")
        }
    return vuln


@dataclass
class Network:
    graph: nx.MultiGraph
    hospitals: gpd.GeoDataFrame
    destinations: gpd.GeoDataFrame = field(default_factory=gpd.GeoDataFrame)
    population: dict[int, int] = field(default_factory=dict)
    vulnerability: dict[int, dict[str, float]] = field(default_factory=dict)
    _coverage_cache: dict[float, dict] = field(default_factory=dict)
    _usage_cache: Optional[dict[tuple[int, int], int]] = None
    _osm_by_node: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir=None) -> "Network":
        all_dest = load_destinations(data_dir, category="all")
        hosp = all_dest[all_dest["category"] == "hospital"]
        if len(hosp) == 0:
            hosp = load_hospitals()
        osm_by_node = {
            int(row["node_id"]): str(row.get("osm_id", row["node_id"]))
            for _, row in all_dest.iterrows()
        }
        return cls(
            graph=load_graph(),
            hospitals=hosp,
            destinations=all_dest,
            population=load_population(),
            vulnerability=load_vulnerability(),
            _osm_by_node=osm_by_node,
        )


# --------------------------------------------------------------------------
# Nearest-hospital assignment (one multi-source Dijkstra, argmin included)
# --------------------------------------------------------------------------
def nearest_hospitals(
    G: nx.MultiGraph,
    hospital_nodes: list[int],
    weight: str = "travel_time",
    return_prev: bool = False,
    closed_edges: Optional[set[tuple[int, int]]] = None,
    boost_dict: Optional[dict[tuple[int, int], float]] = None,
) -> tuple[dict[int, float], dict[int, int]] | tuple[dict[int, float], dict[int, int], dict[int, int]]:
    """Return (time, hospital) per node: minutes to and id of the nearest
    hospital node. Unreachable nodes get time=inf, hospital=None. When
    return_prev=True, also returns prev[node] = previous node toward the
    nearest hospital (shortest-path tree predecessor).

    High-performance in-place traversal: skips closed edges and applies
    boost factors on the fly without expensive deep graph copying."""
    sources = sorted(set(hospital_nodes))
    if not sources:
        if return_prev:
            return {}, {}, {}
        return {}, {}
    time: dict[int, float] = {}
    hospital: dict[int, Optional[int]] = {}
    best_prev: dict[int, int] = {}
    heap: list[tuple[float, int, int]] = [(0.0, i, s) for i, s in enumerate(sources)]
    heapq.heapify(heap)
    adj = G._adj  # noqa: SLF001 - networkx MultiGraph adjacency
    while heap:
        d, sid, u = heapq.heappop(heap)
        if u in time:
            continue
        time[u] = d
        hospital[u] = sources[sid]
        for v, edges in adj[u].items():
            if v in time:
                continue
            pair = (u, v) if u < v else (v, u)
            if closed_edges and pair in closed_edges:
                continue
            w = min((e.get(weight, INF) for e in edges.values()), default=INF)
            if w == INF:
                continue
            if boost_dict and pair in boost_dict:
                w *= boost_dict[pair]
            new_d = d + w
            heapq.heappush(heap, (new_d, sid, v))
            if v not in time and new_d < best_prev.get(v, INF):
                best_prev[v] = u
    if return_prev:
        return time, {n: h for n, h in hospital.items() if h is not None}, best_prev
    return time, {n: h for n, h in hospital.items() if h is not None}


# --------------------------------------------------------------------------
# Baseline coverage
# --------------------------------------------------------------------------
def coverage(
    net: Network,
    threshold: float = DEFAULT_THRESHOLD_MIN,
) -> dict:
    threshold = float(threshold)
    if hasattr(net, "_coverage_cache") and threshold in net._coverage_cache:
        return net._coverage_cache[threshold]
    
    G, hospitals, population = net.graph, net.hospitals, net.population
    if getattr(net, "_baseline_nearest", None) is None:
        hospital_nodes = [int(n) for n in hospitals["node_id"]]
        net._baseline_nearest = nearest_hospitals(G, hospital_nodes)
    time, hospital = net._baseline_nearest

    total_pop = sum(
        (population.get(n, 0) for n in G.nodes), 0
    )
    covered_pop = sum(
        (population.get(n, 0) for n in G.nodes if time.get(n, INF) <= threshold), 0
    )
    # pop-weighted mean access time over nodes with a finite path to a hospital
    finite_pop = sum(
        (population.get(n, 0) for n in time if time[n] != INF), 0
    )
    avg_access = (
        sum(time[n] * population.get(n, 0) for n in time if time[n] != INF)
        / finite_pop
        if finite_pop
        else float("nan")
    )

    per_hospital = {}
    for i, h in hospitals.iterrows():
        # Nodes whose nearest hospital is this one.
        node_ids = [n for n, hn in hospital.items() if hn == h["node_id"]]
        service_pop = sum(population.get(n, 0) for n in node_ids)
        covered = sum(
            population.get(n, 0)
            for n in node_ids
            if time.get(n, INF) <= threshold
        )
        per_hospital[str(h["osm_id"])] = {
            "osm_id": str(h["osm_id"]),
            "name": h["name"],
            "node_id": int(h["node_id"]),
            "type": str(h.get("type", "Hospital")),
            "capacity": int(h.get("capacity", 0)),
            "service_pop": int(service_pop),
            "covered_pop": int(covered),
        }

    res = {
        "threshold": float(threshold),
        "total_pop": int(total_pop),
        "covered_pop": int(covered_pop),
        "coverage_pct": (covered_pop / total_pop * 100.0) if total_pop else 0.0,
        "avg_access_min": float(avg_access),
        "hospitals": list(per_hospital.values()),
        "node_time": time,
        "node_hospital": hospital,
    }
    if hasattr(net, "_coverage_cache"):
        net._coverage_cache[threshold] = res
    return res


# --------------------------------------------------------------------------
# Closure impact
# --------------------------------------------------------------------------
def closure_impact(
    net: Network,
    closed_edges: list[tuple[int, int]],
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> dict:
    """Impact of closing road segments.

    ``closed_edges`` is a list of (u, v) node pairs (both directions are
    closed: every parallel edge between the pair is removed). Returns a dict
    describing who lost access and who was delayed.
    """
    if baseline is None:
        baseline = coverage(net, threshold)
    fields = _evaluate_modification(net, baseline, threshold,
                                    list(closed_edges), [])
    return {
        "threshold": float(threshold),
        "closed_edges": [(int(u), int(v)) for u, v in closed_edges],
        "baseline_covered_pop": int(baseline["covered_pop"]),
        **fields,
    }


def _work_graph(
    net: Network,
    closed_edges: list[tuple[int, int]],
    boost_edges: list[tuple[int, int, float]],
) -> nx.MultiGraph:
    """Copy of the road graph with segments closed and optional emergency
    corridors sped up (boost < 1 shortens travel time on those edges)."""
    work = net.graph.copy()
    for u, v in closed_edges:
        if u in work and v in work:
            for k in list((work.get_edge_data(u, v) or {})):
                work.remove_edge(u, v, k)
    for u, v, factor in boost_edges:
        data = work.get_edge_data(u, v)
        if data:
            for d in data.values():
                d["travel_time"] = float(d.get("travel_time", 0.0)) * factor
    return work


def _classify(
    baseline: dict,
    new_time: dict,
    population: dict,
    threshold: float,
    osm_by_node: dict[int, str],
    vulnerability: Optional[dict[int, dict[str, float]]] = None,
) -> dict:
    """Classify every node vs the baseline and return the impact fields.

    Accessibility Debt (pop-minutes) is the population-weighted sum of
    travel-time deterioration:
        AD = sum_i P_i * (T_scenario,i - T_baseline,i)
    Nodes that lose all access (< threshold before, unreachable / above
    threshold after) are charged the synthetic value (old + threshold) so the
    debt stays finite and comparable across scenarios.
    """
    vulnerability = vulnerability or {}
    added: dict[int, float] = {}
    lost_nodes: list[int] = []
    zone_impact: dict[int, float] = {}
    lost_per_hospital: dict[str, int] = {}
    pop_affected = pop_lost_coverage = pop_worsened = 0
    old_time = baseline["node_time"]
    equity: dict[str, dict] = {}

    for n, old in old_time.items():
        if old == INF:
            continue  # never had access; closure cannot change that
        new = new_time.get(n, INF)
        pop = population.get(n, 0)
        osm_id = osm_by_node.get(baseline["node_hospital"].get(n))
        crossed = old <= threshold < new
        if new == INF:
            lost_nodes.append(n)
            added[n] = float("inf")
            zone_impact[n] = pop * (old + threshold)
            pop_affected += pop
            pop_lost_coverage += pop
            if osm_id is not None:
                lost_per_hospital[osm_id] = lost_per_hospital.get(osm_id, 0) + pop
            continue
        if new > old:
            delta = new - old
            added[n] = delta
            zone_impact[n] = pop * delta
            pop_affected += pop
            if crossed:
                pop_lost_coverage += pop
                if osm_id is not None:
                    lost_per_hospital[osm_id] = lost_per_hospital.get(osm_id, 0) + pop
            elif new <= threshold:
                pop_worsened += pop

    num = den = 0
    for n, old in old_time.items():
        if old == INF:
            continue
        v = new_time.get(n, INF)
        if v == INF:
            continue
        num += v * population.get(n, 0)
        den += population.get(n, 0)
    avg_after = num / den if den else float("nan")

    groups = {"general": None, "elderly": 0, "mobility": 0, "lowcar": 0}
    for group, idx in groups.items():
        if group == "general":
            before_sum = sum(
                old * population.get(n, 0)
                for n, old in old_time.items() if old != INF
            )
            after_sum = sum(
                new_time[n] * population.get(n, 0)
                for n, old in old_time.items()
                if old != INF and new_time.get(n, INF) != INF
            )
            group_pop = sum(
                population.get(n, 0)
                for n, old in old_time.items() if old != INF
            )
            after_pop = sum(
                population.get(n, 0)
                for n, old in old_time.items()
                if old != INF and new_time.get(n, INF) != INF
            )
            lost_pop = pop_lost_coverage
        else:
            w_sum = b_sum = a_sum = lost_pop = 0.0
            for n, shares in vulnerability.items():
                share = shares.get(group, 0.0) if shares else 0.0
                old = old_time.get(n, INF)
                if old == INF or share <= 0.0:
                    continue
                pop = population.get(n, 0) * share
                new = new_time.get(n, INF)
                w_sum += pop
                b_sum += pop * old
                if new == INF or old <= threshold < new:
                    lost_pop += pop
                elif new != INF:
                    a_sum += pop * new
            group_pop, before_sum, after_sum, after_pop = w_sum, b_sum, a_sum, (w_sum - lost_pop)
        before_avg = before_sum / group_pop if group_pop else float("nan")
        after_avg = after_sum / after_pop if after_pop else float("nan")
        delta = (after_avg - before_avg) if (after_avg == after_avg and before_avg == before_avg) else float("nan")
        equity[group] = {
            "group": group,
            "group_pop": float(group_pop),
            "pop_lost_coverage": float(lost_pop),
            "before_avg_min": float(before_avg),
            "after_avg_min": float(after_avg),
            "delta_min": float(delta),
        }

    gen_delta = equity["general"]["delta_min"]
    disproportionately = [
        g for g in ("elderly", "mobility", "lowcar")
        if equity[g]["pop_lost_coverage"] > 0
        and gen_delta == gen_delta
        and equity[g]["delta_min"] == equity[g]["delta_min"]
        and equity[g]["delta_min"] > gen_delta * 1.15
    ]
    equity["disproportionately_affected"] = disproportionately

    max_z = max(zone_impact.values()) if zone_impact else 0.0
    zone_impact_score = (
        {n: (v / max_z * 100.0) for n, v in zone_impact.items()} if max_z else {}
    )
    debt = float(sum(zone_impact.values()))

    return {
        "pop_affected": int(pop_affected),
        "pop_lost_coverage": int(pop_lost_coverage),
        "pop_worsened": int(pop_worsened),
        "avg_access_before": float(baseline["avg_access_min"]),
        "avg_access_after": float(avg_after),
        "hospitals_affected": int(len(lost_per_hospital)),
        "pop_added_minutes": added,
        "zone_impact": zone_impact,
        "zone_impact_score": zone_impact_score,
        "lost_nodes": lost_nodes,
        "hospitals_lost": lost_per_hospital,
        "debt_pop_minutes": debt,
        "per_capita_debt_min": (debt / pop_affected) if pop_affected else 0.0,
        "equity": equity,
    }


def _evaluate_modification(
    net: Network,
    baseline: dict,
    threshold: float,
    remove_edges: list[tuple[int, int]],
    boost_edges: list[tuple[int, int, float]] = (),
    extra_sources: list[int] = (),
) -> dict:
    """Impact of a graph modification (closures + corridor boosts) relative
    to the baseline. Fast in-place traversal without graph copying."""
    closed_set = set((min(u, v), max(u, v)) for u, v in remove_edges) if remove_edges else None
    boost_dict = {(min(u, v), max(u, v)): float(factor) for u, v, factor in boost_edges} if boost_edges else None
    sources = [int(n) for n in net.hospitals["node_id"]] + [int(s) for s in extra_sources]
    new_time, new_hosp = nearest_hospitals(net.graph, sources, closed_edges=closed_set, boost_dict=boost_dict)
    osm_by_node = getattr(net, "_osm_by_node", None)
    if not osm_by_node:
        osm_by_node = {
            int(row["node_id"]): str(row["osm_id"])
            for _, row in net.hospitals.iterrows()
        }
    fields = _classify(baseline, new_time, net.population, threshold, osm_by_node,
                       net.vulnerability)
    base_time = baseline["node_time"]
    fields["new_covered_pop"] = sum(
        net.population.get(n, 0)
        for n in net.graph.nodes
        if base_time.get(n, INF) > threshold and new_time.get(n, INF) <= threshold
    )
    fields["time_to_hospital"] = new_time
    fields["node_hospital"] = new_hosp
    return fields


def _edge_name(net: Network, u: int, v: int) -> Optional[str]:
    """Return OSM road name or route ref for an edge, if known."""
    data = net.graph.get_edge_data(u, v) or {}
    for d in data.values():
        if d.get("name"):
            return str(d["name"])
        if d.get("ref"):
            return str(d["ref"])
    return None


def _path_corridor_name(net: Network, edges: list[tuple[int, int]]) -> str:
    """Return a clean composite street name for a list of edges."""
    names = []
    for u, v in edges:
        n = _edge_name(net, u, v)
        if n and n not in names:
            names.append(n)
    if names:
        return " / ".join(names[:2])
    return "Parallel Arterial Route"


def _find_bypass_corridor(
    net: Network, closed_edges: list[tuple[int, int]], worst_edge: tuple[int, int]
) -> tuple[list[tuple[int, int]], str]:
    """Find the shortest detour around all closed edges from the worst edge endpoints."""
    work = net.graph.copy()
    for u, v in closed_edges:
        if u in work and v in work:
            for k in list((work.get_edge_data(u, v) or {})):
                work.remove_edge(u, v, k)
    u, v = worst_edge
    try:
        path = nx.shortest_path(work, u, v, weight="travel_time")
        pairs = [(min(path[i], path[i + 1]), max(path[i], path[i + 1])) for i in range(len(path) - 1)]
        name = _path_corridor_name(net, pairs)
        return pairs, name
    except Exception:
        return [], "Parallel Arterial Route"


def interventions(
    net: Network,
    closed_edges: list[tuple[int, int]],
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
    max_segments: int = 8,
) -> list[dict]:
    """Rank candidate tactical interventions for a road-closure scenario.

    Candidates generated:
      * Targeted Bottleneck Clearance (reopen single highest-yield chokepoint)
      * Dedicated EMS Green-Wave Corridor (speed up detour around disruption)
      * Tactical Mobile Triage Unit (deploy field clinic at highest-debt cluster)
      * Phased Corridor Recovery (reopen individual major arterials in multi-road closures)
      * Contraflow EMS Transit Lane (two-way emergency transit on parallel route)
      * Comprehensive Network Clearance (full recovery benchmark)
    """
    if baseline is None:
        baseline = coverage(net, threshold)
    threshold = float(threshold)
    closed = sorted(set((min(u, v), max(u, v)) for u, v in closed_edges))
    if not closed:
        return []

    disrupted = _evaluate_modification(net, baseline, threshold, closed, [])
    if disrupted["pop_affected"] == 0:
        return []
    disrupted_debt = disrupted["debt_pop_minutes"]
    lost_set_ref = disrupted["pop_lost_coverage"]
    affected_ref = disrupted["pop_affected"]

    usage = route_edge_usage(net)

    def _usage(e):
        return usage.get(e, usage.get((e[1], e[0]), 0))

    keyed = sorted(closed, key=_usage, reverse=True)
    worst = keyed[0]
    worst_name = _edge_name(net, worst[0], worst[1]) or "Critical Arterial Section"
    top = keyed[:min(max_segments, 2)]
    rest = keyed[min(max_segments, 2):] if len(closed) > 2 else []

    candidates: list[dict] = []

    # 1. Comprehensive Reopening (Instant Benchmark - Zero Dijkstra overhead)
    candidates.append({
        "kind": "reopen_all",
        "category": "Full Network Recovery",
        "name": "Comprehensive Network Clearance (All Corridors Cleared)",
        "tactic": "Mobilize full-scale municipal operations across all affected sectors to restore all closed corridors simultaneously.",
        "effort": "🔴 High (Full City Mobilization)",
        "remove_edges": [],
        "boost_edges": [],
        "extra_sources": [],
        "_fast_eval": {
            "population_restored": int(disrupted["pop_lost_coverage"]),
            "population_recovered": int(disrupted["pop_affected"]),
            "avg_time_saved_min": float(disrupted["debt_pop_minutes"] / disrupted["pop_affected"]) if disrupted["pop_affected"] else 0.0,
            "accessibility_recovery_pct": 100.0,
            "debt_after_pop_min": 0.0,
            "debt_reduction_pct": 100.0,
        },
    })

    # 2. Targeted Bottleneck Clearance (Top critical segment)
    worst_candidates = top[:1] if len(closed) > 5 else top
    for e in worst_candidates:
        e_name = _edge_name(net, e[0], e[1]) or f"Segment {e[0]}-{e[1]}"
        others = [o for o in closed if o != e]
        is_worst = (e == worst)
        candidates.append({
            "kind": "reopen_one",
            "category": "Chokepoint Clearance" if is_worst else "Segment Clearance",
            "name": f"Targeted Bottleneck Clearance: {e_name}" if is_worst else f"Reopen Arterial Segment: {e_name}",
            "tactic": (
                f"Deploy rapid mobile de-watering pumps and towing to clear the critical chokepoint on {e_name}."
                if is_worst else
                f"Clear localized obstruction on {e_name} to restore secondary bypass connectivity."
            ),
            "effort": "⚡ Low (1 Rapid Crew)",
            "remove_edges": others,
            "boost_edges": [],
            "extra_sources": [],
        })

    # 3. Dedicated EMS Green-Wave Transit Corridor
    bypass_edges, bypass_name = _find_bypass_corridor(net, closed, worst)
    if not bypass_edges:
        alt_legacy = _alternate_path(net, worst)
        if alt_legacy:
            bypass_edges = alt_legacy
            bypass_name = _path_corridor_name(net, alt_legacy)

    if bypass_edges:
        candidates.append({
            "kind": "corridor",
            "category": "Green-Wave EMS Corridor",
            "name": f"Dedicated EMS Green-Wave Corridor: {bypass_name}",
            "tactic": f"Activate dynamic traffic signal preemption (TSP) and dedicated police-escorted ambulance lanes along {bypass_name} (+40% transit speed).",
            "effort": "🟢 Low (Signal Phasing)",
            "remove_edges": closed,
            "boost_edges": [(u, v, 0.6) for u, v in bypass_edges],
            "extra_sources": [],
        })

    # 4. Phased Corridor Reopenings (Top 1-2 major corridors if multi-road closure)
    road_groups: dict[str, list[tuple[int, int]]] = {}
    for u, v in closed:
        rname = _edge_name(net, u, v)
        if rname:
            road_groups.setdefault(rname, []).append((u, v))

    if len(road_groups) > 1:
        top_corridors = sorted(road_groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:2]
        for rname, redges in top_corridors:
            candidates.append({
                "kind": "phased_corridor",
                "category": "Phased Corridor Recovery",
                "name": f"Priority Corridor Clearance: Reopen {rname}",
                "tactic": f"Concentrate municipal heavy machinery and civil defense crews exclusively on {rname} first to re-establish primary arterial throughput before secondary links.",
                "effort": "🟠 Moderate (Dedicated Fleet)",
                "remove_edges": [e for e in closed if e not in set(redges)],
                "boost_edges": [],
                "extra_sources": [],
            })

    # 5. Deploy Tactical Mobile Triage Unit (Field Stabilization Pod)
    if disrupted.get("zone_impact") and len(closed) > 2:
        hotspot_node = max(disrupted["zone_impact"].items(), key=lambda kv: kv[1])[0]
        hotspot_d = net.graph.nodes[hotspot_node]
        if "x" in hotspot_d and "y" in hotspot_d:
            neighbors = list(net.graph.neighbors(hotspot_node))
            hotspot_street = _edge_name(net, hotspot_node, neighbors[0]) if neighbors else "Hazard Sector"
            hotspot_label = hotspot_street or f"Sector Node {hotspot_node}"
            candidates.append({
                "kind": "mobile_facility",
                "category": "Mobile Triage Unit",
                "name": f"Deploy Mobile Triage Pod: Near {hotspot_label}",
                "tactic": f"Position an Advanced Life Support (ALS) mobile field triage unit at {hotspot_label}, instantly restoring emergency stabilization within the 8-minute golden window.",
                "effort": "🟡 Medium (1 Mobile Unit)",
                "remove_edges": closed,
                "boost_edges": [],
                "extra_sources": [hotspot_node],
                "facility_node": hotspot_node,
                "facility_coord": {
                    "lat": float(hotspot_d.get("y", 0.0)),
                    "lng": float(hotspot_d.get("x", 0.0)),
                    "node_id": hotspot_node,
                },
            })

    # Limit to top 3 distinct strategic candidates for optimal sub-second response time
    candidates = candidates[:3]

    results = []
    for cand in candidates:
        if "_fast_eval" in cand:
            fe = cand["_fast_eval"]
            res_item = {
                "kind": cand["kind"],
                "category": cand.get("category", "Intervention"),
                "name": cand["name"],
                "tactic": cand.get("tactic", ""),
                "effort": cand.get("effort", "Medium"),
                "remove_edges": [(int(a), int(b)) for a, b in cand["remove_edges"]],
                "boost_edges": [(int(a), int(b), float(x)) for a, b, x in cand.get("boost_edges", [])],
                "population_restored": fe["population_restored"],
                "population_recovered": fe["population_recovered"],
                "avg_time_saved_min": fe["avg_time_saved_min"],
                "accessibility_recovery_pct": fe["accessibility_recovery_pct"],
                "debt_after_pop_min": fe["debt_after_pop_min"],
                "debt_reduction_pct": fe["debt_reduction_pct"],
            }
            results.append(res_item)
            continue
        f = _evaluate_modification(
            net,
            baseline,
            threshold,
            cand["remove_edges"],
            cand.get("boost_edges", []),
            cand.get("extra_sources", []),
        )
        lost_nodes_int = set(f["lost_nodes"])
        restored = sum(
            net.population.get(n, 0)
            for n in disrupted["lost_nodes"] if n not in lost_nodes_int
        )
        time_saved = benefited = 0.0
        for n, add in disrupted["pop_added_minutes"].items():
            if add == INF:
                continue
            f_add = f["pop_added_minutes"].get(n, 0.0)
            if f_add >= add:
                continue
            saved = add - f_add
            time_saved += saved * net.population.get(n, 0)
            benefited += net.population.get(n, 0)
        recovered_affected = max(disrupted["pop_affected"] - f["pop_affected"], 0)
        avg_saved = time_saved / benefited if benefited else 0.0
        if lost_set_ref:
            recovery = restored / lost_set_ref * 100.0
        else:
            recovery = recovered_affected / affected_ref * 100.0 if affected_ref else 0.0
        debt_after = float(f["debt_pop_minutes"])
        
        res_item = {
            "kind": cand["kind"],
            "category": cand.get("category", "Intervention"),
            "name": cand["name"],
            "tactic": cand.get("tactic", ""),
            "effort": cand.get("effort", "Medium"),
            "remove_edges": [(int(a), int(b)) for a, b in cand["remove_edges"]],
            "boost_edges": [(int(a), int(b), float(x)) for a, b, x in cand.get("boost_edges", [])],
            "population_restored": int(restored),
            "population_recovered": int(recovered_affected),
            "avg_time_saved_min": float(avg_saved),
            "accessibility_recovery_pct": float(recovery),
            "debt_after_pop_min": debt_after,
            "debt_reduction_pct": (disrupted_debt - debt_after) / disrupted_debt * 100.0
            if disrupted_debt else 0.0,
        }
        if "facility_node" in cand:
            res_item["facility_node"] = cand["facility_node"]
            res_item["facility_coord"] = cand["facility_coord"]
        results.append(res_item)

    # Filter zero-yield duplicate candidates while preserving reopen_all / primary options
    filtered_results = []
    seen_names = set()
    for r in results:
        if r["name"] in seen_names:
            continue
        if r["kind"] == "reopen_all" or r["debt_reduction_pct"] > 0.05 or r["population_restored"] > 0 or r["avg_time_saved_min"] > 0.05:
            seen_names.add(r["name"])
            filtered_results.append(r)
        elif len(results) <= 3:
            seen_names.add(r["name"])
            filtered_results.append(r)

    if not filtered_results:
        filtered_results = results

    _score_interventions(filtered_results)
    filtered_results.sort(key=lambda r: r["score"], reverse=True)
    return filtered_results[:8]


def _score_interventions(results: list[dict]) -> None:
    n = len(results)
    if n == 0:
        return
    for key, weight in (("population_restored", 0.5),
                        ("population_recovered", 0.3),
                        ("avg_time_saved_min", 0.2)):
        vals = [r[key] for r in results]
        rmax = max(vals)
        if rmax <= 0:
            continue
        for r, v in zip(results, vals):
            r[f"_r_{key}"] = v / rmax
    for r in results:
        score = 0.0
        for key, weight in (("population_restored", 0.5),
                            ("population_recovered", 0.3),
                            ("avg_time_saved_min", 0.2)):
            score += weight * r.get(f"_r_{key}", 0.0)
        r["score"] = round(score * 100.0, 1)
        for key in ("_r_population_restored", "_r_population_recovered",
                    "_r_avg_time_saved_min"):
            r.pop(key, None)


def _alternate_path(net: Network, edge: tuple[int, int]) -> list[tuple[int, int]]:
    """Shortest alternate route between an edge's endpoints that does not use
    that edge (used to build an emergency corridor)."""
    u, v = edge
    if u not in net.graph or v not in net.graph:
        return []
    work = net.graph.copy()
    for k in list((work.get_edge_data(u, v) or {})):
        work.remove_edge(u, v, k)
    try:
        path = nx.shortest_path(work, u, v, weight="travel_time")
    except nx.NetworkXNoPath:
        return []
    pairs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    return [(min(a, b), max(a, b)) for a, b in pairs]


def closure_impact_many(
    net: Network,
    edge_list: list[tuple[int, int]],
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> list[dict]:
    """Single-edge closure impacts for many edges, reusing one baseline
    coverage (fast path used by the criticality precompute)."""
    if baseline is None:
        baseline = coverage(net, threshold)
    return [closure_impact(net, [e], threshold, baseline) for e in edge_list]


def route_edge_usage(
    net: Network,
    time: Optional[dict] = None,
    hospital: Optional[dict] = None,
    prev: Optional[dict] = None,
) -> dict[tuple[int, int], int]:
    """Pop-weighted count of how many residents' nearest-hospital route uses
    each undirected edge. Cached on net._usage_cache for fast repeated lookups."""
    if time is None and hospital is None and prev is None:
        if getattr(net, "_usage_cache", None) is not None:
            return net._usage_cache
        time, hospital, prev = nearest_hospitals(
            net.graph, [int(n) for n in net.hospitals["node_id"]], return_prev=True
        )
    elif time is None or hospital is None or prev is None:
        time, hospital, prev = nearest_hospitals(
            net.graph, [int(n) for n in net.hospitals["node_id"]], return_prev=True
        )
    usage: dict[tuple[int, int], int] = {}
    population = net.population
    for n in net.graph.nodes:
        h = hospital.get(n)
        pop = population.get(n, 0)
        if h is None or pop == 0:
            continue
        cur = n
        seen = set()
        while cur != h and cur not in seen:
            seen.add(cur)
            p = prev.get(cur)
            if p is None or p == cur:
                break
            key = (min(cur, p), max(cur, p))
            usage[key] = usage.get(key, 0) + pop
            cur = p
    if time is None and getattr(net, "_usage_cache", None) is None:
        net._usage_cache = usage
    return usage


# --------------------------------------------------------------------------
# Named-road helpers (used by the scenario builder + natural-language input)
# --------------------------------------------------------------------------
def named_roads(graph: nx.MultiGraph) -> list[dict]:
    """Street names present on the graph with their segment counts.

    Returns a list of ``{"name": ..., "segments": ...}`` sorted by most
    segments first (the 'Main Road A' style selector). Parsed from the
    ``name`` edge attribute; unnamed segments are ignored."""
    counts: dict[str, int] = {}
    for _u, _v, data in graph.edges(data=True):
        name = str(data.get("name", "")).strip()
        if name and name.lower() not in ("junction", "edge", "jnct", "nan"):
            counts[name] = counts.get(name, 0) + 1
    return [
        {"name": name, "segments": count}
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def road_edges(graph: nx.MultiGraph, road_name: str) -> list[tuple[int, int]]:
    """All undirected (u, v) segments belonging to a given street name."""
    target = road_name.strip().lower()
    out: set[tuple[int, int]] = set()
    for u, v, data in graph.edges(data=True):
        name = str(data.get("name", "")).strip().lower()
        if name and name == target:
            out.add((min(int(u), int(v)), max(int(u), int(v))))
    return sorted(out)


def close_road(
    net: Network,
    road_name: str,
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> dict:
    """Impact of closing every segment of a named road."""
    returned = closure_impact(net, road_edges(net.graph, road_name),
                              threshold, baseline)
    returned["road_name"] = road_name
    return returned


def intervention_outcome(
    net: Network,
    closed_edges: list[tuple[int, int]],
    intervention: dict,
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> dict:
    """Post-intervention snapshot: the closure scenario after one candidate
    intervention is applied. Returns the same shape as ``closure_impact`` so
    the map/metrics can render the *result* of e.g. 'Reopen road', or a
    'Diversion/emergency corridor'."""
    if baseline is None:
        baseline = coverage(net, threshold)
    fields = _evaluate_modification(
        net, baseline, float(threshold),
        [(int(a), int(b)) for a, b in intervention["remove_edges"]],
        [(int(a), int(b), float(x)) for a, b, x in intervention["boost_edges"]],
    )
    return {
        "threshold": float(threshold),
        "closed_edges": [(int(u), int(v)) for u, v in intervention["remove_edges"]],
        "baseline_covered_pop": int(baseline["covered_pop"]),
        **fields,
    }


# --------------------------------------------------------------------------
# What-if helpers (beyond road closures)
# --------------------------------------------------------------------------
def coverage_with_facility(
    net: Network,
    facility_node: int,
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> dict:
    """Baseline coverage if an emergency facility is added at ``facility_node``.

    Returns the same shape as ``coverage()`` (with hospitals replaced by all
    sources) plus ``new_covered_pop``: residents newly within the threshold
    who were not covered by the existing hospital network."""
    if baseline is None:
        baseline = coverage(net, threshold)
    facility_node = int(facility_node)
    sources = [int(n) for n in net.hospitals["node_id"]] + [facility_node]
    time, hospital = nearest_hospitals(net.graph, sources)

    total_pop = sum((net.population.get(n, 0) for n in net.graph.nodes), 0)
    covered_pop = sum(
        (net.population.get(n, 0) for n in net.graph.nodes
         if time.get(n, INF) <= threshold), 0
    )
    base_time = baseline["node_time"]
    new_covered_pop = sum(
        (net.population.get(n, 0) for n in net.graph.nodes
         if base_time.get(n, INF) > threshold and time.get(n, INF) <= threshold), 0
    )
    finite_pop = sum((net.population.get(n, 0) for n in time if time[n] != INF), 0)
    avg_access = (
        sum(time[n] * net.population.get(n, 0) for n in time if time[n] != INF)
        / finite_pop if finite_pop else float("nan")
    )
    facility_covered = sum(
        (net.population.get(n, 0) for n, hn in hospital.items()
         if hn == facility_node and time.get(n, INF) <= threshold), 0
    )
    x, y = net.graph.nodes[facility_node]["x"], net.graph.nodes[facility_node]["y"]
    return {
        "threshold": float(threshold),
        "total_pop": int(total_pop),
        "covered_pop": int(covered_pop),
        "new_covered_pop": int(new_covered_pop),
        "covered_pop_after": int(covered_pop),
        "facility_node": facility_node,
        "facility_lon": float(x),
        "facility_lat": float(y),
        "facility_covered_pop": int(facility_covered),
        "coverage_pct": (covered_pop / total_pop * 100.0) if total_pop else 0.0,
        "avg_access_min": float(avg_access),
        "hospitals": list(baseline["hospitals"]),
        "node_time": time,
        "node_hospital": hospital,
    }


def add_facility_to_closure(
    net: Network,
    facility_node: int,
    closed_edges: list[tuple[int, int]],
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
) -> dict:
    """Impact of a road closure *plus* an emergency facility at a location.

    Same output shape as ``closure_impact``: measures the accessibility debt
    that remains even after the new facility is open, and how much debt the
    facility prevents.""" 
    if baseline is None:
        baseline = coverage(net, threshold)
    closed = sorted(set((min(u, v), max(u, v)) for u, v in closed_edges))
    disrupted = _evaluate_modification(net, baseline, threshold, closed, [])
    fields = _evaluate_modification(net, baseline, threshold, closed, [],
                                    extra_sources=[int(facility_node)])
    facility_node = int(facility_node)
    x, y = net.graph.nodes[facility_node]["x"], net.graph.nodes[facility_node]["y"]
    debt_prevented = displaced = disrupted["debt_pop_minutes"]
    return {
        "threshold": float(threshold),
        "closed_edges": [(int(u), int(v)) for u, v in closed],
        "baseline_covered_pop": int(baseline["covered_pop"]),
        "facility_node": facility_node,
        "facility_lon": float(x),
        "facility_lat": float(y),
        "debt_without_facility_pop_min": disrupted["debt_pop_minutes"],
        "debt_prevented_pop_min": max(debt_prevented - fields["debt_pop_minutes"], 0.0),
        "debt_prevented_pct": (debt_prevented - fields["debt_pop_minutes"]) / displaced * 100.0
        if displaced else 0.0,
        **fields,
    }


def corridor_road(
    net: Network,
    road_name: str,
    factor: float = 0.7,
    threshold: float = DEFAULT_THRESHOLD_MIN,
    closed_edges: list[tuple[int, int]] = (),
    baseline: Optional[dict] = None,
) -> dict:
    """What-if: priority travel (emergency corridor) along a named road.

    Speeds up every segment of ``road_name`` by ``factor`` (boost<1 shortens
    travel time), optionally while ``closed_edges`` stay closed. Returns a
    ``closure_impact``-shaped dict so the map/metrics render the result."""
    if baseline is None:
        baseline = coverage(net, threshold)
    closed = sorted(set((min(u, v), max(u, v)) for u, v in closed_edges))
    segs = road_edges(net.graph, road_name)
    fields = _evaluate_modification(net, baseline, threshold, closed,
                                    [(u, v, float(factor)) for u, v in segs])
    return {
        "threshold": float(threshold),
        "closed_edges": [(int(u), int(v)) for u, v in closed],
        "baseline_covered_pop": int(baseline["covered_pop"]),
        "road_name": road_name,
        "corridor_factor": float(factor),
        **fields,
    }


# --------------------------------------------------------------------------
# Multi-Hazard Disaster Presets & Isochrone / Surge Extensions
# --------------------------------------------------------------------------
DISASTER_PRESETS = {
    "monsoon_flood": {
        "title": "Monsoon Flash Flood (Underpass Inundation)",
        "description": "Heavy monsoon waterlogging submerging low-lying underpasses along Madhya Marg and Dakshin Marg.",
        "roads": ["Madhya Marg", "Dakshin Marg"],
        "icon": "🌊",
    },
    "vip_lockdown": {
        "title": "VIP Security Arterial Lockdown",
        "description": "Coordinated security lockdown sealing primary civic corridors across Jan Marg and Himalaya Marg.",
        "roads": ["Jan Marg", "Himalaya Marg"],
        "icon": "🚨",
    },
    "industrial_hazard": {
        "title": "Industrial Corridor Hazmat Spill",
        "description": "Hazardous materials disruption closing key freight arterials on Vikas Marg and Udyog Path.",
        "roads": ["Vikas Marg", "Udyog Path"],
        "icon": "⚠️",
    },
}


def get_preset_edges(net: Network, preset_id: str) -> list[tuple[int, int]]:
    """Return all graph edges for a given multi-hazard preset."""
    preset = DISASTER_PRESETS.get(preset_id)
    if not preset:
        return []
    edges = set()
    for road in preset["roads"]:
        # Find matching edges (supports exact or partial road name matching)
        for u, v in road_edges(net.graph, road):
            edges.add((min(u, v), max(u, v)))
    # If no named edges found directly, match fuzzy road names from graph
    if not edges:
        all_named = named_roads(net.graph)
        for target in preset["roads"]:
            for r in all_named:
                if target.lower() in r["name"].lower():
                    for u, v in road_edges(net.graph, r["name"]):
                        edges.add((min(u, v), max(u, v)))
    return sorted(edges)


def travel_time_bands(net: Network, time_dict: dict[int, float]) -> dict[str, dict]:
    """Bucket network nodes and population into travel-time accessibility bands.

    Bands:
      * '<5 min'    : rapid response
      * '5-10 min'  : optimal emergency access
      * '10-15 min' : threshold limit
      * '15-20 min' : delayed response
      * '>20 min'   : critical delay / unreachable
    """
    bands = {
        "<5 min": {"pop": 0, "nodes": 0, "color": "#2ecc71"},
        "5-10 min": {"pop": 0, "nodes": 0, "color": "#3498db"},
        "10-15 min": {"pop": 0, "nodes": 0, "color": "#f39c12"},
        "15-20 min": {"pop": 0, "nodes": 0, "color": "#e67e22"},
        ">20 min / Isolated": {"pop": 0, "nodes": 0, "color": "#e74c3c"},
    }

    total_pop = sum(net.population.values()) or 1
    total_nodes = len(net.graph.nodes) or 1

    for node in net.graph.nodes:
        t = time_dict.get(node, INF)
        pop = net.population.get(node, 0)

        if t < 5.0:
            key = "<5 min"
        elif t < 10.0:
            key = "5-10 min"
        elif t < 15.0:
            key = "10-15 min"
        elif t < 20.0:
            key = "15-20 min"
        else:
            key = ">20 min / Isolated"

        bands[key]["pop"] += pop
        bands[key]["nodes"] += 1

    for k, v in bands.items():
        v["pop_pct"] = (v["pop"] / total_pop) * 100.0
        v["nodes_pct"] = (v["nodes"] / total_nodes) * 100.0

    return bands


def hospital_surge_analysis(
    net: Network,
    baseline: dict,
    impact: dict | None,
) -> list[dict]:
    """Calculate hospital patient load shift and capacity strain under disruption."""
    hospitals_df = net.hospitals
    if hospitals_df.empty:
        return []

    # Map hospital node_id to metadata
    hosp_map = {}
    for h in hospitals_df.to_dict("records"):
        node_id = int(h["node_id"])
        hosp_map[node_id] = {
            "name": h.get("name", f"Hospital @ node {node_id}"),
            "osm_id": str(h.get("osm_id", node_id)),
            "capacity": int(h.get("capacity", 100) or 100),
            "type": str(h.get("type", "Hospital")),
            "baseline_pop": 0,
            "current_pop": 0,
        }

    # Baseline assignment
    base_hosp = baseline.get("node_hospital", {})
    base_time = baseline.get("node_time", {})
    thresh = float(baseline.get("threshold", 15.0))
    for node, pop in net.population.items():
        h_node = base_hosp.get(node)
        if h_node in hosp_map:
            t = base_time.get(node, INF)
            if t <= thresh:
                hosp_map[h_node]["baseline_pop"] += pop

    # Current scenario assignment
    if impact is not None:
        if "node_hospital" in impact and "time_to_hospital" in impact:
            curr_time = impact["time_to_hospital"]
            curr_hosp = impact["node_hospital"]
        else:
            closed = impact.get("closed_edges", [])
            closed_set = set((min(u, v), max(u, v)) for u, v in closed) if closed else None
            sources = [int(n) for n in net.hospitals["node_id"]]
            curr_time, curr_hosp = nearest_hospitals(net.graph, sources, closed_edges=closed_set)
        curr_thresh = float(impact.get("threshold", thresh))
        for node, pop in net.population.items():
            h_node = curr_hosp.get(node)
            if h_node in hosp_map:
                t = curr_time.get(node, INF)
                if t <= curr_thresh:
                    hosp_map[h_node]["current_pop"] += pop
    else:
        for h_node in hosp_map:
            hosp_map[h_node]["current_pop"] = hosp_map[h_node]["baseline_pop"]

    surge_list = []
    for h_node, d in hosp_map.items():
        base_p = d["baseline_pop"]
        curr_p = d["current_pop"]
        diff = curr_p - base_p
        diff_pct = (diff / base_p * 100.0) if base_p > 0 else 0.0

        if diff > 1000 or diff_pct > 25.0:
            status = "CRITICAL SURGE"
            badge = "🚨 Critical Surge"
        elif diff > 200 or diff_pct > 10.0:
            status = "STRAINED"
            badge = "⚠️ Strained"
        elif diff < -500 or (base_p > 0 and curr_p < base_p * 0.75):
            status = "CUT OFF"
            badge = "⛔ Access Severed"
        else:
            status = "STABLE"
            badge = "✅ Stable"

        surge_list.append({
            "node_id": h_node,
            "name": d["name"],
            "osm_id": d["osm_id"],
            "capacity_beds": d["capacity"],
            "baseline_pop": base_p,
            "current_pop": curr_p,
            "delta_pop": diff,
            "delta_pct": diff_pct,
            "status": status,
            "badge": badge,
        })

    return sorted(surge_list, key=lambda x: -x["delta_pop"])


def facility_node_for_road(net: Network, road_name: str) -> int | None:
    """Where to place an emergency facility for a given road: the segment
    endpoint closest to the road's midpoint (its most central junction)."""
    segs = road_edges(net.graph, road_name)
    if not segs:
        return None
    xs, ys = [], []
    for u, v in segs:
        try:
            xu, yu = float(net.graph.nodes[u]["x"]), float(net.graph.nodes[u]["y"])
            xv, yv = float(net.graph.nodes[v]["x"]), float(net.graph.nodes[v]["y"])
        except (KeyError, TypeError):
            continue
        xs += [xu, xv]
        ys += [yu, yv]
    if not xs:
        return None
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    best, best_d = None, INF
    for n in {p for s in segs for p in s}:
        if n in net.graph.nodes:
            x, y = float(net.graph.nodes[n]["x"]), float(net.graph.nodes[n]["y"])
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < best_d:
                best, best_d = n, d
    return best


def nearest_node_to_coord(net: Network, lat: float, lng: float) -> Optional[int]:
    """Find the closest graph node to a lat/lng coordinate."""
    best_n = None
    best_d = INF
    for n, d in net.graph.nodes(data=True):
        if "y" in d and "x" in d:
            ny, nx_ = float(d["y"]), float(d["x"])
            dist = (ny - lat) ** 2 + (nx_ - lng) ** 2
            if dist < best_d:
                best_d = dist
                best_n = int(n)
    return best_n


def _find_dijkstra_path(
    G: nx.MultiGraph,
    origin: int,
    dest_targets: set[int],
    closed_set: Optional[set[tuple[int, int]]] = None,
) -> tuple[Optional[int], list[int], float]:
    """Find shortest path from origin node to any target in dest_targets."""
    if origin in dest_targets:
        return origin, [origin], 0.0

    pq = [(0.0, origin, [origin])]
    visited: dict[int, float] = {}

    while pq:
        t, u, path = heapq.heappop(pq)
        if u in visited and visited[u] <= t:
            continue
        visited[u] = t

        if u in dest_targets:
            return u, path, t

        for v, edge_dict in G[u].items():
            if closed_set:
                edge_pair = (min(u, v), max(u, v))
                if edge_pair in closed_set:
                    continue
            min_cost = min(float(d.get("travel_time", 1.0)) for d in edge_dict.values())
            if v not in visited or t + min_cost < visited[v]:
                heapq.heappush(pq, (t + min_cost, v, path + [v]))

    return None, [], INF


def _path_to_coords(net: Network, path: list[int]) -> list[list[float]]:
    coords = []
    for n in path:
        d = net.graph.nodes[n]
        if "y" in d and "x" in d:
            coords.append([float(d["y"]), float(d["x"])])
    return coords


def compute_point_route(
    net: Network,
    origin_node: int,
    dest_nodes: Optional[list[int]] = None,
    closed_edges: list[tuple[int, int]] = (),
    category: str = "hospital",
) -> dict:
    """Compute original and alternative detour routes from an origin to destination."""
    if not dest_nodes:
        if hasattr(net, "destinations") and len(net.destinations) > 0:
            if category == "all":
                df = net.destinations
            else:
                df = net.destinations[net.destinations["category"] == category]
            if len(df) == 0:
                df = net.hospitals
            dest_nodes = [int(n) for n in df["node_id"]]
        else:
            dest_nodes = [int(n) for n in net.hospitals["node_id"]]

    dest_set = set(dest_nodes)
    closed_set = set((min(u, v), max(u, v)) for u, v in closed_edges) if closed_edges else None

    # 1. Baseline Route (Normal network)
    orig_target, orig_path, orig_time = _find_dijkstra_path(net.graph, origin_node, dest_set, closed_set=None)

    # 2. Detour / Alternative Route (Disrupted network)
    detour_target, detour_path, detour_time = _find_dijkstra_path(net.graph, origin_node, dest_set, closed_set=closed_set)

    # Find destination metadata
    dest_meta = {}
    chosen_dest = detour_target if detour_target is not None else orig_target
    if chosen_dest is not None and hasattr(net, "destinations") and len(net.destinations) > 0:
        match = net.destinations[net.destinations["node_id"] == chosen_dest]
        if len(match) > 0:
            row = match.iloc[0]
            dest_meta = {
                "name": str(row["name"]),
                "category": str(row.get("category", "facility")),
                "type": str(row.get("type", "Facility")),
                "capacity": int(row.get("capacity", 0)),
                "node_id": int(chosen_dest),
            }

    orig_edges = set((min(orig_path[i], orig_path[i+1]), max(orig_path[i], orig_path[i+1])) for i in range(len(orig_path)-1)) if len(orig_path) > 1 else set()
    hit_closed = bool(closed_set and (orig_edges & closed_set)) if closed_set else False

    delay = (detour_time - orig_time) if (detour_time != INF and orig_time != INF) else 0.0

    return {
        "success": (orig_target is not None or detour_target is not None),
        "origin_node": int(origin_node),
        "destination": dest_meta,
        "is_diverted": hit_closed or (detour_path != orig_path and bool(closed_edges)),
        "baseline_time_min": float(orig_time) if orig_time != INF else None,
        "detour_time_min": float(detour_time) if detour_time != INF else None,
        "delay_min": max(float(delay), 0.0),
        "baseline_route": _path_to_coords(net, orig_path),
        "detour_route": _path_to_coords(net, detour_path),
        "nodes_count_baseline": len(orig_path),
        "nodes_count_detour": len(detour_path),
    }


def get_primary_alternative_route(
    net: Network,
    closed_edges: list[tuple[int, int]],
    category: str = "hospital",
) -> Optional[dict]:
    """Find the most affected population origin and return its baseline vs detour alternative route."""
    if not closed_edges:
        return None

    candidate_origins = []
    for u, v in closed_edges[:5]:
        candidate_origins.extend([u, v])
        for n in list(net.graph.neighbors(u))[:2] + list(net.graph.neighbors(v))[:2]:
            candidate_origins.append(n)

    if not candidate_origins:
        return None

    candidate_origins.sort(key=lambda n: net.population.get(n, 0), reverse=True)
    best_route = None
    max_delay = -1.0

    for orig in candidate_origins[:6]:
        r = compute_point_route(net, orig, closed_edges=closed_edges, category=category)
        if r.get("success") and r.get("is_diverted"):
            delay = r.get("delay_min", 0.0)
            if delay > max_delay or best_route is None:
                max_delay = delay
                best_route = r

    return best_route


def find_edges_between_nodes(
    net: Network,
    node_a: int,
    node_b: int,
    max_hops: int = 50,
) -> list[tuple[int, int]]:
    """Find all edge pairs connecting node_a and node_b.
    
    If direct edge exists, returns [(min(node_a, node_b), max(node_a, node_b))].
    Otherwise, finds the shortest corridor path between node_a and node_b and
    returns all edge pairs along that path.
    """
    if node_a not in net.graph or node_b not in net.graph:
        return []

    if node_a == node_b:
        return []

    # 1. Direct edge check
    if net.graph.has_edge(node_a, node_b):
        return [(min(node_a, node_b), max(node_a, node_b))]

    # 2. Shortest path corridor search
    try:
        path = nx.shortest_path(net.graph, source=node_a, target=node_b, weight="travel_time")
        if len(path) <= max_hops + 1:
            edges = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edges.append((min(int(u), int(v)), max(int(u), int(v))))
            return edges
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass

    return []