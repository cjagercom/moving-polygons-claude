"""Validate an import JSON against the app's real import path.

Dashboard -> Import (app/pages/DashboardPage.tsx) creates every layer,
keyframe and marker with its own request and does NOT check the responses:
anything the server rejects is silently dropped. Errors here are exactly
those rejections (plus things that break playback); warnings are quality
issues (pacing, ring matching, size, overlaps).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from . import dates, pacing

HEX7 = "#0123456789abcdefABCDEF"
KNOWN_STYLES = {
    "mapbox://styles/mapbox/light-v11", "mapbox://styles/mapbox/dark-v11",
    "mapbox://styles/mapbox/streets-v12", "mapbox://styles/mapbox/outdoors-v12",
    "mapbox://styles/mapbox/satellite-v9", "mapbox://styles/mapbox/satellite-streets-v12",
    "vintage", "vintage-soft", "tactical", "dark-glow", "polar", "tapestry",
}
SIZE_BUDGET = 3_300_000
SIZE_WARN = 3_000_000
INSTANCE_LIMIT = 3_500_000
DECIMATE_VERTS = 1500
# app/utils/interpolate.ts matchRings
MAX_MATCH_SIZE_FACTOR = 2
MAX_MATCH_SLACK = 0.3
OVERLAP_ROWS = 64
MIN_OVERLAP_SHARE = 0.1
ABSORBED_FRACTION = 0.5


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def text(self) -> str:
        out = []
        for title, items in (("ERRORS", self.errors), ("WARNINGS", self.warnings), ("INFO", self.info)):
            if items:
                out.append(f"{title} ({len(items)})")
                out += [f"  - {x}" for x in items]
        return "\n".join(out) if out else "no issues"


def _chars(s: str) -> int:
    return len(s)  # Python str length counts code points, like Postgres varchar


def _is_hex(c) -> bool:
    return isinstance(c, str) and len(c) == 7 and c[0] == "#" and all(ch in HEX7 for ch in c[1:])


def _ring_area(r) -> float:
    a = 0.0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return abs(a) / 2


def _centroid(r):
    # same as getCentroid in interpolate.ts: plain vertex average (closing point included)
    n = len(r)
    return (sum(p[0] for p in r) / n, sum(p[1] for p in r) / n)


def _bbox(r):
    xs = [p[0] for p in r]
    ys = [p[1] for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def _scanline_crossings(r, y0: float, h: float, rows: int):
    out = [[] for _ in range(rows)]
    n = len(r)
    for i in range(n):
        p, q = r[i], r[(i + 1) % n]
        if p[1] == q[1]:
            continue
        lo, hi = min(p[1], q[1]), max(p[1], q[1])
        # half-open [lo, hi): a vertex exactly on a scanline counts once
        r0 = max(0, math.ceil((lo - y0) / h - 0.5))
        r1 = min(rows - 1, math.ceil((hi - y0) / h - 0.5) - 1)
        for row in range(r0, r1 + 1):
            y = y0 + (row + 0.5) * h
            out[row].append(p[0] + (y - p[1]) * (q[0] - p[0]) / (q[1] - p[1]))
    for xs in out:
        xs.sort()
    return out


def _shared_length(a, b) -> float:
    i = j = 0
    total = 0.0
    while i + 1 < len(a) and j + 1 < len(b):
        lo, hi = max(a[i], b[j]), min(a[i + 1], b[j + 1])
        if hi > lo:
            total += hi - lo
        if a[i + 1] < b[j + 1]:
            i += 2
        else:
            j += 2
    return total


def ring_overlap_area(a, b, rows: int = OVERLAP_ROWS) -> float:
    """Port of ringOverlapArea: scanlines over the bbox intersection, exact per scanline."""
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    y0, y1 = max(ay0, by0), min(ay1, by1)
    if not y1 > y0 or not min(ax1, bx1) > max(ax0, bx0):
        return 0.0
    h = (y1 - y0) / rows
    ca = _scanline_crossings(a, y0, h, rows)
    cb = _scanline_crossings(b, y0, h, rows)
    return sum(_shared_length(ca[k], cb[k]) for k in range(rows)) * h


def match_rings(a, b):
    """Port of matchRings: overlapping rings pair first (by IoU); rings that overlap nothing
    pair by centroid distance + area penalty (distance-capped); absorbed rings collapse/grow."""
    fa = [{"c": _centroid(r), "area": _ring_area(r), "box": _bbox(r), "covered": 0.0} for r in a]
    fb = [{"c": _centroid(r), "area": _ring_area(r), "box": _bbox(r), "covered": 0.0} for r in b]
    used_a, used_b, pairs = set(), set(), []

    def dist(i, j):
        return math.hypot(fa[i]["c"][0] - fb[j]["c"][0], fa[i]["c"][1] - fb[j]["c"][1])

    def take(cands):
        for i, j in cands:
            if i in used_a or j in used_b:
                continue
            used_a.add(i)
            used_b.add(j)
            pairs.append((i, j, dist(i, j)))

    if len(a) == 1 and len(b) == 1:
        take([(0, 0)])  # a lone ring moving to a lone ring is a deliberate move
    else:
        overlaps = []
        for i, ma in enumerate(fa):
            for j, mb in enumerate(fb):
                if ma["box"][0] > mb["box"][2] or ma["box"][2] < mb["box"][0]:
                    continue
                if ma["box"][1] > mb["box"][3] or ma["box"][3] < mb["box"][1]:
                    continue
                shared = min(ring_overlap_area(a[i], b[j]), ma["area"], mb["area"])
                if not shared > 0:
                    continue
                ma["covered"] += shared
                mb["covered"] += shared
                if shared < MIN_OVERLAP_SHARE * min(ma["area"], mb["area"]):
                    continue
                overlaps.append((-shared / (ma["area"] + mb["area"] - shared), dist(i, j), i, j))
        overlaps.sort()
        take((i, j) for _, _, i, j in overlaps)

        def absorbed(m):
            return m["covered"] > ABSORBED_FRACTION * m["area"]

        cands = []
        for i, ma in enumerate(fa):
            if i in used_a or absorbed(ma):
                continue
            for j, mb in enumerate(fb):
                if j in used_b or absorbed(mb):
                    continue
                d = dist(i, j)
                mx = max(ma["area"], mb["area"])
                if d > MAX_MATCH_SIZE_FACTOR * math.sqrt(mx) + MAX_MATCH_SLACK:
                    continue
                pen = (abs(ma["area"] - mb["area"]) / mx) * math.sqrt(mx) * 0.5 if mx > 0 else 0
                cands.append((d + pen, i, j))
        cands.sort()
        take((i, j) for _, i, j in cands)
    pairs.sort()
    return pairs, [i for i in range(len(a)) if i not in used_a], [j for j in range(len(b)) if j not in used_b]


def _check_geometry(g, where: str, rep: Report) -> int:
    if g is None:
        return 0
    if not isinstance(g, list):
        rep.errors.append(f"{where}: geometry must be a list of rings or null")
        return 0
    verts = 0
    for ri, ring in enumerate(g):
        if not isinstance(ring, list) or len(ring) < 4:
            rep.errors.append(f"{where}: ring {ri} has fewer than 4 positions")
            continue
        for pos in ring:
            if (not isinstance(pos, list) or len(pos) != 2 or not all(isinstance(v, (int, float)) for v in pos)
                    or not all(math.isfinite(v) for v in pos)):
                rep.errors.append(f"{where}: ring {ri} has a bad position {pos!r}")
                break
            if not (-180 <= pos[0] <= 180 and -90 <= pos[1] <= 90):
                rep.errors.append(f"{where}: ring {ri} position {pos} out of range (must be [lon, lat])")
                break
        else:
            if ring[0] != ring[-1]:
                rep.errors.append(f"{where}: ring {ri} is not closed (first != last)")
        verts += len(ring)
    return verts


def _is_tiny(g) -> bool:
    """morphPlan.isEffectivelyHidden: <= 6 vertices and < 1e-3 deg² counts as absent."""
    if not g:
        return True
    verts = sum(len(r) for r in g)
    return verts <= 6 and sum(_ring_area(r) for r in g) < 1e-3


def _casualty_bar_problem(bar) -> str | None:
    """Mirror of app/lib/casualtyBar.ts validateCasualtyBar."""
    if not isinstance(bar, dict):
        return "must be an object"
    # No right side makes the bar one-sided: only the left counts are required
    two_sided = bar.get("right") is not None
    required = ("left", "right") if two_sided else ("left",)
    for side in required:
        s = bar.get(side)
        if not (isinstance(s, dict) and str(s.get("label") or "").strip()
                and re.fullmatch(r"#[0-9a-fA-F]{6}", str(s.get("color") or ""))):
            return f"{side} needs a label and a #rrggbb color"
    points = bar.get("points")
    if not isinstance(points, list) or not points:
        return "points is empty"
    if len(points) > 500:
        return "more than 500 points"
    prev = None
    for i, p in enumerate(points):
        if not isinstance(p, dict) or not isinstance(p.get("date"), str):
            return f"points[{i}] has no date"
        if prev is not None and p["date"] < prev:
            return "points must be in date order"
        prev = p["date"]
        for k in ("left", "right", "leftLow", "leftHigh", "rightLow", "rightHigh"):
            v = p.get(k)
            if (k in required or v is not None) and not (isinstance(v, (int, float)) and v >= 0):
                return f"points[{i}].{k} is not a count"
    return None


def validate(doc: dict) -> Report:
    rep = Report()
    if not isinstance(doc, dict):
        rep.errors.append("top level must be an object")
        return rep
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        rep.warnings.append("name missing: the import will be called 'Imported Map'")
    elif _chars(name.strip()) > 100:
        rep.errors.append(f"map name is {_chars(name.strip())} chars (max 100): the whole import fails")
    style = doc.get("mapStyle")
    if style and style not in KNOWN_STYLES:
        rep.warnings.append(f"mapStyle {style!r} is not one of the editor's styles")
    if doc.get("casualtyBar") is not None:
        problem = _casualty_bar_problem(doc["casualtyBar"])
        if problem:
            rep.errors.append(f"casualtyBar: {problem} (the import skips the bar)")

    size = len(json.dumps(doc, separators=(",", ":")))
    if size > SIZE_BUDGET:
        rep.errors.append(f"size {size / 1e6:.2f} MB > {SIZE_BUDGET / 1e6:.1f} MB budget (public map API returns the whole map)")
    elif size > SIZE_WARN:
        rep.warnings.append(f"size {size / 1e6:.2f} MB is close to the {SIZE_BUDGET / 1e6:.1f} MB budget")
    rep.info.append(f"size {size / 1e6:.2f} MB")

    phs = doc.get("polygonPlaceholders") or []
    if not isinstance(phs, list):
        rep.errors.append("polygonPlaceholders must be a list")
        phs = []
    labels_at: dict[int, set] = {}
    all_times: set[int] = set()
    total_inst = 0
    for pi, ph in enumerate(phs):
        pname = ph.get("name")
        where = f"layer {ph.get('id') or pi + 1} ({pname})"
        if not isinstance(pname, str) or not pname.strip() or _chars(pname) > 100:
            rep.errors.append(f"{where}: name required, max 100 chars (layer and all its keyframes are skipped)")
        color = ph.get("color")
        if not isinstance(color, str) or len(color) > 7:
            rep.errors.append(f"{where}: color must be a string of at most 7 chars (layer skipped)")
        elif not _is_hex(color):
            rep.warnings.append(f"{where}: color {color!r} is not #RRGGBB (colour blending needs hex)")
        do = ph.get("displayOrder")
        if do is not None and (not isinstance(do, str) or _chars(do) > 50):
            rep.warnings.append(f"{where}: displayOrder must be a string of at most 50 chars (ignored otherwise)")
        insts = ph.get("instances") or []
        prev = None
        prev_t = None
        seen_times = set()
        for ii, inst in enumerate(insts):
            iw = f"{where} keyframe {ii + 1}"
            t = dates.parse_app_datetime(inst.get("datetime"))
            if t is None:
                rep.errors.append(f"{iw}: datetime {inst.get('datetime')!r} is not parseable (dropped)")
                continue
            iw = f"{where} @ {inst.get('datetime')}"
            if t in seen_times:
                rep.warnings.append(f"{iw}: two keyframes at the same time in one layer")
            seen_times.add(t)
            if prev_t is not None and t < prev_t:
                rep.info.append(f"{where}: instances not in time order (the app sorts them)")
            prev_t = t
            all_times.add(t)
            label = inst.get("label")
            if label is not None:
                if not isinstance(label, str):
                    rep.errors.append(f"{iw}: label must be text (dropped)")
                elif _chars(label.strip()) > 50:
                    rep.errors.append(f"{iw}: label is {_chars(label.strip())} chars (max 50) — keyframe silently dropped: {label!r}")
                if isinstance(label, str) and label.strip():
                    labels_at.setdefault(t, set()).add(label.strip())
            c = inst.get("color")
            if c is not None and not _is_hex(c):
                rep.errors.append(f"{iw}: color {c!r} must be #RRGGBB or null (dropped)")
            g = inst.get("geometry")
            verts = _check_geometry(g, iw, rep)
            if verts > DECIMATE_VERTS * 20:
                rep.warnings.append(f"{iw}: {verts} vertices — heavy; raise tolerance")
            blob = len(json.dumps(g, separators=(",", ":")))
            if blob > INSTANCE_LIMIT:
                rep.errors.append(f"{iw}: geometry {blob / 1e6:.1f} MB exceeds one request (~4 MB)")
            if isinstance(g, list) and g and _is_tiny(g) and not (len(g) == 1 and len(g[0]) <= 4):
                rep.warnings.append(f"{iw}: shape has <= 6 positions and < 1e-3 deg² — the engine treats it as absent")
            total_inst += 1
            if prev is not None and isinstance(g, list) and isinstance(prev, list) and not _is_tiny(g) and not _is_tiny(prev):
                _check_matching(prev, g, iw, rep)
            if isinstance(g, list) or g is None:
                prev = g
    rep.info.append(f"{len(phs)} layers, {total_inst} keyframe instances, {len(all_times)} time points")

    for t, labels in labels_at.items():
        if len(labels) > 1:
            rep.warnings.append(f"{dates.from_ms(t).iso}: different labels at the same time {sorted(labels)} (the first layer's wins)")

    times = sorted(all_times)
    if len(times) >= 3:
        n = sum(pacing.floored(times))
        if n:
            rep.info.append(f"{n} of {len(times) - 1} transitions are floored at {pacing.MIN_TRANSITION_FRACTION}x an average "
                            "one (time runs faster there; each still gets a visible morph)")
        avg = (times[-1] - times[0]) / (len(times) - 1)
        close = [(a, b) for a, b in zip(times, times[1:]) if b - a < 0.1 * avg]
        if close:
            pairs = ", ".join(f"{dates.from_ms(a).iso[:16]}→{dates.from_ms(b).iso[:16]}" for a, b in close[:5])
            rep.warnings.append(f"{len(close)} keyframe pair(s) are near-coincident (< 10% of an average gap): {pairs} — "
                                "consider merging them into one keyframe")
    if len(times) >= 2:
        rep.info.append(f"playback {pacing.playback_ms(times) / 1000:.1f} s at 1x")

    markers = doc.get("markers") or []
    for mi, mk in enumerate(markers):
        title = mk.get("title")
        mw = f"marker {mi + 1} ({title})"
        if not isinstance(title, str) or not title.strip() or _chars(title.strip()) > 100:
            rep.errors.append(f"{mw}: title required, max 100 chars (dropped)")
        lon, lat = mk.get("longitude"), mk.get("latitude")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            rep.errors.append(f"{mw}: longitude/latitude must be numbers (dropped)")
        elif not (-180 <= lon <= 180 and -90 <= lat <= 90):
            rep.errors.append(f"{mw}: position out of range")
        s = dates.parse_app_datetime(mk.get("startDatetime"))
        if s is None:
            rep.errors.append(f"{mw}: startDatetime not parseable (dropped)")
        e_raw = mk.get("endDatetime")
        if e_raw is None:
            rep.warnings.append(f"{mw}: no endDatetime — stays on screen until the end")
        else:
            e = dates.parse_app_datetime(e_raw)
            if e is None:
                rep.errors.append(f"{mw}: endDatetime not parseable (dropped)")
            elif s is not None and e < s:
                rep.errors.append(f"{mw}: ends before it starts (never visible)")
        c = mk.get("color")
        if c is not None and (not isinstance(c, str) or len(c) > 7):
            rep.errors.append(f"{mw}: color must be at most 7 chars (dropped)")
        if "mini" in mk and not isinstance(mk["mini"], bool):
            rep.warnings.append(f"{mw}: mini must be true or false (anything else imports as a normal marker)")
    if markers:
        minis = sum(1 for mk in markers if mk.get("mini") is True)
        rep.info.append(f"{len(markers)} markers" + (f" ({minis} mini)" if minis else ""))
    return rep


def _check_matching(a, b, where: str, rep: Report) -> None:
    """Flag splits and merges: one ring whose area continues as 2+ rings in the next keyframe
    (or the reverse). The engine pairs one of them and grows/collapses the rest in place, so
    the paired ring visibly slides. Fix with ring_groups (pieces keep their own rings)."""
    try:
        import shapely
    except ImportError:
        return
    min_area = 0.01  # deg²; ignore islets
    pa = [shapely.make_valid(shapely.Polygon(r)) for r in a]
    pb = [shapely.make_valid(shapely.Polygon(r)) for r in b]
    def comparable_pieces(whole, pieces) -> bool:
        # a small ring joining or leaving a big one is fine (it grows/collapses in place);
        # trouble is a ring that continues as 2+ pieces that each hold >= 25% of it
        shares = sorted((whole.intersection(q).area for q in pieces
                         if q.area >= min_area and whole.intersects(q)), reverse=True)
        return len(shares) >= 2 and shares[1] >= 0.25 * whole.area

    splits = sum(1 for qa in pa if qa.area >= min_area and comparable_pieces(qa, pb))
    merges = sum(1 for qb in pb if qb.area >= min_area and comparable_pieces(qb, pa))
    if splits or merges:
        what = " and ".join(x for x in (f"{splits} ring split(s)" if splits else "",
                                         f"{merges} ring merge(s)" if merges else "") if x)
        rep.warnings.append(f"{where}: {what} — one piece will slide while the other grows/collapses in place; "
                            "consider ring_groups so the pieces keep separate rings throughout")
