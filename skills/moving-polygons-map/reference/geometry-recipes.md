# Geometry recipes

How to turn research into region expressions for common kinds of maps, and what to do about
each report message. The two files in `examples/` are complete versions of recipes 2 and 5.

## How the app animates (why the recipes look like this)

- Between two keyframes each layer **morphs** from its old shape to its new one. Rings are
  paired by position and size.
  - A ring with no partner shrinks away or grows in place.
  - A layer going from nothing to something (or back) **crossfades** instead of morphing.
- Territory layers built by this skill share their borders exactly, so neighbours slide together
  with no gaps or overlaps mid-morph.
- Each keyframe gets roughly the same screen time (proportional to real time, but never below
  0.6× an average transition). About 0.8 s per transition at 1× speed.
- Layers later in the file are drawn on top. Fills are semi-transparent, so overlapping free layers blend.

## 1. Borders that follow modern units (most maps after ~1800, and many before)

Where historical borders match modern admin units, use them. They are crisp, coast-accurate and
consistent with each other.

```json
"tuscany": {"minus": [{"admin1": "Toscana", "country": "ITA"}, {"admin1": "Massa-Carrara", "country": "ITA"}]},
"romagna": {"admin1": ["Bologna", "Ferrara", "Ravenna", "Forlì-Cesena", "Rimini"], "country": "ITA"}
```

- `lookup.py admin1 --country ITA` lists a country's units, with the region each belongs to.
- Admin-1 is provinces in some countries (Italy, Spain) and states or regions in others (Germany,
  France has départements). Regions select all their units: `{"admin1": "Veneto", "country": "ITA"}`.
