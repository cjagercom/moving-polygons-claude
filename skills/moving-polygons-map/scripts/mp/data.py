"""Bundled geodata (skills/moving-polygons-map/data/), loaded lazily.

- admin1 / admin0 / land: Natural Earth 10m, simplified topology-aware; admin0
  and land are dissolved from admin1 so all three share border vertices.
- lakes, rivers: Natural Earth 10m (context + river cut lines).
- cliopatria: historical polity borders 3400 BC – 2024 (quantized TopoJSON).
- places: GeoNames cities1000 (+ a few Latin-script alternate names).
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import box, shape

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _open(name: str):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"missing bundled data {path} — in the repo run `npm run skill:data`; "
            "on claude.ai re-upload the skill zip (it must contain data/)"
        )
    return gzip.open(path, "rt", encoding="utf8")


def norm(s: str) -> str:
    """Accent/case/punctuation-insensitive key: 'Île-de-France' -> 'ile de france'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s).strip().lower()
    return s


def _valid(g):
    if g is None or g.is_empty:
        return g
    return g if g.is_valid else shapely.make_valid(g)


class FeatureSet:
    """Polygon/line features with properties and a spatial index."""

    def __init__(self, features: list[dict[str, Any]]):
        self.props = [f.get("properties") or {} for f in features]
        self.geoms = np.array([_valid(shape(f["geometry"])) for f in features], dtype=object)
        self.tree = shapely.STRtree(self.geoms)

    def query_bbox(self, bbox) -> np.ndarray:
        return self.tree.query(box(*bbox))

    def containing(self, lon: float, lat: float) -> list[int]:
        pt = shapely.Point(lon, lat)
        return [int(i) for i in self.tree.query(pt, predicate="intersects")]


def _load_geojson(name: str) -> FeatureSet:
    with _open(name) as f:
        return FeatureSet(json.load(f)["features"])


@lru_cache(maxsize=None)
def admin1() -> FeatureSet:
    return _load_geojson("admin1.geojson.gz")


@lru_cache(maxsize=None)
def admin0() -> FeatureSet:
    return _load_geojson("admin0.geojson.gz")


@lru_cache(maxsize=None)
def land() -> FeatureSet:
    return _load_geojson("land.geojson.gz")


@lru_cache(maxsize=None)
def lakes() -> FeatureSet:
    return _load_geojson("lakes.geojson.gz")


@lru_cache(maxsize=None)
def rivers() -> FeatureSet:
    return _load_geojson("rivers.geojson.gz")


def land_in(bbox) -> shapely.Geometry:
    """Land polygons clipped to bbox."""
    fs = land()
    frame = box(*bbox)
    idx = fs.query_bbox(bbox)
    if len(idx) == 0:
        return shapely.Polygon()
    parts = shapely.intersection(fs.geoms[idx], frame)
    parts = [q for g in parts for q in shapely.get_parts(g) if isinstance(q, (shapely.Polygon, shapely.MultiPolygon))]
    return shapely.union_all(parts) if parts else shapely.Polygon()


# --- admin units -------------------------------------------------------------

def _admin0_lookup() -> dict[str, list[int]]:
    fs = admin0()
    out: dict[str, list[int]] = {}
    for i, p in enumerate(fs.props):
        for key in (p.get("adm0_a3"), p.get("admin")):
            if key:
                out.setdefault(norm(key), []).append(i)
    return out


_A0: dict[str, list[int]] | None = None


def admin0_shape(code_or_name: str):
    global _A0
    if _A0 is None:
        _A0 = _admin0_lookup()
    idx = _A0.get(norm(code_or_name))
    if not idx:
        raise KeyError(f"admin0 {code_or_name!r} not found (use ISO3 like 'FRA' or the NE country name; try lookup.py admin0)")
    return shapely.union_all(admin0().geoms[idx])


