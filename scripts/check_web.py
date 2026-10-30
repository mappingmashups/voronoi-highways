"""Check the palette page's JavaScript colours against the Python implementation.

Run after `python scripts/export_web.py --check`: opens the built page in Chromium and
compares every cell's colour for every preset on both route pairs (tolerance: 1/255).
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from svgmap import launch_browser

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "output" / "web" / "interstate_palettes.html"
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


def main():
    check = json.loads(CHECK.read_text())
    errors = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(PAGE.as_uri())
        page.wait_for_timeout(500)
        worst = page.evaluate(COMPARE, check)
        browser.close()
    bad = {k: v for k, v in worst.items() if v > 1}
    print(f"{len(worst)} preset/pair combinations, max channel difference {max(worst.values())}")
    for k, v in bad.items():
        print(f"  {k}: off by {v}", file=sys.stderr)
    for e in errors:
        print(f"  page error: {e}", file=sys.stderr)
    sys.exit(1 if bad or errors else 0)


if __name__ == "__main__":
    main()
