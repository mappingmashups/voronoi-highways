"""Bivariate map: overlay a north-south and an east-west nearest-route layer and colour
each intersection by its pair of route numbers.

Usage: python scripts/bivariate.py [ns_selection ew_selection [scheme ...]]
       default: x5_odd x10, all schemes
"""
import colorsys
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely.ops
from shapely.geometry import Point

from colorspace import hex_to_oklab, hex_to_rgb, oklab_to_hex, rgb_to_hex
from selection import PREFIX, SELECTIONS, route_numbers
from svgmap import CRS, SvgMap

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
OUT = ROOT / "output" / "bivariate"
FONT = "Helvetica, Arial, sans-serif"

# Both numbers are looked up on a fixed 0-100 scale (not by rank), like the rainbow maps.
# u: north-south (odd) route number -> runs west (0) to east (1)
# v: east-west (even) route number  -> runs south (0) to north (1)
SCALE = (0, 100)


def norm(n):
    lo, hi = SCALE
    return min(max((n - lo) / (hi - lo), 0), 1)


def grid(rows, xs=None, ys=None):
    """Colour function from a grid of control colours, blended piecewise-bilinearly in OKLab.

    rows: list of rows from south to north, each a list of colours from west to east.
    xs / ys: positions (0-1) of the columns / rows; evenly spaced by default
    (2x2 = four corners, 3x3 adds midpoints and a centre).
    """
    lab = np.array([[hex_to_oklab(h) for h in row] for row in rows])  # [row, col, 3]
    nr, nc = lab.shape[:2]
    xs = np.linspace(0, 1, nc) if xs is None else np.asarray(xs, float)
    ys = np.linspace(0, 1, nr) if ys is None else np.asarray(ys, float)

    def fn(u, v):
        i = min(max(np.searchsorted(xs, u, side="right") - 1, 0), nc - 2)
        j = min(max(np.searchsorted(ys, v, side="right") - 1, 0), nr - 2)
        tx = (u - xs[i]) / (xs[i + 1] - xs[i])
        ty = (v - ys[j]) / (ys[j + 1] - ys[j])
        c = (lab[j, i] * (1 - tx) * (1 - ty) + lab[j, i + 1] * tx * (1 - ty)
             + lab[j + 1, i] * (1 - tx) * ty + lab[j + 1, i + 1] * tx * ty)
        return oklab_to_hex(c)
    fn.spec = dict(kind="grid", rows=[list(r) for r in rows], xs=xs.tolist(), ys=ys.tolist())
    return fn


def corners(sw, nw, se, ne):
    """2x2 grid from four corner colours."""
    return grid([[sw, se], [nw, ne]])


def multiply(ew_ramp_end, ns_ramp_end):
    """True 'ink' overlay: white->colour ramp per layer, multiplied (like stacking transparencies)."""
    a, b = hex_to_rgb(ew_ramp_end), hex_to_rgb(ns_ramp_end)

    def fn(u, v):
        ew = 1 - v * (1 - a)  # white -> a going south -> north
        ns = 1 - u * (1 - b)  # white -> b going west -> east
        return rgb_to_hex(ew * ns)
    fn.spec = dict(kind="multiply", ew=ew_ramp_end, ns=ns_ramp_end)
    return fn


def oklab_plane(lightness=0.80, chroma=0.13):
    """Full-spectrum 2D colour map: u drives OKLab a (green->red), v drives b (blue->yellow)."""
    def fn(u, v):
        return oklab_to_hex([lightness, (2 * u - 1) * chroma, (2 * v - 1) * chroma])
    fn.spec = dict(kind="plane", lightness=lightness, chroma=chroma)
    return fn


def hue_lightness():
    """Rainbow hue from the N-S route (as in the single maps), lightness from the E-W route."""
    def fn(u, v):
        r, g, b = colorsys.hls_to_rgb(u * 285 / 360, 0.88 - 0.48 * v, 0.80)
        return rgb_to_hex(np.array([r, g, b]))
    fn.spec = dict(kind="hue_lightness")
    return fn


