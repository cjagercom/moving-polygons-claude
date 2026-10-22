---
name: moving-polygons-map
description: Research a historical event, war, battle, empire or era and build an importable Moving Polygons map JSON (animated borders, army positions, markers). Use for any "make a map of…" idea.
---

# Moving Polygons map builder

Turns an idea ("the Battle of Austerlitz", "the partitions of Poland", "the Mongol conquests")
into a JSON file that imports into movingpolygons.com via **Dashboard → Import**, plus a
preview image to check before importing.

You never hand-write coordinates for the final file. You research, write a compact
**scenario** (keyframes, layers made of region expressions, markers, test places), and the
bundled builder turns it into the import JSON with shared borders, correct dates, and a
validation report.

## Files in this skill

| Path | Use |
|---|---|
| `scripts/build_map.py` | scenario → `<slug>.json` + `-preview.png` + `-report.txt` |
| `scripts/lookup.py` | find admin units, Cliopatria polities, places, rivers, "what is at lon,lat" |
| `scripts/validate_map.py` | check any import JSON (also hand-made or exported ones) |
| `reference/scenario-spec.md` | every scenario field and region expression — **read before writing a scenario** |
| `reference/geometry-recipes.md` | how to model empires, treaties, fronts, battles, fleets, spread; fixes for report messages |
| `reference/research-method.md` | how to research: keyframes, test places, sources, dates (BC, Julian, times of day) |
| `reference/import-format.md` | the app's import format and its hidden limits |
| `reference/styling.md` | colours, map styles, labels, descriptions |
| `examples/*.scenario.json` | two complete worked examples (a battle; a territorial map) |
| `data/` | Natural Earth admin/land/rivers, Cliopatria borders 3400 BC–2024, GeoNames places |

## Step 0 — environment (once per conversation)

- `SKILL` = the folder containing this file. Run scripts as `python $SKILL/scripts/…` from anywhere.
  On Windows, set `PYTHONIOENCODING=utf8` so place names print correctly.
- Check Python deps: `python -c "import shapely, matplotlib; print(shapely.__version__)"`.
  If shapely is missing or older than 2.1: `pip install "shapely>=2.1" matplotlib` (add `--break-system-packages` if pip refuses).
