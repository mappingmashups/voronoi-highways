"""Render the lower-48 outline and selected highways to a clean SVG (+ PNG preview)."""
from pathlib import Path

import geopandas as gpd

from selection import keep_interstate, route_numbers
from svgmap import CRS, SvgMap

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
OUT = ROOT / "output" / "lower48_highways.svg"

SHOW_US_HIGHWAYS = False
STYLE = {
    "land": dict(fill="#f4f1ea", stroke="#9a9a9a", stroke_width=0.75),
    "Federal": dict(stroke="#c9a46b", stroke_width=0.6),
    "Interstate": dict(stroke="#b2332b", stroke_width=1.2),
}


def main():
    outline = gpd.read_file(DATA / "lower48.geojson").to_crs(CRS)
    roads = gpd.read_file(DATA / "highways_lower48.geojson").to_crs(CRS)
    roads["numbers"] = roads.routes.map(route_numbers)
    is_interstate = roads.level == "Interstate"
    roads = roads[
        (is_interstate & roads.numbers.map(lambda ns: any(map(keep_interstate, ns))))
        | (~is_interstate & SHOW_US_HIGHWAYS)
    ]

    m = SvgMap(outline.total_bounds)
    s = STYLE
    m.add(f'<path id="land" d="{m.area_d(outline.geometry.iloc[0])}" fill="{s["land"]["fill"]}" fill-rule="evenodd" '
          f'stroke="{s["land"]["stroke"]}" stroke-width="{s["land"]["stroke_width"]}" stroke-linejoin="round"/>')
    m.add('<g fill="none" stroke-linecap="round" stroke-linejoin="round">')
    for level, layer_id in (("Federal", "us-highways"), ("Interstate", "interstates")):  # Interstates on top
        d = m.line_d(roads[roads.level == level].geometry)
        m.add(f'  <path id="{layer_id}" d="{d}" stroke="{s[level]["stroke"]}" stroke-width="{s[level]["stroke_width"]}"/>')
    m.add("</g>")
    m.save(OUT)

    shown = {n for ns in roads[roads.level == "Interstate"].numbers for n in ns if keep_interstate(n)}
    print("interstates:", sorted(shown))


if __name__ == "__main__":
    main()
