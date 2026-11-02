"""Check the palette page's JavaScript colours against the Python implementation.

Run after `python scripts/export_web.py --check`: opens the built page in Chromium and
compares every cell's colour for every preset on both route pairs (tolerance: 1/255), then
checks the palette turning (quarter turns, mirrors and colour-ring turns) for consistency.
Usage: python scripts/check_web.py [page.html or URL]   (default: output/web/voronoi_highways.html)
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from svgmap import launch_browser

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "output" / "web" / "voronoi_highways.html"
CHECK = ROOT / "web" / "palette_check.json"

COMPARE = """(check) => {
  const {makeFn, norm, DATA} = window.__ipl, out = {};
  for (const [k, ref] of Object.entries(check)) {
    const [pid, sid] = k.split('/'), pair = DATA.pairs.find(p => p.id === pid);
    const fn = makeFn(DATA.presets.find(p => p.id === sid).spec, pair);
    let worst = 0;
    pair.cells.forEach((c, i) => {
      const a = fn(norm(c.ns), norm(c.ew)), r = ref[i];
      for (const o of [1, 3, 5]) worst = Math.max(worst, Math.abs(parseInt(a.substr(o, 2), 16) - parseInt(r.substr(o, 2), 16)));
    });
    out[k] = worst;
  }
  return out;
}"""


ORIENT = """() => {
  const {makeFn, orientSpec, ringable, DATA} = window.__ipl, pair = DATA.pairs[0], fails = [];
  const pts = []; for (let i = 0; i <= 10; i++) for (let j = 0; j <= 10; j++) pts.push([i / 10, j / 10]);
  const diff = (a, b) => Math.max(...[1, 3, 5].map(o => Math.abs(parseInt(a.substr(o, 2), 16) - parseInt(b.substr(o, 2), 16))));
  const same = (name, f, g, tol = 1) => {
    const worst = Math.max(...pts.map(([u, v]) => diff(f(u, v), g(u, v))));
    if (worst > tol) fails.push(`${name}: off by ${worst}`);
  };
  const turned = (spec, o) => makeFn(orientSpec(spec, {rot: 0, mirror: false, ring: 0, ...o}), pair);
  for (const p of DATA.presets) {
    const f = makeFn(p.spec, pair);
    if (p.spec.kind === "grid") {
      // grid turns rearrange the colours, so they stack: four quarter turns or two mirrors give it back
      let s = p.spec; for (let k = 0; k < 4; k++) s = orientSpec(s, {rot: 1, mirror: false, ring: 0});
      same(`${p.id} 4 quarter turns`, f, makeFn(s, pair));
      same(`${p.id} mirrored twice`, f, makeFn(orientSpec(orientSpec(p.spec, {rot: 0, mirror: true, ring: 0}), {rot: 0, mirror: true, ring: 0}), pair));
      if (ringable(p.spec)) {
        same(`${p.id} ring -45 then +45`, makeFn(orientSpec(orientSpec(p.spec, {rot: 0, mirror: false, ring: -45}), {rot: 0, mirror: false, ring: 45}), pair), f);
      }
    }
    // on evenly spaced grids and formulas, turning the palette = sampling the original at turned coordinates
    if (p.spec.kind !== "grid" || p.spec.center === "even") {
      same(`${p.id} 90° clockwise`, turned(p.spec, {rot: 1}), (u, v) => f(1 - v, u));
      same(`${p.id} 180°`, turned(p.spec, {rot: 2}), (u, v) => f(1 - u, 1 - v));
      same(`${p.id} 90° anticlockwise`, turned(p.spec, {rot: 3}), (u, v) => f(v, 1 - u));
      same(`${p.id} mirror east–west`, turned(p.spec, {mirror: true}), (u, v) => f(1 - u, v));
      same(`${p.id} mirror north–south`, turned(p.spec, {mirror: true, rot: 2}), (u, v) => f(u, 1 - v));
    }
    if (ringable(p.spec)) {
      same(`${p.id} ring 90 = quarter turn`, turned(p.spec, {ring: 90}), turned(p.spec, {rot: 1}));
      same(`${p.id} ring 360 = unchanged`, turned(p.spec, {ring: 360}), f);
    }
  }
  const nonRing = DATA.presets.filter(p => !ringable(p.spec)).map(p => p.id);
  for (const id of nonRing) {
    const spec = DATA.presets.find(p => p.id === id).spec;
    same(`${id} ignores ring turns`, turned(spec, {ring: 45}), makeFn(spec, pair), 0);
  }
  return {fails, ringable: DATA.presets.filter(p => ringable(p.spec)).map(p => p.id)};
}"""


def main():
    check = json.loads(CHECK.read_text())
    errors = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        target = sys.argv[1] if len(sys.argv) > 1 else PAGE.as_uri()
        page.goto(target if "://" in target else Path(target).resolve().as_uri())
        page.wait_for_timeout(500)
        worst = page.evaluate(COMPARE, check)
        orient = page.evaluate(ORIENT)
        browser.close()
    bad = {k: v for k, v in worst.items() if v > 1}
    print(f"{len(worst)} preset/pair combinations, max channel difference {max(worst.values())}")
    for k, v in bad.items():
        print(f"  {k}: off by {v}", file=sys.stderr)
    print(f"turning: ring rotation on {', '.join(orient['ringable'])}; {len(orient['fails'])} problem(s)")
    for f in orient["fails"]:
        print(f"  {f}", file=sys.stderr)
    for e in errors:
        print(f"  page error: {e}", file=sys.stderr)
    sys.exit(1 if bad or errors or orient["fails"] else 0)


if __name__ == "__main__":
    main()
