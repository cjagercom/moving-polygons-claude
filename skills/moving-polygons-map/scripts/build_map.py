#!/usr/bin/env python3
"""Build an importable Moving Polygons map from a scenario spec.

    python build_map.py scenario.json --out DIR [--no-preview] [--tolerance-scale 1.5]

Writes DIR/<slug>.json (import via Dashboard -> Import), DIR/<slug>-preview.png
and DIR/<slug>-report.txt. Exit code 1 when there are errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mp import require_shapely  # noqa: E402

require_shapely()

from mp import build, validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario")
    ap.add_argument("--out", default=None, help="output directory (default: next to the scenario)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--tolerance-scale", type=float, default=1.0, help="multiply simplification tolerances")
    args = ap.parse_args()

    sc_path = Path(args.scenario)
    try:
        sc = json.loads(sc_path.read_text(encoding="utf8"))
    except json.JSONDecodeError as e:
        print(f"ERROR scenario is not valid JSON: {e}")
        return 1
    out_dir = Path(args.out) if args.out else sc_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = build.build(sc, tolerance_scale=args.tolerance_scale)
    except build.ScenarioError as e:
        print(f"ERROR {e}")
        return 1

    slug = build._slug(res.doc["name"])
    json_path = out_dir / f"{slug}.json"
    json_path.write_text(json.dumps(res.doc, separators=(",", ":"), ensure_ascii=False), encoding="utf8")

    rep = validate.validate(res.doc)
    rep.warnings = res.warnings + rep.warnings
    lines = [f"# {res.doc['name']}", f"file: {json_path.name}", ""]
    lines.append(f"scale={res.params['scale']} tolerance x{res.params['tolerance_scale']:.2f}")
    lines += res.report
    lines += ["", "## Keyframes"]
    for k in res.keyframes:
        lines.append(f"{k.id:>6}  {k.when.iso}  {k.label}")
    lines += ["", "## Validation", rep.text(), ""]
    if res.tests:
        passed = sum(1 for t in res.tests if t["ok"])
        rate = passed / len(res.tests)
        lines.append(f"## Test places: {passed}/{len(res.tests)} pass ({rate:.0%})")
        for t in res.tests:
            if not t["ok"]:
                tt = t["test"]
                where = tt.get("place") or f"{tt.get('lon')},{tt.get('lat')}"
                at = f" [{t['lon']:.4f}, {t['lat']:.4f}]" if t.get("lon") is not None and tt.get("place") else ""
                want = f"expected {tt.get('expect')}" if "expect" in tt else ""
                if "expect_not" in tt:
                    want += (", " if want else "") + f"not {tt['expect_not']}"
                lines.append(f"  MISS {t.get('kf', tt.get('at'))} | {where}{at} | {want} | "
                             f"got {t.get('error') or t['got']}" + (f" | {tt['note']}" if tt.get("note") else ""))
        if rate < 0.95:
            rep.warnings.append(f"test-place pass rate {rate:.0%} is below 95%")
    else:
        lines.append("## Test places: none (add 'tests' to check borders)")
    report_path = out_dir / f"{slug}-report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    previews = []
    if not args.no_preview:
        from mp import preview

        previews = preview.render(res.doc, sc["bbox"], out_dir / f"{slug}-preview.png", tests=res.tests)

    print("\n".join(lines))
    print("")
    print(f"wrote {json_path}")
    print(f"wrote {report_path}")
    for p in previews:
        print(f"wrote {p}")
    print(f"RESULT errors={len(rep.errors)} warnings={len(rep.warnings)} size={res.params['size_bytes'] / 1e6:.2f}MB")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
