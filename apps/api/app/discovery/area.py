"""Validated operator-supplied areas and the Overpass endpoint allowlist (P2.2).

A bounding box comes from explicit operator configuration with a citation; it
is never derived from a place name and never geocoded. The Pakistan envelope
below is a sanity check only (rejects typos like swapped signs or a
continent-sized box); it does not define any city boundary.
"""

import math
from dataclasses import dataclass

OVERPASS_ENDPOINTS = frozenset({"https://overpass-api.de/api/interpreter"})
MAX_SPAN_DEGREES = 0.6
_PAKISTAN_SANITY = (23.5, 60.5, 37.5, 78.0)  # south, west, north, east


class BBoxError(ValueError):
    pass


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    def overpass(self) -> str:
        return f"{self.south:.6f},{self.west:.6f},{self.north:.6f},{self.east:.6f}"


def parse_bbox(raw: str) -> BBox:
    parts = raw.split(",")
    if len(parts) != 4:
        raise BBoxError("bbox must be south,west,north,east")
    try:
        south, west, north, east = (float(p) for p in parts)
    except ValueError:
        raise BBoxError("bbox values must be numbers") from None
    if not all(math.isfinite(v) for v in (south, west, north, east)):
        raise BBoxError("bbox values must be finite")
    if not (south < north and west < east):
        raise BBoxError("bbox must have south < north and west < east")
    if north - south > MAX_SPAN_DEGREES or east - west > MAX_SPAN_DEGREES:
        raise BBoxError("bbox is too large for one bounded query")
    s, w, n, e = _PAKISTAN_SANITY
    if not (s <= south and north <= n and w <= west and east <= e):
        raise BBoxError("bbox is outside the configured sanity envelope")
    return BBox(south, west, north, east)