def compass(center="#ffffff"):
    """3x3 compass grid: a hue in each direction, `center` colour in the middle."""
    return [["#d1495b", "#f08c2e", "#e8c52a"],
            ["#8a5fc4", center, "#5fae5a"],
            ["#3d5fc4", "#2f8fc7", "#2aa39a"]]


COMPASS = compass()
GRAY, BLACK = "#8f8f8f", "#000000"
LIGHT_ROUTES = dict(stroke="#ffffff", opacity=0.55)  # for schemes with a dark middle

# Geographic centre of the contiguous US (near Lebanon, Kansas)
US_CENTER = (39.8283, -98.5795)

SCHEMES = {
    "yellow_blue": dict(fn=corners(sw="#ffffff", nw="#2f6fd6", se="#f2cc0c", ne="#2f9a4a"),
                        title="White→blue (south→north) × white→yellow (west→east), green where both are high"),
    "cmy_multiply": dict(fn=multiply(ew_ramp_end="#00b7eb", ns_ramp_end="#ffe600"),
                         title="Cyan (north) × yellow (east) ink overlay (multiply blend)"),
    "pink_teal": dict(fn=corners(sw="#e8e8e8", nw="#be64ac", se="#5ac8c8", ne="#3b4994"),
                      title="Classic bivariate: grey, pink (north), teal (east), indigo (north-east)"),
    "orange_purple": dict(fn=corners(sw="#f3f3f3", nw="#f0a030", se="#8e6cc8", ne="#9b2a3a"),
                          title="Orange (north) × purple (east) → burgundy north-east"),
    # --- 3x2 and 3x3 control grids (rows south -> north, colours west -> east) ---
    "coasts_3x2": dict(fn=grid([["#d9643f", "#f6f1e7", "#f2c40c"],
                                ["#2f62c8", "#cfd8e6", "#2f9a4a"]]),
                       title="3×2 coasts: terracotta SW, yellow SE, blue NW, green NE; muted interior"),
    "landscape_3x3": dict(fn=grid([["#d36b3f", "#e6b45c", "#f0d03a"],
                                   ["#9fb79b", "#f3efe4", "#93c26a"],
                                   ["#2f62b8", "#6e8ea6", "#25744a"]]),
                          title="3×3 landscape: desert, wheat, sun / sage, cream, meadow / rain, slate, forest"),
    "compass_3x3": dict(fn=grid(COMPASS),
                        title="3×3 compass: white centre of the grid, a different hue in every direction"),
    # same colours, but the white centre sits at the route numbers found at the
    # geographic centre of the lower 48 (fn is built per map pair, see centred_fn)
    "compass_centered": dict(rows=COMPASS, centered=True,
                             title="3×3 compass, white at the geographic centre of the lower 48"),
    "compass_gray": dict(fn=grid(compass(GRAY)),
                         title="3×3 compass, grey centre of the grid"),
    "compass_black": dict(fn=grid(compass(BLACK)), routes=LIGHT_ROUTES,
                          title="3×3 compass, black centre of the grid"),
    "compass_centered_gray": dict(rows=compass(GRAY), centered=True,
                                  title="3×3 compass, grey at the geographic centre of the lower 48"),
    "compass_centered_black": dict(rows=compass(BLACK), centered=True, routes=LIGHT_ROUTES,
                                   title="3×3 compass, black at the geographic centre of the lower 48"),
    "stevens_pink_teal_3x3": dict(fn=grid([["#e8e8e8", "#ace4e4", "#5ac8c8"],
                                           ["#dfb0d6", "#a5add3", "#5698b9"],
                                           ["#be64ac", "#8c62aa", "#3b4994"]]),
                                  title="3×3 classic bivariate (Stevens): pink north × teal east"),
    "stevens_green_blue_3x3": dict(fn=grid([["#e8e8e8", "#b8d6be", "#73ae80"],
                                            ["#b5c0da", "#90b2b3", "#5a9178"],
                                            ["#6c83b5", "#567994", "#2a5a5b"]]),
                                   title="3×3 classic bivariate (Stevens): blue north × green east"),
    "spectrum": dict(fn=oklab_plane(),
                     title="Full-spectrum plane: west green / east red × south blue / north yellow"),
    "hue_lightness": dict(fn=hue_lightness(),
                          title="Rainbow hue from north–south route, darkness from east–west route"),
}


