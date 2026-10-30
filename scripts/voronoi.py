"""Nearest-route regions: colour every part of the lower 48 by the closest selected route.

Lines -> densified points (each tagged with its route number) -> Voronoi cells ->
dissolve by route number -> clip to the lower-48 outline. Distances are measured in
Conus Albers (EPSG:5070) metres. Where a point belongs to several selected routes
(shared pavement, or coincident points at junctions) the lowest number wins.

Usage: python scripts/voronoi.py [selection ...]   (default: all, see selection.py)
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.ops import polylabel

from selection import PREFIX, SELECTIONS, fill_color, line_color, route_numbers
from svgmap import CRS, SvgMap

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
OUT = ROOT / "output"

SPACING_M = 1_000  # point spacing along the routes
LEGEND_COLS = 12
LEGEND_ROW_H = 22
FONT = "Helvetica, Arial, sans-serif"


def route_points(roads):
    """One point per vertex of the densified routes, tagged with its route number."""
    xs, ys, nums = [], [], []
    for geom, n in zip(roads.geometry, roads.number):
        coords = shapely.get_coordinates(shapely.segmentize(geom, SPACING_M))
        xs.append(coords[:, 0]); ys.append(coords[:, 1]); nums.append(np.full(len(coords), n))
    pts = gpd.GeoDataFrame({"x": np.concatenate(xs), "y": np.concatenate(ys), "number": np.concatenate(nums)})
    # coincident points (junctions, shared pavement): lowest number wins
    pts = pts.round({"x": 0, "y": 0}).groupby(["x", "y"], as_index=False).number.min()
    return gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts.x, pts.y), crs=CRS)


def voronoi_regions(pts, outline):
    land = outline.geometry.iloc[0]
    cells = shapely.voronoi_polygons(shapely.MultiPoint(pts.geometry.values),
                                     extend_to=land.buffer(200_000), ordered=True)
    cells = gpd.GeoDataFrame({"number": pts.number.values}, geometry=list(cells.geoms), crs=CRS)
    regions = cells.dissolve(by="number", as_index=False)
    regions["geometry"] = regions.intersection(land)
    regions["area_km2"] = (regions.area / 1e6).round()
    return regions


def label_point(geom):
    """Visual centre of the region's largest part."""
    part = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    return polylabel(part, tolerance=2_000)


def run(name, outline, all_roads):
    sel = SELECTIONS[name]
    keep, prefix = sel["keep"], PREFIX[sel["level"]]
    roads = all_roads[all_roads.level == sel["level"]].copy()
    roads["number"] = roads.routes.map(lambda r: min((n for n in route_numbers(r) if keep(n)), default=None))
    roads = roads[roads.number.notna()]
    roads["number"] = roads.number.astype(int)

    pts = route_points(roads)
    regions = voronoi_regions(pts, outline)
    regions.to_crs("EPSG:4326").to_file(DATA / f"voronoi_{name}.geojson", driver="GeoJSON")
    print(f"[{name}] {len(pts)} points -> {len(regions)} regions: "
          + ", ".join(f"{prefix}{n}" for n in regions.number))

    numbers = sorted(regions.number)
    rows = -(-len(numbers) // LEGEND_COLS)
    m = SvgMap(outline.total_bounds, extra_bottom=40 + rows * LEGEND_ROW_H)
    m.add('<g id="regions" stroke="#ffffff" stroke-width="0.6" stroke-linejoin="round">')
    for _, r in regions.iterrows():
        m.add(f'  <path id="region-{r.number}" d="{m.area_d(r.geometry)}" fill="{fill_color(r.number)}" fill-rule="evenodd"/>')
    m.add("</g>")
    m.add(f'<path id="outline" d="{m.area_d(outline.geometry.iloc[0])}" fill="none" stroke="#8a8a8a" '
          f'stroke-width="0.75" stroke-linejoin="round"/>')
    width = 1.4 if len(numbers) <= 12 else 1.0
    m.add('<g id="routes" fill="none" stroke-linecap="round" stroke-linejoin="round">')
    for n, group in roads.groupby("number"):
        m.add(f'  <path id="route-{n}" d="{m.line_d(group.geometry)}" stroke="{line_color(n)}" stroke-width="{width}"/>')
    m.add("</g>")

    # route number at the visual centre of each region
    size = 13 if len(numbers) <= 12 else 10
    m.add(f'<g id="labels" font-family="{FONT}" font-size="{size}" font-weight="bold" text-anchor="middle" '
          f'paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round">')
    for _, r in regions.iterrows():
        x, y = m.xy(*label_point(r.geometry).coords[0])
        m.add(f'  <text x="{x:.0f}" y="{y + size / 3:.0f}" fill="{line_color(r.number)}">{r.number}</text>')
    m.add("</g>")

    # legend below the map
    x0, y0 = m.pad + 10, m.map_height + 8
    m.add(f'<g id="legend" font-family="{FONT}" font-size="12" fill="#333">')
    m.add(f'  <text x="{x0}" y="{y0}" font-weight="bold" font-size="14">{sel["title"]}</text>')
    col_w = (m.width - 2 * x0) / LEGEND_COLS
    for i, n in enumerate(numbers):
        x, y = x0 + (i % LEGEND_COLS) * col_w, y0 + 14 + (i // LEGEND_COLS) * LEGEND_ROW_H
        m.add(f'  <rect x="{x:.0f}" y="{y}" width="14" height="14" fill="{fill_color(n)}" stroke="{line_color(n)}" stroke-width="1.5"/>')
        m.add(f'  <text x="{x + 19:.0f}" y="{y + 11.5}">{prefix}{n}</text>')
    m.add("</g>")
    m.save(OUT / f"voronoi_{name}.svg")


def main():
    names = sys.argv[1:] or list(SELECTIONS)
    outline = gpd.read_file(DATA / "lower48.geojson").to_crs(CRS)
    roads = gpd.read_file(DATA / "highways_lower48.geojson").to_crs(CRS)
    for name in names:
        run(name, outline, roads)


if __name__ == "__main__":
    main()
