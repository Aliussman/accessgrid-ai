"""AccessGrid - Streamlit map UI.

A what-if engine for equitable urban accessibility. A planner simulates a
city change (road closure, emergency corridor, new facility), the engine
measures WHO loses access (accessibility debt by zone and by vulnerability
group), and the app compares interventions that minimise that loss.

Layout: Overview / Simulate / Impact / Interventions.
"""
from __future__ import annotations

import hashlib
import json

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw, Fullscreen
from shapely import wkt
from shapely.geometry import LineString
from streamlit_folium import st_folium

from src.ai import explain_interventions, summarize_closure
from src.config import (
    CENTRE_LAT,
    CENTRE_LON,
    DATA_DIR,
    DEFAULT_THRESHOLD_MIN,
    POP_RASTER_PATH,
)
from src.engine import (
    Network,
    add_facility_to_closure,
    closure_impact,
    corridor_road,
    coverage,
    intervention_outcome,
    interventions,
    named_roads,
    road_edges,
)
from src.nl import parse_scenario

st.set_page_config(page_title="AccessGrid - hospital access under road closures",
                   layout="wide")

_DEFAULT_THRESHOLD = int(DEFAULT_THRESHOLD_MIN)
INF = float("inf")


# --------------------------------------------------------------------------
# Cached heavy computations
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_network():
    net = Network.load()
    edge_lines = []
    edge_index = {}
    for u, v, data in net.graph.edges(data=True):
        geom = None
        if data.get("geometry"):
            try:
                geom = wkt.loads(data["geometry"])
            except Exception:  # noqa: BLE001 - malformed WKT -> fall back
                geom = None
        if geom is None:
            a, b = net.graph.nodes[u], net.graph.nodes[v]
            geom = LineString([(float(a["x"]), float(a["y"])),
                               (float(b["x"]), float(b["y"]))])
        key = (min(u, v), max(u, v))
        edge_lines.append((u, v, geom))
        edge_index[key] = geom
    return net, edge_lines, edge_index


@st.cache_data(show_spinner=False)
def read_criticality() -> pd.DataFrame:
    path = DATA_DIR / "criticality.csv"
    if not path.exists():
        return pd.DataFrame(columns=["u", "v", "score", "pop_affected"])
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def run_coverage(threshold: float) -> dict:
    net, _, _ = get_network()
    return coverage(net, threshold)


@st.cache_data(show_spinner=False)
def run_impact(closed_tuple: tuple, threshold: float) -> dict:
    net, _, _ = get_network()
    return closure_impact(net, list(closed_tuple), threshold,
                          run_coverage(threshold))


@st.cache_data(show_spinner=False)
def run_interventions(closed_tuple: tuple, threshold: float) -> list:
    net, _, _ = get_network()
    return interventions(net, list(closed_tuple), threshold,
                         run_coverage(threshold))


@st.cache_data(show_spinner=False)
def run_intervention_outcome(closed_tuple: tuple, threshold: float,
                             inter_name: str) -> dict:
    net, _, _ = get_network()
    baseline = run_coverage(threshold)
    cand = next(c for c in run_interventions(closed_tuple, threshold)
                if c["name"] == inter_name)
    return intervention_outcome(net, list(closed_tuple), cand, threshold,
                                baseline)


@st.cache_data(show_spinner=False)
def run_facility(closed_tuple: tuple, threshold: float,
                 facility_node: int) -> dict:
    net, _, _ = get_network()
    return add_facility_to_closure(net, facility_node, list(closed_tuple),
                                   threshold, run_coverage(threshold))


@st.cache_data(show_spinner=False)
def run_corridor(closed_tuple: tuple, threshold: float, road: str) -> dict:
    net, _, _ = get_network()
    return corridor_road(net, road, 0.7, threshold, list(closed_tuple),
                         run_coverage(threshold))


@st.cache_data(show_spinner=False)
def road_names() -> list[str]:
    net, _, _ = get_network()
    return [r["name"] for r in named_roads(net.graph)]


