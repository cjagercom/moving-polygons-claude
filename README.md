# Moving Polygons for Claude

Turn history into animated maps. Ask Claude for "the Thirty Years' War", "how Poland's borders
moved" or "the Battle of Austerlitz": it researches the event, builds the borders from historical
data sets and puts the map in your [Moving Polygons](https://www.movingpolygons.com) account,
ready to publish or embed.

This plugin bundles two parts:

- **The Moving Polygons connector** (remote MCP server at `https://www.movingpolygons.com/mcp`).
  Claude can search and read published maps without signing in. Creating, changing and
  publishing maps in your own account asks you to sign in with your Moving Polygons account
  (OAuth) the first time.
- **The `moving-polygons-map` skill.** It researches a period, picks borders from Cliopatria and
  Natural Earth, places towns, battles and armies, validates the result and writes the map file.

## Install

### Claude Code

```
/plugin marketplace add cjagercom/moving-polygons-claude
/plugin install moving-polygons@moving-polygons
```

Then ask, for example: *"Make a map of the Roman Republic's expansion in Italy, 509–264 BC,
with the main battles as markers."* The first time Claude saves a map, run `/mcp`, pick
`moving-polygons` and choose Authenticate.

### claude.ai and the Claude apps

- Connector: Settings → Connectors → add `https://www.movingpolygons.com/mcp` as a custom
  connector.
- Skill: download the zip from https://www.movingpolygons.com/create-with-ai and upload it under
  Settings → Capabilities → Skills (code execution must be on).

Step-by-step instructions: https://www.movingpolygons.com/create-with-ai

## What Claude can do with the connector

| Tool | What it does | Sign-in |
| --- | --- | --- |
| `search_maps` | Find published maps by topic, place or year | no |
| `get_public_map` | One published map as text: timeline, layers, events, embed code | no |
| `get_import_format` | The JSON format for maps | no |
| `get_account` | Your handle, plan and how many maps you can still create | yes |
| `list_maps`, `get_map` | Your maps, and one map's summary plus a download link | yes |
| `create_map`, `create_upload_link` | Create a private draft map (big files go through a one-time upload link) | yes |
| `replace_map_content` | Overwrite a map's content; the old version is backed up | yes |
| `publish_map`, `unpublish_map` | Make a map public at its link, or private again | yes |

New maps are private drafts. Claude only publishes when you ask.

## Skill requirements

Python 3 with `shapely>=2.1` and `matplotlib` (the skill checks and tells Claude how to install
them). The skill works offline from the bundled data in `skills/moving-polygons-map/data/`.

## Data and attribution

The bundled data comes from Natural Earth (public domain), Cliopatria by the Seshat Global History
Databank (CC BY 4.0) and GeoNames (CC BY 4.0). See
[`DATA_SOURCES.md`](skills/moving-polygons-map/DATA_SOURCES.md) for details and the attribution
line to use when you publish a map built on it.

## Links

- Website: https://www.movingpolygons.com
- Example maps: https://www.movingpolygons.com/explore
- Privacy policy: https://www.movingpolygons.com/privacy
- Terms: https://www.movingpolygons.com/terms
- Support: https://www.movingpolygons.com/contact
