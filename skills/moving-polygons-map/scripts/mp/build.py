"""Scenario spec -> importable Moving Polygons JSON.

Territory layers form one exclusive partition with shared borders:
  1. evaluate every layer's region at every keyframe (clipped to the domain)
  2. polygonize all region boundaries into faces ("atoms")
  3. give each face an owner per keyframe (later layers win overlaps)
  4. dissolve faces with the same owner history, fold slivers into neighbours
  5. simplify ONCE with shapely.coverage_simplify (shared edges stay identical)
  6. union per layer (and ring group) per keyframe
so neighbouring layers share bit-identical border vertices, which the app's
sharedBorders.ts morphs flush. Free layers (units, fleets, arrows, zones)
are evaluated per keyframe independently and drawn on top.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box
from shapely.ops import nearest_points

from . import data, dates, geo, pacing
from .regions import Context, RegionError, polygonal

SCALES: dict[str, dict[str, float]] = {
    # tolerance: coverage simplification; islands/holes/cells in km²; slit: width of the cut that opens a hole;
    # test_snap_km: a test place this close to a territory (e.g. a port on the simplified coast) counts as inside
    "battle": dict(tolerance_km=0.015, free_tolerance_km=0.008, decimals=5, min_island_km2=0.002,
                   min_hole_km2=0.02, min_cell_km2=0.001, slit_km=0.008, test_snap_km=0.03,
                   clio_coast_km=0),
    "campaign": dict(tolerance_km=0.4, free_tolerance_km=0.15, decimals=4, min_island_km2=1,
                     min_hole_km2=10, min_cell_km2=0.3, slit_km=0.2, test_snap_km=2,
                     clio_coast_km=4),
    "regional": dict(tolerance_km=1.0, free_tolerance_km=0.4, decimals=4, min_island_km2=8,
                     min_hole_km2=40, min_cell_km2=2, slit_km=0.5, test_snap_km=5,
                     clio_coast_km=8),
    "continental": dict(tolerance_km=3.0, free_tolerance_km=1.2, decimals=3, min_island_km2=80,
                        min_hole_km2=400, min_cell_km2=15, slit_km=1.5, test_snap_km=10,
                        clio_coast_km=15),
}
MAP_STYLES = {
    "light": "mapbox://styles/mapbox/light-v11",
    "dark": "mapbox://styles/mapbox/dark-v11",
    "streets": "mapbox://styles/mapbox/streets-v12",
    "outdoors": "mapbox://styles/mapbox/outdoors-v12",
    "satellite": "mapbox://styles/mapbox/satellite-v9",
    "satellite-streets": "mapbox://styles/mapbox/satellite-streets-v12",
    "vintage": "vintage",
    "vintage-soft": "vintage-soft",
    "tactical": "tactical",
    "dark-glow": "dark-glow",
    "tapestry": "tapestry",
}
SIZE_BUDGET = 3_300_000
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
STUB_PROGRESS = 0.14
FREE_SIMPLIFY_ABOVE = 600


class ScenarioError(ValueError):
    pass


@dataclass
class Keyframe:
    id: str
    when: dates.When
    label: str

    @property
    def ms(self) -> int:
        return self.when.ms


@dataclass
class Layer:
    id: str
    name: str
    color: str
    kind: str  # territory | free
    clip: str  # land | sea | none
    per_kf: list[dict | None]
    ring_groups: list[dict] = field(default_factory=list)


@dataclass
class BuildResult:
    doc: dict
    report: list[str]
    errors: list[str]
    warnings: list[str]
    tests: list[dict]
    keyframes: list[Keyframe]
    layers: list[Layer]
    params: dict


# --- scenario parsing -----------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "map"


def parse_keyframes(sc: dict) -> list[Keyframe]:
    raw = sc.get("keyframes")
    if not isinstance(raw, list) or len(raw) < 2:
        raise ScenarioError("scenario needs at least 2 keyframes")
    kfs = []
    for i, k in enumerate(raw):
        if not isinstance(k, dict) or "date" not in k:
            raise ScenarioError(f"keyframe #{i + 1} needs a date")
        try:
            when = dates.parse(k["date"])
        except ValueError as e:
            raise ScenarioError(f"keyframe #{i + 1}: {e}") from None
        label = str(k.get("label") or "").strip()
        if len(label) > 50:
            raise ScenarioError(f"keyframe {k.get('id', i + 1)} label is {len(label)} chars (max 50): {label!r}")
        kfs.append(Keyframe(str(k.get("id") or f"K{i + 1:02d}"), when, label))
    kfs.sort(key=lambda k: k.ms)
    seen: dict[int, str] = {}
    for k in kfs:
        if k.ms in seen:
            raise ScenarioError(f"keyframes {seen[k.ms]} and {k.id} have the same date/time")
        seen[k.ms] = k.id
    ids = [k.id for k in kfs]
    if len(set(ids)) != len(ids):
        raise ScenarioError("keyframe ids must be unique")
    return kfs


def kf_index(ref, kfs: list[Keyframe], side: str) -> int:
    """Keyframe id, or a date: 'from' snaps to the first keyframe at/after it, 'to' to the last at/before."""
    for i, k in enumerate(kfs):
        if ref == k.id:
            return i
    try:
        ms = dates.parse(ref).ms
    except ValueError:
        raise ScenarioError(f"unknown keyframe {ref!r}") from None
    if side == "from":
        for i, k in enumerate(kfs):
            if k.ms >= ms:
                return i
        return len(kfs)
    for i in range(len(kfs) - 1, -1, -1):
        if kfs[i].ms <= ms:
            return i
    return -1


def parse_layers(sc: dict, kfs: list[Keyframe]) -> list[Layer]:
    raw = sc.get("layers")
    if not isinstance(raw, list) or not raw:
        raise ScenarioError("scenario needs layers")
    layers, ids = [], set()
    for i, L in enumerate(raw):
        lid = str(L.get("id") or f"layer-{i + 1}")
        if lid in ids:
            raise ScenarioError(f"duplicate layer id {lid!r}")
        ids.add(lid)
        name = str(L.get("name") or lid)
        if len(name) > 100:
            raise ScenarioError(f"layer {lid}: name longer than 100 chars")
        color = L.get("color", "#3b82f6")
        if not isinstance(color, str) or not HEX.match(color):
            raise ScenarioError(f"layer {lid}: color must be #RRGGBB, got {color!r}")
        kind = L.get("kind", "territory")
        if kind not in ("territory", "free"):
            raise ScenarioError(f"layer {lid}: kind must be 'territory' or 'free'")
        clip = L.get("clip", "land" if kind == "territory" else "none")
        if clip not in ("land", "sea", "none"):
            raise ScenarioError(f"layer {lid}: clip must be land, sea or none")
        per_kf: list[dict | None] = [None] * len(kfs)
        states = L.get("states")
        if not isinstance(states, list) or not states:
            raise ScenarioError(f"layer {lid}: needs states [{{from, to, region}}]")
        for s in states:
            if not isinstance(s, dict) or "region" not in s:
                raise ScenarioError(f"layer {lid}: every state needs 'region' (null = absent)")
            if "at" in s:
                a = b = kf_index(s["at"], kfs, "from")
            else:
                a = kf_index(s["from"], kfs, "from") if "from" in s else 0
                b = kf_index(s["to"], kfs, "to") if "to" in s else len(kfs) - 1
            if s.get("color") is not None and not HEX.match(str(s["color"])):
                raise ScenarioError(f"layer {lid}: state color must be #RRGGBB")
            for k in range(max(a, 0), min(b, len(kfs) - 1) + 1):
                per_kf[k] = s  # later states override earlier ones
        layers.append(Layer(lid, name, color, kind, clip, per_kf, L.get("ring_groups") or []))
    return layers


def resolve_params(sc: dict) -> dict:
    scale = sc.get("scale", "regional")
    if scale not in SCALES:
        raise ScenarioError(f"scale must be one of {list(SCALES)}")
    p = dict(SCALES[scale])
    p.update({k: v for k, v in (sc.get("build") or {}).items() if k in p or k in ("territory_clip", "fill_gaps_km")})
    p["scale"] = scale
    p.setdefault("territory_clip", "land")
    return p


# --- geometry helpers ------------------------------------------------------------

def _rings_from_polys(polys, p: dict, lat: float, keep_largest: bool = True,
                      occupied=None) -> list[list[list[float]]]:
    """Polygons -> closed outer rings (the app draws no holes): big holes, and any hole that
    holds another layer's territory (`occupied(hole) -> bool`), are opened with a slit; small
    empty ones are filled."""
    deg2 = geo.km2_per_deg2(lat)
    min_island = p["min_island_km2"] / deg2
    min_hole = p["min_hole_km2"] / deg2
    slit = p["slit_km"] / geo.km_per_deg_lon(lat)
    parts: list[Polygon] = []
    for poly in polys:
        if poly.is_empty:
            continue
        big = [h for h in poly.interiors
               if Polygon(h).area >= min_hole or (occupied is not None and occupied(Polygon(h)))]
        if not big:
            parts.append(Polygon(poly.exterior))
            continue
        cuts = []
        for h in big:
            a, b = nearest_points(LineString(h.coords), LineString(poly.exterior.coords))
            d = np.array([b.x - a.x, b.y - a.y])
            n = np.linalg.norm(d)
            d = d / n if n > 0 else np.array([1.0, 0.0])
            # run the cut from inside the hole to beyond the outer ring, so no hairline keeps the ring closed
            a2 = np.array([a.x, a.y]) - d * slit
            b2 = np.array([b.x, b.y]) + d * slit
            cuts.append(Polygon(h))
            cuts.append(LineString([a2, b2]).buffer(slit / 2, cap_style="flat"))
        opened = Polygon(poly.exterior).difference(shapely.union_all(cuts))
        for q in shapely.get_parts(opened):
            if isinstance(q, Polygon) and not q.is_empty:
                parts.append(Polygon(q.exterior))
    if not parts:
        return []
    parts.sort(key=lambda q: -q.area)
    kept = [q for i, q in enumerate(parts) if q.area >= min_island or (keep_largest and i == 0)]
    rings = []
    for q in kept:
        q = shapely.orient_polygons(q) if hasattr(shapely, "orient_polygons") else shapely.geometry.polygon.orient(q)
        c = np.round(np.asarray(q.exterior.coords), int(p["decimals"]))
        keep = np.ones(len(c), dtype=bool)
        keep[1:] = np.any(c[1:] != c[:-1], axis=1)
        c = c[keep]
        if len(c) < 4:
            continue
        if not np.array_equal(c[0], c[-1]):
            c = np.vstack([c, c[:1]])
        rings.append(c.tolist())
    return rings


def _explode(g) -> list[Polygon]:
    return [q for q in shapely.get_parts(g) if isinstance(q, Polygon) and not q.is_empty]


# --- territory partition ------------------------------------------------------------

class Territory:
    def __init__(self, layers: list[Layer], kfs: list[Keyframe], ctx: Context, domain, p: dict, lat: float,
                 notes: list[str]):
        self.layers, self.kfs, self.p, self.lat, self.notes = layers, kfs, p, lat, notes
        K, nL = len(kfs), len(layers)
        regions: dict[tuple[int, int], Any] = {}
        for li, layer in enumerate(layers):
            for k, st in enumerate(layer.per_kf):
                if st is None or st.get("region") is None:
                    continue
                try:
                    g = ctx.eval(st["region"], year=kfs[k].when.year)
                except (RegionError, ValueError) as e:
                    raise ScenarioError(f"layer {layer.id} at {kfs[k].id}: {e}") from None
                g = polygonal(g.intersection(domain))
                if not g.is_empty:
                    regions[(li, k)] = g
        groups: list[list[Any]] = []
        for layer in layers:
            gl = []
            for grp in layer.ring_groups:
                try:
                    gl.append(polygonal(ctx.eval(grp["region"], year=kfs[0].when.year).intersection(domain)))
                except (RegionError, ValueError, KeyError) as e:
                    raise ScenarioError(f"layer {layer.id} ring group {grp.get('id')}: {e}") from None
            groups.append(gl)

        uniq: dict[bytes, Any] = {}
        for g in [*regions.values(), *(g for gl in groups for g in gl)]:
            uniq.setdefault(shapely.to_wkb(g), g)
        faces = self._faces(domain, list(uniq.values()))
        pts = shapely.point_on_surface(faces)
        xs, ys = shapely.get_x(pts), shapely.get_y(pts)
        owner = np.full((K, len(faces)), -1, dtype=np.int32)
        for (li, k) in sorted(regions, key=lambda t: (t[0], t[1])):
            g = regions[(li, k)]
            shapely.prepare(g)
            owner[k, shapely.contains_xy(g, xs, ys)] = li
        grp = np.full((nL, len(faces)), -1, dtype=np.int32)
        for li, gl in enumerate(groups):
            for gi in range(len(gl) - 1, -1, -1):
                shapely.prepare(gl[gi])
                grp[li, shapely.contains_xy(gl[gi], xs, ys)] = gi
        # per keyframe: group of the owner
        ogrp = np.where(owner >= 0, grp[np.clip(owner, 0, None), np.arange(len(faces))[None, :]], -1)
        sig = np.vstack([owner, ogrp]).T  # faces x 2K
        self.cells, self.cell_sig = self._dissolve(faces, sig)
        self.K = K
        self.cells, self.cell_sig = self._fold_slivers(self.cells, self.cell_sig)
        if self.p.get("fill_gaps_km"):
            self.cells, self.cell_sig = self._fill_gaps(self.cells, self.cell_sig)
        self.cells, self.cell_sig = self._absorb_enclaves(self.cells, self.cell_sig, domain)

    def _fill_gaps(self, cells, sig):
        """Thin unclaimed strips (narrower than fill_gaps_km) between territories from different
        sources join, per keyframe, the claimed neighbour with the longest shared border."""
        K = self.K
        half = self.p["fill_gaps_km"] / 2 / 111.0
        tree = shapely.STRtree(cells)
        sig = sig.copy()
        filled = 0
        for i in np.where((sig[:, :K] < 0).any(axis=1))[0]:
            if not cells[i].buffer(-half).is_empty:
                continue
            bi = cells[i].boundary
            shared = [(bi.intersection(cells[j].boundary).length, int(j))
                      for j in tree.query(cells[i], predicate="intersects") if j != i]
            shared.sort(reverse=True)
            for k in np.where(sig[i, :K] < 0)[0]:
                for length, j in shared:
                    if length > 0 and sig[j, k] >= 0:
                        sig[i, k], sig[i, K + k] = sig[j, k], sig[j, K + k]
                        filled += 1
                        break
        if filled:
            self.notes.append(f"filled {filled} thin gaps (< {self.p['fill_gaps_km']} km wide) from neighbours")
        return self._dissolve(cells, sig)

    def _faces(self, domain, geoms):
        lines = [shapely.boundary(polygonal(g)) for g in [domain, *geoms]]
        noded = shapely.union_all([l for l in lines if l is not None and not l.is_empty], grid_size=1e-7)
        faces = np.array(_explode(shapely.polygonize(shapely.get_parts(noded))), dtype=object)
        if len(faces) == 0:
            raise ScenarioError("nothing to draw: the domain is empty (check bbox / territory_clip)")
        shapely.prepare(domain)
        inside = shapely.contains(domain, shapely.point_on_surface(faces))
        return faces[inside]

    def _dissolve(self, faces, sig):
        by: dict[bytes, list[int]] = {}
        for i in range(len(faces)):
            by.setdefault(sig[i].tobytes(), []).append(i)
        cells, csig = [], []
        for key, idx in by.items():
            u = shapely.coverage_union_all(faces[idx]) if len(idx) > 1 else faces[idx[0]]
            for q in _explode(u):
                cells.append(q)
                csig.append(sig[idx[0]])
        return np.array(cells, dtype=object), np.array(csig)

    def _fold_slivers(self, cells, sig):
        min_cell = self.p["min_cell_km2"] / geo.km2_per_deg2(self.lat)
        areas = shapely.area(cells)
        small = np.where(areas < min_cell)[0]
        if len(small) == 0:
            return cells, sig
        tree = shapely.STRtree(cells)
        parent = np.arange(len(cells))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in small[np.argsort(areas[small])]:
            best, best_len = -1, 0.0
            bi = cells[i].boundary
            for j in tree.query(cells[i], predicate="intersects"):
                if j == i:
                    continue
                shared = bi.intersection(cells[j].boundary).length
                if shared > best_len:
                    best, best_len = int(j), shared
            if best >= 0:
                parent[i] = root(best)
        new_sig = sig[[root(i) for i in range(len(cells))]]
        folded = int((parent != np.arange(len(cells))).sum())
        if folded:
            self.notes.append(f"folded {folded} sliver cells (< {self.p['min_cell_km2']} km²) into neighbours")
        return self._dissolve(cells, new_sig)

    def _absorb_enclaves(self, cells, sig, domain):
        """A small patch (connected same-owner cells) enclosed by a single other owner joins that
        owner at that keyframe: filling the resulting hole would otherwise overlap it.
        Owned land never becomes unowned."""
        min_hole = self.p["min_hole_km2"] / geo.km2_per_deg2(self.lat)
        areas = shapely.area(cells)
        tree = shapely.STRtree(cells)
        coast = shapely.boundary(domain)
        n = len(cells)
        on_coast = np.array([cells[i].boundary.intersection(coast).length > 1e-9 for i in range(n)])
        adj: list[list[int]] = [[] for _ in range(n)]
        for i in range(n):
            if areas[i] >= min_hole:
                continue  # only small cells can be part of a small patch; big ones still border them
            b = cells[i].boundary
            for j in tree.query(cells[i], predicate="intersects"):
                j = int(j)
                if j != i and b.intersection(cells[j].boundary).length > 0:
                    adj[i].append(j)
                    adj[j].append(i)
        sig = sig.copy()
        changed = 0
        for k in range(self.K):
            seen = np.zeros(n, dtype=bool)
            for start in range(n):
                if seen[start] or areas[start] >= min_hole:
                    continue
                own = sig[start, k]
                comp, stack, area, border = [], [start], 0.0, set()
                seen[start] = True
                ok = True
                while stack:
                    i = stack.pop()
                    comp.append(i)
                    area += areas[i]
                    if on_coast[i] or area >= min_hole:
                        ok = False
                    for j in adj[i]:
                        if sig[j, k] == own:
                            if not seen[j]:
                                if areas[j] >= min_hole:
                                    ok = False
                                    continue
                                seen[j] = True
                                stack.append(j)
                        else:
                            border.add(j)
                owners = {int(sig[j, k]) for j in border}
                if ok and len(owners) == 1:
                    o = owners.pop()
                    if o >= 0:
                        g = next(int(sig[j, self.K + k]) for j in border)
                        for i in comp:
                            sig[i, k] = o
                            sig[i, self.K + k] = g
                        changed += 1
        if not changed:
            return cells, sig
        self.notes.append(f"absorbed {changed} small enclaves (< {self.p['min_hole_km2']} km²) into the surrounding layer")
        return self._dissolve(cells, sig)

    def simplified(self, tol_deg: float):
        try:
            return np.array(shapely.coverage_simplify(self.cells, tol_deg), dtype=object)
        except Exception as e:  # invalid coverage: fall back, borders may no longer be flush
            self.notes.append(f"coverage_simplify failed ({e}); fell back to per-cell simplify")
            return np.array(shapely.simplify(self.cells, tol_deg, preserve_topology=True), dtype=object)

    def _cell_points(self, cells):
        """A point inside every (simplified) cell, computed once per simplification."""
        if getattr(self, "_pts_for", None) is not cells:
            pts = shapely.point_on_surface(cells)
            self._pts_for, self._pts = cells, (shapely.get_x(pts), shapely.get_y(pts))
        return self._pts

    def rings(self, cells, li: int, k: int) -> list | None:
        mask = self.cell_sig[:, k] == li
        if not mask.any():
            return None
        groups = self.cell_sig[mask, self.K + k]
        sel = cells[mask]
        polys: list[Polygon] = []
        for gid in sorted(set(groups.tolist())):
            u = shapely.coverage_union_all(sel[groups == gid])
            if not u.is_valid:
                # simplified cells can pinch the union's outer ring at a quadripoint (e.g. Kazungula):
                # the ring then loops around a neighbour, and its exterior alone would cover it
                u = shapely.make_valid(u)
            polys.extend(_explode(u))
        others = (self.cell_sig[:, k] >= 0) & ~mask

        def occupied(hole) -> bool:
            if not others.any():
                return False
            xs, ys = self._cell_points(cells)
            return bool(shapely.contains_xy(hole, xs[others], ys[others]).any())

        return _rings_from_polys(polys, self.p, self.lat, occupied=occupied) or None


# --- main build ------------------------------------------------------------------

def build(sc: dict, *, tolerance_scale: float = 1.0, auto_size: bool = True) -> BuildResult:
    kfs = parse_keyframes(sc)
    layers = parse_layers(sc, kfs)
    p = resolve_params(sc)
    m = sc.get("map") or {}
    name = str(m.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ScenarioError("map.name is required (max 100 chars)")
    bbox = sc.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ScenarioError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
    lat = (bbox[1] + bbox[3]) / 2
    notes: list[str] = []

    land_cache: dict[str, Any] = {}

    def land_domain():
        if "land" not in land_cache:
            land_cache["land"] = data.land_in(bbox)
        return land_cache["land"]

    frame = box(*bbox)
    t_domain = polygonal(land_domain()) if p["territory_clip"] == "land" else frame
    ctx = Context(sc.get("regions") or {}, bbox, lambda: t_domain, p["clio_coast_km"])

    t_layers = [L for L in layers if L.kind == "territory"]
    f_layers = [L for L in layers if L.kind == "free"]
    territory = Territory(t_layers, kfs, ctx, t_domain, p, lat, notes) if t_layers else None

    # free layers: evaluate once (with stubs for 'grow' states)
    free_geoms: dict[tuple[int, int], Any] = {}
    for fi, layer in enumerate(f_layers):
        for k, st in enumerate(layer.per_kf):
            stub = False
            if (st is None or st.get("region") is None) and k + 1 < len(kfs):
                nxt = layer.per_kf[k + 1]
                if nxt is not None and nxt.get("region") is not None and nxt.get("grow"):
                    st, stub = nxt, True
            if st is None or st.get("region") is None:
                continue
            try:
                g = ctx.eval(st["region"], year=kfs[k].when.year, progress_scale=STUB_PROGRESS if stub else 1.0)
            except (RegionError, ValueError) as e:
                raise ScenarioError(f"layer {layer.id} at {kfs[k].id}: {e}") from None
            if layer.clip == "land":
                g = polygonal(g.intersection(land_domain()))
            elif layer.clip == "sea":
                g = polygonal(g.difference(land_domain()))
            if not g.is_empty:
                free_geoms[(fi, k)] = g

    scale = tolerance_scale
    for attempt in range(4):
        marker_warnings: list[str] = []
        doc, stats = _emit(sc, m, name, kfs, layers, t_layers, f_layers, territory, free_geoms, p, lat, scale,
                           marker_warnings)
        size = len(json.dumps(doc, separators=(",", ":")))
        if size <= SIZE_BUDGET or not auto_size:
            break
        notes.append(f"output {size / 1e6:.2f} MB > budget; coarser simplification x{scale * 1.6:.2f}")
        scale *= 1.6
    p["tolerance_scale"] = scale
    p["size_bytes"] = size

    tests = run_tests(sc, doc, kfs, layers, p["test_snap_km"])
    overlaps = territory_overlaps(doc, kfs, layers, lat)
    fragments = inland_fragments(doc, kfs, layers, t_domain, lat, p)
    test_warnings = [f"test {t['test'].get('place') or ''} at [{t['lon']:.4f}, {t['lat']:.4f}] is outside the map area (bbox)"
                     for t in tests if t.get("lon") is not None and not data.near_bbox(bbox, t["lon"], t["lat"], 0.1)]
    return BuildResult(doc, notes + stats, [], overlaps + fragments + marker_warnings + test_warnings,
                       tests, kfs, layers, p)


def _emit(sc, m, name, kfs, layers, t_layers, f_layers, territory, free_geoms, p, lat, scale, marker_warnings):
    tol_deg = p["tolerance_km"] * scale / 111.0
    ftol_deg = p["free_tolerance_km"] * scale / 111.0
    cells = territory.simplified(tol_deg) if territory else None
    K = len(kfs)
    per_layer: dict[str, list[tuple[int, list | None, str | None]]] = {}

    for li, layer in enumerate(t_layers):
        seq = []
        for k in range(K):
            st = layer.per_kf[k]
            rings = territory.rings(cells, li, k)
            seq.append((k, rings, (st or {}).get("color")))
        per_layer[layer.id] = seq
    for fi, layer in enumerate(f_layers):
        seq = []
        for k in range(K):
            st = layer.per_kf[k] or (layer.per_kf[k + 1] if k + 1 < K else None)
            g = free_geoms.get((fi, k))
            rings = None
            if g is not None and shapely.get_num_coordinates(g) > FREE_SIMPLIFY_ABOVE:
                # built shapes (lines, arrows, formations) keep their exact vertex structure so they
                # morph vertex-to-vertex; only big free shapes (e.g. clipped zones) are simplified
                simple = shapely.simplify(g, ftol_deg, preserve_topology=True)
                # small blocks must keep > 6 positions or the engine treats them as absent
                if min((len(q.exterior.coords) for q in _explode(simple)), default=0) >= 8:
                    g = simple
            if g is not None:
                rings = _rings_from_polys(_explode(g), p, lat) or None
            seq.append((k, rings, (st or {}).get("color") if rings else None))
        per_layer[layer.id] = seq

    # emit only on change; the first instance is the first present keyframe
    instances: dict[str, list[dict]] = {L.id: [] for L in layers}
    for layer in [*t_layers, *f_layers]:
        last = None
        started = False
        for k, rings, color in per_layer[layer.id]:
            if not started and rings is None:
                continue
            started = True
            key = (json.dumps(rings), color)
            if key != last:
                instances[layer.id].append({"k": k, "geometry": rings, "color": color})
                last = key

    # every keyframe needs at least one instance: it defines the tick and its label
    hosted = {inst["k"] for insts in instances.values() for inst in insts}
    ordered = [*t_layers, *f_layers]
    for k in range(K):
        if k in hosted:
            continue
        host = next((L for L in ordered if instances[L.id] and instances[L.id][0]["k"] < k), None)
        if host is None:
            host = ordered[0]
            instances[host.id].append({"k": k, "geometry": None, "color": None})
        else:
            prev = [i for i in instances[host.id] if i["k"] < k][-1]
            instances[host.id].append({"k": k, "geometry": prev["geometry"], "color": prev["color"]})
        instances[host.id].sort(key=lambda i: i["k"])

    placeholders = []
    for order, layer in enumerate(ordered):
        insts = []
        for inst in instances[layer.id]:
            kf = kfs[inst["k"]]
            out = {"label": kf.label or None, "datetime": kf.when.iso, "geometry": inst["geometry"]}
            out["color"] = inst["color"]
            insts.append(out)
        placeholders.append({"id": layer.id, "name": layer.name, "color": layer.color,
                             "displayOrder": str(order), "instances": insts})

    description = str(m.get("description") or "").strip()
    uses_clio = "clio" in json.dumps(sc.get("layers")) + json.dumps(sc.get("regions") or {})
    if uses_clio and "cliopatria" not in description.lower():
        description = (description + "\n\n" if description else "") + \
            "Base borders: Cliopatria (Seshat Global History Databank, CC BY 4.0) and Natural Earth."
    style = m.get("mapStyle", "light")
    style = MAP_STYLES.get(style, style)

    doc = {
        "name": name,
        "description": description or None,
        "mapStyle": style,
        "polygonPlaceholders": placeholders,
        "markers": build_markers(sc, kfs, marker_warnings),
    }
    if m.get("casualtyBar"):
        doc["casualtyBar"] = m["casualtyBar"]
    stats = []
    for ph in placeholders:
        verts = sum(len(r) for i in ph["instances"] if i["geometry"] for r in i["geometry"])
        stats.append(f"layer {ph['id']}: {len(ph['instances'])} instances, {verts} vertices")
    return doc, stats


def territory_overlaps(doc: dict, kfs: list[Keyframe], layers: list[Layer], lat: float) -> list[str]:
    """Territory layers must not overlap (a filled hole or a bad cut would show as a darker patch)."""
    terr = {L.id for L in layers if L.kind == "territory"}
    phs = [ph for ph in doc["polygonPlaceholders"] if ph["id"] in terr]
    out = []
    deg2 = geo.km2_per_deg2(lat)
    for k in kfs:
        geoms = [(ph["id"], geometry_at(ph, k.ms)) for ph in phs]
        geoms = [(i, g) for i, g in geoms if g is not None]
        for x in range(len(geoms)):
            for y in range(x + 1, len(geoms)):
                (a, ga), (b, gb) = geoms[x], geoms[y]
                if not shapely.intersects(shapely.envelope(ga), shapely.envelope(gb)):
                    continue
                area = ga.intersection(gb).area * deg2
                if area > 1.0:
                    out.append(f"{k.id}: territory layers {a} and {b} overlap by {area:.0f} km²")
    return out


def inland_fragments(doc: dict, kfs: list[Keyframe], layers: list[Layer], domain, lat: float, p: dict) -> list[str]:
    """Small detached rings of a territory layer that are not islands: usually two sources
    (Cliopatria vs admin units) disagreeing about a border. Reported where they first appear."""
    terr = {L.id for L in layers if L.kind == "territory"}
    coast = shapely.boundary(domain)
    shapely.prepare(coast)
    near = 3 * p["tolerance_km"] / 111.0
    deg2 = geo.km2_per_deg2(lat)
    out, seen = [], set()
    for ph in doc["polygonPlaceholders"]:
        if ph["id"] not in terr:
            continue
        for inst in ph["instances"]:
            rings = inst["geometry"] or []
            if len(rings) < 2:
                continue
            polys = [shapely.make_valid(Polygon(r)) for r in rings]
            biggest = max(q.area for q in polys)
            frags = []
            for q in polys:
                # genuine small exclaves exist (and are kept); only sizeable fragments are suspicious
                if (q.area >= 0.05 * biggest or q.area * deg2 < p["min_hole_km2"]
                        or shapely.dwithin(q, coast, near)):
                    continue
                c = q.representative_point()
                key = (ph["id"], round(c.x, 1), round(c.y, 1))
                if key not in seen:
                    seen.add(key)
                    frags.append(f"{q.area * deg2:.0f} km² at [{c.x:.2f}, {c.y:.2f}]")
            if frags:
                out.append(f"{ph['id']} @ {inst['datetime'][:16]}: {len(frags)} detached inland fragment(s): "
                           f"{'; '.join(frags[:4])} — sources disagree? clip the shape (intersect/minus admin0)")
    return out


# --- markers ---------------------------------------------------------------------------

def build_markers(sc: dict, kfs: list[Keyframe], warnings: list[str] | None = None) -> list[dict]:
    bbox = sc["bbox"]
    times = [k.ms for k in kfs]
    total_ms = pacing.playback_ms(times)
    out = []
    for i, mk in enumerate(sc.get("markers") or []):
        title = str(mk.get("title") or "").strip()
        if not title or len(title) > 100:
            raise ScenarioError(f"marker #{i + 1}: title required, max 100 chars")
        if "lon" in mk and "lat" in mk:
            lon, lat = float(mk["lon"]), float(mk["lat"])
        elif "place" in mk:
            try:
                lon, lat = data.place_point(mk["place"], bbox)
            except KeyError as e:
                raise ScenarioError(f"marker {title!r}: {str(e).strip(chr(34))}") from None
        else:
            raise ScenarioError(f"marker {title!r}: needs lon/lat or place")
        if warnings is not None and not data.near_bbox(bbox, lon, lat, 0.1):
            warnings.append(f"marker {title!r} at [{lon:.4f}, {lat:.4f}] is outside the map area (bbox)")
        start = mk.get("start")
        if start is None:
            raise ScenarioError(f"marker {title!r}: needs start (keyframe id or date)")
        s_ms = _ref_ms(start, kfs)
        end = mk.get("end", "auto")
        if end is None:
            e_ms = None
        elif end == "auto" or isinstance(end, dict):
            if isinstance(end, dict) and ("days" in end or "years" in end):
                e_ms = s_ms + int(float(end.get("days", 0)) * dates.DAY_MS + float(end.get("years", 0)) * 365.2425 * dates.DAY_MS)
            else:
                min_ms = float((end or {}).get("playback_ms", 1400)) if isinstance(end, dict) else 1400.0
                p0 = pacing.time_to_progress(s_ms, times)
                e_ms = pacing.progress_to_time(min(1.0, p0 + min_ms / max(total_ms, 1)), times)
                nxt = next((t for t in times if t > s_ms), times[-1])
                e_ms = int(max(e_ms, nxt))
        else:
            e_ms = _ref_ms(end, kfs)
        if e_ms is not None and e_ms < s_ms:
            raise ScenarioError(f"marker {title!r}: end before start")
        color = mk.get("color", "#ef4444")
        if not HEX.match(str(color)):
            raise ScenarioError(f"marker {title!r}: color must be #RRGGBB")
        mini = mk.get("mini", False)
        if not isinstance(mini, bool):
            raise ScenarioError(f"marker {title!r}: mini must be true or false")
        out.append({
            "title": title,
            "description": (str(mk["description"]).strip() or None) if mk.get("description") else None,
            "longitude": round(lon, 5), "latitude": round(lat, 5),
            "startDatetime": dates.from_ms(s_ms).iso,
            "endDatetime": dates.from_ms(e_ms).iso if e_ms is not None else None,
            "color": color,
            **({"mini": True} if mini else {}),
        })
    return out


def _ref_ms(ref, kfs: list[Keyframe]) -> int:
    for k in kfs:
        if ref == k.id:
            return k.ms
    try:
        return dates.parse(ref).ms
    except ValueError as e:
        raise ScenarioError(str(e)) from None


# --- test places ------------------------------------------------------------------------

def geometry_at(ph: dict, ms: int):
    """The placeholder's shape at a keyframe time (latest instance at or before it)."""
    cur = None
    for inst in ph["instances"]:
        t = dates.parse_app_datetime(inst["datetime"])
        if t is not None and t <= ms:
            cur = inst["geometry"]
    if not cur:
        return None
    # rounded rings may self-touch; the engine doesn't care but GEOS does
    return shapely.union_all([shapely.make_valid(Polygon(r)) for r in cur if len(r) >= 4])