# --------------------------------------------------------------------------
# Drawing -> closed road segments
# --------------------------------------------------------------------------
def building_roads(net: Network) -> pd.DataFrame:
    rows = []
    for r in named_roads(net.graph):
        pairs = road_edges(net.graph, r["name"])
        length_m = sum(
            min((d.get("length", 0.0) for d in
                 net.graph.get_edge_data(u, v).values()), default=0.0)
            for u, v in pairs
        )
        rows.append({"Road": r["name"], "Segments": r["segments"],
                     "Length (km)": round(length_m / 1000.0, 2)})
    return pd.DataFrame(rows)


def drawing_features(drawing) -> list:
    if not drawing:
        return []
    if drawing.get("type") == "FeatureCollection":
        return drawing.get("features", [])
    if drawing.get("type") == "Feature":
        return [drawing]
    return []


def close_edges_for_drawing(drawing, edge_lines: list) -> set:
    """Match the drawn polyline to road segments within ~130 m."""
    matched = set()
    for feat in drawing_features(drawing):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        buf = LineString(coords).buffer(0.0012)
        for u, v, eline in edge_lines:
            if buf.intersects(eline):
                matched.add(tuple(sorted((u, v))))
    return matched


def drawing_fingerprint(drawing) -> str:
    if not drawing:
        return ""
    blob = json.dumps(drawing, sort_keys=True, default=str)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Map building
# --------------------------------------------------------------------------
def _edge_line(u: int, v: int) -> LineString | None:
    _, _, edge_index = get_network()
    return edge_index.get((min(u, v), max(u, v)))


def build_map(net: Network, snap: dict, impact: dict | None, *,
              boosts: list | None = None, improved_nodes: list | None = None,
              draw_controls: bool = True) -> folium.Map:
    m = folium.Map(location=(float(CENTRE_LAT), float(CENTRE_LON)),
                   zoom_start=12, tiles="CartoDB positron", control_scale=True)
    Fullscreen().add_to(m)

    hosp_layer = folium.FeatureGroup(name="Hospitals").add_to(m)
    for h in snap["hospitals"]:
        row = net.hospitals[net.hospitals["osm_id"].astype(str) == str(h["osm_id"])]
        if row.empty:
            continue
        g = row.iloc[0].geometry
        lon, lat = (g.x, g.y) if g.geom_type == "Point" else (g.centroid.x, g.centroid.y)
        radius = 5 + 7 * (h["covered_pop"] / (snap["covered_pop"] or 1)) ** 0.5
        pop = (f"<b>{h['name']}</b><br>type: {h.get('type', 'Hospital')}<br>"
               f"beds: {h.get('capacity', 0):,}<br>served pop: {h['service_pop']:,}<br>"
               f"covered pop: {h['covered_pop']:,}")
        folium.CircleMarker((lat, lon), radius=radius, color="black", weight=1,
                            fill=True, fill_color="blue", fill_opacity=0.85,
                            popup=pop).add_to(hosp_layer)

    layers = [hosp_layer]

    crit = read_criticality()
    crit = crit[crit["score"].notna()]
    if not crit.empty:
        risk_layer = folium.FeatureGroup(name="Riskiest corridors")
        top = crit.sort_values("score", ascending=False).head(40)
        for _, row in top.iterrows():
            line = _edge_line(int(row["u"]), int(row["v"]))
            if line is None:
                continue
            s = float(row["score"])
            color = ("darkred" if s >= 90 else "red" if s >= 75
                     else "orange" if s >= 60 else "yellow")
            folium.PolyLine(
                [(c[1], c[0]) for c in line.coords],
                color=color, weight=3, opacity=0.8,
                tooltip=(f"risk {s:.0f} · affected {int(row['pop_affected']):,}"
                         f" · lost {int(row['pop_lost']):,}"),
            ).add_to(risk_layer)
        layers.insert(1, risk_layer)

    if boosts:
        boost_layer = folium.FeatureGroup(name="Emergency corridors")
        for u, v in boosts:
            line = _edge_line(u, v)
            if line is not None:
                folium.PolyLine([(c[1], c[0]) for c in line.coords],
                                color="green", weight=4, opacity=0.9,
                                dash_array="8 4").add_to(boost_layer)
        layers.append(boost_layer)

    if impact is not None:
        closed_layer = folium.FeatureGroup(name="Closed segments")
        for u, v in impact.get("closed_edges", []):
            line = _edge_line(u, v)
            if line is not None:
                folium.PolyLine([(c[1], c[0]) for c in line.coords], color="red",
                                weight=5, opacity=0.9).add_to(closed_layer)
        layers.append(closed_layer)

        affected = folium.FeatureGroup(name="Affected population")
        added = impact.get("pop_added_minutes", {})
        markers = sorted(added.items(), key=lambda kv: -kv[1])[:3500]
        for n, extra in markers:
            try:
                x, y = _node_xy(net, n)
            except KeyError:
                continue
            lost = extra == INF
            color = "darkred" if lost else "orange"
            label = "LOST access" if lost else f"Delayed +{extra:.1f} min"
            folium.CircleMarker((y, x), radius=4, color="black", weight=0.5,
                                fill=True, fill_color=color, fill_opacity=0.8,
                                popup=f"<b>{label}</b>").add_to(affected)
        layers.append(affected)

        if "facility_node" in impact \
                and impact.get("facility_node") is not None:
            fac_layer = folium.FeatureGroup(name="Emergency facility")
            fn = int(impact["facility_node"])
            try:
                x, y = _node_xy(net, fn)
            except KeyError:
                x, y = impact.get("facility_lon"), impact.get("facility_lat")
            folium.Marker((y, x), icon=folium.Icon(color="purple", icon="plus",
                                                   prefix="fa"),
                          popup="<b>Proposed emergency facility</b>").add_to(fac_layer)
            layers.append(fac_layer)

    if improved_nodes:
        improved = folium.FeatureGroup(name="Improved access")
        for n in improved_nodes[:2500]:
            try:
                x, y = _node_xy(net, n)
            except KeyError:
                continue
            folium.CircleMarker((y, x), radius=4, color="black", weight=0.5,
                                fill=True, fill_color="green", fill_opacity=0.75,
                                popup=f"<b>Improved access</b>").add_to(improved)
        layers.append(improved)

    folium.LayerControl().add_to(m)
    for layer in layers:
        m.add_child(layer)

    if draw_controls:
        Draw(export=False, draw_options={
            "polyline": True, "polygon": False, "rectangle": False,
            "circle": False, "marker": False, "circlemarker": False,
        }, edit_options={"remove": True, "edit": True})
    return m


