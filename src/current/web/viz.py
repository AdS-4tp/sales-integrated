"""Geometry for the living stream: a band that narrows stage by stage.

Pure functions, so the shape can be tested without a browser. The viewBox is
1200 x 260; stage centres sit at x = 100, 300, ... 1100 so HTML labels in a
six-column grid line up underneath.
"""
from __future__ import annotations

from math import sqrt

XS = [0, 100, 300, 500, 700, 900, 1100, 1200]
MID = 130.0
MAX_HALF = 100.0
MIN_HALF = 2.0


def _halves(counts: list[int]) -> list[float]:
    top = max(counts) or 1
    # sqrt keeps small late stages visible next to a large first stage
    return [max(MIN_HALF, MAX_HALF * sqrt(c / top)) for c in counts]


def _curve(x0: float, y0: float, x1: float, y1: float) -> str:
    if y0 == y1:
        return f"L{x1:g},{y1:.1f}"
    mx = (x0 + x1) / 2
    return f"C{mx:g},{y0:.1f} {mx:g},{y1:.1f} {x1:g},{y1:.1f}"


def _edge(ys: list[float]) -> str:
    return " ".join(_curve(XS[i - 1], ys[i - 1], XS[i], ys[i]) for i in range(1, len(XS)))


def _edge_back(ys: list[float]) -> str:
    return " ".join(_curve(XS[i], ys[i], XS[i - 1], ys[i - 1]) for i in range(len(XS) - 1, 0, -1))


def stream(counts: list[int]) -> dict:
    """counts: six stage values. Returns SVG path data for the band and three particle lanes."""
    if len(counts) != 6:
        raise ValueError("expected six stage counts")
    h = _halves(counts)
    pts = [h[0], h[0], *h[1:], h[-1]]  # one per x in XS
    top = [MID - p for p in pts]
    bot = [MID + p for p in pts]
    band = f"M0,{top[0]:.1f} {_edge(top)} L1200,{bot[-1]:.1f} {_edge_back(bot)} Z"
    lanes = []
    for name, t in (("a", 0.25), ("b", 0.5), ("c", 0.75)):
        ys = [a + t * (b - a) for a, b in zip(top, bot)]
        lanes.append({"id": name, "d": f"M0,{ys[0]:.1f} {_edge(ys)}"})
    return {"band": band, "lanes": lanes}


# (lane id, seconds per pass, negative start offset, radius): desynchronised particles
PARTICLES = [
    ("a", 11, 1, 3), ("a", 11, 4, 2.5), ("a", 11, 7, 3), ("a", 11, 9.5, 2),
    ("b", 9, 0.5, 3.5), ("b", 9, 3, 2.5), ("b", 9, 5.5, 3), ("b", 9, 7.5, 2),
    ("c", 12, 2, 3), ("c", 12, 5, 2.5), ("c", 12, 8, 3), ("c", 12, 10.5, 2),
]
