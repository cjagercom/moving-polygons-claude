#!/usr/bin/env python3
"""Validate any Moving Polygons import JSON (built, hand-made or exported).

    python validate_map.py map.json [more.json ...]

Errors are things the app's importer would silently drop (or that break
playback); warnings are quality issues. Exit code 1 when any file has errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mp import validate  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    bad = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        print(f"== {path.name}")
        try:
            doc = json.loads(path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR cannot read: {e}")
            bad += 1
            continue
        rep = validate.validate(doc)
        print(rep.text())
        print(f"RESULT errors={len(rep.errors)} warnings={len(rep.warnings)}\n")
        bad += bool(rep.errors)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
