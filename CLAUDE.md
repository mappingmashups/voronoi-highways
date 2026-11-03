# Notes for Claude

## Language

Use **American English** everywhere: code, comments, identifiers, UI text, docs, commit messages and PR descriptions. This is a map of American highways. So: color, center/centered, gray, labeled, neighbor, meters, counterclockwise, math, northeast; -ize rather than -ise (normalize, visualize). Keep standard names that happen to use British spelling as they are (e.g. HTML's `aria-labelledby`).

## Project

The pipeline steps, file layout and route selections are in `README.md`. Run scripts from the repo root with the project's Python environment (`requirements.txt`).

- `data/` and `output/` are generated and git-ignored. `scripts/download_data.py` fetches the pinned Natural Earth data; the README gives the order to rebuild the rest.
- PNG previews, the palette-page checks and `spin_gif.py` use headless Chromium through Playwright. Where Playwright's own browser isn't installed, set `CHROME_PATH` to a Chromium binary.
- `bivariate.py`'s `SCHEMES` is the single source of palettes for both the static maps and the palette page.

## Palette page and GitHub Pages

- Edit `web/palette_template.html`, never `docs/index.html`. `docs/index.html` is the GitHub Pages copy, built by `scripts/export_web.py` and committed.
- After changing the template, `SCHEMES`, or the data, rebuild it and run the checks:

  ```sh
  python scripts/export_web.py --check
  python scripts/check_web.py docs/index.html   # page colors vs Python, and palette turning
  python scripts/check_pages.py                 # docs/index.html matches its sources (also runs in CI)
  ```

- Images with text drawn into them, like the issue figures and README previews, need regenerating when that text changes.

## Workflow

Work on a branch and open a pull request against `main`; don't commit to `main` directly.
