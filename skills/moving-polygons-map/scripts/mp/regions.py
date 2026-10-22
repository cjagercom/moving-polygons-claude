"""Region expressions -> shapely geometry (lon/lat).

An expression is one of:
  "name"                      a named region from scenario["regions"]
  "admin0:FRA" "admin1:Lombardia/ITA" "clio:Roman Empire"   shorthands
  [expr, expr, ...]           union
  {"admin0": "FRA" | [...]}
  {"admin1": "Lombardia" | [...], "country": "ITA"}
  {"clio": "Kingdom of Sardinia", "year": 1859, "window": 10, "coast_km": 8}
                              (year defaults to the keyframe's; coast_km pulls the coarse outline out to the real coast)
  {"snap": expr, "to": "admin1" | "admin0", "min_share": 0.5}   whole admin units mostly inside expr
  {"poly": [[lon, lat], ...]}
  {"bbox": [minlon, minlat, maxlon, maxlat]}
  {"circle": [lon, lat] | "Place", "radius_km": 5}
  {"disks": [[lon, lat] | "Place", ...], "radius_km": 25, "close_km": 10}
  {"line": [[lon, lat], ...], "width_km": 1.5, "smooth": true}
  {"formation": [lon, lat] | "Place", "width_km": 2, "depth_km": 0.5, "facing": 180, "rounding": 0.3}
  {"arrow": [[lon, lat], ...], "width_km": 0.8, "head_km": 2, "head_width_km": 2.2, "progress": 1}
  {"side": expr, "line": [[lon, lat], ...] | {"river": "Rhine"}, "keep": "left" | "right" | [lon, lat] | "Place"}
  {"union": [...]}  {"minus": [a, b, ...]}  {"intersect": [...]}
  {"buffer": expr, "km": 5}   {"hull": expr, "buffer_km": 0}
  {"ref": "name"}   {"all": true} (the whole build domain)
  {"file": "ohm/prussia_1850.geojson"}   union of the polygons in a GeoJSON file (path relative
                              to the working directory), e.g. OpenHistoricalMap borders
"""

from __future__ import annotations

import json
from typing import Any

import shapely
from shapely.geometry import LineString, Polygon, box

from . import data, geo

EMPTY = Polygon()


class RegionError(ValueError):
    pass


class Context:
    def __init__(self, named: dict[str, Any], bbox, domain_fn, clio_coast_km: float = 0.0):
        self.named = named
        self.bbox = bbox
        self.frame = box(*bbox)
        self.domain_fn = domain_fn  # lazily computed build domain
        self.clio_coast_km = clio_coast_km
        self._bands: dict[float, Any] = {}
        self.year: float | None = None
        self.progress_scale = 1.0  # < 1 turns arrows into stubs
        self._cache: dict[str, Any] = {}
        self._stack: list[str] = []

    def coast_band(self, km: float):
        """Land within `km` of the real coastline (bbox edges are not coast)."""
        if km not in self._bands:
            land = data.land_in(_grown(self.bbox, 0.1))
            coast = land.boundary.difference(box(*_grown(self.bbox, 0.1)).boundary.buffer(1e-6))
            self._bands[km] = land.intersection(_buffer_km(coast, km)) if not coast.is_empty else EMPTY
        return self._bands[km]

    def eval(self, expr, *, year: float | None = None, progress_scale: float = 1.0):
        self.year = year
        self.progress_scale = progress_scale
        key = json.dumps(expr, sort_keys=True) + f"|{year if _uses_year(expr, self.named) else ''}|{progress_scale}"
        if key not in self._cache:
            g = _eval(expr, self)
            g = polygonal(g)
            self._cache[key] = g
        return self._cache[key]


_FILES: dict[str, Any] = {}


def _file_shape(path: str):
    if path not in _FILES:
        try:
            doc = json.loads(open(path, encoding="utf8").read())
        except OSError as e:
            raise RegionError(f"file region: cannot read {path}: {e}") from e
        feats = doc.get("features", [doc] if doc.get("type") == "Feature" else [])
        geoms = [shapely.geometry.shape(f["geometry"]) for f in feats if f.get("geometry")]
        if doc.get("type") in ("Polygon", "MultiPolygon"):
            geoms = [shapely.geometry.shape(doc)]
        _FILES[path] = polygonal(shapely.make_valid(shapely.union_all(geoms))) if geoms else EMPTY
    return _FILES[path]


