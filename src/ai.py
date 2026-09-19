"""Closure impact narrative powered by Google GenAI.

Turns the engine's (numeric) closure impact into a short analyst-style
briefing for a city planner. Falls back to a deterministic template when no
API key is configured or the model call fails, so the app always works.
"""
from __future__ import annotations

from typing import Optional

from .config import GEMINI_API_KEY, GEMINI_MODEL

_PROMPT = """\
You are an emergency-access analyst for a South Asian urban metro area. A city \
planner has closed a set of road segments to test emergency access to \
hospitals. Below is a structured fact sheet (numbers in your answer must match \
it exactly; do not invent figures). Write a short, plain-critical briefing \
(under 140 words) for the planner covering: (1) what was closed, (2) the \
population impact - total affected, those who lose all in-time hospital \
access, and those just delayed but still served, plus the ACCESSIBILITY DEBT \
the closure imposes (population-minutes of travel-time loss), (3) which named \
hospitals absorb the lost access or lose catchment population, (4) equity: \
which population groups are disproportionately affected (if any), (5) one \
concrete recommendation. Use bullet points for the numbers. End with a \
one-line "Bottom line".

FACT SHEET
----------
Area population: {total_pop}
Emergency threshold: {threshold} minutes
Baseline coverage: {covered_pop} people ({coverage_pct:.1f}%)
Closed road segments: {closed_count} ({closed_km:.1f} km total)
Population affected by closure: {affected}
Population that LOST coverage (no hospital within {threshold} min): {lost}
Population delayed but still covered: {worsened}
Accessibility debt: {debt_pop_minutes} pop-minutes \
({per_capita_debt_min:.1f} min per affected person)
Population groups (avg t-change / lost coverage):
{equity}
Disproportionately affected groups: {disproportionate}
Hospitals absorbing lost access (osm_id -> lost population):
{hospital_losses}
"""

_INTERVENTION_PROMPT = """\
You are an emergency-access analyst for a South Asian urban metro area. A city \
planner has closed road segments and needs to pick an intervention that \
restores the most emergency-hospital access. Below is a structured fact sheet \
(numbers in your answer must match it exactly; do not invent figures). Write \
a short briefing (under 140 words) for the planner: (1) restate the disruption \
in one line and its accessibility debt, (2) rank the tested interventions from \
most to least access restored / debt removed, (3) explain why the top \
intervention helps the most (e.g. it reconnects the most high-impact zones), \
(4) give one action recommendation. Use bullet points for the numbers. End \
with a one-line "Bottom line".

FACT SHEET
----------
Emergency threshold: {threshold} minutes
Population affected by the closure: {affected}
Population that LOST coverage: {lost}
Accessibility debt of the closure: {debt} pop-minutes
Road segments closed: {closed_count} ({closed_km:.1f} km total)
Tested interventions (ranked by score):
{interventions}
"""


def summarize_closure(impact: dict, net, interventions: Optional[list] = None) -> dict:
    """Return a closure briefing. ``interventions`` (optional) is the ranked
    candidate list from ``engine.interventions``; when provided, the briefing
    also names the best intervention to restore access."""
    context = _build_context(impact, net)
    provider = "gemini"
    text = _gemini_summary(context)
    if text is None:
        provider = "template"
        text = _template_summary(impact, net, interventions)
    return {"provider": provider, "text": text}