- Output folder (`OUT`):
  - claude.ai: work in `/mnt/user-data/outputs/<slug>/` so the files are downloadable
    (if that path doesn't exist, use a local folder and share the files at the end).
  - Claude Code inside the moving-polygons repo: `examples/<slug>/` (gitignored).
  - Elsewhere: `./<slug>/`.

## Step 1 — scope (keep it short)

Decide and state in one or two lines:
- **Subject and span** (e.g. 18 June 1815, 10:00–21:00; or 1859–1871).
- **Scale** — `battle` (km, hours), `campaign` (tens–hundreds of km, days–months),
  `regional` (a country or sea, years), `continental` (an empire or world region, decades–centuries).
- **bbox** `[min_lon, min_lat, max_lon, max_lat]` — tight around the action, with some context.
- **Layers** — who or what gets a colour: states, armies, fronts, zones. Typically 3–12.
- **Keyframe target** — battle 8–20, war 15–35, era 20–60. More keyframes means more research.
- **Map style** — `light` for political maps, `outdoors` for battles and terrain, `satellite` for the dramatic look.

Ask the user at most one round of questions, and only if the idea is genuinely ambiguous
(e.g. "the war" with several candidates). Otherwise state your assumptions and proceed.

## Step 2 — research

Follow `reference/research-method.md`. In short:
1. Use web search: build a dated event list with sources, and pick keyframes at the moments the
   map changes (treaties, conquests, phases of a battle). Give each a ≤ 50-character label.
2. For every keyframe, write down who holds what (or where each unit stands) and **10–25 test
   places**: `place or [lon, lat]` + the layer that must contain it. Tests turn the research
   into checks, and they are what catches wrong borders.
3. Collect markers: battles, sieges, treaties, deaths — title, date, place, one-line description.
   Smaller actions around them (skirmishes, raids, landings) become `"mini": true` markers: small
   dots with a hover label that don't pause playback.
4. Save it as `OUT/research.md` (sources and confidence H/M/L per keyframe).

Big topics: research era by era or region by region, saving to `research.md` as you go.
In Claude Code you may fan out subagents with the brief in `research-method.md`.
Without web search, use what you know, say so in the description, and mark confidence lower.

## Step 3 — write the scenario

Read `reference/scenario-spec.md` and the matching recipe in `reference/geometry-recipes.md`,
then write `OUT/scenario.json`. Use `lookup.py` rather than guessing names or codes:

```bash
python $SKILL/scripts/lookup.py clio "Sardinia" --year 1859     # Cliopatria polity names + year spans
python $SKILL/scripts/lookup.py admin1 "Veneto" --country ITA   # provinces / regions
python $SKILL/scripts/lookup.py place "Austerlitz"              # towns ≥ 1,000 people, incl. historical names
python $SKILL/scripts/lookup.py where 16.76 49.13 --year 1805    # what contains a point
```

The shape of a scenario (see the examples for complete ones):

```json
{
  "map": {"name": "…", "description": "… Sources: …", "mapStyle": "light"},
  "scale": "regional",
  "bbox": [5.8, 36.5, 19.0, 47.2],
  "keyframes": [{"id": "K1", "date": "1859-01-01", "label": "1859 · Italy on the eve of war"}],
  "regions": {"lombardy_1859": {"minus": [{"admin1": "Lombardia", "country": "ITA"}, {"admin1": "Mantova", "country": "ITA"}]}},
  "layers": [
    {"id": "austria", "name": "Austrian Empire", "color": "#e2b53f",
     "states": [{"from": "K1", "region": {"clio": "Austrian Empire", "year": 1858}}, {"from": "K6", "region": null}]}
  ],
  "markers": [{"title": "Battle of Solferino", "lon": 10.5664, "lat": 45.3717, "start": "1859-06-24"}],
  "tests": [{"at": "K1", "place": "Milan", "expect": "austria"}]
}
```

The gazetteer has towns, not battlefield landmarks: villages under ~1,000 people, farms, hills and
redoubts need `[lon, lat]` from research (a Wikipedia article's coordinates). Place names in a
scenario resolve to the largest match near the bbox; a name that only matches far away is an error.

The rules that matter most:
- `kind: "territory"` layers (the default) form one partition: they never overlap, share their
  borders exactly, and **later layers win** where regions overlap. Use them for states and zones of control.
- `kind: "free"` layers (units, fleets, arrows, fronts) may overlap anything and are drawn on top.
- In a layer's `states`, later entries override earlier ones; `"region": null` removes the layer from that keyframe on.
- Cliopatria outlines are coarse (±10–30 km) and may spill into neighbours: clip them with
  `intersect`/`minus` against modern countries (`admin0`), and prefer admin units wherever the
  historical border matches a modern one.

## Step 4 — build

```bash
python $SKILL/scripts/build_map.py OUT/scenario.json --out OUT
```

This prints the report and writes `OUT/<slug>.json`, `OUT/<slug>-preview.png` and
`OUT/<slug>-report.txt`. The last line reads `RESULT errors=N warnings=M size=X MB`.

## Step 5 — fix loop (at most ~4 rounds)

Look at the preview image and read the report, then fix the **scenario**, not the output:
- **ERROR** lines stop the build or would be silently dropped by the importer — always fix.
- **Test-place misses** (`MISS K3 | Florence | expected italy | got ['tuscany']`): target
  ≥ 95% passing. A miss means either the research or a region is wrong. Fix the region with a rule
  (add/cut a `poly`, a `side` cut, another admin unit), or fix the test if the research was wrong.
- **Warnings** (overlaps, detached inland fragments, ring splits, near-coincident keyframes, size):
  see "Report messages → fixes" in `reference/geometry-recipes.md`.
- Check the preview for things tests can't see: gaps along coasts, slivers, a layer in the wrong
  place, markers piling up, labels that don't read well.

Stop when there are no errors, tests pass ≥ 95%, and every remaining warning is explained.

## Step 6 — deliver

**If the Moving Polygons connector is available** (MCP tools such as `create_upload_link`,
`create_map`, `list_maps`), put the map straight into the user's account:
- Call `create_upload_link` and run its `curl` line with `OUT/<slug>.json` as the file (use its
  gzip variant above 4 MB). On claude.ai the sandbox needs `www.movingpolygons.com` on its
  network allowlist; if curl can't connect, say so and fall back to the file hand-off below.
- To change a map that is already in the account, use `create_upload_link` with
  `mode: "replace"` and its `mapId` (from `list_maps`). Confirm first if that map is published.
- Give the user the `editorUrl` / `previewUrl` from the reply and any `warnings`. The map is a
  private draft. Call `publish_map` only when the user asks to publish.
- Still show the preview image and the summary (items 2, 3 and 5 below).

Otherwise give the user:
1. `OUT/<slug>.json` — the file to import (on claude.ai it's downloadable, and can be saved to
   Google Drive from a phone; import from a desktop browser).
2. `OUT/<slug>-preview.png` — show it inline if you can.
3. A short summary: layers, number of keyframes, playback length, file size, test pass rate, main
   uncertainties or simplifications, and key sources.
4. How to import: **movingpolygons.com → Dashboard → Import → choose the .json**. It opens in the
   editor. Mention that the connector (movingpolygons.com/create-with-ai#connect) skips this step.
5. Keep `scenario.json` and `research.md` with the map. Later requests ("move the Union line
   south at 15:00", "add 1866") are edits to the scenario plus a rebuild, never a rewrite.

## Step 7 — only in Claude Code inside the moving-polygons repo

Also run the file through the real animation engine:

```bash
npx tsx skills/moving-polygons-map/dev/check_matching.ts OUT/<slug>.json
```

`jump=` lines mean a territory flies across the map — fix them with `ring_groups` or more keyframes.
Never write to the database directly from here: use the connector (Step 6) or let the user import
the file.

## Hard limits (the builder enforces them; know them while writing)

- Keyframe label ≤ 50 characters; map/layer name and marker title ≤ 100.
- Colours `#RRGGBB`. Dates: `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM`, BC as `-0216-08-02` (= 216 BC).
- Whole file ≤ 3.3 MB (the builder simplifies more if needed).
- No holes are drawn: the builder opens enclaves with a thin slit.
- Two keyframes can't share a timestamp; each keyframe needs at least one layer instance (the builder adds one).
