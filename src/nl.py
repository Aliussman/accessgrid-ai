"""Deterministic natural-language interface for AccessGrid.

Turns free-text planner queries into structured ``{action, ...}`` dicts the
engine can execute. Road names are resolved by fuzzy-matching street names
already present on the graph (rapidfuzz), so queries work fully offline and
never need a live LLM to *parse* the scenario.
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz, process

from .engine import Network, named_roads

_ACTION_WORDS = {
    "close": {"close", "closed", "closing", "shut", "block", "blocked",
              "cut", "sever", "interrupt", "shutdown", "closure", "disrupt"},
    "reopen": {"reopen", "reopened", "open", "restore", "unblock", "unclos",
               "reconnect"},
    "interventions": {"intervention", "which", "helps", "help", "fix",
                      "restore access", "best"},
    "coverage": {"coverage", "baseline", "overview", "summary", "how many",
                 "accessible"},
}

_FACILITY_WORDS = ("add", "add a hospital", "new hospital", "new facility",
                   "emergency facility", "build a hospital", "build a facility",
                   "place a hospital", "add hospital", "siting", "site a")
_CORRIDOR_WORDS = ("emergency corridor", "priority route", "corridor",
                   "speed up", "pedestrianize", "pedestrianise",
                   "priority lane", "green wave")


def parse_scenario(query: str, net: Network) -> dict:
    """Parse a planner sentence into a scenario dict.

    Returns one of:
        {"action": "close", "road": str | None}   -> close a road
        {"action": "reopen", "road": str | None}  -> clear (reopen) a road
        {"action": "add_facility", "road": str}   -> add an emergency facility
        {"action": "corridor", "road": str}       -> priority route along a road
        {"action": "interventions"}               -> run intervention analysis
        {"action": "coverage"}                    -> show baseline
        {"action": "help", "roads": list}         -> ask for a road name
    """
    q = query.strip()
    if not q:
        return {"action": "help", "roads": [], "question": q}

    lower = q.lower()
    if _match_interventions(lower):
        return {"action": "interventions", "question": q}
    if any(w in lower for w in _FACILITY_WORDS):
        road = _match_road(q, net)
        if road:
            return {"action": "add_facility", "road": road, "question": q}
        return {"action": "help", "roads": _top_roads(net), "question": q}
    if any(w in lower for w in _CORRIDOR_WORDS):
        road = _match_road(q, net)
        if road:
            return {"action": "corridor", "road": road, "question": q}
        return {"action": "help", "roads": _top_roads(net), "question": q}

    action = _classify_action(q)
    if action == "interventions":
        return {"action": "interventions", "question": q}

    road = _match_road(q, net)
    if action == "close":
        if road is None:
            return {"action": "help", "roads": _top_roads(net), "question": q}
        return {"action": "close", "road": road, "question": q}
    if action == "reopen":
        return {"action": "reopen", "road": road, "question": q}
    if action == "coverage":
        return {"action": "coverage", "question": q}
    if road is not None:
        return {"action": "close", "road": road, "question": q}
    return {"action": "help", "roads": _top_roads(net), "question": q}


def _classify_action(query: str) -> str:
    lower = query.lower()
    if _match_interventions(lower):
        return "interventions"
    if any(w in lower for w in ("reopen", "reopen ", "unblock", "unclos", "reconnect", "restore the road", "open the road", "open it back")):
        return "reopen"
    if any(w in lower for w in ("close", "closure", "closing", "shut", "block", "blocked", "cut", "sever", "disrupt", "what if", "what happens")):
        return "close"
    if any(w in lower for w in ("coverage", "baseline", "overview", "summary", "how many", "accessible", "normal")):
        return "coverage"
    return "close"


def _match_interventions(lower: str) -> bool:
    return bool(re.search(
        r"(intervention|which (intervention |one )?helps|which .* (helps|restore|fix|recover)|"
        r"what .* (intervention|help|fix)|best .*(intervention|way)|help[s]? most|"
        r"minimi[sz]e[s]? .*(loss|debt|impact|access)|reduce[s]? .*(loss|debt|impact))", lower
    ))


def _match_road(query: str, net: Network) -> Optional[str]:
    roads = [r["name"] for r in named_roads(net.graph)]
    if not roads:
        return None
    lower = query.lower()
    for name in roads:
        if name.lower() in lower:
            return name
    # fuzzy match the query against all road names
    result = process.extractOne(
        query, roads, scorer=fuzz.token_set_ratio, score_cutoff=55
    )
    return result[0] if result else None


def _top_roads(net: Network, n: int = 12) -> list[str]:
    return [r["name"] for r in named_roads(net.graph)[:n]]