def run_tests(sc: dict, doc: dict, kfs: list[Keyframe], layers: list[Layer], snap_km: float = 0.0) -> list[dict]:
    """expect: layer id | [ids] | null. null = no territory layer there (on maps without
    territory layers: no layer at all). expect_not: id | [ids] that must NOT be there."""
    kinds = {L.id: L.kind for L in layers}
    has_territory = any(k == "territory" for k in kinds.values())
    results = []
    cache: dict[tuple[str, int], Any] = {}
    for t in sc.get("tests") or []:
        lon = lat = None
        try:
            k = kf_index(t["at"], kfs, "from")
            if k >= len(kfs):
                raise ScenarioError("after the last keyframe")
            if "lon" in t and "lat" in t:
                lon, lat = float(t["lon"]), float(t["lat"])
            else:
                lon, lat = data.place_point(t["place"], sc["bbox"])
        except (KeyError, ScenarioError) as e:
            results.append({"test": t, "ok": False, "got": None, "error": str(e).strip('"'), "lon": lon, "lat": lat})
            continue
        pt = shapely.Point(lon, lat)
        inside, near = [], []
        for ph in doc["polygonPlaceholders"]:
            key = (ph["id"], k)
            if key not in cache:
                cache[key] = geometry_at(ph, kfs[k].ms)
            g = cache[key]
            if g is None:
                continue
            if g.covers(pt):
                inside.append(ph["id"])
            elif kinds.get(ph["id"]) == "territory":
                near.append((g.distance(pt) * geo.km_per_deg_lon(lat), ph["id"]))
        terr = [i for i in inside if kinds.get(i) == "territory"]
        snapped = None
        if not terr and near and snap_km > 0:
            d, pid = min(near)
            if d <= snap_km:  # a port on the simplified coast
                terr, snapped = [pid], round(d, 2)
                inside.append(pid)
        ok = True
        if "expect" in t:
            expect = t["expect"]
            options = expect if isinstance(expect, list) else [expect]
            empty = not terr if has_territory else not inside
            ok = any((e is None and empty) or (e is not None and e in inside) for e in options)
        if "expect_not" in t:
            banned = t["expect_not"] if isinstance(t["expect_not"], list) else [t["expect_not"]]
            ok = ok and not any(b in inside for b in banned)
        results.append({"test": t, "ok": ok, "got": terr or inside or None, "kf": kfs[k].id, "kf_ms": kfs[k].ms,
                        "snapped_km": snapped, "lon": lon, "lat": lat})
    return results
