# Scenario spec

A scenario is one JSON file. `build_map.py` turns it into the import JSON.

```json
{
  "map":       {"name": "…", "description": "…", "mapStyle": "light"},
  "scale":     "battle | campaign | regional | continental",
  "bbox":      [min_lon, min_lat, max_lon, max_lat],
  "build":     {"territory_clip": "land"},
  "keyframes": [{"id": "K1", "date": "…", "label": "…"}],
  "regions":   {"name": <region expression>},
  "layers":    [{"id": "…", "name": "…", "color": "#RRGGBB", "kind": "territory", "states": [...]}],
  "markers":   [{"title": "…", "lon": 0, "lat": 0, "start": "K1", "end": "auto"}],
  "tests":     [{"at": "K1", "place": "Milan", "expect": "austria"}]
}
```

Coordinates are always `[lon, lat]` (x, y), never `[lat, lon]`.

## map

| Field | Notes |
|---|---|
| `name` | required, ≤ 100 chars; becomes the file name slug |
| `description` | shown on the public map page; tell the story in 2–4 sentences and list sources. If you use Cliopatria, the builder appends the CC BY attribution automatically. |
| `casualtyBar` | optional, copied to the import JSON as is: see `casualtyBar` in `import-format.md` |
| `mapStyle` | `light` (default), `dark`, `streets`, `outdoors`, `satellite`, `satellite-streets`, `vintage`, `vintage-soft`, `tactical`, `dark-glow`, `tapestry`, or a full `mapbox://styles/…` URL |

## scale and build

`scale` sets the defaults below. Override any of them under `build`.

| | battle | campaign | regional | continental |
|---|---|---|---|---|
| `tolerance_km` (border simplification) | 0.015 | 0.4 | 1.0 | 3.0 |
| `free_tolerance_km` (free layers) | 0.008 | 0.15 | 0.4 | 1.2 |
| `decimals` (coordinate rounding) | 5 | 4 | 4 | 3 |
| `min_island_km2` (smaller pieces dropped) | 0.002 | 1 | 8 | 80 |
| `min_hole_km2` (smaller holes filled / enclaves absorbed) | 0.02 | 10 | 40 | 400 |
| `min_cell_km2` (slivers folded into neighbours) | 0.001 | 0.3 | 2 | 15 |
| `clio_coast_km` (Cliopatria outlines pulled out to the coast) | 0 | 4 | 8 | 15 |
| `test_snap_km` (a test place this close to a territory counts as inside) | 0.03 | 2 | 5 | 10 |

`build.fill_gaps_km` (default off): thin unclaimed strips narrower than this, typical where shapes from different
sources meet (OHM vs admin units), join the neighbour with the longest shared border, per keyframe.

`build.territory_clip`: `"land"` (default) clips territory layers to Natural Earth land.
Use `"none"` for battles inland, where the whole bbox is ground.

If the output would exceed 3.3 MB the builder retries with coarser tolerances automatically
(noted in the report). `--tolerance-scale 1.5` on the command line does the same by hand.

## keyframes

```json
{"id": "K3", "date": "1860-03-24", "label": "Mar 1860 · Centre joins; Nice and Savoy to France"}
```

- `id`: any unique string; layers, markers and tests refer to it. `K1`, `K2`… is fine.
- `date` formats:
  - `1815`
  - `1815-06`
  - `1815-06-18` (12:00 UTC)
  - `1815-06-18T11:30` (a clock time: write local time as is; the app shows it as written)
  - `-0216-08-02` or `216 BC` for BC. `-0216` is the app's convention for 216 BC.
- `label`: ≤ 50 characters. It is the caption shown during playback. Start it with the date the
  way people say it ("1859", "Jul 1859", "11:30"), then what changed.
- Keyframes are sorted by date; two keyframes may not share a date and time.
- Keyframes whose borders don't change are fine (a label-only moment). The builder makes sure
  each keyframe appears on the timeline.

## layers

```json
{"id": "italy", "name": "Kingdom of Sardinia → Kingdom of Italy", "color": "#2f6db5",
 "kind": "territory", "clip": "land",
 "ring_groups": [{"id": "sicily", "region": {"admin1": "Sicily", "country": "ITA"}}],
 "states": [
   {"from": "K1", "region": "sardinia_1858"},
   {"from": "K5", "region": "italy_1861", "color": "#3a9a5b"},
   {"at": "K9", "region": null}
 ]}
```

