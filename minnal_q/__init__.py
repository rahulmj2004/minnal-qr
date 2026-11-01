"""Minnal-Q (മിന്നൽ): severity- and traffic-aware multi-stop ambulance routing with QAOA."""
from .city import SLOTS, build_graph, travel_matrix
from .scenario import Incident, Scenario, evaluate, route_label


def make_scenario(base, hospital, incidents, slot, blocked=None) -> Scenario:
    g = build_graph(slot, blocked)
    pts = [base, hospital] + [i.location for i in incidents]
    times, paths = travel_matrix(g, list(dict.fromkeys(pts)))
    return Scenario(base, hospital, incidents, slot, times, paths)


DEMO_INCIDENTS = {
    3: [("Edappally", 1), ("Ernakulam North", 2), ("Kakkanad", 4)],
    4: [("Edappally", 2), ("Palarivattom", 1), ("Ernakulam North", 1), ("Kakkanad", 4)],
}


def demo_scenario(slot: str = "Morning peak (9 AM)", n: int = 3) -> Scenario:
    """Mass-casualty demo: minor cases lie on the way, the critical patient is off to the east (Kakkanad)."""
    return make_scenario("Ambulance Base (Kalamassery)", "Lakeshore Hospital",
                         [Incident(l, s) for l, s in DEMO_INCIDENTS[n]], slot)
