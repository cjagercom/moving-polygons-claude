"""Build importable Moving Polygons map JSON from a scenario spec.

Modules: dates (app date convention), pacing (playback timing, mirrors
app/lib/animation/timeline.ts), data (bundled geodata), geo (km shapes),
regions (region expressions), build (scenario -> import JSON),
validate (import contract + quality checks), preview (contact sheet).
"""

import sys

MIN_SHAPELY = (2, 1)


def require_shapely() -> None:
    """Fail early with an actionable message (claude.ai sandboxes may lack shapely 2.1)."""
    try:
        import shapely
    except ImportError:
        sys.exit('shapely is missing: pip install "shapely>=2.1" matplotlib')
    version = tuple(int(p) for p in shapely.__version__.split(".")[:2])
    if version < MIN_SHAPELY:
        sys.exit(f'shapely {shapely.__version__} is too old (need >= 2.1): pip install -U "shapely>=2.1"')
