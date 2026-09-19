"""Precompute edge criticality for the AccessGrid road network.

For every road edge we score how much harm closing it would do to hospital
access. The score blends three measured quantities:

  * ``usage``      - how many residents' nearest-hospital shortest path uses
                     the edge (pop-weighted route share)
  * ``pop_affected`` - exact population whose access worsens if the edge is
                     closed alone (full re-computation, top-K edges only)
  * ``pop_lost``   - exact population that loses all in-threshold access if
                     the edge is closed alone (top-K edges only)

The exact closures are expensive (one multi-source Dijkstra each), so they
run only for the top-K edges by ``usage``; all other edges carry ``usage``
but a null score. ``score`` is 0-100 = weighted average of percentile ranks
(50% lost, 30% affected, 20% usage).

Usage:  python -m scripts.precompute_criticality [--top 150]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import CRITICALITY_PATH, DEFAULT_THRESHOLD_MIN  # noqa: E402
from src.engine import Network  # noqa: E402
from src.engine import (  # noqa: E402
    closure_impact_many,
    coverage,
    nearest_hospitals,
    route_edge_usage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=150,
                        help="number of top edges to score exactly")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_MIN,
                        help="emergency coverage threshold in minutes")
    parser.add_argument("--out", type=Path, default=CRITICALITY_PATH)
    args = parser.parse_args()

    net = Network.load()
    print(f"Graph: {net.graph.number_of_nodes()} nodes, "
          f"{net.graph.number_of_edges()} edges, {len(net.hospitals)} hospitals")

    print("Computing baseline coverage and route usage...")
    baseline = coverage(net, args.threshold)
    time, hospital, prev = nearest_hospitals(
        net.graph, [int(n) for n in net.hospitals["node_id"]], return_prev=True
    )
    usage = route_edge_usage(net, time, hospital, prev)
    usage_df = pd.DataFrame(
        [{"u": u, "v": v, "usage": usage[(u, v)]} for (u, v) in usage]
    )
    usage_df = usage_df[usage_df.u != usage_df.v].sort_values(
        "usage", ascending=False
    ).reset_index(drop=True)
    print(f"Usage computed for {len(usage_df)} unique edges; "
          f"max usage={int(usage_df['usage'].max()):,}")

    top = usage_df.head(args.top)
    edge_list = list(zip(top.u, top.v))
    print(f"Running exact single-edge closures for top {len(edge_list)} edges...")
    impacts = closure_impact_many(net, edge_list, args.threshold, baseline)

    rows = []
    for (u, v), imp in zip(edge_list, impacts):
        rows.append({
            "u": u, "v": v, "evaluated": True,
            "pop_affected": imp["pop_affected"],
            "pop_lost": imp["pop_lost_coverage"],
        })
    exact = pd.DataFrame(rows)

    scored = usage_df.merge(exact, on=["u", "v"], how="left")
    scored["evaluated"] = scored["evaluated"].fillna(False)
    scored["pop_affected"] = scored["pop_affected"].fillna(0).astype(int)
    scored["pop_lost"] = scored["pop_lost"].fillna(0).astype(int)

    ev = scored[scored["evaluated"]].copy()
    for col in ("pop_lost", "pop_affected", "usage"):
        ev[f"{col}_r"] = ev[col].rank(pct=True)
    ev["score"] = (0.5 * ev["pop_lost_r"] + 0.3 * ev["pop_affected_r"]
                   + 0.2 * ev["usage_r"]) * 100
    scored["score"] = float("nan")
    scored.loc[ev.index, "score"] = ev["score"]
    scored = scored.drop(columns=["evaluated"])

    out = scored.sort_values("score", ascending=False).reset_index(drop=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({len(out)} rows).")
    print("Top 10 by score:")
    print(out.head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())