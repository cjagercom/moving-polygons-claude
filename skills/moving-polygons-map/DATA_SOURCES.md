# Data sources

The files in `data/` are derived from these datasets. Attribute them when publishing maps
built on them. The builder adds the Cliopatria line to a map's description automatically.

| File | Source | Licence | Processing |
|---|---|---|---|
| `admin1.geojson.gz` | Natural Earth 1:10m Admin 1 – States, Provinces (naturalearthdata.com) | Public domain | Antarctica removed; topology-aware simplification at 1.2 km (mapshaper); islets < 1 km² dropped; 4 decimals |
| `admin0.geojson.gz`, `land.geojson.gz` | dissolved from the admin-1 file above | Public domain | shares border vertices with admin-1 |
| `lakes.geojson.gz`, `rivers.geojson.gz` | Natural Earth 1:10m lakes; rivers and lake centerlines | Public domain | lakes > 80 km²; simplified at 0.8 km |
| `cliopatria.topojson.gz` | Cliopatria polities, Seshat Global History Databank (github.com/Seshat-Global-History-Databank/cliopatria) | CC BY 4.0 | polities only; simplified at 3 km; quantized TopoJSON |
| `places.tsv.gz` | GeoNames cities1000 (geonames.org) | CC BY 4.0 | name, ASCII name, Latin-script alternate names (as normalised lookup keys) for towns ≥ 3k, position, country, admin1, population |

Suggested attribution in a map description:
"Base borders: Cliopatria (Seshat Global History Databank, CC BY 4.0) and Natural Earth."

Rebuild the data in the moving-polygons repo with `npm run skill:data`
(`dev/prepare_data.py`; needs Node for mapshaper).
