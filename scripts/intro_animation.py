"""Intro animation: how the nearest-Interstate maps are built, rendered to an MP4.

1. A blank map. The odd Interstates divisible by 5 (I-5 … I-95) draw in, west to east, as thick
   rainbow lines in black casings, each with its shield; then their nearest-route zones fill in,
   west to east, in the same colors.
2. Everything fades back to the outline. The Interstates divisible by 10 draw in from I-90 down
   to I-10, and their zones fill in, north to south.
3. Back to the outline. Both sets draw in together in black, sweeping from the northwest, and the
   map fills with the combined zones in the gray-centered compass palette, which then turns once
   around its color ring.

The timeline lives in a generated HTML page (render(t) draws any moment), so every frame is exact;
headless Chromium captures the frames and ffmpeg encodes them.

Usage: python scripts/intro_animation.py [--fps 30] [--width 1600] [--out PATH] [--gif PATH] [--html-only]
       python scripts/intro_animation.py --readme   # docs/images/intro.mp4 and intro.gif
Needs the processed data (see README) and ffmpeg. Writes output/intro/intro.html and intro.mp4.
The GIF is captured separately, smaller (--gif-width, --gif-fps), straight from the page:
making it from the MP4 would carry the video's compression noise into banding stripes.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
from playwright.sync_api import sync_playwright
from shapely.geometry import Point

import bivariate as bv
from colorspace import hex_to_oklab, oklab_to_hex
from selection import SELECTIONS, fill_color, hsl_hex, hue_for, route_numbers
from svgmap import CRS, SvgMap, launch_browser, lines

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
OUT = ROOT / "output" / "intro"
NS, EW = "x5_odd", "x10"          # the major-route pair
SPIN_STEPS = 240                  # precomputed color-ring angles for the final turn
SHIELD_GAP = 44                   # min distance between shield centers (map units, 1200 wide)
MARGIN = 36                       # room around the map for shields at its edges


def line_color(n):
    """Bright rainbow color for a route line (the zones use selection.fill_color)."""
    return hsl_hex(hue_for(n), 0.80, 0.52)


def route_geoms(roads, numbers):
    """All Interstate segments carrying each route number (shared stretches count for both)."""
    inter = roads[roads.level == "Interstate"]
    nums = inter.routes.map(route_numbers)
    return {n: inter[nums.map(lambda ns, n=n: n in ns)].geometry for n in numbers}


def turn_ring(rows, deg):
    """Turn a 3x3 grid's outer colors clockwise around the ring (mirrors the palette page)."""
    ring = [(0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0), (0, 0), (0, 1)]  # (i, j) clockwise from NW
    s = ((deg / 45) % 8 + 8) % 8
    n, f = int(np.floor(s)), s - np.floor(s)
    old = [hex_to_oklab(rows[j][i]) for i, j in ring]
    out = [list(r) for r in rows]
    for k, (i, j) in enumerate(ring):
        out[j][i] = oklab_to_hex(old[(k - n) % 8] * (1 - f) + old[(k - n - 1) % 8] * f)
    return out


def relax(shields, width, height):
    """Nudge shields apart where they would overlap, pulling each gently back to its anchor."""
    pos = np.array([[s["x"], s["y"]] for s in shields], float)
    anchor = pos.copy()
    for _ in range(400):
        for a in range(len(pos)):
            for b in range(a + 1, len(pos)):
                d = pos[b] - pos[a]
                dist = np.hypot(*d)
                if dist < SHIELD_GAP:
                    v = d / dist if dist > 1e-6 else np.array([1.0, 0.0])
                    push = (SHIELD_GAP - dist) / 2 * v
                    pos[a] -= push
                    pos[b] += push
        pos += (anchor - pos) * 0.02
        pos[:, 0] = pos[:, 0].clip(20 - MARGIN, width + MARGIN - 20)
        pos[:, 1] = pos[:, 1].clip(22 - MARGIN, height + MARGIN - 22)
    for s, (x, y) in zip(shields, pos):
        s["x"], s["y"] = round(float(x), 1), round(float(y), 1)