def admin1_matches(query: str, country: str | None = None) -> list[int]:
    """adm1_code ('ITA-1234'), ISO 3166-2 ('IT-25'), name / English / alternate name, or the
    NE region the unit belongs to ('Veneto' selects all its provinces)."""
    fs = admin1()
    q = norm(query)
    c = norm(country) if country else None
    hits = []
    for i, p in enumerate(fs.props):
        if c and c not in (norm(p.get("adm0_a3", "")), norm(p.get("admin", ""))):
            continue
        keys = [p.get("adm1_code"), p.get("iso_3166_2"), p.get("name"), p.get("name_en"), p.get("region")]
        keys += (p.get("name_alt") or "").split("|")
        if any(k and norm(k) == q for k in keys):
            hits.append(i)
    return hits


def admin1_shape(query: str, country: str | None = None):
    if "/" in query and not country:  # "Lombardia/ITA" shorthand
        query, country = query.rsplit("/", 1)
    hits = admin1_matches(query, country)
    if not hits:
        raise KeyError(f"admin1 {query!r}{' in ' + country if country else ''} not found (try lookup.py admin1)")
    codes = {admin1().props[i].get("adm0_a3") for i in hits}
    if len(codes) > 1:
        raise KeyError(f"admin1 {query!r} is ambiguous across {sorted(codes)} — add country")
    return shapely.union_all(admin1().geoms[hits])


# --- rivers --------------------------------------------------------------------

def river_line(name: str, bbox=None):
    fs = rivers()
    q = norm(name)
    idx = [i for i, p in enumerate(fs.props) if q in (norm(p.get("name") or ""), norm(p.get("name_en") or ""))]
    if not idx:
        raise KeyError(f"river {name!r} not found (try lookup.py river)")
    lines = shapely.union_all(fs.geoms[idx])
    if bbox is not None:
        lines = lines.intersection(box(*bbox))
    return shapely.line_merge(lines)


# --- Cliopatria (TopoJSON) ------------------------------------------------------

class Topology:
    def __init__(self, topo: dict):
        t = topo.get("transform")
        self.scale = np.array(t["scale"]) if t else None
        self.translate = np.array(t["translate"]) if t else None
        self.raw_arcs = topo["arcs"]
        self._arcs: dict[int, np.ndarray] = {}
        obj = next(iter(topo["objects"].values()))
        self.geometries = obj["geometries"]

    def arc(self, i: int) -> np.ndarray:
        j = ~i if i < 0 else i
        a = self._arcs.get(j)
        if a is None:
            a = np.array(self.raw_arcs[j], dtype=float)
            if self.scale is not None:
                a = np.cumsum(a, axis=0) * self.scale + self.translate
            self._arcs[j] = a
        return a[::-1] if i < 0 else a

    def ring(self, arc_ids: list[int]) -> np.ndarray:
        parts = []
        for k, i in enumerate(arc_ids):
            a = self.arc(i)
            parts.append(a if k == 0 else a[1:])
        return np.vstack(parts)

    def geometry(self, g: dict):
        if g.get("type") == "Polygon":
            polys = [g["arcs"]]
        elif g.get("type") == "MultiPolygon":
            polys = g["arcs"]
        else:
            return shapely.Polygon()
        out = []
        for rings in polys:
            coords = [self.ring(r) for r in rings]
            coords = [c for c in coords if len(c) >= 4]
            if coords:
                out.append(shapely.Polygon(coords[0], coords[1:]))
        return _valid(shapely.MultiPolygon(out) if len(out) != 1 else out[0]) if out else shapely.Polygon()


@lru_cache(maxsize=None)
def clio() -> Topology:
    with _open("cliopatria.topojson.gz") as f:
        return Topology(json.load(f))


@lru_cache(maxsize=None)
def clio_index() -> list[tuple[str, str, int, int, int]]:
    """(normalised name, name, from year, to year, geometry index)."""
    out = []
    for i, g in enumerate(clio().geometries):
        p = g.get("properties") or {}
        name = p.get("Name") or ""
        out.append((norm(name), name, int(p.get("FromYear", -9999)), int(p.get("ToYear", 9999)), i))
    return out


def clio_records(name: str) -> list[tuple[str, int, int, int]]:
    q = norm(name)
    return [(n, a, b, i) for (k, n, a, b, i) in clio_index() if k == q]


