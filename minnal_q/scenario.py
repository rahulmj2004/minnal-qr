"""Scenario definition and exact route evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_LABEL = {1: "Minor", 2: "Moderate", 3: "Serious", 4: "Critical"}
SEVERITY_WEIGHT = {1: 1, 2: 2, 3: 4, 4: 8}


@dataclass
class Incident:
    location: str
    severity: int  # 1..4

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHT[self.severity]

    @property
    def label(self) -> str:
        return f"{self.location} ({SEVERITY_LABEL[self.severity]})"


@dataclass
class Scenario:
    base: str
    hospital: str
    incidents: list[Incident]
    slot: str
    times: dict = field(default_factory=dict)  # (a, b) -> minutes, filled by city.travel_matrix
    paths: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.incidents)


@dataclass
class RouteResult:
    order: tuple[int, ...]           # incident indices in visiting order
    total_time: float                # base -> ... -> hospital, minutes
    arrivals: list[float]            # arrival minute at each incident, indexed by incident
    weighted_arrival: float          # sum_i w_i * arrival_i (exact, lower is better)
    critical_arrival: float          # arrival time of the highest-severity patient


def evaluate(sc: Scenario, order) -> RouteResult:
    """Exact metrics for a visiting order. Time-to-patient = first medical contact."""
    t, prev = 0.0, sc.base
    arrivals = [0.0] * sc.n
    for i in order:
        loc = sc.incidents[i].location
        t += sc.times[(prev, loc)]
        arrivals[i] = round(t, 2)
        prev = loc
    total = t + sc.times[(prev, sc.hospital)]
    weighted = sum(sc.incidents[i].weight * arrivals[i] for i in range(sc.n))
    top = max(range(sc.n), key=lambda i: sc.incidents[i].severity)
    return RouteResult(tuple(order), round(total, 2), arrivals, round(weighted, 2), arrivals[top])


def route_label(sc: Scenario, order) -> str:
    return " → ".join(["Base"] + [sc.incidents[i].location for i in order] + [sc.hospital])