def build_data():
    outline = gpd.read_file(DATA / "lower48.geojson").to_crs(CRS)
    roads = gpd.read_file(DATA / "highways_lower48.geojson").to_crs(CRS)
    m = SvgMap(outline.total_bounds)
    W, H = m.width, m.map_height

    zones = {name: gpd.read_file(DATA / f"voronoi_{name}.geojson").to_crs(CRS) for name in (NS, EW)}
    ns_nums = sorted(zones[NS].number)
    ew_nums = sorted(zones[EW].number, reverse=True)  # drawn from I-90 down

    def svg_coords(geoms):
        pts = np.array([m.xy(x, y) for g in geoms for line in lines(g.simplify(500)) for x, y, *_ in line.coords])
        return pts

    routes, shields = [], []
    for kind, nums in (("ns", ns_nums), ("ew", ew_nums)):
        geoms = route_geoms(roads, nums)
        for n in nums:
            pts = svg_coords(geoms[n])
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            routes.append(dict(kind=kind, n=int(n), d=m.line_d(geoms[n]), color=line_color(n),
                               bbox=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]))
            if kind == "ns":   # shield above the route's northern end
                ex, ey = pts[pts[:, 1].argmin()]
                shields.append(dict(kind=kind, n=int(n), x=ex, y=ey - 20))
            else:              # shield left of the route's western end
                ex, ey = pts[pts[:, 0].argmin()]
                shields.append(dict(kind=kind, n=int(n), x=ex - 20, y=ey))
    relax(shields, W, H)

    zone_data = {}
    for name, nums in ((NS, ns_nums), (EW, ew_nums)):
        z = zones[name].set_index("number")
        zone_data[name] = [dict(n=int(n), d=m.area_d(z.loc[n].geometry), color=fill_color(n)) for n in nums]

    # combined zones in the gray-centered compass, at every step of one turn of its color ring
    combo = gpd.read_file(DATA / f"bivariate_{NS}__{EW}.geojson").to_crs(CRS)
    center = gpd.GeoSeries([Point(bv.US_CENTER[1], bv.US_CENTER[0])], crs=4326).to_crs(CRS).iloc[0]
    cu = bv.center_value(bv.routes_for(NS, roads), center, "x")[0]
    cv = bv.center_value(bv.routes_for(EW, roads), center, "y")[0]
    rows = bv.compass(bv.GRAY)
    xs, ys = [0, bv.norm(cu), 1], [0, bv.norm(cv), 1]
    spin = []
    for k in range(SPIN_STEPS):
        fn = bv.grid(turn_ring(rows, 360 * k / SPIN_STEPS), xs=xs, ys=ys)
        spin.append([fn(bv.norm(r.ns), bv.norm(r.ew)) for r in combo.itertuples()])
    cells = []
    for r in combo.itertuples():
        cx, cy = m.xy(r.geometry.centroid.x, r.geometry.centroid.y)
        cells.append(dict(d=m.area_d(r.geometry), diag=round((cx / W + cy / H) / 2, 4)))

    return dict(width=W, height=H, margin=MARGIN, outline=m.area_d(outline.geometry.iloc[0]),
                routes=routes, shields=shields, zones=zone_data, ns=NS, ew=EW, cells=cells, spin=spin)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Overpass:wght@800&display=swap">
<style>
  html, body { margin: 0; background: #fff; }
  svg { display: block; width: 100vw; height: auto; }
  .shield text { font-family: Overpass, "Helvetica Neue", Arial, sans-serif; font-weight: 800; }
</style></head>
<body>
<svg id="svg" xmlns="http://www.w3.org/2000/svg"></svg>
<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg", svg = document.getElementById("svg");
const W = DATA.width, H = DATA.height, M = DATA.margin;
svg.setAttribute("viewBox", `${-M} ${-M} ${W + 2 * M} ${H + 2 * M}`);
const el = (name, attrs, parent = svg) => {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e); return e;
};
const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
const ramp = (t, start, dur) => ease((t - start) / dur);

// ---------- timeline (seconds) ----------
const nNS = DATA.routes.filter((r) => r.kind === "ns").length, nEW = DATA.routes.length - nNS;
const DRAW = 1.0, FADE = 0.7, OUT = 1.0, HOLD = 1.6, PAUSE = 0.6;
const T = {};
T.a = 1.0;                                            // blank map first
T.aStep = 0.55; T.aZones = T.a + (nNS - 1) * T.aStep + DRAW + PAUSE;
T.aZoneStep = 0.35; T.aOut = T.aZones + (nNS - 1) * T.aZoneStep + FADE + HOLD;
T.b = T.aOut + OUT + PAUSE;
T.bStep = 0.6; T.bZones = T.b + (nEW - 1) * T.bStep + DRAW + PAUSE;
T.bZoneStep = 0.4; T.bOut = T.bZones + (nEW - 1) * T.bZoneStep + FADE + HOLD;
T.c = T.bOut + OUT + PAUSE;
T.cSweep = 3.0;                                       // routes draw in from the northwest
T.cFill = T.c + 1.0; T.cFillSweep = 3.0; T.cCellFade = 0.8;
T.spin = T.cFill + T.cFillSweep + T.cCellFade + 1.2; T.spinDur = 6.0;
T.end = T.spin + T.spinDur + 2.0;
window.TOTAL = T.end;

