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

from .config import DATA_DIR, DEFAULT_THRESHOLD_MIN, HOSPITALS_PATH, POP_PATH

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


def load_hospitals() -> gpd.GeoDataFrame:
    df = gpd.read_file(str(HOSPITALS_PATH))
    df["node_id"] = df["node_id"].astype(int)
    df["name"] = df["name"].astype(str)
    # Backwards compatibility for cached files built before type/capacity.
    if "type" not in df.columns:
        df["type"] = "Hospital"
    if "capacity" not in df.columns:
        df["capacity"] = 0
    df["capacity"] = df["capacity"].fillna(0).astype(int)
    df["type"] = df["type"].fillna("Hospital").astype(str)
    return df


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
    population: dict[int, int] = field(default_factory=dict)
    vulnerability: dict[int, dict[str, float]] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir=None) -> "Network":
        return cls(graph=load_graph(), hospitals=load_hospitals(),
                   population=load_population(), vulnerability=load_vulnerability())


# --------------------------------------------------------------------------
# Nearest-hospital assignment (one multi-source Dijkstra, argmin included)
# --------------------------------------------------------------------------
def nearest_hospitals(
    G: nx.MultiGraph,
    hospital_nodes: list[int],
    weight: str = "travel_time",
    return_prev: bool = False,
) -> tuple[dict[int, float], dict[int, int]] | tuple[dict[int, float], dict[int, int], dict[int, int]]:
    """Return (time, hospital) per node: minutes to and id of the nearest
    hospital node. Unreachable nodes get time=inf, hospital=None. When
    return_prev=True, also returns prev[node] = previous node toward the
    nearest hospital (shortest-path tree predecessor)."""
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
            w = min((e.get(weight, INF) for e in edges.values()), default=INF)
            if w == INF:
                continue
            new_d = d + w
            heapq.heappush(heap, (new_d, sid, v))
            # the last relaxation with the minimal distance gives the SP parent
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
    """Baseline coverage snapshot.

    Returns a dict with total/covered population, per-hospital service and
    covered population, plus the raw per-node time/hospital maps.
    """
    G, hospitals, population = net.graph, net.hospitals, net.population
    hospital_nodes = [int(n) for n in hospitals["node_id"]]
    time, hospital = nearest_hospitals(G, hospital_nodes)

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

    return {
        "threshold": float(threshold),
        "total_pop": int(total_pop),
        "covered_pop": int(covered_pop),
        "coverage_pct": (covered_pop / total_pop * 100.0) if total_pop else 0.0,
        "avg_access_min": float(avg_access),
        "hospitals": list(per_hospital.values()),
        "node_time": time,
        "node_hospital": hospital,
    }


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
    to the baseline. ``extra_sources`` adds nodes as emergency facilities."""
    work = _work_graph(net, remove_edges, boost_edges)
    sources = [int(n) for n in net.hospitals["node_id"]] + [int(s) for s in extra_sources]
    new_time, _ = nearest_hospitals(work, sources)
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
    return fields


def interventions(
    net: Network,
    closed_edges: list[tuple[int, int]],
    threshold: float = DEFAULT_THRESHOLD_MIN,
    baseline: Optional[dict] = None,
    max_segments: int = 8,
) -> list[dict]:
    """Rank candidate interventions for a road-closure scenario.

    Candidates generated:
      * reopen every closed segment at once (full recovery)
      * reopen each of the top-``max_segments`` most-used segments
        (per-segment marginal benefit; the rest are evaluated jointly as
        'reopen all other segments')
      * an emergency corridor: traffic sped up along the best parallel route
        for the single most destructive segment (segment stays closed)

    Closing a named road can remove hundreds of segments, so per-segment
    evaluation is capped at ``max_segments`` (ranked by pop-weighted route
    usage, which is free from the baseline tree) to keep the UI responsive.

    Each candidate reports population restored (all-in-threshold access back),
    population recovered (no longer affected at all), average time saved and
    accessibility recovery %. Score is a 0-100 blend of those (50/30/20)."""
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
    top = keyed[:max_segments]
    rest = keyed[max_segments:]

    candidates: list[dict] = [{
        "kind": "reopen_all",
        "name": "Reopen all closed segments",
        "remove_edges": [],  # nothing stays closed
        "boost_edges": [],
    }]
    for e in top:
        others = [o for o in closed if o != e]
        candidates.append({
            "kind": "reopen_one",
            "name": f"Reopen segment {e[0]}-{e[1]}",
            "remove_edges": others,  # keep the rest closed, reopen this one
            "boost_edges": [],
        })
    if rest:
        candidates.append({
            "kind": "reopen_rest",
            "name": "Reopen all other closed segments",
            "remove_edges": top,  # keep top harmful segments closed
            "boost_edges": [],
        })

    alt = _alternate_path(net, worst)
    if alt:
        candidates.append({
            "kind": "corridor",
            "name": ("Emergency corridor: speed up the parallel route around "
                     f"{worst[0]}-{worst[1]}"),
            "remove_edges": closed,  # segment stays closed
            "boost_edges": [(u, v, 0.7) for (u, v) in alt],
        })

    results = []
    for cand in candidates:
        f = _evaluate_modification(net, baseline, threshold,
                                   cand["remove_edges"], cand["boost_edges"])
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
        results.append({
            "kind": cand["kind"],
            "name": cand["name"],
            "remove_edges": [(int(a), int(b)) for a, b in cand["remove_edges"]],
            "boost_edges": [(int(a), int(b), float(x)) for a, b, x in cand["boost_edges"]],
            "population_restored": int(restored),
            "population_recovered": int(recovered_affected),
            "avg_time_saved_min": float(avg_saved),
            "accessibility_recovery_pct": float(recovery),
            "debt_after_pop_min": debt_after,
            "debt_reduction_pct": (disrupted_debt - debt_after) / disrupted_debt * 100.0
            if disrupted_debt else 0.0,
        })

    _score_interventions(results)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


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
    each undirected edge. ``prev`` is the shortest-path tree from
    ``nearest_hospitals(..., return_prev=True)``."""
    if time is None or hospital is None or prev is None:
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
        # walk the SP tree from n up to its hospital, weighting each edge
        while cur != h and cur not in seen:
            seen.add(cur)
            p = prev.get(cur)
            if p is None or p == cur:
                break
            key = (min(cur, p), max(cur, p))
            usage[key] = usage.get(key, 0) + pop
            cur = p
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
        closed = impact.get("closed_edges", [])
        work = _work_graph(net, closed, [])
        sources = [int(n) for n in net.hospitals["node_id"]]
        curr_time, curr_hosp = nearest_hospitals(work, sources)
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