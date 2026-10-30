"""Check that the committed GitHub Pages copy (docs/index.html) is up to date.

Usage: python scripts/check_pages.py

docs/index.html is built by export_web.py and committed, so it can fall behind its sources.
This checks the parts that don't need the data pipeline to rebuild:

- the page around the data matches web/palette_template.html,
- the palette presets match SCHEMES in bivariate.py,
- the Electoral College numbers match results/electoral_x5_odd__x10.csv.

The map geometry itself is not checked: that needs the full pipeline (see README).
Exits 1, saying what is stale, if anything differs.
"""
import json
import re
import sys

import pandas as pd

from export_web import ELECTORAL, PAGES, WEB, embed, preset_specs, standalone, zone_fields


def main():
    page = PAGES.read_text()
    m = re.search(r"const DATA = (\{.*?\});\n</script>", page, re.S)
    if not m:
        sys.exit(f"{PAGES}: no inlined palette data found")
    data = json.loads(m.group(1))
    stale = []

    template = (WEB / "palette_template.html").read_text()
    if standalone(embed(template, data)) != page:
        stale.append("page code differs from web/palette_template.html")

    if data["presets"] != json.loads(json.dumps(preset_specs())):
        stale.append("palette presets differ from SCHEMES in bivariate.py")

    if ELECTORAL.exists():
        want = [zone_fields(r) for r in pd.read_csv(ELECTORAL, keep_default_na=False).itertuples()]
        built = [{k: z.get(k) for k in want[0]} for z in data["pairs"][0].get("electoral", [])]
        if built != want:
            stale.append(f"Electoral College data differs from {ELECTORAL.relative_to(ELECTORAL.parent.parent)}")

    if stale:
        print(f"{PAGES.relative_to(PAGES.parent.parent)} is out of date:", file=sys.stderr)
        for s in stale:
            print(f"  - {s}", file=sys.stderr)
        print("Rebuild it with `python scripts/export_web.py --check` and commit docs/index.html.", file=sys.stderr)
        sys.exit(1)
    print(f"{PAGES.relative_to(PAGES.parent.parent)} is up to date")


if __name__ == "__main__":
    main()