def _node_xy(net: Network, n: int):
    d = net.graph.nodes[n]
    return float(d["x"]), float(d["y"])


def facility_node_for_road(net: Network, road_name: str) -> int | None:
    """Where to place an emergency facility for a given road: the segment
    endpoint closest to the road's midpoint (its most central junction)."""
    segs = road_edges(net.graph, road_name)
    if not segs:
        return None
    xs, ys = [], []
    for u, v in segs:
        try:
            xu, yu = _node_xy(net, u)
            xv, yv = _node_xy(net, v)
        except KeyError:
            continue
        xs += [xu, xv]
        ys += [yu, yv]
    if not xs:
        return None
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    best, best_d = None, INF
    for n in {p for s in segs for p in s}:
        if n in net.graph.nodes:
            x, y = _node_xy(net, n)
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < best_d:
                best, best_d = n, d
    return best


# --------------------------------------------------------------------------
# Table helpers
# --------------------------------------------------------------------------
def most_affected_zones(net: Network, impact: dict, top: int = 10) -> pd.DataFrame:
    scores = impact.get("zone_impact_score", {})
    added = impact.get("pop_added_minutes", {})
    rows = []
    for n, score in sorted(scores.items(), key=lambda kv: -kv[1])[:top]:
        extra = added.get(n, 0)
        if extra == INF:
            delta = "LOST access"
        else:
            delta = f"+{extra:.1f} min"
        rows.append({
            "Zone / node": int(n),
            "Population": int(net.population.get(n, 0)),
            "Travel change": delta,
            "Impact score (0-100)": round(float(score), 1),
        })
    return pd.DataFrame(rows)


