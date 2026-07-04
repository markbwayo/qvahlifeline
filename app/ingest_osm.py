"""Phase 1: ingest real OSM assets for the locked pilot bounding box.

Run AFTER the D-004 pilot decision. Usage (from /opt/lifeline):
    .venv/bin/python -m app.ingest_osm --bbox S,W,N,E

Overpass queries per object type (attribution: (c) OpenStreetMap contributors, ODbL):
  bridges/culverts/fords: way[bridge](bbox); way[tunnel=culvert](bbox); way[ford](bbox)
  roads: way[highway~"^(primary|secondary|tertiary|unclassified|track)$"](bbox)
  settlements: node[place~"^(town|village|hamlet)$"](bbox)
  clinics: nwr[amenity~"^(clinic|hospital|doctors)$"](bbox); nwr[healthcare](bbox)
  schools: nwr[amenity=school](bbox)
  water points: nwr[man_made=water_well](bbox); nwr[amenity=drinking_water](bbox)
  rivers: way[waterway~"^(river|stream)$"](bbox)

Pipeline (build in Phase 1, one step per session):
 1. Pull each type -> objects table (source='osm', keep osm id in props).
 2. Split rivers into reaches at crossings; attach nearest GloFAS grid point.
 3. Infer links per 09: crosses (bridge within 50 m of waterway), carries
    (road within 30 m of bridge), connects (shared endpoints), access_via
    (nearest road within 500 m of settlement/facility), serves (nearest facility
    of each kind within 10 km serving each settlement - committee-editable),
    on_floodplain (SRTM: object elevation within 5 m of reach elevation AND
    within 300 m horizontal - heuristic v1, flag for review).
 4. Write an ingest report: counts per type, unnamed assets, suspect links -
    the operator (a civil engineer) reviews and fixes in the UI.
 5. AI edge MAY propose names/types for ambiguous features; operator confirms
    before the object enters the graph (see 07). Never auto-commit.

Keep this file the ONLY place Overpass is called. Rate-limit politely (sleep 2s
between queries); cache raw responses in db.geocache.
"""
import sys

if __name__ == "__main__":
    sys.exit("Phase 1 module - build after the D-004 pilot decision. See docstring.")
