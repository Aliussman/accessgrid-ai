"""Shared pytest fixtures: small hand-built road networks."""
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import Network  # noqa: E402


def make_small_net() -> Network:
    """A 6-node MultiGraph with two hospitals (node 0 and 3):

    path:  0 --3--> 1 --4--> 2 --5--> 3
    alt:        1 -----8----- 3        (parallel-ish alternate road)
    leaf:                3 --2--> 5    (dead-end village)
    4: disconnected node.
    Edge lengths (m) are 2 km for every edge (used by the AI length display).
    """
    G = nx.MultiGraph()
    G.add_weighted_edges_from(
        [(0, 1, 3.0), (1, 2, 4.0), (2, 3, 5.0), (1, 3, 8.0), (3, 5, 2.0)],
        weight="travel_time", length=2000.0,
    )
    # Named roads for the road-selector / NL features.
    road_by_edge = {(0, 1): "Main Road", (1, 2): "Main Road",
                    (2, 3): "High Street", (1, 3): "Bypass Road",
                    (3, 5): "Village Road"}
    for (u, v), name in road_by_edge.items():
        for k, d in G[u][v].items():
            d["name"] = name
    G.add_node(4)  # isolated node with population but no road access
    hospitals = gpd.GeoDataFrame(
        [
            {"osm_id": "h0", "name": "Hospital Zero", "node_id": 0},
            {"osm_id": "h1", "name": "Hospital One", "node_id": 3},
        ]
    )
    population = {0: 10, 1: 20, 2: 30, 3: 40, 5: 50, 4: 100}
    return Network(graph=G, hospitals=hospitals, population=population)


@pytest.fixture(scope="module")
def small_net() -> Network:
    return make_small_net()


@pytest.fixture(scope="module")
def real_net() -> Network:
    """The cached tri-city dataset; only used when data files exist."""
    from src.config import GRAPHML_PATH, HOSPITALS_PATH, POP_PATH

    if not (GRAPHML_PATH.exists() and HOSPITALS_PATH.exists() and POP_PATH.exists()):
        pytest.skip("cached data files not present")
    return Network.load()