def explain_interventions(impact: dict, interventions: list, net) -> dict:
    """Briefing focused on which tested intervention restores the most access,
    used by the Interventions page and the 'which intervention helps most'
    natural-language query."""
    if not interventions:
        return {"provider": "template", "text": "No interventions were tested."}
    rows = []
    for i, r in enumerate(interventions, 1):
        tactic_str = f" — {r['tactic']}" if r.get("tactic") else ""
        effort_str = f" [Effort: {r.get('effort', 'N/A')}]" if r.get("effort") else ""
        rows.append(
            f"{i}. {r['name']}{effort_str}: restored {r['population_restored']:,}, "
            f"recovered {r['population_recovered']:,}, "
            f"saved {r['avg_time_saved_min']:.2f} min avg, "
            f"reduced accessibility debt {r.get('debt_reduction_pct', 0.0):.1f}%{tactic_str}"
        )
    context = _INTERVENTION_PROMPT.format(
        threshold=impact["threshold"],
        affected=impact["pop_affected"],
        lost=impact["pop_lost_coverage"],
        debt=impact.get("debt_pop_minutes", 0.0),
        closed_count=len(impact["closed_edges"]),
        closed_km=_closed_length_km(net.graph, impact["closed_edges"]),
        interventions="\n".join(rows),
    )
    text = _gemini_summary(context)
    if text is None:
        best = interventions[0]
        tactic_note = f"\n- Tactical directive: {best['tactic']}" if best.get("tactic") else ""
        effort_note = f"\n- Resource commitment: {best.get('effort', 'Standard mobilization')}" if best.get("effort") else ""
        lines = [
            f"The recommended tactical intervention is '{best['name']}'.",
            "It delivers optimal recovery vs implementation effort in this scenario:",
            f"- {best['population_restored']:,} people regain all-threshold emergency access.",
            f"- Average time saved {best['avg_time_saved_min']:.2f} min per affected person.",
            f"- Accessibility debt reduced by {best.get('debt_reduction_pct', 0.0):.1f}%.",
            f"{tactic_note}",
            f"{effort_note}",
        ]
        return {"provider": "template", "text": "\n".join(lines)}
    return {"provider": "gemini", "text": text}


def _build_context(impact: dict, net) -> str:
    loss_lines = []
    if "hospitals_lost" in impact and impact["hospitals_lost"]:
        osm_to_name = {
            str(h["osm_id"]): h["name"] for h in net.hospitals.to_dict("records")
        }
        for osm_id, pop in sorted(
            impact["hospitals_lost"].items(), key=lambda kv: -kv[1]
        ):
            name = osm_to_name.get(osm_id, osm_id)
            loss_lines.append(f"- {name} ({osm_id}): {pop:,}")
    hospital_losses = "\n".join(loss_lines) or "- none (delays only)"

    closed_km = _closed_length_km(net.graph, impact["closed_edges"])
    total_pop = _sum_pop(net)
    pct = impact.get("coverage_pct")
    covered_pop = impact.get("baseline_covered_pop", 0)

    eq = impact.get("equity", {})
    labels = {"general": "General", "elderly": "Elderly",
              "mobility": "Mobility-limited", "lowcar": "Low-car households"}
    eq_lines = []
    for g in ("general", "elderly", "mobility", "lowcar"):
        d = eq.get(g)
        if d:
            eq_lines.append(
                f"- {labels.get(g, g)}: +{d['delta_min']:.1f} min avg, "
                f"{d['pop_lost_coverage']:,.0f} lose coverage"
            )
    dispro = eq.get("disproportionately_affected", [])
    return _PROMPT.format(
        total_pop=total_pop,
        threshold=impact["threshold"],
        covered_pop=covered_pop,
        coverage_pct=pct if pct is not None else (covered_pop / total_pop * 100 if total_pop else 0),
        closed_count=len(impact["closed_edges"]),
        closed_km=closed_km,
        affected=impact["pop_affected"],
        lost=impact["pop_lost_coverage"],
        worsened=impact["pop_worsened"],
        debt_pop_minutes=impact.get("debt_pop_minutes", 0.0),
        per_capita_debt_min=impact.get("per_capita_debt_min", 0.0),
        equity="\n".join(eq_lines) or "- none",
        disproportionate=", ".join(dispro) if dispro else "none",
        hospital_losses=hospital_losses,
    )


def _sum_pop(net) -> int:
    return int(sum(net.population.values()))


def _closed_length_km(graph, closed_edges) -> float:
    total_m = 0.0
    for u, v in closed_edges:
        data = graph.get_edge_data(u, v)
        if data:
            total_m += sum(
                float(d.get("length", 0.0)) for d in data.values()
            )
    return total_m / 1000.0


