"""Render the social-media preview card for the palette page (Open Graph / Twitter image).

Usage: python scripts/social_card.py

Writes docs/images/social_card.png (1200x630, the size Facebook, LinkedIn, Slack, Bluesky and X expect
for a large link preview). It takes the map from docs/images/bivariate_compass_centered.png, so rerun this
after regenerating that image, or after changing the title or text below.
"""
import base64

from PIL import Image
from playwright.sync_api import sync_playwright

from svgmap import launch_browser
from export_web import ROOT

SOURCE = ROOT / "docs" / "images" / "bivariate_compass_centered.png"
OUT = ROOT / "docs" / "images" / "social_card.png"
W, H = 1200, 630
MAP_BOTTOM = 1520  # the source image's map ends here; the legend is below

TITLE = "Voronoi Highways"
LEDE = ("Every point in the lower 48, colored by its nearest north–south "
        "and nearest east–west Interstate.")
URL = "mappingmashups.github.io/voronoi-highways"

HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Overpass:wght@400;800&display=swap">
<style>
html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; }}
body {{ background: #ffffff; color: #16201b; font-family: Overpass, Arial, sans-serif;
        display: grid; grid-template-columns: 350px 1fr; align-items: center; }}
.text {{ position: relative; z-index: 1; padding: 0 0 0 48px; display: grid; gap: 18px; }}
svg {{ width: 66px; height: 69px; }}
h1 {{ font-size: 62px; font-weight: 800; line-height: 0.98; margin: 0; letter-spacing: -0.015em; }}
p {{ font-size: 23px; line-height: 1.32; color: #56635c; margin: 0; }}
.url {{ font-size: 16px; white-space: nowrap; color: #1c6b42; font-weight: 800; }}
img {{ width: 100%; height: {H}px; object-fit: contain; padding: 20px 24px 20px 4px; box-sizing: border-box; }}
</style></head>
<body>
<div class="text">
  <svg viewBox="0 0 44 46">
    <path d="M4 4 C14 0 30 0 40 4 C44 18 42 34 22 44 C2 34 0 18 4 4 Z" fill="#1d4f9c" stroke="#fff" stroke-width="2"/>
    <path d="M4.6 4.2 C14 0.6 30 0.6 39.4 4.2 L40.4 13 L3.6 13 Z" fill="#c41e3a"/>
    <text x="22" y="34" text-anchor="middle" font-family="Overpass, Arial, sans-serif" font-weight="800" font-size="17" fill="#fff">×</text>
  </svg>
  <h1>{title}</h1>
  <p>{lede}</p>
  <div class="url">{url}</div>
</div>
<img src="data:image/png;base64,{map}">
</body></html>
"""


def main():
    src = Image.open(SOURCE)
    cropped = src.crop((0, 0, src.width, MAP_BOTTOM))
    tmp = OUT.with_name("_map_crop.png")
    cropped.save(tmp)
    data = base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink()
    html = HTML.format(W=W, H=H, title=TITLE, lede=LEDE, url=URL, map=data)
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content(html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=OUT)
        browser.close()
    print(f"wrote {OUT.relative_to(ROOT)} ({W}x{H})")


if __name__ == "__main__":
    main()
