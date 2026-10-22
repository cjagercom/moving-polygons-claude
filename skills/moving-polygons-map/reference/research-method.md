# Research method

The method that produced the best maps so far (Rome, 509 BC – 1453 AD; Sweden's empire; the
Hanseatic League):
1. dated keyframes with sources;
2. per keyframe, what each layer holds, written as **test places**;
3. geometry from the best base data plus dated rules;
4. checking the result against the tests and fixing with rules, not by nudging points.

Point-based fixes alone make round blobs. Large disagreements need a region rule
(a `poly`, a `side` cut, different admin units).

## 1. Scope

Before searching, write down:
- the question the map answers ("how did Italy go from seven states to one?");
- the span, bbox, scale, and the layers (states, armies, zones);
- a keyframe budget: battle 8–20, war 15–35, era 20–60. Every keyframe needs a known state of
  every layer, so more keyframes cost more research.

## 2. Sources

- Start with Wikipedia for the event list and dates (articles on the war, each treaty, each
  battle), then check contested points in more specialised sources: national archives, academic
  atlases, and Wikipedia in the relevant language, which often has better regional detail.
- Many historical states have a Wikipedia map. Use it to understand borders, but take
  coordinates from text or place articles, not by eyeballing images.
- Coordinates of places (villages, forts, farms, bridges): the place's Wikipedia article (its
  coordinates line), GeoNames via `lookup.py place`, or OpenStreetMap search results.
  At battle scale, expect to take most coordinates from articles. The gazetteer only has towns
  of about 1,000 people and up, and a common name may exist elsewhere in the same country.
  The local-language Wikipedia is often best for village coordinates.
- Record every source you rely on (URL or title). The map description lists the main ones.
- When sources disagree, pick one, note the alternative, and give that keyframe lower confidence.

## 3. Choosing keyframes

- A keyframe is a moment the map **changes**: a treaty signed or ratified (pick one convention
  and keep it), a conquest completed, a phase of a battle.
- Merge events that are less than ~10% of an average gap apart into one keyframe with a combined
  label. The app gives short transitions a minimum share of playback, so near-simultaneous
  keyframes just look like stutter.
- Quiet decades can go without keyframes. The morph spreads the change over the gap. If a change
  happened suddenly after a long quiet period, add a keyframe just before it (unchanged borders)
  so the morph happens at the right time.
- The first keyframe sets the scene (the state before the story). The last shows the outcome.
- Labels are ≤ 50 characters: `"1860 · Garibaldi enters Naples"`, `"13:30 · d'Erlon's attack"`.
  Put detail into marker descriptions.

## 4. Dates

- Use the date format in `scenario-spec.md`. The date sets the order and spacing on the timeline.
- **BC:** `-0216-08-02` = 2 August 216 BC. The app has no year 0: 1 BC is `-0001`.
- **Julian vs Gregorian:** sources before 1582 (and later in Britain, Sweden, Russia and Greece)
  often use the Julian calendar. Use dates as your main sources give them, consistently, and
  note the calendar if it matters.
- **Times of day** (battles): write them as local time (`1815-06-18T13:30`). The app shows them
  as written. Times in accounts are approximate; use one chronology consistently.
- A year only (`1648`) becomes 1 January 1648, 12:00. If an event is known only by year, that's
  fine; keep the order right relative to events with exact dates.

## 5. Per-keyframe notes and test places

For each keyframe, write:

```markdown
### K3 · 1860-03-24 · Mar 1860 · Centre joins; Nice and Savoy to France   (confidence: H)
Holdings:
- Sardinia/Italy: Piedmont, Liguria, Sardinia island, Lombardy except Mantua, Tuscany, Parma, Modena, Romagna
- France: gains Savoy and the County of Nice (Treaty of Turin, 24 Mar 1860)
- Papal States: Lazio, Umbria, Marche (Romagna lost)
Tests: Florence→italy, Bologna→italy, Nice→france, Chambéry→france, Ancona→papal, Perugia→papal
Sources: https://en.wikipedia.org/wiki/Treaty_of_Turin_(1860), …
```

Test places:
- 10–25 per keyframe for territorial maps.
- For battles, 3–6 on the keyframes where units move or ground changes hands: unit positions
  and strongpoints. Anchor them to named places the sources put the unit in; tests that just
  restate where you drew a block catch nothing. Use `expect_not` for "unit X is no longer here".
- Include **border-near places** on both sides of every border that changes at this keyframe.
  They catch wrong borders; capitals alone don't.
- Include places that must be in **no** layer (`expect: null`) where that matters.
- Coastal and island towns can fall outside the simplified coastline. The builder snaps tests a
  few km, but for lagoon or island cities (Venice) test a nearby mainland town instead.
- Use `lookup.py place` to confirm a name resolves to the right place, and use `[lon, lat]` for
  ambiguous names ("Frankfurt", "Alexandria").

## 6. Markers

- Title (≤ 100 chars), date (start), place or coordinates, a one- or two-sentence description.
  Colour by side or type (see `styling.md`).
- Point events get `end: "auto"`; ongoing states (a siege) get an explicit end.
- A marker for every keyframe is too many. Mark the events the borders don't show: battles,
  sieges, massacres, treaties signed away from the border change, deaths of leaders.

## 7. Parallel research (Claude Code only)

For big maps, split the span into eras or regions and give each subagent this brief:

```
Research <topic> for <era/region>, <start>–<end>, for an animated border map.
Return JSON: {"keyframes": [{"date": "YYYY-MM-DD", "label": "≤50 chars", "confidence": "H|M|L",
  "holdings": "prose: who holds what", "tests": [{"place": "...", "lon": 0, "lat": 0, "expect": "<layer id>",
  "note": "..."}], "sources": ["url", ...]}], "markers": [{"title": "...", "date": "...", "lon": 0, "lat": 0,
  "description": "..."}], "open_questions": ["..."]}
Layer ids: <list>. At least 15 test places per keyframe, including places on both sides of every
border that changes. Coordinates as lon/lat decimal degrees from the place's article or GeoNames.
```

Merge the results, resolve conflicts, and write one `research.md`.

## 8. No web search available

Build from your own knowledge, keep keyframes to well-known events, add fewer and safer tests,
and tell the user the map is unverified. Suggest a re-run with web search for accuracy.
