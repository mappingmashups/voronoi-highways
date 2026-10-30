"""Export map geometry and palette presets for the interactive palette page (web/).

Writes web/palette_data.json, then builds output/web/interstate_palettes.html from
web/palette_template.html by inlining that JSON. Also writes a standalone copy to
docs/index.html (with its own <head>), which GitHub Pages serves from the docs/ folder. Optionally (--check) also writes the
Python-computed colour of every cell for every preset, to test the page's JS port against.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import polylabel

import bivariate as bv
from selection import PREFIX, SELECTIONS
from svgmap import CRS, SvgMap

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
WEB = ROOT / "web"
OUT = ROOT / "output" / "web" / "interstate_palettes.html"
PAGES = ROOT / "docs" / "index.html"
ELECTORAL = ROOT / "results" / "electoral_x5_odd__x10.csv"  # from electoral.py (the Easter egg)

# The template is written for a host that supplies the document skeleton and a small CSS
# reset; the GitHub Pages copy carries its own.
STANDALONE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 44 46'%3E%3Cpath d='M4 4C14 0 30 0 40 4C44 18 42 34 22 44C2 34 0 18 4 4Z' fill='%231d4f9c'/%3E%3Cpath d='M4.6 4.2C14 .6 30 .6 39.4 4.2L40.4 13H3.6Z' fill='%23c41e3a'/%3E%3C/svg%3E">
<style>
:root { color-scheme: light; padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
body { margin: 0; font: 14px system-ui, sans-serif; }
img { max-width: 100%; }
[hidden] { display: none !important; }
</style>
"""


def standalone(page):
    """Wrap the built page in a full HTML document: title, fonts and styles go in <head>."""
    split = page.index("</style>") + len("</style>")
    return f"{STANDALONE_HEAD}{page[:split]}\n</head>\n<body>\n{page[split:]}\n</body>\n</html>\n"

PAIRS = [("x5_odd", "x10", "Major routes", "I-5 … I-95 (odd, ÷5) × I-10 … I-90 (÷10)"),
         ("odd", "even", "All Interstates", "every odd × every even 1–2 digit Interstate")]

NAMES = {
    "yellow_blue": "Blue × yellow", "cmy_multiply": "Cyan × yellow ink", "pink_teal": "Pink × teal",
    "orange_purple": "Orange × purple", "coasts_3x2": "Coasts 3×2", "landscape_3x3": "Landscape 3×3",
    "compass_3x3": "Compass", "compass_centered": "Compass, centred",
    "compass_gray": "Compass, grey", "compass_centered_gray": "Compass, grey, centred",
    "compass_black": "Compass, black", "compass_centered_black": "Compass, black, centred",
    "stevens_pink_teal_3x3": "Stevens pink × teal", "stevens_green_blue_3x3": "Stevens blue × green",
    "spectrum": "Full spectrum", "hue_lightness": "Rainbow × darkness",
}


def preset_specs():
    out = []
    for key, s in bv.SCHEMES.items():
        if s.get("centered"):
            spec = dict(kind="grid", rows=s["rows"], center="geo")
        else:
            spec = dict(s["fn"].spec)
            if spec["kind"] == "grid":
                spec["center"] = "even"
                spec.pop("xs"), spec.pop("ys")  # all non-centred grids are evenly spaced
        light = s.get("routes", {}).get("stroke", "").lower() == "#ffffff"
        out.append(dict(id=key, name=NAMES.get(key, key), title=s["title"], spec=spec,
                        routes="light" if light else "dark"))
    return out