def equity_table(impact: dict) -> pd.DataFrame:
    """Per-vulnerability-group accessibility impact (who loses access)."""
    groups = ["general", "elderly", "mobility", "lowcar"]
    eq = impact.get("equity", {})
    rows = []
    for g in groups:
        d = eq.get(g)
        if not d:
            continue
        rows.append({
            "Population group": {
                "general": "General", "elderly": "Elderly (65+)",
                "mobility": "Mobility-limited", "lowcar": "Low-car households",
            }[g],
            "Group population": f"{d['group_pop']:,.0f}",
            "Avg access before (min)": f"{d['before_avg_min']:.1f}",
            "Avg access after (min)": f"{d['after_avg_min']:.1f}",
            "Change (min)": f"+{d['delta_min']:.1f}" if d["delta_min"] > 0
            else f"{d['delta_min']:.1f}",
            "Lose coverage": f"{d['pop_lost_coverage']:,.0f}",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
def main() -> None:
    st.title("AccessGrid AI - a what-if engine for equitable urban access")
    st.caption("Simulate a city change (road closure, emergency corridor, new "
               "facility) -> measure who loses access -> test interventions "
               "that minimise the loss.")
    st.caption("Mock study area: Mohali / Chandigarh / Panchkula road network.")

    net, edge_lines, _ = get_network()
    if "closed_edges" not in st.session_state:
        st.session_state.closed_edges = set()
    if "closed_road" not in st.session_state:
        st.session_state.closed_road = None
    if "active_intervention" not in st.session_state:
        st.session_state.active_intervention = None
    if "handled_drawing" not in st.session_state:
        st.session_state.handled_drawing = ""
    if "scenario" not in st.session_state:
        st.session_state.scenario = "closure"
    if "scenario_road" not in st.session_state:
        st.session_state.scenario_road = None
    if "facility_node" not in st.session_state:
        st.session_state.facility_node = None
    closed = st.session_state.closed_edges
    closed_road = st.session_state.closed_road
    scenario = st.session_state.scenario

    # --- Sidebar: settings + natural-language input -----------------------
    st.sidebar.header("Settings")
    threshold = st.sidebar.slider("Emergency threshold (min)",
                                  min_value=5, max_value=30, value=_DEFAULT_THRESHOLD, step=1)
    crit = read_criticality()
    if not crit[crit["score"].notna()].empty:
        st.sidebar.caption("Riskiest corridors (top 40) shown on the map by "
                           "criticality score.")

    if POP_RASTER_PATH is None:
        st.sidebar.warning("Population is SYNTHETIC (formula-based), not real "
                          "survey / WorldPop data. Hospital bed counts and "
                          "vulnerability shares (elderly / mobility-limited / "
                          "low-car) are synthetic too.")

    snap = run_coverage(float(threshold))

    # Current scenario result depends on the active scenario type.
    if scenario == "facility" and st.session_state.facility_node is not None:
        impact = run_facility(tuple(sorted(closed)), float(threshold),
                              int(st.session_state.facility_node))
        candidates = []
    elif scenario == "corridor" and st.session_state.scenario_road:
        impact = run_corridor(tuple(sorted(closed)), float(threshold),
                              st.session_state.scenario_road)
        candidates = []
    else:
        st.session_state.scenario = "closure"
        impact = run_impact(tuple(sorted(closed)), float(threshold)) if closed else None
        candidates = (run_interventions(tuple(sorted(closed)), float(threshold))
                      if closed else [])

    st.sidebar.subheader("Ask AccessGrid")
    query = st.sidebar.text_input(
        "Natural-language scenario",
        placeholder='e.g. "What if Dakshin Marg is closed?" or "Which '
                    'intervention helps the most?"',
        label_visibility="collapsed")
    if query.strip():
        intent = parse_scenario(query, net)
        st.sidebar.caption(f"Parsed: {intent.get('action')}"
                           f"{' - ' + intent['road'] if intent.get('road') else ''}")
        if intent["action"] == "close" and intent.get("road"):
            segs = road_edges(net.graph, intent["road"])
            if segs and st.sidebar.button("Run suggested closure"):
                st.session_state.closed_edges = set(segs)
                st.session_state.closed_road = intent["road"]
                st.session_state.active_intervention = None
                st.session_state.scenario = "closure"
                st.rerun()
        elif intent["action"] == "reopen" and intent.get("road"):
            segs = road_edges(net.graph, intent["road"])
            if segs and st.sidebar.button("Reopen this road"):
                st.session_state.closed_edges -= set(segs)
                if not st.session_state.closed_edges:
                    st.session_state.closed_road = None
                st.session_state.active_intervention = None
                st.session_state.scenario = "closure"
                st.rerun()
        elif intent["action"] == "add_facility" and intent.get("road"):
            fn = facility_node_for_road(net, intent["road"])
            if fn is not None and st.sidebar.button("Run suggested facility"):
                st.session_state.facility_node = fn
                st.session_state.scenario_road = intent["road"]
                st.session_state.scenario = "facility"
                st.session_state.active_intervention = None
                st.session_state.closed_road = None
                st.rerun()
        elif intent["action"] == "corridor" and intent.get("road"):
            if st.sidebar.button("Run suggested corridor"):
                st.session_state.scenario_road = intent["road"]
                st.session_state.scenario = "corridor"
                st.session_state.active_intervention = None
                st.session_state.closed_road = None
                st.rerun()
        elif intent["action"] == "interventions":
            st.sidebar.caption("Intervention analysis runs automatically in the "
                              "Interventions tab once a road is closed.")
        elif intent["action"] == "help":
            st.sidebar.caption("Please name a road, e.g. " +
                               ", ".join(intent.get("roads", [])[:5]))

    # --- Tabs -------------------------------------------------------------
    tab_overview, tab_simulate, tab_impact, tab_interventions = st.tabs(
        ["Overview", "Simulate", "Impact", "Interventions"])

    with tab_overview:
        _overview_page(net, snap, threshold)

    with tab_simulate:
        _simulate_page(net, edge_lines, snap, threshold, closed, closed_road,
                       scenario)

    with tab_impact:
        _impact_page(net, snap, impact, threshold, scenario)

    with tab_interventions:
        _interventions_page(net, snap, impact, threshold, closed, candidates,
                            scenario)

    if impact is not None:
        _sidebar_briefing(impact, candidates, net, closed_road)


def _sidebar_briefing(impact, candidates, net, closed_road) -> None:
    st.sidebar.subheader("Closure briefing")
    if impact is None:
        st.sidebar.markdown("Run a scenario in the Simulate tab to see the "
                            "briefing here.")
        return
    scenario = st.session_state.scenario
    if scenario != "closure":
        if scenario == "facility":
            st.sidebar.info(
                f"Facility near {st.session_state.scenario_road} prevents "
                f"{impact.get('debt_prevented_pop_min', 0.0):,.0f} pop-min of "
                f"debt and newly covers {int(impact.get('new_covered_pop', 0)):,} "
                f"residents within {int(impact['threshold'])} min.")
        else:
            st.sidebar.info(
                f"Corridor along {st.session_state.scenario_road} changes avg "
                f"access by "
                f"{impact['avg_access_after'] - impact['avg_access_before']:+.1f} "
                f"min. Close a road to compare interventions.")
        return
    result = summarize_closure(impact, net, candidates)
    st.sidebar.info(f"Provider: {result['provider']}")
    st.sidebar.markdown(result["text"])


def _overview_page(net, snap, threshold) -> None:
    st.subheader("City overview")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Population", f"{snap['total_pop']:,}")
    col2.metric("Hospitals", f"{len(snap['hospitals'])}")
    col3.metric("Avg access time", f"{snap['avg_access_min']:.1f} min")
    col4.metric("Within %d min" % threshold, f"{snap['coverage_pct']:.1f}%")

    st.markdown(
        "**Baseline accessibility** - the model city with no disruptions. "
        "Every junction is assigned to its nearest hospital; covered if the "
        "drive time is within the threshold.")
    m = build_map(net, snap, None, draw_controls=False)
    st_folium(m, height=560, use_container_width=True, key="overview_map")


def _simulate_page(net, edge_lines, snap, threshold, closed, closed_road,
                   scenario) -> dict | None:
    st.subheader("Simulate a city change")
    st.markdown(
        "Choose what the city does, then see **who loses access** in the "
        "Impact tab and **which intervention minimises the loss** in the "
        "Interventions tab.")
    left, right = st.columns([1, 2])

    with left:
        scenario_choice = st.radio(
            "What-if scenario",
            ["Road closure", "Add emergency facility", "Emergency corridor"],
            index=0 if scenario == "closure" else
            (1 if scenario == "facility" else 2))
        mode = st.radio("Scenario input", ["Pick a named road", "Draw on the map"],
                        index=0)
        names = road_names()
        chosen = st.selectbox("Select road", [""] + names,
                              format_func=lambda x: x or "Choose a road...")
        run = st.button("RUN SIMULATION", type="primary",
                        disabled=not chosen)

        def _run_scenario(choice: str, road: str) -> None:
            if choice == "Road closure":
                segs = road_edges(net.graph, road)
                if segs:
                    st.session_state.closed_edges = set(segs)
                    st.session_state.closed_road = road
                    st.session_state.scenario = "closure"
            elif choice == "Add emergency facility":
                fn = facility_node_for_road(net, road)
                if fn is not None:
                    st.session_state.scenario = "facility"
                    st.session_state.scenario_road = road
                    st.session_state.facility_node = fn
                    st.session_state.closed_road = None
            else:
                st.session_state.scenario = "corridor"
                st.session_state.scenario_road = road
                st.session_state.closed_road = None
            st.session_state.active_intervention = None
            st.rerun()

        if run and chosen:
            _run_scenario(scenario_choice, chosen)

        if mode == "Draw on the map":
            st.caption("Draw a red line over roads on the map to close them. "
                       "Segments within ~130 m of the line are closed.")
        if closed:
            st.button("Clear all closures", on_click=_clear_state)

    impact = None
    if scenario == "facility" and st.session_state.facility_node is not None:
        impact = run_facility(tuple(sorted(closed)), float(threshold),
                              int(st.session_state.facility_node))
    elif scenario == "corridor" and st.session_state.scenario_road:
        impact = run_corridor(tuple(sorted(closed)), float(threshold),
                              st.session_state.scenario_road)
    elif closed:
        impact = run_impact(tuple(sorted(closed)), float(threshold))

    with right:
        if impact is not None:
            _before_after(net, snap, impact, threshold, closed_road, scenario)
            improved = _improved_nodes(snap, impact)
            boosts = None
            if scenario == "corridor" and st.session_state.scenario_road:
                boosts = road_edges(net.graph, st.session_state.scenario_road)
            impact_map = build_map(net, snap, impact, boosts=boosts,
                                   improved_nodes=improved)
        else:
            st.info("No scenario yet. Pick a road and run the simulation, or "
                    "draw a line over the map, to start.")
            impact_map = build_map(net, snap, None)

    output = st_folium(impact_map, height=640, use_container_width=True,
                       key="access_map", returned_objects=["last_active_drawing"])
    drawing = (output or {}).get("last_active_drawing")
    if drawing:
        fp = drawing_fingerprint(drawing)
        if fp and fp != st.session_state.handled_drawing:
            new_matches = close_edges_for_drawing(drawing, edge_lines)
            if new_matches:
                if st.session_state.scenario != "closure":
                    st.session_state.scenario = "closure"
                    st.session_state.scenario_road = None
                    st.session_state.facility_node = None
                st.session_state.closed_edges |= new_matches
                st.session_state.closed_road = None
                st.session_state.active_intervention = None
                st.session_state.handled_drawing = fp
                st.rerun()

    if impact is not None:
        return impact
    return None


def _improved_nodes(snap: dict, impact: dict) -> list:
    """Nodes whose access got *better* than baseline by > 1 min (e.g. after a
    new facility or an emergency corridor)."""
    base = snap.get("node_time", {})
    new = impact.get("node_time", {})
    out = [n for n, t in new.items() if base.get(n, INF) - t > 1.0]
    return sorted(out, key=lambda n: -(base.get(n, INF) - new.get(n, INF)))


def _before_after(net, snap, impact, threshold, closed_road, scenario) -> None:
    improving = scenario in ("facility", "corridor") and \
        impact.get("pop_affected", 1) == 0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Baseline avg access time",
                f"{impact['avg_access_before']:.1f} min")
    delta = impact["avg_access_after"] - impact["avg_access_before"]
    label = "After: avg access time"
    if improving:
        label = "After: avg access time"
    col2.metric(label, f"{impact['avg_access_after']:.1f} min",
                delta=f"{delta:+.1f} min")
    debt = impact.get("debt_pop_minutes", 0.0)
    col3.metric("Accessibility debt", f"{debt:,.0f} pop-min",
                help="Population-weighted sum of travel-time deterioration "
                     "(AD = sum P_i * (T_after - T_before)). The cost a "
                     "change imposes on residents' access.")
    lost = impact["pop_lost_coverage"]
    newly_covered = int(impact.get("new_covered_pop", 0))
    if improving:
        col4.metric("Population within %d min" % threshold,
                    f"{snap['covered_pop'] - lost + newly_covered:,}",
                    delta=f"+{newly_covered:,}" if newly_covered else None)
    else:
        col4.metric("Population within %d min" % threshold,
                    f"{snap['covered_pop'] - lost:,}",
                    delta=f"-{lost:,}", delta_color="inverse")
    if scenario == "closure":
        st.caption(f"Disruption: {closed_road or len(impact['closed_edges'])} "
                   f"road segment(s) closed · {impact['pop_affected']:,} people "
                   f"affected · {lost:,} lose coverage · "
                   f"{impact['pop_worsened']:,} delayed.")
    elif scenario == "facility":
        st.caption(f"Proposed emergency corridor CONCEPT: new facility placed "
                   f"near {st.session_state.scenario_road} · "
                   f"{int(impact.get('new_covered_pop', 0)):,} residents "
                   f"newly within {threshold} min · "
                   f"debt prevented "
                   f"{impact.get('debt_prevented_pop_min', 0.0):,.0f} pop-min.")
    else:
        st.caption(f"Emergency corridor: priority travel along "
                   f"{st.session_state.scenario_road} (0.7x travel time) · "
                   f"access improved for residents whose avg access fell "
                   f"{delta:+.1f} min.")


def _impact_page(net, snap, impact, threshold, scenario) -> None:
    st.subheader("Impact analysis")
    if impact is None:
        st.info("Run a scenario in the Simulate tab to see impact here.")
        return
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Affected population", f"{impact['pop_affected']:,}")
    col2.metric("Lost coverage", f"{impact['pop_lost_coverage']:,}")
    col3.metric("Delayed but served", f"{impact['pop_worsened']:,}")
    col4.metric("Hospitals affected", f"{impact['hospitals_affected']}")

    col1a, col2a, col3a = st.columns([1, 1, 1])
    debt = impact.get("debt_pop_minutes", 0.0)
    per_cap = impact.get("per_capita_debt_min", 0.0)
    col1a.metric("Accessibility debt", f"{debt:,.0f} pop-min",
                 delta=f"{per_cap:+.1f} min / affected person",
                 help="AD = sum P_i x (T_scenario,i - T_baseline,i). The "
                      "population-weighted cost of a city change.")
    if scenario == "facility":
        col2a.metric("Debt prevented by facility",
                     f"{impact.get('debt_prevented_pop_min', 0.0):,.0f} pop-min")
        col3a.metric("Newly covered",
                     f"{int(impact.get('new_covered_pop', 0)):,}")
    else:
        col2a.metric("Debt per affected person",
                     f"{per_cap:.1f} min")

    st.markdown("**Who loses access?** (by population group, equity analysis)")
    eq = equity_table(impact)
    if not eq.empty:
        st.dataframe(eq, use_container_width=True, hide_index=True)

    dispro = (impact.get("equity") or {}).get("disproportionately_affected", [])
    if dispro:
        names = {"elderly": "elderly", "mobility": "mobility-limited",
                 "lowcar": "low-car households"}
        st.warning(f"Disruption disproportionately affects: "
                   f"{', '.join(names.get(g, g) for g in dispro)}. Their "
                   f"average access deteriorates more than the general "
                   f"population, while a larger share loses coverage.")
    else:
        st.caption("No group is disproportionately affected - the disruption "
                   "spreads evenly across population groups.")

    st.markdown("**Most affected zones** (by population × travel-time change, "
                "normalised 0-100)")
    zones = most_affected_zones(net, impact)
    if not zones.empty:
        st.dataframe(zones, use_container_width=True, hide_index=True)

    m = build_map(net, snap, impact, draw_controls=False)
    st_folium(m, height=520, use_container_width=True, key="impact_map")
    _hospital_catchment(impact, net)


def _hospital_catchment(impact, net) -> None:
    if not impact.get("hospitals_lost"):
        st.caption("No hospital lost catchment population - access was delayed "
                   "but not lost anywhere.")
        return
    osm_to_name = {str(h["osm_id"]): h["name"]
                   for h in net.hospitals.to_dict("records")}
    rows = [
        {"Hospital": osm_to_name.get(oid, oid),
         "Population lost": int(p)}
        for oid, p in sorted(impact["hospitals_lost"].items(),
                             key=lambda kv: -kv[1])
    ]
    st.markdown("**Hospitals absorbing lost access**")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _interventions_page(net, snap, impact, threshold, closed,
                        candidates: list | None = None, scenario="closure") -> None:
    st.subheader("Intervention analysis")
    if impact is None:
        st.info("Run a scenario in the Simulate tab to see interventions here.")
        return
    if scenario != "closure":
        st.markdown(
            "This tab compares interventions for a **road closure** scenario. "
            "The current scenario is an intervention itself:")
        if scenario == "facility":
            st.success(
                f"**Add emergency facility** (near "
                f"{st.session_state.scenario_road}) prevents "
                f"**{impact.get('debt_prevented_pop_min', 0.0):,.0f} "
                f"pop-min of accessibility debt** and brings "
                f"**{int(impact.get('new_covered_pop', 0)):,} residents** "
                f"within {threshold} min.")
        else:
            st.success(
                f"**Emergency corridor** along "
                f"{st.session_state.scenario_road} improved access for "
                f"residents whose avg access changed "
                f"{impact['avg_access_after'] - impact['avg_access_before']:+.1f} "
                f"min. Compare it against closing a different road to see "
                f"trade-offs.")
        return
    if candidates is None:
        candidates = run_interventions(tuple(sorted(closed)), float(threshold))
    if not candidates:
        st.success("No population affected - no intervention needed.")
        return

    st.markdown(
        "**Tested interventions** - each option reports how much accessibility "
        "it restores and how much debt it removes.")
    rows = [
        {"Intervention": c["name"],
         "Population restored": c["population_restored"],
         "Population recovered": c["population_recovered"],
         "Debt after (pop-min)": f"{c['debt_after_pop_min']:,.0f}",
         "Debt reduction %": round(c["debt_reduction_pct"], 1),
         "Avg time saved (min)": round(c["avg_time_saved_min"], 2),
         "Accessibility recovery %": round(c["accessibility_recovery_pct"], 1),
         "Score (0-100)": c["score"],
         "kind": c["kind"]}
        for c in candidates
    ]
    table = pd.DataFrame(rows)
    st.dataframe(table.drop(columns=["kind"]), use_container_width=True,
                 hide_index=True)

    chosen_name = st.selectbox(
        "Apply an intervention to preview its result on the map",
        [""] + [c["name"] for c in candidates],
        format_func=lambda x: x or "No intervention - show disruption only")
    if chosen_name:
        st.session_state.active_intervention = chosen_name
        outcome = run_intervention_outcome(tuple(sorted(closed)),
                                           float(threshold), chosen_name)
        boosts = next(c["boost_edges"] for c in candidates
                      if c["name"] == chosen_name) or None
        boost_pairs = [(int(u), int(v)) for u, v, _ in boosts] if boosts else None
        col1, col2, col3 = st.columns(3)
        col1.metric("Affected after", f"{outcome['pop_affected']:,}")
        col2.metric("Lost coverage after", f"{outcome['pop_lost_coverage']:,}")
        col3.metric("Debt after", f"{outcome['debt_pop_minutes']:,.0f} pop-min")
        choosing = next(c for c in candidates if c["name"] == chosen_name)
        col4m = st.columns(1)[0]
        col4m.metric("Debt reduction",
                     f"{choosing['debt_reduction_pct']:.1f}%")
        m = build_map(net, snap, outcome, boosts=boost_pairs,
                      draw_controls=False)
        st_folium(m, height=480, use_container_width=True,
                  key="intervention_map")
    else:
        st.session_state.active_intervention = None

    st.markdown("**AI planner insight**")
    ai = explain_interventions(impact, candidates, net)
    st.sidebar.info(f"Intervention AI: {ai['provider']}")
    st.markdown(ai["text"])


def _clear_state() -> None:
    st.session_state.closed_edges = set()
    st.session_state.closed_road = None
    st.session_state.active_intervention = None
    st.session_state.handled_drawing = ""


if __name__ == "__main__":
    main()