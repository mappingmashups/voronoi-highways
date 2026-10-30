"""Prepare lower-48 outline and Interstate / US highway subsets from Natural Earth."""
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from routes import assign_routes, split_at_junctions

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

EXCLUDE_STATES = {"AK", "HI"}
ROAD_LEVELS = {"Interstate", "Federal"}  # Federal == US highways
CRS = "EPSG:5070"  # NAD83 / Conus Albers (metres)
CLIP_BUFFER_M = 10_000
# Longest gap to try bridging along the same-level network. Interstates share pavement for
# long stretches (I-20/59 Birmingham-Meridian ~250 km); US routes mostly vanish onto
# Interstates, which this same-level bridging can't follow, so keep it short there.
MAX_GAP_M = {"Interstate": 300_000, "Federal": 80_000}

# Natural Earth label fixes (see output/ne_issues/ISSUES.md).
# (current name or None, [(lat, lon) endpoints identifying the segment], new attribute values)
FIXES = [
    ("5", [(45.517, -122.677), (45.531, -122.557)], {"name": "84"}),  # Portland: I-84
    ("5", [(45.548, -122.222)], {"name": "84"}),  # Columbia Gorge: I-84
    ("5", [(47.580, -122.176), (47.594, -122.322)], {"name": "90"}),  # Seattle: I-90 Mercer Island
    ("55", [(41.647, -87.524)], {"name": "94"}),  # Chicago: Dan Ryan / Bishop Ford
    ("55", [(41.627, -87.696)], {"name": "57"}),  # Chicago: I-57
    ("85", [(33.763, -84.491), (33.739, -84.388)], {"name": "20"}),  # Atlanta: I-20
    ("235", [(37.608, -97.310), (37.903, -96.846)], {"name": "35"}),  # Wichita: Kansas Turnpike
    ("75", [(36.113, -96.008), (36.146, -95.987)], {"name": "44"}),  # Tulsa: I-44
    ("75", [(36.146, -95.987), (36.162, -95.975)], {"name": "44"}),  # Tulsa: I-44
    ("244", [(36.162, -95.975), (36.561, -95.219)], {"name": "44"}),  # Will Rogers Turnpike: I-44
    (None, [(39.062, -84.537), (38.878, -84.621)], {"name": "75", "namealt": "71"}),  # Cincinnati
    (None, [(36.045, -79.774), (36.031, -79.812)], {"level": "Interstate", "name": "40", "namealt": "85"}),  # Greensboro
    ("70", [(40.821, -97.595), (40.823, -97.044)], {"name": "80"}),  # Nebraska: I-80 near York
    ("44", [(35.472, -94.325), (35.467, -94.440)], {"name": "40"}),  # Fort Smith, AR: I-40
    ("44", [(35.472, -94.325), (35.524, -94.222)], {"name": "40"}),  # Fort Smith, AR: I-40
    ("2", [(47.561, -120.600), (47.623, -120.235)], {"namealt": "97"}),  # Wenatchee: US 2/97
    # state routes tagged as US highways
    ("1", [(35.696, -85.809), (35.936, -85.484)], {"level": "State"}),  # TN SR 1
    ("3", [(36.678, -101.474), (36.617, -100.523)], {"level": "State"}),  # OK SH 3
    ("15", [(37.219, -83.056), (37.113, -82.802)], {"level": "State"}),  # KY 15
    ("15", [(37.219, -83.056), (37.227, -83.163)], {"level": "State"}),  # KY 15
    ("50", [(35.072, -86.271), (35.299, -85.903)], {"level": "State"}),  # TN SR 50
    ("6", [(34.212, -90.530), (34.310, -89.919)], {"level": "State"}),  # MS 6
    ("85", [(27.531, -99.479), (27.760, -99.439)], {"level": "State"}),  # no US 85 in Texas
]


# US route numbers (< 100) that don't exist in the current system; Natural Earth has a few
# state routes (all in Pennsylvania) tagged as US highways with these numbers.
NOT_US_ROUTES = {"32", "38", "66"}


def fix_attributes(roads):
    def ends(g):
        g = g.geoms[0] if g.geom_type.startswith("Multi") else g
        return Point(g.coords[0]), Point(g.coords[-1])

    for name, pts, values in FIXES:
        same = roads.name.isna() if name is None else roads.name == name
        hit = same & roads.geometry.map(
            lambda g: all(min(e.distance(Point(lon, lat)) for e in ends(g)) < 0.003 for lat, lon in pts))
        if hit.sum() != 1:
            raise ValueError(f"fix {name}->{values} at {pts} matched {hit.sum()} segments")
        for col, val in values.items():
            roads.loc[hit, col] = val
    roads.loc[(roads.level == "Federal") & roads.name.isin(NOT_US_ROUTES), "level"] = "State"
    return roads


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    states = gpd.read_file(RAW / "ne_10m_admin_1_states_provinces_lakes.geojson")
    states = states[(states.iso_a2 == "US") & ~states.postal.isin(EXCLUDE_STATES)]
    outline = states[["geometry"]].dissolve()
    outline["geometry"] = outline.buffer(0)  # clean up shared-edge slivers
    outline["name"] = "Lower 48"
    outline.to_file(OUT / "lower48.geojson", driver="GeoJSON")

    roads = gpd.read_file(RAW / "ne_10m_roads.geojson")
    roads = roads[roads.sov_a3 == "USA"]
    roads.loc[roads.namealtt != roads.level, "namealt"] = None  # only same-level alt names count
    roads = fix_attributes(roads)
    roads = roads[roads.level.isin(ROAD_LEVELS)]
    roads = roads[["name", "namealt", "level", "type", "expressway", "scalerank", "geometry"]]
    # clip with a buffered outline so bridges over water (e.g. Mackinac) survive
    reach = outline.to_crs(CRS).buffer(CLIP_BUFFER_M).to_crs(outline.crs)
    roads = gpd.clip(roads, reach)
    roads = roads[~roads.is_empty].explode(index_parts=False)
    roads = roads[roads.geom_type == "LineString"].to_crs(CRS).reset_index(drop=True)
    roads = split_at_junctions(roads)

    # routes: every route number a segment carries, including concurrencies ("55,70")
    # Connectors are short synthetic links that close data gaps (connector=True).
    parts = []
    for level in sorted(ROAD_LEVELS):
        segs = roads[roads.level == level].reset_index(drop=True)
        routes, connectors, log = assign_routes(segs, max_gap=MAX_GAP_M[level])
        extra = gpd.GeoDataFrame(
            {"level": level, "connector": True}, index=range(len(connectors)),
            geometry=list(connectors.values()), crs=CRS,
        )
        segs = pd.concat([segs.assign(connector=False), extra], ignore_index=True)
        segs["routes"] = [",".join(sorted(r, key=int)) for r in routes]
        parts.append(segs[(segs.routes != "") | ~segs.connector])
        if level == "Interstate":
            for num, gap, length, via, xy in log:
                if gap > 3000:
                    ll = gpd.GeoSeries([Point(xy)], crs=CRS).to_crs("EPSG:4326").iloc[0]
                    via_txt = ", ".join(f"I-{n}" for n in via) or "unnamed/connector links"
                    print(f"  I-{num}: bridged {gap / 1000:.0f} km gap at {ll.y:.2f},{ll.x:.2f} via {via_txt}")

    roads = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=CRS)
    roads = roads.to_crs("EPSG:4326")
    roads.to_file(OUT / "highways_lower48.geojson", driver="GeoJSON")

    print(f"outline: {len(states)} states dissolved")
    print(roads.level.value_counts().to_string())


if __name__ == "__main__":
    main()
