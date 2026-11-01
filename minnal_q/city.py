"""Kochi road graph with time-of-day traffic.

Coordinates are approximate and travel times are synthetic but realistic
(minutes, off-peak). Traffic multipliers per time slot are illustrative.
"""
from __future__ import annotations

import networkx as nx

# name -> (lat, lon, kind)
NODES: dict[str, tuple[float, float, str]] = {
    "Ambulance Base (Kalamassery)": (10.0530, 76.3150, "base"),
    "Edappally": (10.0261, 76.3086, "junction"),
    "Palarivattom": (10.0030, 76.3090, "junction"),
    "Kaloor": (9.9970, 76.2990, "junction"),
    "Ernakulam North": (9.9900, 76.2880, "junction"),
    "MG Road": (9.9707, 76.2860, "junction"),
    "Kadavanthra": (9.9662, 76.3000, "junction"),
    "Vyttila": (9.9673, 76.3203, "junction"),
    "Kakkanad": (10.0159, 76.3419, "junction"),
    "Thrippunithura": (9.9497, 76.3463, "junction"),
    "Amrita Hospital": (10.0330, 76.2930, "hospital"),
    "Aster Medcity": (10.0450, 76.2780, "hospital"),
    "General Hospital Ernakulam": (9.9729, 76.2810, "hospital"),
    "Lakeshore Hospital": (9.9330, 76.3170, "hospital"),
    "Medical Trust Hospital": (9.9620, 76.2880, "hospital"),
}

# (a, b, off-peak minutes, road class)
EDGES: list[tuple[str, str, float, str]] = [
    ("Ambulance Base (Kalamassery)", "Edappally", 8, "highway"),
    ("Ambulance Base (Kalamassery)", "Kakkanad", 14, "arterial"),
    ("Edappally", "Palarivattom", 6, "highway"),
    ("Edappally", "Amrita Hospital", 4, "arterial"),
    ("Amrita Hospital", "Aster Medcity", 6, "arterial"),
    ("Aster Medcity", "Ernakulam North", 12, "arterial"),
    ("Palarivattom", "Kaloor", 5, "city"),
    ("Palarivattom", "Vyttila", 9, "highway"),
    ("Palarivattom", "Kakkanad", 12, "arterial"),
    ("Kaloor", "Ernakulam North", 5, "city"),
    ("Kaloor", "Kadavanthra", 7, "city"),
    ("Ernakulam North", "MG Road", 6, "city"),
    ("Ernakulam North", "General Hospital Ernakulam", 5, "city"),
    ("MG Road", "General Hospital Ernakulam", 3, "city"),
    ("MG Road", "Medical Trust Hospital", 3, "city"),
    ("MG Road", "Kadavanthra", 6, "city"),
    ("Kadavanthra", "Medical Trust Hospital", 4, "city"),
    ("Kadavanthra", "Vyttila", 6, "city"),
    ("Vyttila", "Kakkanad", 13, "arterial"),
    ("Vyttila", "Thrippunithura", 9, "highway"),
    ("Vyttila", "Lakeshore Hospital", 8, "highway"),
    ("Thrippunithura", "Lakeshore Hospital", 10, "arterial"),
]

# time slot -> multiplier per road class (synthetic, illustrative)
TRAFFIC: dict[str, dict[str, float]] = {
    "Night (11 PM)": {"highway": 0.8, "arterial": 0.8, "city": 0.8},
    "Off-peak (2 PM)": {"highway": 1.0, "arterial": 1.1, "city": 1.2},
    "Morning peak (9 AM)": {"highway": 2.0, "arterial": 1.6, "city": 1.5},
    "Evening peak (6 PM)": {"highway": 1.6, "arterial": 1.5, "city": 2.1},
}
SLOTS = list(TRAFFIC)


def build_graph(slot: str, blocked: set[frozenset[str]] | None = None) -> nx.Graph:
    """Road graph whose edge weight is traffic-adjusted minutes for `slot`."""
    blocked = blocked or set()
    g = nx.Graph()
    for name, (lat, lon, kind) in NODES.items():
        g.add_node(name, lat=lat, lon=lon, kind=kind)
    mult = TRAFFIC[slot]
    for a, b, base, cls in EDGES:
        if frozenset((a, b)) in blocked:
            continue
        g.add_edge(a, b, minutes=round(base * mult[cls], 2), base=base, cls=cls)
    return g


def travel_matrix(g: nx.Graph, points: list[str]):
    """All-pairs shortest travel time (minutes) and paths between `points` (Dijkstra)."""
    times: dict[tuple[str, str], float] = {}
    paths: dict[tuple[str, str], list[str]] = {}
    for a in points:
        dist, path = nx.single_source_dijkstra(g, a, weight="minutes")
        for b in points:
            if b not in dist:
                raise ValueError(f"No road from {a} to {b} (blocked?)")
            times[(a, b)] = round(dist[b], 2)
            paths[(a, b)] = path[b]
    return times, paths
