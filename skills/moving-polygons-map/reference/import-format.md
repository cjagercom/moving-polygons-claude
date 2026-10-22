# Moving Polygons import format

The file that **Dashboard → Import** accepts. `build_map.py` writes it; `validate_map.py`
checks any file against it. You should rarely need to edit this JSON by hand. Change the
scenario and rebuild instead.

```json
{
  "name": "Unification of Italy, 1859–1871",
  "description": "From a peninsula of seven states to one kingdom… Sources: …",
  "mapStyle": "mapbox://styles/mapbox/light-v11",
  "polygonPlaceholders": [
    {
      "id": "italy",
      "name": "Kingdom of Sardinia → Kingdom of Italy",
      "color": "#2f6db5",
      "displayOrder": "9",
      "instances": [
        {"label": "1859 · Italy on the eve of war", "datetime": "1859-01-01T12:00:00.000Z",
         "geometry": [[[7.6, 45.1], [7.7, 45.0], [7.5, 44.9], [7.6, 45.1]]], "color": null},
        {"label": "Mar 1861 · Kingdom of Italy proclaimed", "datetime": "1861-03-17T12:00:00.000Z",
         "geometry": [[…ring…], […ring…]], "color": "#3a9a5b"}
      ]
    }
  ],
  "markers": [
    {"title": "Battle of Solferino", "description": null, "longitude": 10.5664, "latitude": 45.3717,
     "startDatetime": "1859-06-24T12:00:00.000Z", "endDatetime": "1859-07-11T12:00:00.000Z", "color": "#ef4444"},
    {"title": "Skirmish at San Martino", "description": null, "longitude": 10.5167, "latitude": 45.4333,
     "startDatetime": "1859-06-24T12:00:00.000Z", "endDatetime": "1859-06-30T12:00:00.000Z", "color": "#6b7280",
     "mini": true}
  ]
}
```

## Fields

| Field | Rules |
|---|---|
| `name` | required, ≤ 100 chars (a missing name becomes "Imported Map") |
| `description` | optional text, no limit |
| `mapStyle` | a Mapbox style URL; the editor offers light-v11, dark-v11, streets-v12, outdoors-v12, satellite-v9, satellite-streets-v12, or the in-app styles `"vintage"`, `"vintage-soft"`, `"tactical"`, `"dark-glow"`, `"tapestry"` and `"polar"` (not URLs; `"polar"` only fits pre-projected data, see styling.md) |
| `casualtyBar` | optional: a bar centred at the top of the map comparing two sides' cumulative losses, interpolated by date during playback. `{"title"?, "left": {"label", "color"}, "right": {"label", "color"}, "points": [{"date", "left", "right", "leftLow"?, "leftHigh"?, "rightLow"?, "rightHigh"?, "note"?}], "source"?}`: colours `#RRGGBB`, points in date order (≤ 500), counts ≥ 0, low/high draw a lighter band around the central estimate, `note` is the point's source in the tooltip. Zero before the first point, the last point's counts after it. Leave out `right` for a one-sided bar (a single total, e.g. reported deaths): points then need only `left` (+ `leftLow`/`leftHigh`/`note`), the bar fills from its left edge and any `right*` counts are ignored, e.g. `{"title": "Reported COVID-19 deaths", "left": {"label": "Deaths", "color": "#D94F4F"}, "points": [{"date": "2020-03-01", "left": 3000}, {"date": "2020-04-01", "left": 45000, "leftHigh": 60000, "note": "WHO"}], "source": "WHO"}`. An invalid bar is skipped on import |
| `polygonPlaceholders[]` | the layers ("timelines") |
| `.name` | required, ≤ 100 chars |
| `.color` | `#RRGGBB` |
| `.displayOrder` | a **string**, ≤ 50 chars; stored, not used for drawing order |
| `.id` | ignored on import |
| `.instances[]` | the layer's keyframes |
| `..datetime` | ISO string. BC as `-0509-01-01T00:00:00.000Z` (= 509 BC); `-000509-…` also works |
| `..label` | ≤ 50 characters, or null |
| `..geometry` | list of rings, or `null` (absent) |
| `..color` | `#RRGGBB` override from this keyframe on, or null (use the layer colour) |
| `markers[]` | point events |
| `.title` | required, ≤ 100 chars |
| `.description` | optional |
| `.longitude`, `.latitude` | numbers |
| `.startDatetime` | required |
| `.endDatetime` | or null = visible to the end |
| `.color` | `#RRGGBB`, default red |
| `.mini` | optional, `true` = **mini event**: a small dot whose title (and description) shows on hover; a tap toggles it. Playback never pauses for it, and like every marker it is not a keyframe, so it is not on the timeline or in the event list. Omit or `false` = a normal pin that pauses playback and opens its description when clicked |

## Geometry

- `geometry` is **not GeoJSON**: it is `[[[lon, lat], …], [[lon, lat], …]]`, a list of rings.
- Each ring is drawn as its own filled polygon. **There are no holes:** an inner ring would be
  filled over. Enclaves are handled by cutting a thin slit from the hole to the outside (the builder does this).
- Rings must be closed (first position = last) and have ≥ 4 positions. Coordinates are `[lon, lat]`.
- `null`, or a tiny shape (≤ 6 positions in total and < 0.001 deg²), means the layer is absent
  at that keyframe. Going to or from absent is a crossfade, not a morph.

## Semantics that matter

- **The importer checks the whole file first.** Dashboard → Import, the connector's
  `create_map` and its upload links build the map on the server in one go. Any invalid item
  (a 51-character label, a bad colour, an unparseable date, a layer without a name) rejects the
  file with a list of errors, and nothing is created. Open rings are closed and an invalid
  casualty bar is skipped, each with a warning. Still validate before handing a file over.
- **Timeline:**
  - Every distinct instance datetime across all layers is a keyframe.
  - A keyframe's caption is the label of the first instance found at that time, so give all
    instances at a keyframe the same label (the builder does).
  - Ticks show years, or "Jul 1863", "1 Jul", "1 Jul 14:00" for shorter maps.
- **Holding shape:** a layer keeps its last shape until its next instance. The morph happens in
  the transition leading into the instance where the shape changes. So an instance is needed only
  where the shape or colour changes, plus one per keyframe somewhere to carry the label.
- **Playback:** about 800 ms per transition at 1×, split by real time but floored at 0.6× an
  average transition.
- **Draw order:** layers are created in file order, and later layers are drawn on top.
- **Size:** the public map page loads the whole map in one response. Keep the file ≤ 3.3 MB.
  An upload may be at most 4.5 MB (gzip larger files; 40 MB unzipped at most).
- **Account limit:** the import fails when the account's map limit is reached.