| Field | Notes |
|---|---|
| `id` | unique; used by tests |
| `name` | ≤ 100 chars; shown in the legend and layer list |
| `color` | `#RRGGBB`, the layer's base colour |
| `kind` | `territory` (default) or `free` |
| `clip` | `land` (territory default), `sea` (fleets), `none` (free default) |
| `ring_groups` | territory only: pieces that must keep their own ring throughout (see recipes: splits) |
| `states` | what the layer is at each keyframe |

**Territory layers** together form one partition of the land:
- They never overlap. Where two regions overlap at a keyframe, the layer listed **later** in `layers` wins.
- Neighbours share bit-identical borders, so the app morphs them flush.
- Unclaimed land stays empty.
- Put broad or background claims first and specific or winning claims later.

**Free layers** (armies, fleets, arrows, fronts, zones of operation) are evaluated on their own
and may overlap anything. The file lists territory layers first and free layers after them,
because later layers are drawn on top.

**States** say what the layer is at each keyframe:
- `{"from": "K2", "to": "K5", "region": …}` covers K2..K5. `from` defaults to the first
  keyframe and `to` to the last.
- `{"at": "K4", "region": …}` covers K4 only.
- `from`/`to`/`at` may also be dates: `from` snaps to the first keyframe on or after the date,
  `to` to the last keyframe on or before it.
- Later states override earlier ones. So a list of `from` states reads like a timeline:
  `[{"from": "K1", …A}, {"from": "K4", …B}]` means A for K1–K3 and B from K4.
- `"region": null` means absent: the layer fades out and later fades back in if a state brings it back.
- `"color": "#RRGGBB"` recolours the layer from that keyframe (colours blend during the morph).
  Use it for successions such as Sardinia → Italy, or a dynasty change.
- `"grow": true` (free layers): at the keyframe before this state, a short stub of the arrow is
  shown and then grows to full length. Use it for attack arrows (details in the recipes).

## regions (named, reusable)

`"regions": {"name": <expression>}`. Refer to one by its bare name (`"region": "tuscany"`) or
`{"ref": "tuscany"}`. Regions may refer to other regions.

## Region expressions

