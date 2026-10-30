"""Minimal SVG map writer: projected geometries -> SVG paths, plus a PNG preview."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon

CRS = "EPSG:5070"  # NAD83 / Conus Albers
WIDTH = 1200
PAD = 20
SIMPLIFY_M = 500  # metres, applied after projection


def rings(geom):
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom] if isinstance(geom, Polygon) else []
    for p in polys:
        yield p.exterior
        yield from p.interiors


def lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from lines(g)


def launch_browser(p):
    """Chromium for PNG previews: Playwright's own build, or CHROME_PATH if set
    (e.g. when Playwright's browser download isn't available)."""
    return p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)


class SvgMap:
    def __init__(self, bounds, width=WIDTH, pad=PAD, extra_bottom=0):
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.width, self.pad = width, pad
        self.scale = (width - 2 * pad) / (self.maxx - self.minx)
        self.map_height = round((self.maxy - self.miny) * self.scale + 2 * pad)
        self.height = self.map_height + extra_bottom
        self.items = []

    def xy(self, x, y):
        return (x - self.minx) * self.scale + self.pad, (self.maxy - y) * self.scale + self.pad

    def _path(self, coords, close=False):
        pts = ("{:.1f},{:.1f}".format(*self.xy(x, y)) for x, y, *_ in coords)
        return "M" + "L".join(pts) + ("Z" if close else "")

    def area_d(self, geom):
        return "".join(self._path(r.coords, close=True) for r in rings(geom.simplify(SIMPLIFY_M)))

    def line_d(self, geoms):
        return "".join(self._path(l.coords) for g in geoms for l in lines(g.simplify(SIMPLIFY_M)))

    def add(self, svg):
        self.items.append(svg)

    def save(self, out: Path, background="#ffffff"):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
               f'viewBox="0 0 {self.width} {self.height}">\n'
               f'  <rect width="100%" height="100%" fill="{background}"/>\n  '
               + "\n  ".join(self.items) + "\n</svg>\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg)
        png = out.with_suffix(".png")
        # raster preview (2x) for viewing on devices that don't preview SVG
        with sync_playwright() as p:
            browser = launch_browser(p)
            page = browser.new_page(viewport={"width": self.width, "height": self.height}, device_scale_factor=2)
            page.goto(out.as_uri())
            page.screenshot(path=png)
            browser.close()
        print(f"wrote {out} ({self.width}x{self.height}, {len(svg) / 1024:.0f} KB) and {png.name}")