def clio_shape(name: str, year: float, window: float = 0):
    """Union of the polity's Cliopatria polygons valid at `year` (or the nearest record within `window` years)."""
    recs = clio_records(name)
    if not recs:
        raise KeyError(f"Cliopatria polity {name!r} not found (names are exact, e.g. 'Roman Empire'; try lookup.py clio)")
    y = int(year)
    exact = [i for (_, a, b, i) in recs if a <= y <= b]
    if not exact:
        dist = [(min(abs(y - a), abs(y - b)), i, a, b) for (_, a, b, i) in recs]
        dist.sort()
        best = dist[0]
        if best[0] > window:
            spans = ", ".join(f"{a}..{b}" for (_, _, a, b) in sorted(dist, key=lambda d: d[2])[:12])
            raise KeyError(f"Cliopatria {name!r} has no record for {y} (records: {spans}); set a 'window' or pick another year")
        exact = [i for (d, i, _, _) in dist if d == best[0]]
    topo = clio()
    return shapely.union_all([topo.geometry(topo.geometries[i]) for i in exact])


def clio_at_point(lon: float, lat: float, year: float) -> list[str]:
    topo = clio()
    pt = shapely.Point(lon, lat)
    y = int(year)
    names = []
    for (_, n, a, b, i) in clio_index():
        if a <= y <= b:
            g = topo.geometry(topo.geometries[i])
            if g.intersects(pt):
                names.append(n)
    return names


# --- places --------------------------------------------------------------------

@lru_cache(maxsize=None)
def places() -> dict[str, Any]:
    names, lat, lon, country, admin1c, pop, fcode, keys = [], [], [], [], [], [], [], {}
    with _open("places.tsv.gz") as f:
        reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\")
        next(reader)
        for i, row in enumerate(reader):
            name, ascii_name, alt, la, lo, cc, a1, p, fc = row
            names.append(name)
            lat.append(float(la))
            lon.append(float(lo))
            country.append(cc)
            admin1c.append(a1)
            pop.append(int(p))
            fcode.append(fc)
            for k in {norm(name), norm(ascii_name) if ascii_name else "", *(norm(a) for a in alt.split("|") if a)}:
                if k:
                    keys.setdefault(k, []).append(i)
    return {"name": names, "lat": lat, "lon": lon, "country": country, "admin1": admin1c,
            "pop": pop, "fcode": fcode, "keys": keys}


def find_places(query: str, country: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    P = places()
    q = query
    if country is None and "," in query:  # "Waterloo, BE"
        q, country = (s.strip() for s in query.rsplit(",", 1))
    idx = P["keys"].get(norm(q), [])
    if country:
        cc = country.upper()
        idx = [i for i in idx if P["country"][i] == cc]
    idx = sorted(set(idx), key=lambda i: -P["pop"][i])[:limit]
    return [{"name": P["name"][i], "lon": P["lon"][i], "lat": P["lat"][i], "country": P["country"][i],
             "admin1": P["admin1"][i], "pop": P["pop"][i], "fcode": P["fcode"][i]} for i in idx]


def near_bbox(bbox, lon: float, lat: float, grow: float = 0.5) -> bool:
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return bbox[0] - w * grow <= lon <= bbox[2] + w * grow and bbox[1] - h * grow <= lat <= bbox[3] + h * grow


def place_point(query: str, bbox=None) -> tuple[float, float]:
    """Largest gazetteer match — within (or near) the map's bbox when one is given, so
    'Austerlitz' in a Moravian battle doesn't resolve to the Dutch village."""
    hits = find_places(query, limit=200)
    if not hits:
        raise KeyError(f"place {query!r} not in the gazetteer — use [lon, lat] (from web research) instead")
    if bbox is None:
        return hits[0]["lon"], hits[0]["lat"]
    near = [h for h in hits if near_bbox(bbox, h["lon"], h["lat"])]
    if not near:
        h = hits[0]
        raise KeyError(f"place {query!r} only matches places far outside the map area "
                       f"(e.g. {h['name']}, {h['country']} [{h['lon']:.3f}, {h['lat']:.3f}]) — use [lon, lat] instead")
    return near[0]["lon"], near[0]["lat"]
