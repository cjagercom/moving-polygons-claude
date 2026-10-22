# Styling

## Map style

| mapStyle | When |
|---|---|
| `light` | political and territorial maps (default); colours read best |
| `outdoors` | battles and campaigns where terrain (ridges, rivers, forests) matters |
| `satellite` / `satellite-streets` | dramatic look for battles and naval maps; use stronger, lighter colours |
| `dark` | night-themed maps or light-coloured layers |
| `streets` | modern-era maps where today's towns and roads help orientation |
| `vintage` | old school wall-map look: parchment paper, rivers, graticule, no modern labels or borders. Polygons get a pale wash, a broad watercolour band inside the border and a thin ink line, so mid-saturation colours (ochre, sage, rose, slate blue) work best |
| `vintage-soft` | the vintage basemap with **soft borders**: no ink line, each colour fades into its neighbour across the border. Use it where frontiers were never surveyed and a hard line would claim too much (early medieval kingdoms, tribal lands, spheres of influence). Coasts and rivers stay crisp. The blur is a fixed share of the map (the fade is about 3% of the map's longer side wide), so it widens on screen when the viewer zooms in. A part smaller than that (one town, a pale) keeps a small crisp core, so it never dissolves. Clearly different hues for neighbours work best; near-identical tints merge |
| `tactical` | "Modern Warfare" military briefing screen: dark relief-shaded ground, black sea, coordinate grid, no labels or modern borders; HUD chrome with amber accents and waypoint-diamond markers. Polygons get a faint tinted fill, a bright border and a soft inner glow, so use **saturated, light colours** (`#4fc3f7` blue, `#ff5252` red, `#69f0ae` green, `#ffb300` amber). Best for 20th–21st century wars, operations and campaigns. Its game-like look trivialises suffering: avoid it for ongoing conflicts and for maps that show casualties, and use `dark-glow`, `dark` or `light` there |
| `dark-glow` | Mapbox's dark basemap with tactical's glowing polygons (faint fill, bright border, soft inner glow) but the normal UI: no HUD, no game look. Use it for modern conflicts where tactical would be too much; saturated light colours work best |
| `tapestry` | the map as an **embroidered linen**, after the House of the Dragon titles: land and sea are one cream cloth with folds, the coast is stitched, and every territory is raised thread outlined in dark stitching. Instead of borders sliding, each change pulls the old stitches out and stitches the new colour in (about 3 s per change), and playback is filmed at a tilt with soft focus, a vignette and drifting embers. Made for dynastic and medieval history (succession wars, kingdoms, conquests). Colours are toned toward old sepia thread, so use clearly different, fairly saturated hues (oxblood, ochre, slate blue, moss green, black); near-identical tints merge. Small layers that move (armies, fleets, routes: any layer whose largest shape stays under ~2% of the map) are not stitched: they slide over the cloth as appliqué pieces edged in gold-tinted stitching, so campaigns read well too. Mercator only, not for world maps |
| `polar` | The Arctic and the Antarctic as two polar stereographic discs side by side (rims at 40°N and 50°S), dark ocean, opaque land drawn **over** the polygons, graticule and sea names. It does not show real coordinates: the map data must be pre-projected into its stand-in coordinates, which `build_map.py` cannot do. Only use it with a pipeline that writes that layout, such as `examples/sea-ice/scripts/build_sea_ice.py` in the app repo (sea ice, polar climate data) |

Fills are drawn semi-transparent over the basemap, so mid-saturation colours work best.

## Colours

- Use **conventional colours** where readers expect them:

| Who | Colour | Hex |
|---|---|---|
| Britain | red | `#c0392b` |
| France | blue | `#1f4e9c` / `#2f6ec7` |
| Prussia / Germany | dark grey | `#3d4a57` |
| Austria / Habsburgs | gold | `#e2b53f` |
| Russia | green | `#2e7d32` |
| Ottoman Empire | dark green | `#1b5e20` |
| Rome | crimson | `#8e1b1b` |
| Byzantium | purple | `#6a1b9a` |
| Sweden | yellow-blue | `#f4c430` |
| Union (US Civil War) | blue | `#1f4e9c` |
| Confederacy | grey | `#8d8d8d` |
| Sardinia / Savoy | blue | `#2f6db5` |
| Italy | green | `#3a9a5b` |
| Papal States | lilac | `#b18ad6` |

- **Neighbours must contrast.** Put adjacent states on clearly different hues, and use one hue
  family per side in a war (its units in shades of that hue).
- **Context layers** (neutral countries shown for orientation) get muted greys or pale tints.
- **Arrows and attacks** use a darker shade of their side's colour.
- **Colour changes** (a state's `color` in a later keyframe) mark successions: kingdom → empire,
  dynasty change, occupation.
- Avoid pure black, pure white, and near-identical shades across neighbours.

## Labels, names, descriptions

- Keyframe labels (≤ 50): `<when> · <what changed>`, e.g. `"Oct 1866 · Treaty of Vienna: Venetia to Italy"`,
  `"16:30 · Prussians attack Plancenoit"`.
- Layer names (≤ 100) are what the legend shows: the polity or unit name, with the leader if it
  helps (`"Prussian IV Corps (Bülow)"`), or a succession (`"Kingdom of Sardinia → Kingdom of Italy"`).
- Map name: the subject and span, e.g. `"Unification of Italy, 1859–1871"`,
  `"Battle of Waterloo, 18 June 1815"`.
- Description: 2–4 sentences of story, then simplifications ("positions are simplified"), then
  `Sources: …`. The builder adds the Cliopatria attribution when needed.

## Markers

- Colour by side (the side that achieves the event) or by type:
  - battles: red `#ef4444`
  - treaties: violet `#8b5cf6`
  - uprisings: orange `#f59e0b`
  - deaths and endings: dark `#374151`
- Keep titles short and descriptive; put the story in the description.
- Around 1–3 markers per keyframe is plenty. Overlapping markers in one spot are hard to click.
