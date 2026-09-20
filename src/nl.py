"""Deterministic & AI-augmented natural-language interface for AccessGrid.

Turns free-text planner queries into structured ``{action, ...}`` dicts the
engine can execute. Supports disaster presets, landmark/sector aliases,
high-precision fuzzy matching, and optional Gemini AI intent extraction.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from rapidfuzz import fuzz, process

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .engine import DISASTER_PRESETS, Network, named_roads

# Pre-defined landmark and sector aliases for Chandigarh / Mohali metro
_LANDMARK_ALIASES: dict[str, str] = {
    "sector 17": "Jan Marg",
    "sec 17": "Jan Marg",
    "sector 22": "Himalaya Marg",
    "sec 22": "Himalaya Marg",
    "sector 35": "Dakshin Marg",
    "sec 35": "Dakshin Marg",
    "sector 43": "Himalaya Marg",
    "sec 43": "Himalaya Marg",
    "sector 32": "Dakshin Marg",
    "sec 32": "Dakshin Marg",
    "pgi": "Madhya Marg",
    "pgimer": "Madhya Marg",
    "tribune chowk": "Dakshin Marg",
    "it park": "Madhya Marg",
    "kharar": "Kharar-Banur Road",
    "landran": "Kharar-Landran Road",
    "industrial area": "Udyog Path",
    "railway station": "Vikas Marg",
    "sukhna": "Sukhna Path",
    "panjab university": "Vidya Marg",
    "pu": "Vidya Marg",
}

_PRESET_KEYWORDS: dict[str, set[str]] = {
    "monsoon_flood": {
        "monsoon", "flood", "flooding", "waterlog", "waterlogging",
        "inundat", "submerge", "underpass", "flash flood", "rain", "storm"
    },
    "vip_lockdown": {
        "vip", "lockdown", "security", "curfew", "blockade", "convoy",
        "protocol", "protest", "summit", "police blockade", "dignitary"
    },
    "industrial_hazard": {
        "hazmat", "chemical", "hazard", "industrial", "toxic", "spill",
        "gas leak", "factory fire", "hazardous", "contamination"
    },
}

_FACILITY_WORDS = (
    "add hospital", "add a hospital", "new hospital", "new facility",
    "emergency facility", "build a hospital", "build hospital",
    "mobile triage", "triage unit", "triage pod", "field hospital",
    "place a hospital", "siting", "site a hospital", "add clinic", "mobile unit"
)

_CORRIDOR_WORDS = (
    "emergency corridor", "priority route", "green wave", "greenwave",
    "priority corridor", "speed up", "pedestrianize", "priority lane",
    "ambulance lane", "signal preemption", "transit corridor", "corridor"
)

_RESET_WORDS = (
    "reopen", "clear closure", "clear all", "reset", "back to normal",
    "baseline", "overview", "show coverage", "remove closure", "unblock",
    "restore all", "restore normal", "normal", "initial state"
)


def parse_scenario(query: str, net: Network) -> dict:
    """Parse a planner sentence into a structured scenario dictionary.

    Returns one of:
        {"action": "preset", "preset_id": str, "scenario_title": str}
        {"action": "close", "road": str, "closed_edges": list[tuple[int, int]]}
        {"action": "reopen", "road": str | None}
        {"action": "add_facility", "road": str}
        {"action": "corridor", "road": str}
        {"action": "interventions"}
        {"action": "coverage"}
        {"action": "help", "roads": list, "message": str}
    """
    q = query.strip()
    if not q:
        return {
            "action": "help",
            "roads": _top_roads(net),
            "question": q,
            "message": "Please enter a query like 'What if Dakshin Marg is closed?' or 'Simulate monsoon flood'."
        }

    lower = q.lower()

    # 1. Check for Reset / Baseline / Normal Coverage
    if any(w in lower for w in _RESET_WORDS) and not any(w in lower for w in ("close", "block", "shut", "flood", "hazard")):
        if any(w in lower for w in ("coverage", "overview", "baseline")):
            return {"action": "coverage", "question": q}
        road = _match_road(q, net)
        return {"action": "reopen", "road": road, "question": q}

    # 2. Check for Disaster Preset triggers
    for pid, keywords in _PRESET_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            pdata = DISASTER_PRESETS.get(pid, {})
            return {
                "action": "preset",
                "preset_id": pid,
                "scenario_title": pdata.get("title", pid),
                "question": q,
            }

    # 3. Check for Interventions / Recovery Analysis queries
    if _match_interventions(lower):
        return {"action": "interventions", "question": q}

    # 4. Check for Mobile Triage / Hospital Placement
    if any(w in lower for w in _FACILITY_WORDS):
        road = _match_road(q, net)
        if road:
            return {"action": "add_facility", "road": road, "question": q}
        return {
            "action": "help",
            "roads": _top_roads(net),
            "question": q,
            "message": "Specify which road or sector to place the facility near (e.g. 'Deploy mobile triage near Vidya Marg')."
        }

    # 5. Check for Dedicated EMS Green-Wave Corridors
    if any(w in lower for w in _CORRIDOR_WORDS):
        road = _match_road(q, net)
        if road:
            return {"action": "corridor", "road": road, "question": q}
        return {
            "action": "help",
            "roads": _top_roads(net),
            "question": q,
            "message": "Specify which road to designate as an EMS corridor (e.g. 'Green wave corridor on Dakshin Marg')."
        }

    # 6. Road Closures / Disruption What-If Queries
    road = _match_road(q, net)
    if road:
        action = _classify_action(q)
        return {"action": action, "road": road, "question": q}

    # 7. Optional Gemini LLM Fallback for ambiguous or complex queries
    llm_res = _try_gemini_parse(q, net)
    if llm_res:
        return llm_res

    # 8. Friendly fallback guidance
    return {
        "action": "help",
        "roads": _top_roads(net),
        "question": q,
        "message": f"Could not identify a road matching '{q}'. Try selecting an arterial corridor like Dakshin Marg or Madhya Marg."
    }


def _classify_action(query: str) -> str:
    lower = query.lower()
    if _match_interventions(lower):
        return "interventions"
    if any(w in lower for w in ("reopen", "unblock", "unclos", "reconnect", "restore the road", "open")):
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
    """Resolve road name via landmark dictionary, exact match, or fuzzy token matching."""
    lower = query.lower()

    # 1. Check Landmark / Sector aliases
    for alias, road_target in _LANDMARK_ALIASES.items():
        if alias in lower:
            return road_target

    roads = [r["name"] for r in named_roads(net.graph)]
    if not roads:
        return None

    # 2. Check exact case-insensitive substring
    for name in roads:
        if name.lower() in lower:
            return name

    # 3. Clean query by removing common question framing
    cleaned = re.sub(
        r"\b(what|if|happens|when|simulate|closure|closing|is|closed|blocked|shut|down|road|street|path|marg|on|the|in|near|hazard|at)\b",
        "",
        lower,
        flags=re.IGNORECASE
    ).strip()

    search_target = cleaned if len(cleaned) >= 3 else lower

    # 4. Fuzzy match against all named roads
    result = process.extractOne(
        search_target, roads, scorer=fuzz.token_set_ratio, score_cutoff=60
    )
    if result:
        return result[0]

    # Secondary partial ratio check
    result_part = process.extractOne(
        search_target, roads, scorer=fuzz.partial_ratio, score_cutoff=70
    )
    return result_part[0] if result_part else None


def _try_gemini_parse(query: str, net: Network) -> Optional[dict]:
    """Use Google Gemini to extract intent from complex natural language phrasing."""
    if not GEMINI_API_KEY:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)

        road_names = [r["name"] for r in named_roads(net.graph)[:30]]
        presets = list(DISASTER_PRESETS.keys())

        prompt = f"""You are a query parser for an emergency road network digital twin.
User query: "{query}"

Available named roads: {json.dumps(road_names)}
Available disaster presets: {json.dumps(presets)}

Extract the user's intent into a clean JSON object with this exact schema:
{{
  "action": "close" | "preset" | "corridor" | "facility" | "reopen" | "coverage" | "help",
  "road": "<Exact road name from list if mentioned, else null>",
  "preset_id": "<Exact preset id if matched, else null>",
  "explanation": "<Short 1-sentence explanation of parsed scenario>"
}}

Respond ONLY with valid JSON. Do not include markdown code fences."""

        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        txt = resp.text.strip()
        if txt.startswith("```"):
            txt = re.sub(r"^```[a-z]*\n", "", txt)
            txt = re.sub(r"\n```$", "", txt).strip()

        data = json.loads(txt)
        data["question"] = query
        return data
    except Exception:
        return None


def _top_roads(net: Network, n: int = 12) -> list[str]:
    return [r["name"] for r in named_roads(net.graph)[:n]]