def load_regions(name):
    r = gpd.read_file(DATA / f"voronoi_{name}.geojson").to_crs(CRS)
    return r[["number", "geometry"]]


def routes_for(name, roads):
    sel = SELECTIONS[name]
    r = roads[roads.level == sel["level"]].copy()
    r["number"] = r.routes.map(lambda x: min((n for n in route_numbers(x) if sel["keep"](n)), default=None))
    return r[r.number.notna()]


def center_value(routes, center, axis):
    """Interpolated route number at `center`: the nearest selected route on each side
    (west/east for axis="x", south/north for axis="y"), weighted by distance."""
    sides = {}
    for n, group in routes.groupby("number"):
        geom = group.geometry.union_all()
        d = geom.distance(center)
        near = shapely.ops.nearest_points(geom, center)[0]
        side = (near.x if axis == "x" else near.y) > (center.x if axis == "x" else center.y)
        if side not in sides or d < sides[side][1]:
            sides[side] = (int(n), d)
    (n_lo, d_lo), (n_hi, d_hi) = sides[False], sides[True]
    value = n_lo + (n_hi - n_lo) * d_lo / (d_lo + d_hi)
    return value, (n_lo, d_lo), (n_hi, d_hi)


def centred_fn(scheme, ns, ew, roads):
    center = gpd.GeoSeries([Point(US_CENTER[1], US_CENTER[0])], crs=4326).to_crs(CRS).iloc[0]
    cu, w, e = center_value(routes_for(ns, roads), center, "x")
    cv, so, no = center_value(routes_for(ew, roads), center, "y")
    print(f"  centre: N-S {cu:.1f} (between {w[0]} at {w[1] / 1000:.0f} km W and {e[0]} at {e[1] / 1000:.0f} km E), "
          f"E-W {cv:.1f} (between {so[0]} at {so[1] / 1000:.0f} km S and {no[0]} at {no[1] / 1000:.0f} km N)")
    fn = grid(SCHEMES[scheme]["rows"], xs=[0, norm(cu), 1], ys=[0, norm(cv), 1])
    pre_ns, pre_ew = PREFIX[SELECTIONS[ns]["level"]], PREFIX[SELECTIONS[ew]["level"]]
    title = f"{SCHEMES[scheme]['title']} ({pre_ns}{cu:.1f} × {pre_ew}{cv:.1f})"
    return fn, title, center