def pair_data(ns, ew, label, desc, outline, roads):
    m = SvgMap(outline.total_bounds)
    combo = gpd.read_file(DATA / f"bivariate_{ns}__{ew}.geojson").to_crs(CRS)
    cells = [dict(ns=int(r.ns), ew=int(r.ew), d=m.area_d(r.geometry)) for _, r in combo.iterrows()]
    center = gpd.GeoSeries([Point(bv.US_CENTER[1], bv.US_CENTER[0])], crs=4326).to_crs(CRS).iloc[0]
    cu = bv.center_value(bv.routes_for(ns, roads), center, "x")[0]
    cv = bv.center_value(bv.routes_for(ew, roads), center, "y")[0]
    cx, cy = m.xy(center.x, center.y)
    extra = dict(electoral=electoral_data(m, combo)) if (ns, ew) == ("x5_odd", "x10") and ELECTORAL.exists() else {}
    return dict(
        id=f"{ns}__{ew}", label=label, desc=desc,
        prefix=[PREFIX[SELECTIONS[ns]["level"]], PREFIX[SELECTIONS[ew]["level"]]],
        ns=sorted({c["ns"] for c in cells}), ew=sorted({c["ew"] for c in cells}),
        center=dict(u=round(bv.norm(cu), 4), v=round(bv.norm(cv), 4), ns=round(cu, 1), ew=round(cv, 1),
                    x=round(cx, 1), y=round(cy, 1)),
        width=m.width, height=m.map_height,
        outline=m.area_d(outline.geometry.iloc[0]),
        routes_ns=m.line_d(bv.routes_for(ns, roads).geometry),
        routes_ew=m.line_d(bv.routes_for(ew, roads).geometry),
        cells=cells, **extra,
    ), combo


def electoral_data(m, combo):
    """Per-zone largest city, population, electoral votes and 2024 votes, with label and city-dot points in map pixels."""
    z = pd.read_csv(ELECTORAL, keep_default_na=False)
    out = []
    for _, r in z.iterrows():
        geom = combo[(combo.ns == r.ns) & (combo.ew == r.ew)].geometry.union_all()
        biggest = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
        pt = polylabel(biggest, tolerance=1000)
        x, y = m.xy(pt.x, pt.y)
        zone = dict(ns=int(r.ns), ew=int(r.ew), city=r.city, pop=int(r.population), ev=int(r.ev),
                    r=int(r.votes_gop), d=int(r.votes_dem), t=int(r.total_votes),
                    x=round(x, 1), y=round(y, 1))
        if r.city_lon != "":  # the city's dot (none for zones named after a place outside them)
            c = gpd.GeoSeries([Point(float(r.city_lon), float(r.city_lat))], crs=4326).to_crs(CRS).iloc[0]
            zone["cx"], zone["cy"] = (round(v, 1) for v in m.xy(c.x, c.y))
        out.append(zone)
    return out


def main():
    outline = gpd.read_file(DATA / "lower48.geojson").to_crs(CRS)
    roads = gpd.read_file(DATA / "highways_lower48.geojson").to_crs(CRS)
    pairs, check = [], {}
    for ns, ew, label, desc in PAIRS:
        pd_, combo = pair_data(ns, ew, label, desc, outline, roads)
        pairs.append(pd_)
        if "--check" in sys.argv:  # reference colours from the Python implementation
            for key, s in bv.SCHEMES.items():
                fn = bv.centred_fn(key, ns, ew, roads)[0] if s.get("centered") else s["fn"]
                check[f"{pd_['id']}/{key}"] = [fn(bv.norm(c["ns"]), bv.norm(c["ew"])) for c in pd_["cells"]]
    data = dict(scale=list(bv.SCALE), presets=preset_specs(), pairs=pairs)
    WEB.mkdir(exist_ok=True)
    js = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    (WEB / "palette_data.json").write_text(js)
    if check:
        (WEB / "palette_check.json").write_text(json.dumps(check))
    template = (WEB / "palette_template.html").read_text()
    page = template.replace("/*__PALETTE_DATA__*/null", js.replace("</", "<\\/"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    PAGES.write_text(standalone(page))
    print(f"data {len(js) / 1024:.0f} KB, page {OUT.stat().st_size / 1024:.0f} KB -> {OUT}")
    print(f"GitHub Pages copy -> {PAGES}")


if __name__ == "__main__":
    main()
