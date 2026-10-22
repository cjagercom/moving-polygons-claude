"""Shapes measured in kilometres (circles, lines, formations, arrows) and cuts.

Shapes are built in a local equirectangular projection around their own
centre (accurate to ~1% over a few hundred km) and converted back to lon/lat.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import split, substring

KM_PER_DEG_LAT = 110.574


def km_per_deg_lon(lat: float) -> float:
    return max(111.320 * math.cos(math.radians(lat)), 1e-6)


def km2_per_deg2(lat: float) -> float:
    return km_per_deg_lon(lat) * KM_PER_DEG_LAT


class LocalProj:
    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = lon0, lat0
        self.kx, self.ky = km_per_deg_lon(lat0), KM_PER_DEG_LAT

    def fwd_pts(self, pts) -> np.ndarray:
        a = np.asarray(pts, dtype=float)
        return np.column_stack(((a[:, 0] - self.lon0) * self.kx, (a[:, 1] - self.lat0) * self.ky))

    def inv(self, geom):
        return shapely.transform(
            geom, lambda c: np.column_stack((c[:, 0] / self.kx + self.lon0, c[:, 1] / self.ky + self.lat0))
        )


def _proj_for(pts) -> LocalProj:
    a = np.asarray(pts, dtype=float)
    return LocalProj(float(a[:, 0].mean()), float(a[:, 1].mean()))


def smooth(pts: np.ndarray, samples: int = 10) -> np.ndarray:
    """Catmull-Rom through the waypoints (kept exactly)."""
    if len(pts) < 3:
        return pts
    P = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, samples, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(pts[-1])
    return np.array(out)


def circle(center, radius_km: float):
    proj = LocalProj(*center)
    return proj.inv(Point(0, 0).buffer(radius_km, quad_segs=16))


def disks(points, radius_km: float, close_km: float = 0.0):
    """Union of disks; `close_km` bridges gaps up to ~2x that (morphological closing)."""
    proj = _proj_for(points)
    xy = proj.fwd_pts(points)
    g = shapely.union_all([Point(x, y).buffer(radius_km, quad_segs=12) for x, y in xy])
    if close_km > 0:
        g = g.buffer(close_km, quad_segs=8).buffer(-close_km, quad_segs=8)
    return proj.inv(g)


LINE_SAMPLES = 48
SHAFT_SAMPLES = 32
CAP_SEGMENTS = 8


def _resample(line: LineString, n: int) -> np.ndarray:
    return np.array([line.interpolate(d).coords[0] for d in np.linspace(0, line.length, n)])


def _normals(center: np.ndarray) -> np.ndarray:
    t = np.gradient(center, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1), 1e-12)[:, None]
    return np.column_stack([-t[:, 1], t[:, 0]])


def _cap(center, normal, half: float, from_side: int) -> list:
    """Half circle from one side of the line end to the other, around the end point."""
    a0 = math.atan2(normal[1], normal[0]) if from_side > 0 else math.atan2(-normal[1], -normal[0])
    return [center + half * np.array([math.cos(a0 - math.pi * k / CAP_SEGMENTS), math.sin(a0 - math.pi * k / CAP_SEGMENTS)])
            for k in range(1, CAP_SEGMENTS)]


def _outline(center: np.ndarray, half: float, head=None):
    """Deterministic outline of a thick path: left side, end (cap or arrow head), right side
    back, start cap. Same sample count every time, so the same kind of shape at two keyframes
    has matching vertices and morphs cleanly (a stub arrow grows, a line slides)."""
    nrm = _normals(center)
    left = center + nrm * half
    right = center - nrm * half
    ring = list(left)
    ring += head if head is not None else _cap(center[-1], nrm[-1], half, +1)
    ring += list(right[::-1])
    ring += _cap(center[0], nrm[0], half, -1)
    poly = Polygon(ring)
    return poly if poly.is_valid else None


def thick_line(points, width_km: float, smooth_path: bool = True, cap: str = "round"):
    proj = _proj_for(points)
    xy = proj.fwd_pts(points)
    if smooth_path:
        xy = smooth(xy)
    line = LineString(xy)
    g = _outline(_resample(line, LINE_SAMPLES), width_km / 2) if line.length > 0 else None
    if g is None:  # sharp bends fold the offset sides over: fall back to a (valid) buffer
        g = line.buffer(width_km / 2, quad_segs=8, cap_style=cap, join_style="round")
    return proj.inv(g)


def formation(center, width_km: float, depth_km: float, facing_deg: float = 0.0, rounding: float = 0.3):
    """A unit block: `width_km` frontage across the facing direction, `depth_km` along it.
    facing is a compass bearing (0 = north, 90 = east)."""
    proj = LocalProj(*center)
    r = max(0.0, min(width_km, depth_km) * rounding / 2)
    rect = box(-width_km / 2 + r, -depth_km / 2 + r, width_km / 2 - r, depth_km / 2 - r)
    if r > 0:
        rect = rect.buffer(r, quad_segs=4)
    return proj.inv(affinity.rotate(rect, -facing_deg, origin=(0, 0)))


def arrow(path, width_km: float, head_km: float | None = None, head_width_km: float | None = None,
          progress: float = 1.0, smooth_path: bool = True):
    """Arrow polygon along a path. progress < 1 draws only the first part — a stub with the
    same vertex structure, which the app morphs into the full arrow (it grows along the path)."""
    proj = _proj_for(path)
    xy = proj.fwd_pts(path)
    if smooth_path:
        xy = smooth(xy)
    line = LineString(xy)
    progress = max(0.02, min(1.0, progress))
    if progress < 1:
        line = substring(line, 0, line.length * progress)
    L = line.length
    head_km = head_km if head_km is not None else width_km * 2.2
    head_width_km = head_width_km if head_width_km is not None else width_km * 2.4
    head_len = min(head_km, L * 0.6)
    scale = head_len / head_km if head_km > 0 else 1.0
    head_w = head_width_km * scale
    half = width_km * scale / 2
    shaft = substring(line, 0, max(L - head_len, L * 0.02))
    center = _resample(shaft, SHAFT_SAMPLES)
    tip = np.array(line.coords[-1])
    d = tip - center[-1]
    n = np.linalg.norm(d)
    d = d / n if n > 0 else np.array([0.0, 1.0])
    normal = np.array([-d[1], d[0]])
    head = [center[-1] + normal * head_w / 2, tip, center[-1] - normal * head_w / 2]
    g = _outline(center, half, head)
    if g is None:
        g = shapely.union_all([Polygon(head), shaft.buffer(half, quad_segs=4)])
        if isinstance(g, shapely.MultiPolygon):
            g = max(g.geoms, key=lambda q: q.area)
    return proj.inv(g)


def _extend(line: LineString, dist: float) -> LineString:
    c = np.asarray(line.coords, dtype=float)
    d0 = c[0] - c[1]
    d1 = c[-1] - c[-2]
    d0 = d0 / (np.linalg.norm(d0) or 1)
    d1 = d1 / (np.linalg.norm(d1) or 1)
    return LineString(np.vstack([c[0] + d0 * dist, c, c[-1] + d1 * dist]))


def _side_sign(pt: Point, line: LineString) -> float:
    c = np.asarray(line.coords, dtype=float)
    seg = np.diff(c, axis=0)
    lens = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0], np.cumsum(lens)])
    s = line.project(pt)
    i = int(np.clip(np.searchsorted(cum, s) - 1, 0, len(seg) - 1))
    v = seg[i]
    w = np.array([pt.x, pt.y]) - c[i]
    return float(v[0] * w[1] - v[1] * w[0])


def half_plane(line: LineString, keep, frame: Polygon):
    """The part of `frame` on one side of `line` (extended to cross the frame).
    keep = 'left' | 'right' (relative to the line's direction) or a (lon, lat)
    point that lies on the wanted side."""
    minx, miny, maxx, maxy = frame.bounds
    diag = math.hypot(maxx - minx, maxy - miny) * 2 + 1
    ext = _extend(line, diag)
    pieces = list(split(frame, ext).geoms)
    if len(pieces) < 2:
        raise ValueError("cut line does not cross the area — extend it or check coordinates")
    if isinstance(keep, str):
        want = 1 if keep == "left" else -1
        chosen = [p for p in pieces if _side_sign(p.representative_point(), ext) * want > 0]
    else:
        ref = Point(keep)
        ref_sign = _side_sign(ref, ext)
        chosen = [p for p in pieces if _side_sign(p.representative_point(), ext) * ref_sign > 0]
    return shapely.union_all(chosen) if chosen else Polygon()