| Expression | Meaning |
|---|---|
| `"name"` | a named region |
| `"admin0:FRA"`, `"admin1:Lombardia/ITA"`, `"clio:Roman Empire"` | shorthands |
| `[expr, expr]` | union |
| `{"admin0": "FRA"}` or `{"admin0": ["FRA", "BEL"]}` | countries (ISO3 or the Natural Earth name) |
| `{"admin1": "Veneto", "country": "ITA"}` | admin-1 units by name, English name, alternate name, **region** ("Veneto" selects all its provinces), `adm1_code` or ISO 3166-2. `country` avoids ambiguity. |
| `{"clio": "Papal States", "year": 1858}` | Cliopatria polity at a year. Omitting `year` uses the keyframe's year. `"window": 10` accepts the nearest record within 10 years. `"coast_km": 0` switches off the coast pull-out. |
| `{"file": "ohm/prussia_1850.geojson"}` | union of the polygons in a GeoJSON file, path relative to the working directory (run the builder from the scenario's folder). For sharper borders from another source, e.g. OpenHistoricalMap (CC0) relations. Clip it like a Cliopatria shape; the partition rules still apply. |
| `{"snap": expr, "to": "admin1", "min_share": 0.5}` | whole admin units that are at least 50% inside `expr`: turns a coarse outline into crisp, coast-accurate units |
| `{"poly": [[lon, lat], …]}` | hand-drawn polygon. Clipped to land, so only its inland edges matter: draw generously out to sea. |
| `{"bbox": [w, s, e, n]}` | rectangle |
| `{"circle": [lon, lat] or "Place", "radius_km": 5}` | disk |
| `{"disks": [[lon, lat], "Lübeck", …], "radius_km": 25, "close_km": 10}` | union of disks; `close_km` bridges gaps (a league, a region of towns) |
| `{"line": [[lon, lat], …], "width_km": 0.6}` | a thick smoothed line (a front, a ridge held by an army, a wall). `"smooth": false` keeps straight segments. |
| `{"formation": [lon, lat], "width_km": 1.6, "depth_km": 0.45, "facing": 0, "rounding": 0.3}` | a unit block centred on the point: frontage `width_km` across the facing direction, `depth_km` along it. So the block reaches only ±depth/2 in front of and behind the point (±0.22 km here). `facing` is a compass bearing (0 = north, 90 = east). |
| `{"arrow": [[lon, lat], …], "width_km": 0.2, "head_km": 0.4, "head_width_km": 0.5, "progress": 1}` | a smoothed arrow along the path; `progress < 1` draws the first part only |
| `{"side": expr, "line": [[lon, lat], …], "keep": "left" or "right" or [lon, lat] or "Place"}` | cut `expr` by a line (extended past its ends) and keep one side. Prefer `keep` as a point on the wanted side. |
| `{"side": expr, "line": {"river": "Rhine"}, "keep": [lon, lat]}` | cut along a Natural Earth river (the main stem inside the bbox) |
| `{"union": [a, b]}` `{"minus": [a, b, c]}` `{"intersect": [a, b]}` | set operations (`minus` = a − b − c) |
| `{"buffer": expr, "km": 5}` | grow (or shrink, with negative km) |
| `{"hull": expr or [points], "buffer_km": 5}` | convex hull |
| `{"all": true}` | the whole build domain (land in the bbox, or the bbox with `territory_clip: none`) |

Place names are resolved from the bundled GeoNames gazetteer (towns of about 1,000 people and up,
with historical and foreign names such as Danzig, Königgrätz or Austerlitz for towns ≥ 3,000):
- The largest match within or near the bbox wins, and `"Waterloo, BE"` restricts to an ISO2 country.
- A name that only matches places far outside the bbox is an error, not a silent jump abroad.
- Use `lookup.py place` to check. Give `[lon, lat]` from your research for villages, farms, hills
  and other battlefield landmarks.

## markers

```json
{"title": "Battle of Solferino", "description": "Franco-Sardinian victory…", "lon": 10.5664, "lat": 45.3717,
 "start": "1859-06-24", "end": "auto", "color": "#ef4444"}
```

| Field | Notes |
|---|---|
| `title` | ≤ 100 chars |
| `description` | optional; shown when the marker is clicked |
| `lon`/`lat`, or `place` | position |
| `start` | keyframe id or date |
| `end` | `auto` (default): visible for at least ~1.4 s of playback and through the next keyframe |
| | `{"days": 30}` / `{"years": 5}`: a fixed window |
| | a keyframe id or date |
| | `null`: stays to the end (avoid; they pile up) |
| `color` | `#RRGGBB`; default red |
| `mini` | `true` = mini event: a small dot, title on hover, no pause. Use for the many small actions (skirmishes, raids, landings, sinkings, local uprisings) around the big events, so the main markers stay few. Give them a short `end` (`{"days": …}` or `auto`) and a muted or side colour |

```json
{"title": "Raid on Dieppe", "place": "Dieppe", "start": "1942-08-19", "end": {"days": 20}, "color": "#6b7280", "mini": true}
```

## tests

```json
{"at": "K3", "place": "Florence", "expect": "italy", "note": "annexed March 1860"}
{"at": "K2", "place": "Trieste", "expect": ["austria", "austria-hungary"]}
{"at": "K7", "lon": 4.4121, "lat": 50.6779, "expect_not": "lhs", "note": "La Haye Sainte has fallen"}
{"at": "K1", "place": "Lyon", "expect": null}
```

- `expect` is a layer id, a list of acceptable ids, or `null`.
  - `null` means no territory layer may contain the point.
  - On a map without territory layers (most battles), `null` means no layer at all.
- `expect_not` is a layer id or a list of ids that must **not** contain the point, e.g. a unit that
  has withdrawn. It can be combined with `expect`.
- A test passes if the expected layer contains the point at that keyframe. A territory point
  within `test_snap_km` of the expected territory also counts (ports on a simplified coast).
- The report lists misses as `MISS K3 | Florence | expected italy | got ['tuscany']`.
- Write tests from the research, not from the output. Their value is catching disagreement.
  At battle scale, anchor them to named places the narrative puts a unit in ("Pratzen heights:
  Saint-Hilaire at 09:00"), not to where you happened to draw the block.
- Test places and markers outside the bbox are reported as warnings. The report prints the
  coordinates a place name resolved to, and the preview draws every test on its keyframe
  (green dot = pass, red cross = miss).