def _uses_year(expr, named, seen=None) -> bool:
    seen = seen or set()
    if isinstance(expr, str):
        if expr.startswith("clio:"):
            return True
        if expr in named and expr not in seen:
            seen.add(expr)
            return _uses_year(named[expr], named, seen)
        return False
    if isinstance(expr, list):
        return any(_uses_year(e, named, seen) for e in expr)
    if isinstance(expr, dict):
        if "clio" in expr and "year" not in expr:
            return True
        if "ref" in expr:
            return _uses_year(expr["ref"], named, seen)
        return any(_uses_year(v, named, seen) for v in expr.values() if isinstance(v, (list, dict, str)))
    return False


def polygonal(g):
    """Only the (Multi)Polygon part: clipping can return GeometryCollections with stray lines."""
    if g is None or g.is_empty:
        return EMPTY
    if not g.is_valid:
        g = shapely.make_valid(g)
    if isinstance(g, (shapely.Polygon, shapely.MultiPolygon)):
        return g
    polys = [p for p in shapely.get_parts(g) if isinstance(p, (shapely.Polygon, shapely.MultiPolygon))]
    return shapely.union_all(polys) if polys else EMPTY


def point(p, what="point", bbox=None) -> tuple[float, float]:
    if isinstance(p, str):
        try:
            return data.place_point(p, bbox)
        except KeyError as e:
            raise RegionError(str(e).strip('"')) from None
    if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p):
        lon, lat = float(p[0]), float(p[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise RegionError(f"{what} {p} out of range — coordinates are [lon, lat]")
        return lon, lat
    raise RegionError(f"bad {what} {p!r}: use [lon, lat] or a place name")


def points(ps, what="points", bbox=None) -> list[tuple[float, float]]:
    if not isinstance(ps, list) or not ps:
        raise RegionError(f"{what} must be a non-empty list")
    return [point(p, what, bbox) for p in ps]


def _num(expr: dict, key: str, default=None) -> float:
    v = expr.get(key, default)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise RegionError(f"{key} must be a number in {json.dumps(expr)[:120]}")
    return float(v)


def _cut_line(spec, ctx: Context) -> LineString:
    if isinstance(spec, dict) and "river" in spec:
        try:
            g = data.river_line(spec["river"], _grown(ctx.bbox, 0.5))
        except KeyError as e:
            raise RegionError(str(e)) from None
        if isinstance(g, shapely.MultiLineString):
            g = max(g.geoms, key=lambda l: l.length)  # main stem
        if g.is_empty:
            raise RegionError(f"river {spec['river']!r} is not inside the bbox")
        return g
    return LineString(points(spec, "line", ctx.bbox))


def _grown(bbox, f: float):
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return (bbox[0] - w * f, bbox[1] - h * f, bbox[2] + w * f, bbox[3] + h * f)


def _eval(expr, ctx: Context):
    if expr is None:
        return EMPTY
    if isinstance(expr, str):
        if expr.startswith("admin0:"):
            return _eval({"admin0": expr[7:]}, ctx)
        if expr.startswith("admin1:"):
            return _eval({"admin1": expr[7:]}, ctx)
        if expr.startswith("clio:"):
            return _eval({"clio": expr[5:]}, ctx)
        return _eval({"ref": expr}, ctx)
    if isinstance(expr, list):
        return shapely.union_all([polygonal(_eval(e, ctx)) for e in expr]) if expr else EMPTY
    if not isinstance(expr, dict):
        raise RegionError(f"bad region expression {expr!r}")

    try:
        if "ref" in expr:
            name = expr["ref"]
            if name not in ctx.named:
                raise RegionError(f"unknown region {name!r} (define it under scenario.regions)")
            if name in ctx._stack:
                raise RegionError(f"region {name!r} refers to itself")
            ctx._stack.append(name)
            try:
                return _eval(ctx.named[name], ctx)
            finally:
                ctx._stack.pop()
        # compound operators first: "side" also carries a "line" key
        if "side" in expr:
            base = polygonal(_eval(expr["side"], ctx))
            if base.is_empty:
                return EMPTY
            keep = expr.get("keep", "left")
            if not (keep in ("left", "right")):
                keep = point(keep, "keep", ctx.bbox)
            frame = box(*_grown(base.bounds, 0.05)).union(box(*ctx.bbox))
            frame = box(*frame.bounds)
            return base.intersection(geo.half_plane(_cut_line(expr["line"], ctx), keep, frame))
        if "all" in expr:
            return ctx.domain_fn()
        if "admin0" in expr:
            codes = expr["admin0"] if isinstance(expr["admin0"], list) else [expr["admin0"]]
            return shapely.union_all([data.admin0_shape(c) for c in codes])
        if "admin1" in expr:
            names = expr["admin1"] if isinstance(expr["admin1"], list) else [expr["admin1"]]
            return shapely.union_all([data.admin1_shape(n, expr.get("country")) for n in names])
        if "file" in expr:
            return _file_shape(expr["file"])
        if "clio" in expr:
            year = expr.get("year", ctx.year)
            if year is None:
                raise RegionError("clio needs a year")
            names = expr["clio"] if isinstance(expr["clio"], list) else [expr["clio"]]
            g = shapely.union_all([data.clio_shape(n, float(year), float(expr.get("window", 0))) for n in names])
            # Cliopatria outlines are coarse and often stop short of the coast: pull them out to it
            km = float(expr.get("coast_km", ctx.clio_coast_km))
            if km > 0 and not g.is_empty:
                g = g.union(polygonal(_buffer_km(g, km).intersection(ctx.coast_band(km))))
            return g
        if "snap" in expr:
            g = polygonal(_eval(expr["snap"], ctx))
            level = expr.get("to", "admin1")
            fs = data.admin1() if level == "admin1" else data.admin0() if level == "admin0" else None
            if fs is None:
                raise RegionError("snap 'to' must be admin1 or admin0")
            share = float(expr.get("min_share", 0.5))
            idx = fs.tree.query(g, predicate="intersects")
            keep = [fs.geoms[i] for i in idx
                    if fs.geoms[i].area > 0 and fs.geoms[i].intersection(g).area / fs.geoms[i].area >= share]
            return shapely.union_all(keep) if keep else EMPTY
        if "poly" in expr:
            pts = points(expr["poly"], "poly", ctx.bbox)
            if len(pts) < 3:
                raise RegionError("poly needs at least 3 points")
            return shapely.make_valid(Polygon(pts))
        if "bbox" in expr:
            b = expr["bbox"]
            return box(*b)
        if "circle" in expr:
            return geo.circle(point(expr["circle"], "circle", ctx.bbox), _num(expr, "radius_km"))
        if "disks" in expr:
            return geo.disks(points(expr["disks"], "disks", ctx.bbox), _num(expr, "radius_km"), _num(expr, "close_km", 0))
        if "line" in expr:
            return geo.thick_line(points(expr["line"], "line", ctx.bbox), _num(expr, "width_km"), bool(expr.get("smooth", True)))
        if "formation" in expr:
            return geo.formation(point(expr["formation"], "formation", ctx.bbox), _num(expr, "width_km"),
                                 _num(expr, "depth_km"), _num(expr, "facing", 0), _num(expr, "rounding", 0.3))
        if "arrow" in expr:
            pts = points(expr["arrow"], "arrow", ctx.bbox)
            if len(pts) < 2:
                raise RegionError("arrow needs at least 2 points")
            prog = _num(expr, "progress", 1.0) * ctx.progress_scale
            return geo.arrow(pts, _num(expr, "width_km"), expr.get("head_km"), expr.get("head_width_km"),
                             prog, bool(expr.get("smooth", True)))
        if "union" in expr:
            return _eval(list(expr["union"]), ctx)
        if "minus" in expr:
            items = expr["minus"]
            if not isinstance(items, list) or not items:
                raise RegionError("minus needs [base, subtract, ...]")
            g = polygonal(_eval(items[0], ctx))
            for e in items[1:]:
                g = g.difference(polygonal(_eval(e, ctx)))
            return g
        if "intersect" in expr:
            items = expr["intersect"]
            g = polygonal(_eval(items[0], ctx))
            for e in items[1:]:
                g = g.intersection(polygonal(_eval(e, ctx)))
            return g
        if "buffer" in expr:
            return _buffer_km(polygonal(_eval(expr["buffer"], ctx)), _num(expr, "km"))
        if "hull" in expr:
            h = expr["hull"]
            is_points = isinstance(h, list) and h and all(
                isinstance(p, list) or (isinstance(p, str) and p not in ctx.named) for p in h
            )
            g = shapely.MultiPoint(points(h, "hull", ctx.bbox)).convex_hull if is_points else polygonal(_eval(h, ctx)).convex_hull
            return _buffer_km(g, float(expr.get("buffer_km", 0)))
    except KeyError as e:
        raise RegionError(str(e).strip('"')) from None
    raise RegionError(f"unknown region type in {json.dumps(expr)[:160]}")


def _buffer_km(g, km: float):
    if g.is_empty or not km:
        return g
    c = g.centroid
    proj = geo.LocalProj(c.x, c.y)
    return proj.inv(shapely.transform(g, proj.fwd_pts).buffer(km, quad_segs=8))
