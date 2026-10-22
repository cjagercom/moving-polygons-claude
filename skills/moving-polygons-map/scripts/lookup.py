#!/usr/bin/env python3
"""Look things up in the bundled data while writing a scenario.

    python lookup.py place "Waterloo" [--country BE]      GeoNames places (country = ISO2)
    python lookup.py admin0 "Italy"                        country codes (ISO3)
    python lookup.py admin1 "Lombardia" [--country ITA]    admin-1 units by name/code
    python lookup.py admin1 --country ITA                  list a country's admin-1 units
    python lookup.py clio "Sardinia" [--year 1859]         Cliopatria polities (substring match)
    python lookup.py where 9.19 45.46 [--year 1859]        what contains a point (admin + Cliopatria)
    python lookup.py river "Rhine"                         river names in the data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mp import require_shapely  # noqa: E402

require_shapely()

from mp import data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["place", "admin0", "admin1", "clio", "where", "river"])
    ap.add_argument("query", nargs="*")
    ap.add_argument("--country")
    ap.add_argument("--year", type=float)
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    q = " ".join(a.query)

    if a.what == "place":
        for p in data.find_places(q, a.country, a.limit):
            print(f"{p['name']:<32} [{p['lon']:.4f}, {p['lat']:.4f}]  {p['country']}  pop {p['pop']:,}  {p['fcode']}")
        return 0

    if a.what == "admin0":
        nq = data.norm(q)
        for pr in data.admin0().props:
            if nq in data.norm(pr.get("admin", "")) or nq == data.norm(pr.get("adm0_a3", "")):
                print(f"{pr['adm0_a3']}  {pr.get('admin')}")
        return 0

    if a.what == "admin1":
        fs = data.admin1()
        nq = data.norm(q)
        c = data.norm(a.country) if a.country else None
        n = 0
        for pr in fs.props:
            if c and c not in (data.norm(pr.get("adm0_a3", "")), data.norm(pr.get("admin", ""))):
                continue
            names = [pr.get("name") or "", pr.get("name_en") or "", pr.get("region") or "",
                     *(pr.get("name_alt") or "").split("|")]
            if nq and not any(nq in data.norm(x) for x in names) and nq != data.norm(pr.get("adm1_code", "")):
                continue
            print(f"{pr['adm1_code']:<10} {pr.get('name')!s:<32} {pr.get('adm0_a3')}  {pr.get('type_en') or ''}"
                  f"{'  region: ' + pr['region'] if pr.get('region') else ''}"
                  f"{'  alt: ' + pr['name_alt'] if pr.get('name_alt') else ''}")
            n += 1
            if n >= a.limit * 10:
                break
        return 0

    if a.what == "clio":
        nq = data.norm(q)
        rows: dict[str, list[tuple[int, int]]] = {}
        for (k, name, y0, y1, _) in data.clio_index():
            if nq in k and (a.year is None or y0 <= a.year <= y1):
                rows.setdefault(name, []).append((y0, y1))
        for name, spans in sorted(rows.items())[: a.limit]:
            spans.sort()
            txt = ", ".join(f"{s}..{e}" for s, e in spans[:10]) + (" …" if len(spans) > 10 else "")
            print(f"{name:<48} {txt}")
        return 0

    if a.what == "where":
        lon, lat = float(a.query[0]), float(a.query[1])
        a0 = [data.admin0().props[i].get("admin") for i in data.admin0().containing(lon, lat)]
        a1 = [f"{data.admin1().props[i]['adm1_code']} {data.admin1().props[i].get('name')}"
              for i in data.admin1().containing(lon, lat)]
        print(f"admin0: {a0 or '-'}")
        print(f"admin1: {a1 or '-'}")
        if a.year is not None:
            print(f"Cliopatria {int(a.year)}: {data.clio_at_point(lon, lat, a.year) or '-'}")
        return 0

    if a.what == "river":
        nq = data.norm(q)
        seen = set()
        for pr in data.rivers().props:
            for key in ("name", "name_en"):
                v = pr.get(key)
                if v and nq in data.norm(v) and v not in seen:
                    seen.add(v)
                    print(v)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