def render(ns, ew, scheme, outline, combo, roads):
    center = None
    if SCHEMES[scheme].get("centered"):
        fn, title, center = centred_fn(scheme, ns, ew, roads)
    else:
        fn, title = SCHEMES[scheme]["fn"], SCHEMES[scheme]["title"]
    ns_nums = sorted(combo.ns.unique())
    ew_nums = sorted(combo.ew.unique())

    cell = 22 if max(len(ns_nums), len(ew_nums)) <= 12 else 16
    legend_h = 70 + cell * len(ew_nums)
    m = SvgMap(outline.total_bounds, extra_bottom=legend_h)
    m.add('<g id="cells" stroke="none">')
    for _, r in combo.iterrows():
        colour = fn(norm(r.ns), norm(r.ew))
        m.add(f'  <path id="cell-{r.ns}-{r.ew}" d="{m.area_d(r.geometry)}" fill="{colour}" '
              f'stroke="{colour}" stroke-width="0.3" fill-rule="evenodd"/>')
    m.add("</g>")
    m.add(f'<path id="outline" d="{m.area_d(outline.geometry.iloc[0])}" fill="none" stroke="#7a7a7a" '
          f'stroke-width="0.75" stroke-linejoin="round"/>')
    rs = SCHEMES[scheme].get("routes", dict(stroke="#3a3a3a", opacity=0.7))
    m.add(f'<g id="routes" fill="none" stroke="{rs["stroke"]}" stroke-opacity="{rs["opacity"]}" stroke-width="0.9" '
          'stroke-linecap="round" stroke-linejoin="round">')
    for name in (ns, ew):
        m.add(f'  <path id="routes-{name}" d="{m.line_d(routes_for(name, roads).geometry)}"/>')
    m.add("</g>")

    # bivariate legend: N-S routes across (west -> east), E-W routes up (south -> north)
    pre_ns, pre_ew = PREFIX[SELECTIONS[ns]["level"]], PREFIX[SELECTIONS[ew]["level"]]
    x0, y0 = m.pad + 70, m.map_height + 30
    present = set(zip(combo.ns, combo.ew))
    m.add(f'<g id="legend" font-family="{FONT}" font-size="11" fill="#333">')
    m.add(f'  <text x="{m.pad + 10}" y="{y0 - 12}" font-size="14" font-weight="bold">{title}</text>')
    for j, e in enumerate(reversed(ew_nums)):
        y = y0 + j * cell
        m.add(f'  <text x="{x0 - 6}" y="{y + cell * 0.65:.0f}" text-anchor="end">{pre_ew}{e}</text>')
        for i, n in enumerate(ns_nums):
            x = x0 + i * cell
            inset = 0 if (n, e) in present else cell // 4  # small square: combination not on the map
            size = cell - 2 - 2 * inset
            m.add(f'  <rect x="{x + inset}" y="{y + inset}" width="{size}" height="{size}" fill="{fn(norm(n), norm(e))}"/>')
    yb = y0 + len(ew_nums) * cell + 12
    for i, n in enumerate(ns_nums):
        m.add(f'  <text x="{x0 + i * cell + cell / 2 - 1:.0f}" y="{yb}" text-anchor="middle">{n}</text>')
    xr = x0 + len(ns_nums) * cell + 16
    m.add(f'  <text x="{xr}" y="{y0 + 12}">↑ north: east–west route ({pre_ew}{ew_nums[0]}…{ew_nums[-1]})</text>')
    m.add(f'  <text x="{xr}" y="{y0 + 30}">→ east: north–south route ({pre_ns}{ns_nums[0]}…{ns_nums[-1]})</text>')
    m.add(f'  <text x="{xr}" y="{y0 + 48}" fill="#777">small squares: combinations that don’t occur on the map</text>')
    m.add("</g>")
    if center is not None:  # mark the point the colours are centred on
        x, y = m.xy(center.x, center.y)
        m.add(f'<g id="center" font-family="{FONT}" font-size="11" fill="#222">'
              f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#fff" stroke="#222" stroke-width="1.5"/>'
              f'<text x="{x + 8:.1f}" y="{y - 6:.1f}" paint-order="stroke" stroke="#fff" stroke-width="3">'
              f'geographic centre</text></g>')
    m.save(OUT / f"{ns}__{ew}__{scheme}.svg")


def main():
    args = sys.argv[1:]
    ns, ew = (args[0], args[1]) if len(args) >= 2 else ("x5_odd", "x10")
    schemes = args[2:] or list(SCHEMES)
    outline = gpd.read_file(DATA / "lower48.geojson").to_crs(CRS)
    roads = gpd.read_file(DATA / "highways_lower48.geojson").to_crs(CRS)

    a = load_regions(ns).rename(columns={"number": "ns"})
    b = load_regions(ew).rename(columns={"number": "ew"})
    combo = gpd.overlay(a, b, how="intersection", keep_geom_type=True)
    combo = combo[combo.area > 1e6]  # drop slivers under 1 km²
    OUT.mkdir(parents=True, exist_ok=True)
    combo.to_crs("EPSG:4326").to_file(DATA / f"bivariate_{ns}__{ew}.geojson", driver="GeoJSON")
    print(f"{len(combo)} cells from {len(a)} × {len(b)} regions")
    for s in schemes:
        render(ns, ew, s, outline, combo, roads)


if __name__ == "__main__":
    main()