def _gemini_summary(context: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=context,
        )
        text = (resp.text or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 - network/model errors -> template fallback
        return None


def _template_summary(impact: dict, net, interventions: Optional[list] = None) -> str:
    affected = impact["pop_affected"]
    lost = impact["pop_lost_coverage"]
    worsened = impact["pop_worsened"]
    threshold = impact["threshold"]
    closed = ", ".join(f"{u}-{v}" for u, v in impact["closed_edges"])
    debt = impact.get("debt_pop_minutes", 0.0)
    per_cap = impact.get("per_capita_debt_min", 0.0)
    eq = impact.get("equity", {})
    dispro = eq.get("disproportionately_affected", [])
    labels = {"elderly": "elderly", "mobility": "mobility-limited",
              "lowcar": "low-car households"}
    eq_line = ""
    if dispro:
        eq_line = (
            f"- Equity: disproportionately affects {', '.join(labels.get(g, g) for g in dispro)} "
            "(their average access deteriorates more than the general population)."
        )
    lines = [
        f"Closure impact (threshold {threshold:.0f} min):",
        f"- {affected:,} people ({affected / _sum_pop(net) * 100:.2f}% of the area population) are directly affected.",
        f"- {lost:,} people lose all hospital access within {threshold:.0f} minutes.",
        f"- {worsened:,} people are delayed but still reach a hospital in time.",
        f"- accessibility debt: {debt:,.0f} population-minutes "
        f"({per_cap:.1f} min per affected person).",
    ]
    if eq_line:
        lines.append(eq_line)
    lines.append("- Hospital catchment changes:")
    osm_to_name = {str(h["osm_id"]): h["name"] for h in net.hospitals.to_dict("records")}
    for osm_id, pop in sorted(
        impact.get("hospitals_lost", {}).items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"  * {osm_to_name.get(osm_id, osm_id)} loses {pop:,} served population")
    if not impact.get("hospitals_lost"):
        lines.append("  * none - access is delayed but not lost")
    if interventions:
        best = interventions[0]
        lines.append(
            f"Best-tested intervention: {best['name']} restores "
            f"{best['population_restored']:,} people and cuts accessibility "
            f"debt by {best.get('debt_reduction_pct', 0.0):.1f}%."
        )
    else:
        lines.append(
            f"Recommendation: open/keep bypass roads for the segments {closed}; "
            "monitor the affected residential nodes for rerouting."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Multi-Turn AI Copilot & Incident Action Plan (IAP) Generator
# --------------------------------------------------------------------------
def ask_copilot(
    query: str,
    chat_history: list[dict],
    impact: dict | None,
    net,
    candidates: Optional[list] = None,
) -> dict:
    """Conversational AI Assistant for planners to interrogate scenario details.

    Returns dict with {"provider": "gemini"|"template", "text": str}.
    """
    total_pop = _sum_pop(net)
    hosp_count = len(net.hospitals)

    # Build active context
    if impact is not None:
        closed_km = _closed_length_km(net.graph, impact.get("closed_edges", []))
        affected = impact.get("pop_affected", 0)
        lost = impact.get("pop_lost_coverage", 0)
        debt = impact.get("debt_pop_minutes", 0.0)
        eq = impact.get("equity", {})
        dispro = eq.get("disproportionately_affected", [])

        inter_summary = []
        if candidates:
            for i, c in enumerate(candidates[:3], 1):
                inter_summary.append(
                    f"- {c['name']}: Restores {c['population_restored']:,} people, "
                    f"cuts debt {c.get('debt_reduction_pct', 0.0):.1f}%"
                )
        inter_text = "\n".join(inter_summary) or "None tested."

        system_context = (
            f"You are the AccessGrid Emergency Logistics Copilot for Chandigarh / Mohali.\n"
            f"ACTIVE SCENARIO:\n"
            f"- Total city population: {total_pop:,}, Hospitals: {hosp_count}\n"
            f"- Closed road segments: {len(impact.get('closed_edges', []))} ({closed_km:.1f} km)\n"
            f"- Population affected: {affected:,} | Population lost coverage: {lost:,}\n"
            f"- Accessibility Debt: {debt:,.0f} pop-minutes\n"
            f"- Disproportionately affected vulnerable groups: {', '.join(dispro) if dispro else 'None'}\n"
            f"- Top Interventions:\n{inter_text}\n\n"
            f"Answer the user's questions clearly, concisely, and practically for emergency planners. "
            f"Quote numbers accurately from the facts above. Be direct and helpful."
        )
    else:
        system_context = (
            f"You are the AccessGrid Emergency Logistics Copilot for Chandigarh / Mohali.\n"
            f"STATUS: Normal Baseline (No active road disruptions).\n"
            f"- Total city population: {total_pop:,}\n"
            f"- Operating hospitals: {hosp_count}\n"
            f"Advise the planner on potential risk points, coverage thresholds, or suggest testing road closures."
        )

    # Format conversation history
    history_lines = []
    for msg in chat_history[-6:]:
        role = "User" if msg.get("role") == "user" else "Copilot"
        history_lines.append(f"{role}: {msg.get('content', '')}")
    history_text = "\n".join(history_lines)

    prompt = f"{system_context}\n\nCONVERSATION HISTORY:\n{history_text}\n\nUser Question: {query}\nCopilot Answer:"

    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = (resp.text or "").strip()
            if text:
                return {"provider": "gemini", "text": text}
        except Exception:
            pass

    # Deterministic offline fallback logic
    lower_q = query.lower()
    if "debt" in lower_q or "accessibility debt" in lower_q:
        if impact:
            ans = f"The active scenario generates **{impact.get('debt_pop_minutes', 0):,.0f} population-minutes** of accessibility debt ({impact.get('per_capita_debt_min', 0):.1f} min per affected resident)."
        else:
            ans = "Accessibility debt is currently **0 pop-min** as no disruptions are active on the network."
    elif "hospital" in lower_q or "surge" in lower_q or "capacity" in lower_q:
        if impact and impact.get("hospitals_lost"):
            lost_h = list(impact["hospitals_lost"].items())[:3]
            ans = f"Hospitals with severed or reduced direct catchment: " + ", ".join(f"{h}: {p:,} pop lost" for h, p in lost_h) + "."
        else:
            ans = f"All {hosp_count} hospitals are currently operating within baseline network routing."
    elif "best" in lower_q or "intervention" in lower_q or "recommend" in lower_q:
        if candidates:
            best = candidates[0]
            ans = f"Top recommended action: **{best['name']}**. It restores access for {best['population_restored']:,} residents and cuts accessibility debt by {best.get('debt_reduction_pct', 0.0):.1f}%."
        else:
            ans = "Close a road or select a disaster preset in the Simulate tab to analyze prioritized interventions."
    elif "equity" in lower_q or "elderly" in lower_q or "vulnerable" in lower_q:
        if impact:
            dispro = impact.get("equity", {}).get("disproportionately_affected", [])
            if dispro:
                ans = f"⚠️ Vulnerability Alert: Disproportionate delays detected for: **{', '.join(dispro)}** households."
            else:
                ans = "Delays are distributed across general demographics without high disproportionate concentration."
        else:
            ans = "Baseline equity shares are synthetic and loaded for elderly, mobility-limited, and low-car demographics."
    else:
        if impact:
            ans = (
                f"Active disruption affects **{impact.get('pop_affected', 0):,}** residents "
                f"({impact.get('pop_lost_coverage', 0):,} losing threshold access). "
                f"Primary recommendation is to establish a priority corridor or reopen critical bottlenecks."
            )
        else:
            ans = (
                f"AccessGrid is monitoring {total_pop:,} residents across {hosp_count} emergency hospitals. "
                "Select a disaster scenario preset or draw a road closure to simulate impacts."
            )

    return {"provider": "template", "text": ans}


def generate_incident_action_plan(
    impact: dict,
    net,
    candidates: Optional[list] = None,
) -> str:
    """Generate a formal Incident Action Plan (IAP) report for emergency responders."""
    total_pop = _sum_pop(net)
    closed_edges = impact.get("closed_edges", [])
    closed_km = _closed_length_km(net.graph, closed_edges)
    affected = impact.get("pop_affected", 0)
    lost = impact.get("pop_lost_coverage", 0)
    worsened = impact.get("pop_worsened", 0)
    debt = impact.get("debt_pop_minutes", 0.0)
    threshold = impact.get("threshold", 15.0)

    eq = impact.get("equity", {})
    dispro = eq.get("disproportionately_affected", [])

    top_interventions = ""
    if candidates:
        rows = []
        for i, c in enumerate(candidates[:3], 1):
            rows.append(
                f"| {i} | **{c['name']}** | {c['population_restored']:,} | {c['avg_time_saved_min']:.2f} min | {c.get('debt_reduction_pct', 0.0):.1f}% |"
            )
        top_interventions = "\n".join(rows)
    else:
        top_interventions = "| 1 | Reopen all closed road segments | Full recovery | N/A | 100% |"

    report = f"""# 📋 INCIDENT ACTION PLAN (IAP) — EMERGENCY ACCESS
**Metro Jurisdiction:** Chandigarh / Mohali / Panchkula Urban Area
**Incident Operational Period:** Immediate Tactical Window
**Assessment Platform:** AccessGrid Digital Twin

---

## 1. Executive Situational Overview
- **Network Status:** Active Road Closures Detected ({len(closed_edges)} segments, ~{closed_km:.1f} km total).
- **Emergency Access Threshold:** {threshold:.0f} Minutes (Golden Hour Response).
- **Total Population in Study Area:** {total_pop:,}
- **Directly Impacted Population:** **{affected:,}** ({(affected / total_pop * 100):.1f}% of total).
- **Severe Inaccessibility (Threshold Lost):** **{lost:,}** residents cannot reach any hospital in {threshold:.0f} min.
- **Delayed Coverage:** **{worsened:,}** residents remain within threshold but suffer rerouting delays.
- **Total Accessibility Debt (AD):** **{debt:,.0f} population-minutes** ({impact.get('per_capita_debt_min', 0.0):.1f} min/person).

---

## 2. Demographic Equity & Vulnerability Assessment
{f"⚠️ **DISPROPORTIONATE IMPACT IDENTIFIED:** {', '.join(dispro).upper()} populations suffer higher than average travel-time deterioration." if dispro else "✅ **EQUITY STATUS:** Delay impact is relatively uniform across demographic groups."}

| Group | Avg Delay (Δ min) | Population Losing Coverage |
| :--- | :--- | :--- |
| **General Population** | +{eq.get('general', {}).get('delta_min', 0.0):.1f} min | {eq.get('general', {}).get('pop_lost_coverage', 0):,.0f} |
| **Elderly (>65)** | +{eq.get('elderly', {}).get('delta_min', 0.0):.1f} min | {eq.get('elderly', {}).get('pop_lost_coverage', 0):,.0f} |
| **Mobility-Limited** | +{eq.get('mobility', {}).get('delta_min', 0.0):.1f} min | {eq.get('mobility', {}).get('pop_lost_coverage', 0):,.0f} |
| **Low-Car Households** | +{eq.get('lowcar', {}).get('delta_min', 0.0):.1f} min | {eq.get('lowcar', {}).get('pop_lost_coverage', 0):,.0f} |

---

## 3. Prioritized Recovery Interventions & Tactical Ranking

| Priority | Intervention Measure | Pop. Restored | Avg Time Saved | Debt Reduction |
| :--- | :--- | :--- | :--- | :--- |
{top_interventions}

---

## 4. Operational Directives for Emergency Services & Traffic Police
1. **Traffic Control:** Deploy field personnel to establish priority emergency signal corridors along the highest-ranked detour roads.
2. **EMS Dispatch Advisory:** Reroute ambulance dispatch from isolated zones to adjacent secondary hospitals with surplus triage capacity.
3. **Public Advisory:** Issue immediate travel alerts advising non-emergency vehicles to bypass restricted sectors.
4. **Intervention Priority:** Implement Priority 1 action immediately to eliminate the majority of accumulated accessibility debt.

---
*Report generated automatically by AccessGrid Urban Accessibility Intelligence Engine.*
"""
    return report