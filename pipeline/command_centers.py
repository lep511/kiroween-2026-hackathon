"""Assault Vector targets.

Awakened Machines strike toward "command centers" — a small fixed set of major
world hubs — so every arc has somewhere to point without inventing victim PII.
The target is chosen deterministically from the source location so the globe is
stable across renders of the same report.
"""

from __future__ import annotations

# (name, lat, lon) — major connectivity / population hubs.
COMMAND_CENTERS: list[tuple[str, float, float]] = [
    ("Ashburn", 39.0438, -77.4874),
    ("London", 51.5074, -0.1278),
    ("Frankfurt", 50.1109, 8.6821),
    ("Singapore", 1.3521, 103.8198),
    ("Tokyo", 35.6762, 139.6503),
    ("Sao Paulo", -23.5505, -46.6333),
    ("Sydney", -33.8688, 151.2093),
    ("Mumbai", 19.0760, 72.8777),
    ("Cape Town", -33.9249, 18.4241),
    ("Silicon Valley", 37.3875, -122.0575),
]


def pick_target(lat: float, lon: float) -> tuple[float, float]:
    """Deterministically map a source location to a command-center target."""
    # Simple stable hash of the coarse grid cell -> index.
    key = int(round(lat)) * 1000 + int(round(lon))
    name, tlat, tlon = COMMAND_CENTERS[key % len(COMMAND_CENTERS)]
    return tlat, tlon
