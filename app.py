"""AccessGrid - Streamlit map UI.

A planner closes road segments (by drawing on the map or picking a named
road), the engine recomputes hospital coverage, and the app shows the
before/after accessibility impact, the most-affected zones, ranked
interventions that restore access, and an AI/natural-language briefing.

Layout mirrors the MVP spec: Overview / Simulate / Impact / Interventions.
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
    closure_impact,
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
              boosts: list | None = None, draw_controls: bool = True) -> folium.Map:
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


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
def main() -> None:
    st.title("AccessGrid - Urban Accessibility Digital Twin")
    st.caption("Mock study area: Mohali / Chandigarh / Panchkula road network. "
               "Simulate a road disruption and test interventions that restore "
               "hospital access.")

    net, edge_lines, _ = get_network()
    if "closed_edges" not in st.session_state:
        st.session_state.closed_edges = set()
    if "closed_road" not in st.session_state:
        st.session_state.closed_road = None
    if "active_intervention" not in st.session_state:
        st.session_state.active_intervention = None
    if "handled_drawing" not in st.session_state:
        st.session_state.handled_drawing = ""
    closed = st.session_state.closed_edges
    closed_road = st.session_state.closed_road

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
                          "survey / WorldPop data. Hospital bed counts are "
                          "synthetic too.")

    snap = run_coverage(float(threshold))
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
                st.rerun()
        elif intent["action"] == "reopen" and intent.get("road"):
            segs = road_edges(net.graph, intent["road"])
            if segs and st.sidebar.button("Reopen this road"):
                st.session_state.closed_edges -= set(segs)
                if not st.session_state.closed_edges:
                    st.session_state.closed_road = None
                st.session_state.active_intervention = None
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
        _simulate_page(net, edge_lines, snap, threshold, closed, closed_road)

    with tab_impact:
        _impact_page(net, snap, impact, threshold)

    with tab_interventions:
        _interventions_page(net, snap, impact, threshold, closed, candidates)

    _sidebar_briefing(impact, candidates, net, closed_road)


def _sidebar_briefing(impact, candidates, net, closed_road) -> None:
    st.sidebar.subheader("Closure briefing")
    if impact is None:
        st.sidebar.markdown("Close a road in the Simulate tab to see the "
                            "impact briefing here.")
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


def _simulate_page(net, edge_lines, snap, threshold, closed, closed_road) -> dict | None:
    st.subheader("Simulate disruption")
    left, right = st.columns([1, 2])

    with left:
        mode = st.radio("Scenario input", ["Pick a named road", "Draw on the map"],
                        index=0)
        if mode == "Pick a named road":
            names = road_names()
            chosen = st.selectbox("Select road", [""] + names,
                                  format_func=lambda x: x or "Choose a road...")
            run = st.button("RUN SIMULATION", type="primary",
                            disabled=not chosen)
            if run and chosen:
                segs = road_edges(net.graph, chosen)
                if segs:
                    st.session_state.closed_edges = set(segs)
                    st.session_state.closed_road = chosen
                    st.session_state.active_intervention = None
                    st.rerun()
        else:
            st.caption("Draw a red line over roads on the map to close them. "
                       "Segments within ~130 m of the line are closed.")
        if closed:
            st.button("Clear all closures", on_click=_clear_state)

    impact = None
    if closed:
        impact = run_impact(tuple(sorted(closed)), float(threshold))

    with right:
        if closed:
            _before_after(net, snap, impact, threshold, closed_road)
            impact_map = build_map(net, snap, impact)
        else:
            st.info("No closure yet. Pick a road and run the simulation, or "
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
                st.session_state.closed_edges |= new_matches
                st.session_state.closed_road = None
                st.session_state.active_intervention = None
                st.session_state.handled_drawing = fp
                st.rerun()

    if closed:
        return impact
    return None


def _before_after(net, snap, impact, threshold, closed_road) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Baseline avg access time",
                f"{impact['avg_access_before']:.1f} min")
    delta = impact["avg_access_after"] - impact["avg_access_before"]
    col2.metric("Disrupted avg access time",
                f"{impact['avg_access_after']:.1f} min",
                delta=f"+{delta:.1f} min")
    lost = impact["pop_lost_coverage"]
    col3.metric("Population within %d min" % threshold,
                f"{snap['covered_pop'] - lost:,}",
                delta=f"-{lost:,}", delta_color="inverse")
    st.caption(f"Disruption: {closed_road or len(impact['closed_edges'])} road "
               f"segment(s) closed · {impact['pop_affected']:,} people affected · "
               f"{lost:,} lose coverage · {impact['pop_worsened']:,} delayed.")


def _impact_page(net, snap, impact, threshold) -> None:
    st.subheader("Impact analysis")
    if impact is None:
        st.info("Close a road in the Simulate tab to see impact here.")
        return
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Affected population", f"{impact['pop_affected']:,}")
    col2.metric("Lost coverage", f"{impact['pop_lost_coverage']:,}")
    col3.metric("Delayed but served", f"{impact['pop_worsened']:,}")
    col4.metric("Hospitals affected", f"{impact['hospitals_affected']}")

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
                        candidates: list | None = None) -> None:
    st.subheader("Intervention analysis")
    if impact is None:
        st.info("Close a road in the Simulate tab to see interventions here.")
        return
    if candidates is None:
        candidates = run_interventions(tuple(sorted(closed)), float(threshold))
    if not candidates:
        st.success("No population affected - no intervention needed.")
        return

    st.markdown(
        "**Tested interventions** - reopen every segment, reopen each single "
        "segment, or run an emergency corridor past the worst segment.")
    rows = [
        {"Intervention": c["name"],
         "Population restored": c["population_restored"],
         "Population recovered": c["population_recovered"],
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
        col3.metric("Avg access after", f"{outcome['avg_access_after']:.1f} min")
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