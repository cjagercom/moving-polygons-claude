"""Contact sheet: one panel per keyframe with land, water, layers and active markers."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import box

from . import data, dates

PER_PAGE = 20


def _paths(geom):
    for poly in shapely.get_parts(geom):
        if isinstance(poly, shapely.Polygon) and not poly.is_empty:
            yield np.asarray(poly.exterior.coords)


def _state_at(ph: dict, ms: int):
    cur, color = None, None
    for inst in ph["instances"]:
        t = dates.parse_app_datetime(inst["datetime"])
        if t is not None and t <= ms:
            cur, color = inst["geometry"], inst.get("color")
    return cur, color or ph["color"]


def render(doc: dict, bbox, out: Path, title: str | None = None, tests: list[dict] | None = None) -> list[Path]:
    """One panel per keyframe. Test places are drawn on their keyframe: green dot = pass,
    red cross = miss — the quickest way to see whether shapes sit where the research says."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.patches import Patch

    times = sorted({dates.parse_app_datetime(i["datetime"]) for ph in doc["polygonPlaceholders"]
                    for i in ph["instances"]} - {None})
    labels = {}
    for ph in doc["polygonPlaceholders"]:
        for i in ph["instances"]:
            t = dates.parse_app_datetime(i["datetime"])
            if t is not None and t not in labels and i.get("label"):
                labels[t] = i["label"]
    span = (times[-1] - times[0]) if len(times) > 1 else float("inf")
    kf_ms: dict[str, int] = {}
    if tests:
        # map keyframe ids to their instance times (tests carry the keyframe id)
        for tr in tests:
            at = tr.get("kf")
            if at and at not in kf_ms and tr.get("kf_ms") is not None:
                kf_ms[at] = tr["kf_ms"]

    frame = box(*bbox)
    land = data.land_in(bbox)
    try:
        lk = data.lakes()
        lakes = [lk.geoms[i].intersection(frame) for i in lk.query_bbox(bbox)]
        rv = data.rivers()
        rivers = [rv.geoms[i].intersection(frame) for i in rv.query_bbox(bbox)]
    except FileNotFoundError:
        lakes, rivers = [], []
    river_segs = []
    for r in rivers:
        for part in shapely.get_parts(r):
            if isinstance(part, shapely.LineString) and not part.is_empty:
                river_segs.append(np.asarray(part.coords))

    lat = (bbox[1] + bbox[3]) / 2
    aspect = 1 / max(math.cos(math.radians(lat)), 0.2)
    w_deg, h_deg = bbox[2] - bbox[0], bbox[3] - bbox[1]
    panel_w = 4.2
    panel_h = max(1.6, min(6.0, panel_w * h_deg * aspect / w_deg)) + 0.35
    outputs = []
    pages = [times[i:i + PER_PAGE] for i in range(0, len(times), PER_PAGE)] or [[]]
    for page_no, page in enumerate(pages):
        n = max(1, len(page))
        cols = min(4, n)
        rows = math.ceil(n / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(panel_w * cols, panel_h * rows + 0.9), squeeze=False)
        for ax in axes.flat:
            ax.set_axis_off()
        for idx, t in enumerate(page):
            ax = axes.flat[idx]
            ax.set_xlim(bbox[0], bbox[2])
            ax.set_ylim(bbox[1], bbox[3])
            ax.set_aspect(aspect)
            ax.set_facecolor("#dbe7f0")
            ax.set_axis_on()
            ax.set_xticks([])
            ax.set_yticks([])
            ax.add_collection(PolyCollection(list(_paths(land)), facecolor="#f4f1ea", edgecolor="#b9b3a6", linewidth=0.3))
            lake_paths = [p for g in lakes for p in _paths(g)]
            if lake_paths:
                ax.add_collection(PolyCollection(lake_paths, facecolor="#dbe7f0", edgecolor="#9fb6c8", linewidth=0.3))
            if river_segs:
                ax.add_collection(LineCollection(river_segs, colors="#8fb0cc", linewidths=0.4))
            for ph in doc["polygonPlaceholders"]:
                geom, color = _state_at(ph, t)
                if not geom:
                    continue
                rings = [np.asarray(r) for r in geom]
                ax.add_collection(PolyCollection(rings, facecolor=color, alpha=0.55, edgecolor=color, linewidth=0.8))
            for mk in doc.get("markers") or []:
                s = dates.parse_app_datetime(mk["startDatetime"])
                e = dates.parse_app_datetime(mk["endDatetime"]) if mk.get("endDatetime") else None
                if s is not None and s <= t and (e is None or t <= e):
                    mini = mk.get("mini") is True
                    ax.plot(mk["longitude"], mk["latitude"], "o", ms=2.2 if mini else 4,
                            color=mk.get("color") or "#ef4444", markeredgecolor="white",
                            markeredgewidth=0.4 if mini else 0.6)
                    ax.annotate(mk["title"][:44], (mk["longitude"], mk["latitude"]), fontsize=4 if mini else 5.5,
                                xytext=(3, 3), textcoords="offset points", color="#666" if mini else "#222")
            for tr in tests or []:
                if tr.get("lon") is None or tr.get("kf") is None or kf_ms.get(tr["kf"]) != t:
                    continue
                tt = tr["test"]
                name = str(tt.get("place") or tt.get("note") or "")[:24]
                if tr["ok"]:
                    ax.plot(tr["lon"], tr["lat"], "o", ms=3, color="#1e8449", markeredgecolor="white",
                            markeredgewidth=0.4, zorder=5)
                else:
                    ax.plot(tr["lon"], tr["lat"], "x", ms=5, mew=1.4, color="#c0392b", zorder=6)
                    name = f"{name} ≠ {tt.get('expect')}"
                if name:
                    ax.annotate(name, (tr["lon"], tr["lat"]), fontsize=4.8, xytext=(2, -6),
                                textcoords="offset points", color="#1e8449" if tr["ok"] else "#c0392b")
            tick = dates.format_tick(dates.from_ms(t), span)
            label = labels.get(t, "")
            ax.set_title(label or tick, fontsize=7.5, loc="left")
        handles = [Patch(facecolor=ph["color"], alpha=0.6, label=ph["name"][:60]) for ph in doc["polygonPlaceholders"]]
        fig.legend(handles=handles, loc="lower center", ncol=min(4, max(1, len(handles))), fontsize=7, frameon=False)
        page_title = title or doc.get("name", "")
        if len(pages) > 1:
            page_title += f" ({page_no + 1}/{len(pages)})"
        fig.suptitle(page_title, fontsize=10)
        fig.tight_layout(rect=(0, 0.06, 1, 0.97))
        path = out if len(pages) == 1 else out.with_name(f"{out.stem}-{page_no + 1}{out.suffix}")
        fig.savefig(path, dpi=110)
        plt.close(fig)
        outputs.append(path)
    return outputs