- Natural Earth alternate names can be wrong (Liguria's provinces list "Latium"). Prefer region
  names, unit names or codes, and let the tests catch mistakes.

## 2. Historical states (Cliopatria)

`{"clio": "Papal States", "year": 1858}` gives the polity's outline in that year, from about
1,600 polities, 3400 BC–2024. Find names and year spans with `lookup.py clio "papal"`. Names are exact.

Cliopatria outlines are coarse (±10–30 km) and neighbours don't always agree, so:
- **Clip against modern countries** it plausibly covered, or subtract the ones it didn't.
  This removes spill-over into neighbours:
  ```json
  "sardinia_1858": {"union": [{"intersect": [{"clio": "Kingdom of Sardinia", "year": 1858}, "admin0:ITA"]}, "savoy_nice"]},
  "austria_1858": {"union": [{"minus": [{"clio": "Austrian Empire", "year": 1858}, "admin0:ITA", "admin0:CHE"]},
                             {"admin1": ["Lombardia", "Veneto"], "country": "ITA"}]}
  ```
- **Mix sources:** admin units where the old border matches a modern one (the Italian part of
  Austria above), Cliopatria for the rest.
- **Coasts** are handled automatically: `clio_coast_km` pulls outlines out to the real coastline.
- **Snap** a coarse outline to whole units when that's close enough:
  `{"snap": {"clio": "Duchy of Milan", "year": 1500}, "to": "admin1"}`.
- **Pin years** explicitly (`"year": 1858`) rather than relying on the keyframe's year:
  Cliopatria's record for a war year may show the post-war state.
- **Small or missing polities:** many duchies and free cities are absent. Build them from admin
  units, `poly` or `disks`, and list them later than the big state around them.
- **Fix wrong areas with a rule:** add a `poly` covering the area to the correct layer (later
  layers win), e.g. the Neapolitan Terra di Lavoro that Cliopatria gives to the Papal States:
  ```json
  "terra_di_lavoro_nw": {"poly": [[13.28, 41.28], [13.33, 41.40], [13.50, 41.52], …]},
  "two_sicilies_1858": {"union": [{"intersect": [{"clio": "Kingdom of the Two Sicilies", "year": 1858}, "admin0:ITA"]}, "terra_di_lavoro_nw"]}
  ```

## 3. Treaty lines and partitions

A treaty that splits a region along a line: cut with `side`, keeping the side that contains a
known point.

```json
{"side": "two_sicilies_1858",
 "line": [[13.90, 41.00], [14.10, 41.12], [14.40, 41.15], [14.80, 41.35], [15.10, 41.70], [15.20, 42.00]],
 "keep": "Naples"}
```

- The line is extended past both ends, so it only needs to cover the area being cut. It must cross it completely.
- Rivers: `"line": {"river": "Danube"}` (check names with `lookup.py river`).
- For a demarcation line from a source, write its waypoints with the source's precision. Get
  coordinates of named villages or points with `lookup.py place` or from web research.
- The two sides usually go to two layers: give one layer `keep: A` and the other `keep: B`, or
  give the whole region to one and the cut part to a later layer.

## 4. Wars: occupation and fronts over time

- Occupied zones are their own territory layers (e.g. "German-occupied France"), listed after the
  states they occupy, so they win there. When the occupation ends, set `"region": null` and the
  state reappears underneath.
- Front lines move as `side` cuts with a new line per keyframe. Keep the number of vertices per
  line similar between keyframes so the morph is smooth.
- A contested strip can be a free layer (a `line` with `width_km`) drawn on top.
- Dense periods (a week of fighting) need their own keyframes; quiet years need few.

## 5. Battles

Use `"scale": "battle"`, `"build": {"territory_clip": "none"}`, and usually `mapStyle: "outdoors"`.
Everything is usually a **free** layer.

- **Army lines:** `{"line": [[lon, lat] … along the ridge or road], "width_km": 0.5}`. When a line
  moves, give every position of it the **same number of waypoints in the same order** (west→east)
  and a similar width; otherwise the shape bloats mid-morph.
- **Units:** `{"formation": [lon, lat], "width_km": 1.6, "depth_km": 0.45, "facing": 355}`.
  One layer per corps or division that moves. Move it by giving the same layer a new position in
  a later state; it slides there.
- **Strongpoints:** small formations (a farm, a village) that disappear (`null`) when they fall,
  or change `color` when they change hands.
- **Attacks:** a separate free layer per arrow, with `"grow": true` on the state where it
  appears and `null` in the next:
  ```json
  {"id": "arrow-cavalry", "name": "Charge of the Union Brigade", "color": "#a93226", "kind": "free",
   "states": [{"at": "K4", "grow": true, "region": {"arrow": [[4.4150, 50.6815], [4.4185, 50.6765], [4.4205, 50.6700]], "width_km": 0.14, "head_km": 0.3}},
              {"from": "K5", "region": null}]}
  ```
  `grow` puts a short stub at the previous keyframe, which grows along the path into the full
  arrow. The stub is visible at that earlier keyframe, so start the path where the attack
  starts. Don't reuse one arrow layer for two different attacks: each would morph into the next.
- **Controlled ground** (optional): territory layers with `side` cuts along the front.
- Times of day go in the date (`1815-06-18T13:30`), and labels start with the time (`13:30 · …`).
  The timeline shows "18 Jun 13:30" ticks automatically for maps shorter than 3 days.
- Accounts disagree on times. Pick one widely used chronology, say so in the description, and
  keep keyframes at least ~30 minutes apart unless something decisive happens.

### Vanished terrain

Drained lakes and ponds (the Satschan ponds at Austerlitz), former marshes, old coastlines and
river courses matter for the story but aren't in modern data:
- Draw them as a free layer listed **first** among the free layers (so units draw on top).
- Give it a pale, muted colour (`#9ec5de` for water, `#b8b09a` for marsh) and a clear name
  ("Satschan ponds (drained after 1805)").
- Give it one state for the whole map.

## 6. Naval

Fleets are free layers with `"clip": "sea"` (land is cut away), usually formations or lines.
Coastal cities and ports are markers.

## 7. Spread and diffusion (plague, religion, language, revolt)

- By units: a territory layer whose region grows keyframe by keyframe (admin units or Cliopatria
  outlines, unioned progressively).
- By radius from places: `{"disks": ["Messina", "Genoa", "Marseille"], "radius_km": 60, "close_km": 40}`
  with growing radius or more places per keyframe.
- Clip to a boundary with `intersect` if the spread stops somewhere.

## 8. Leagues, networks and trade (Hanseatic League, colonies)

- Members are `disks` around member towns (`close_km` merges neighbours into a region).
  Tier the radius by importance. Outposts far away are separate rings, which is fine.
- Towns joining or leaving: change the disk list per keyframe.
- Kontors and trading posts: markers, or small circles on a separate layer.

## 9. Migrations, campaigns, routes

- A route is an `arrow` along the path (`progress` grows it over several keyframes:
  `0.3 → 0.6 → 1.0`), or a `line` for a road or wall.
- A moving army is a `formation` whose position changes per keyframe. A single ring moving
  anywhere is a deliberate move; the engine slides it.

## 10. Rings, splits and successions

- A territory made of separate pieces (mainland + islands) is several rings. The engine pairs
  rings by position and size.
- **Split or merge warnings:** when a treaty cuts one piece into two comparable pieces (or joins
  two), one piece slides while the other grows or collapses in place. Fix: `ring_groups` on that
  layer, listing the part that should always be its own ring:
  ```json
  "ring_groups": [{"id": "finland", "region": {"admin0": "FIN"}}]
  ```
  The pieces are then separate rings throughout. A faint seam line shows where they touch, which
  is the price of a stable morph.
- **Succession** (same territory, new ruler or dynasty):
  - Same layer, new `color` (a colour blend; the legend keeps one name). Name the layer for both,
    e.g. "Kingdom of Sardinia → Kingdom of Italy".
  - Or two layers, where the old one gets `null` at the keyframe the new one starts (a crossfade;
    the legend shows both).

## Report messages → fixes

| Message | Likely cause | Fix |
|---|---|---|
| `MISS K3 \| X \| expected a \| got ['b']` | wrong region, or a later layer claims X | check the research; add or cut a region; mind layer order (later wins) |
| `MISS … got None` | X is unclaimed: a gap, a coastal point, or outside the bbox | extend the region (`poly`, more units); for ports `test_snap_km` usually covers it; use a nearby inland point for lagoon or island towns |
| `detached inland fragment(s) … at [lon, lat]` | two sources disagree about a border, leaving a piece behind | clip the Cliopatria shape (`intersect`/`minus` admin0), or add the area to the right layer |
| `territory layers a and b overlap` | should not happen; it means a hole or enclave was mishandled | report it; as a workaround, subtract the enclave explicitly |
| `ring split(s)` / `ring merge(s)` | a piece cut in two, or two joined | `ring_groups`, or an extra keyframe so the change happens in two steps |
| `near-coincident keyframes` | two keyframes almost at the same time | merge them into one keyframe with a combined label |
| `no endDatetime — stays on screen` | marker `end: null` | give it `auto` or a window |
| `size … close to / over budget` | too many vertices | coarser `tolerance_km`, fewer keyframes that change borders, a tighter bbox |
| `label is N chars (max 50)` | long label | shorten; move detail to a marker description |
| `cut line does not cross the area` | a `side` line ends inside the region | extend the line's first and last points outward |
| `Cliopatria … has no record for YEAR` | the polity didn't exist then, or a name mismatch | `lookup.py clio`, set `window`, or pick the right year |