// ---------- scene ----------
const defs = el("defs", {});
el("path", { d: DATA.outline, fill: "#f3f3f1", stroke: "none" });           // land
const zoneLayer = { [DATA.ns]: el("g", {}), [DATA.ew]: el("g", {}) };
const cellLayer = el("g", {});
el("path", { d: DATA.outline, fill: "none", stroke: "#8a8a8a", "stroke-width": 0.9, "stroke-linejoin": "round" });
const routeLayer = el("g", { fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" });
const blackLayer = el("g", { fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" });
const shieldLayer = el("g", {}), blackShieldLayer = el("g", {});

const zones = {};
for (const name of [DATA.ns, DATA.ew]) {
  zones[name] = DATA.zones[name].map((z) => el("path", { d: z.d, fill: z.color, "fill-rule": "evenodd", stroke: z.color, "stroke-width": 0.4, opacity: 0 }, zoneLayer[name]));
}
const cells = DATA.cells.map((c) => el("path", { d: c.d, "fill-rule": "evenodd", "stroke-width": 0.4, opacity: 0 }, cellLayer));

// colored routes, each revealed by its own clip (north -> south, or west -> east)
const routes = DATA.routes.map((r, i) => {
  const clip = el("clipPath", { id: "clip" + i }, defs);
  const rect = el("rect", { x: -M, y: -M, width: W + 2 * M, height: H + 2 * M }, clip);
  const g = el("g", { "clip-path": `url(#clip${i})` }, routeLayer);
  el("path", { d: r.d, stroke: "#111", "stroke-width": 7.5 }, g);
  el("path", { d: r.d, stroke: r.color, "stroke-width": 4.2 }, g);
  return { ...r, g, rect };
});
// the same routes in black for the final sweep, revealed by one diagonal clip from the northwest
const diag = el("polygon", { points: "" }, el("clipPath", { id: "diag" }, defs));
const blackG = el("g", { "clip-path": "url(#diag)" }, blackLayer);
DATA.routes.forEach((r) => el("path", { d: r.d, stroke: "#111", "stroke-width": 3.4 }, blackG));

const SHIELD = "M4 4C14 0 30 0 40 4C44 18 42 34 22 44C2 34 0 18 4 4Z", BAND = "M4.6 4.2C14 .6 30 .6 39.4 4.2L40.4 13H3.6Z";
function shield(s, parent) {
  const g = el("g", { class: "shield", opacity: 0 }, parent);
  const inner = el("g", {}, g);
  el("path", { d: SHIELD, fill: "#1d4f9c", stroke: "#fff", "stroke-width": 2.4 }, inner);
  el("path", { d: BAND, fill: "#c41e3a" }, inner);
  const t = el("text", { x: 22, y: 33, "text-anchor": "middle", fill: "#fff", "font-size": s.n >= 10 ? 17 : 19 }, inner);
  t.textContent = s.n;
  return { ...s, g, inner };
}
const shields = DATA.shields.map((s) => shield(s, shieldLayer));
const blackShields = DATA.shields.map((s) => shield(s, blackShieldLayer));
function placeShield(sh, a) {  // pop in: fade + grow
  sh.g.setAttribute("opacity", a.toFixed(3));
  const sc = 0.78 * (0.6 + 0.4 * a);
  sh.g.setAttribute("transform", `translate(${sh.x} ${sh.y}) scale(${sc}) translate(-22 -23)`);
}

// ---------- render any moment ----------
window.render = function (t) {
  const aOut = 1 - ramp(t, T.aOut, OUT), bOut = 1 - ramp(t, T.bOut, OUT);
  let iNS = 0, iEW = 0;
  routes.forEach((r, i) => {
    const k = r.kind === "ns" ? iNS++ : iEW++;
    const start = r.kind === "ns" ? T.a + k * T.aStep : T.b + k * T.bStep;
    const p = ramp(t, start, DRAW), [x0, y0, x1, y1] = r.bbox, pad = 12;
    if (r.kind === "ns") { r.rect.setAttribute("x", -M); r.rect.setAttribute("width", W + 2 * M); r.rect.setAttribute("y", y0 - pad); r.rect.setAttribute("height", p * (y1 - y0 + 2 * pad)); }
    else { r.rect.setAttribute("y", -M); r.rect.setAttribute("height", H + 2 * M); r.rect.setAttribute("x", x0 - pad); r.rect.setAttribute("width", p * (x1 - x0 + 2 * pad)); }
    const fade = r.kind === "ns" ? aOut : bOut;
    r.g.setAttribute("opacity", fade.toFixed(3));
    placeShield(shields[i], ramp(t, start + 0.05, 0.35) * fade);
  });
  zones[DATA.ns].forEach((z, k) => z.setAttribute("opacity", (ramp(t, T.aZones + k * T.aZoneStep, FADE) * aOut).toFixed(3)));
  zones[DATA.ew].forEach((z, k) => z.setAttribute("opacity", (ramp(t, T.bZones + k * T.bZoneStep, FADE) * bOut).toFixed(3)));

  // final sweep: a diagonal edge moves from the northwest corner to the southeast
  const s = 2 * ((t - T.c) / T.cSweep) * 1.05;  // in units of x/W + y/H
  let pts = "";
  if (s > 0) pts = s <= 1 ? `0,0 ${s * W},0 0,${s * H}` : `0,0 ${W},0 ${W},${(s - 1) * H} ${(s - 1) * W},${H} 0,${H}`;
  diag.setAttribute("points", s >= 2 ? `${-M},${-M} ${W + M},${-M} ${W + M},${H + M} ${-M},${H + M}` : pts);
  blackShields.forEach((sh) => {
    const at = T.c + (T.cSweep / 2.1) * (sh.x / W + sh.y / H);
    placeShield(sh, ramp(t, at, 0.35));
  });
  const k = t < T.spin ? 0 : Math.min(DATA.spin.length - 1, Math.floor(((t - T.spin) / T.spinDur) * DATA.spin.length)) % DATA.spin.length;
  const colors = t >= T.spin + T.spinDur ? DATA.spin[0] : DATA.spin[k];
  cells.forEach((c, i) => {
    c.setAttribute("fill", colors[i]); c.setAttribute("stroke", colors[i]);
    c.setAttribute("opacity", ramp(t, T.cFill + DATA.cells[i].diag * T.cFillSweep, T.cCellFade).toFixed(3));
  });
};
render(0);
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1600, help="video width in pixels")
    ap.add_argument("--out", type=Path, default=OUT / "intro.mp4")
    ap.add_argument("--gif", type=Path, help="also write a GIF here")
    ap.add_argument("--gif-width", type=int, default=720)
    ap.add_argument("--gif-fps", type=int, default=20, help="GIF timing is in 10 ms steps: 20 fps keeps the length exact")
    ap.add_argument("--readme", action="store_true", help="write docs/images/intro.mp4 and docs/images/intro.gif")
    ap.add_argument("--html-only", action="store_true", help="write the timeline page, skip rendering")
    args = ap.parse_args()
    if args.readme:
        args.out, args.gif = ROOT / "docs" / "images" / "intro.mp4", ROOT / "docs" / "images" / "intro.gif"

    data = build_data()
    OUT.mkdir(parents=True, exist_ok=True)
    html = OUT / "intro.html"
    html.write_text(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {html}")
    if args.html_only:
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    capture(html, data, args.width, args.fps, ["-c:v", "libx264", "-crf", "18", "-preset", "slow",
                                               "-pix_fmt", "yuv420p", "-movflags", "+faststart"], args.out)
    if args.gif:
        # one color table from all frames; only changed areas are stored from frame to frame
        args.gif.parent.mkdir(parents=True, exist_ok=True)
        capture(html, data, args.gif_width, args.gif_fps, [
            "-vf", "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
            "-loop", "0"], args.gif)


def capture(html, data, width, fps, encode, out):
    """Render every frame of the timeline page at this width and frame rate, then encode with ffmpeg."""
    m2 = 2 * data["margin"]
    height = round(width * (data["height"] + m2) / (data["width"] + m2) / 2) * 2  # even, for H.264
    with sync_playwright() as p, tempfile.TemporaryDirectory(dir=OUT) as tmp:
        browser = launch_browser(p)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(html.as_uri())
        page.evaluate("document.fonts.ready")
        total = page.evaluate("TOTAL")
        frames = int(total * fps) + 1
        print(f"{out.name}: {total:.1f} s, {frames} frames at {fps} fps, {width}×{height}")
        for f in range(frames):
            page.evaluate("t => render(t)", f / fps)
            page.screenshot(path=f"{tmp}/{f:05d}.png", clip=dict(x=0, y=0, width=width, height=height))
        browser.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{tmp}/%05d.png", *encode, str(out)],
                       check=True)
    print(f"wrote {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
