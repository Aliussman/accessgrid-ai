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
        rows.append(
            f"{i}. {r['name']}: restored {r['population_restored']:,}, "
            f"recovered {r['population_recovered']:,}, "
            f"saved {r['avg_time_saved_min']:.2f} min avg, "
            f"reduced accessibility debt {r.get('debt_reduction_pct', 0.0):.1f}%"
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
        lines = [
            f"The most promising intervention is '{best['name']}'.",
            "It restores the largest share of hospital access in this scenario:",
            f"- {best['population_restored']:,} people regain all-threshold access.",
            f"- average time saved {best['avg_time_saved_min']:.2f} min per affected person.",
            f"- accessibility debt reduced {best.get('debt_reduction_pct', 0.0):.1f}%.",
            "A planner should re-open this route first, or keep it as an "
            "emergency-only corridor while the disruption persists.",
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