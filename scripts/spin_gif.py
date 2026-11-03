"""Animated GIF of a palette turning one full revolution around its colour ring.

Drives the built palette page (docs/index.html) in headless Chromium, so the frames use the
page's own colour code, then assembles them into a looping GIF. With ffmpeg installed, the GIF
uses one colour table built from every frame and stores only what changes between frames,
about half the size of the fallback (a separate colour table per frame, via Pillow).

Usage: python scripts/spin_gif.py [palette] [--frames N] [--ms MS] [--width PX] [--out PATH]
       default: compass_centered_gray, 180 frames (2° apart), 40 ms each, 480 px wide,
       written to docs/images/<palette>_spin.gif
Only palettes with ring=True in bivariate.SCHEMES can turn around their ring.
"""
import argparse
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from svgmap import launch_browser

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "index.html"

SET_RING = """([pid, deg]) => {
  // colour the major-routes map with the palette turned `deg` degrees around its colour ring
  const {makeFn, orientSpec, ringable, norm, DATA} = window.__ipl, pair = DATA.pairs[0];
  const spec = DATA.presets.find(p => p.id === pid).spec;
  if (!ringable(spec)) throw new Error(pid + " has no colour ring to turn");
  const fn = makeFn(orientSpec(spec, {rot: 0, mirror: false, ring: deg}), pair);
  document.querySelectorAll('#views .map .cell').forEach(e => {
    const c = pair.cells[+e.dataset.i], h = fn(norm(c.ns), norm(c.ew));
    e.setAttribute('fill', h); e.setAttribute('stroke', h);
  });
}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("palette", nargs="?", default="compass_centered_gray")
    ap.add_argument("--frames", type=int, default=180)
    ap.add_argument("--ms", type=int, default=40, help="milliseconds per frame (GIF timing is in 10 ms steps)")
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    out = args.out or ROOT / "docs" / "images" / f"{args.palette}_spin.gif"

    frames = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(viewport={"width": 1060, "height": 900}, device_scale_factor=2)
        page.goto(PAGE.as_uri())
        page.wait_for_timeout(600)
        page.click(f'.preset[data-id="{args.palette}"]')
        page.wait_for_timeout(2000)  # let the palette's fade-in and route-line colour settle
        page.uncheck("#show-center")  # no centre marker
        mapsvg = page.locator("#views .map").first
        for k in range(args.frames):
            page.evaluate(SET_RING, [args.palette, k * 360 / args.frames])
            img = Image.open(BytesIO(mapsvg.screenshot(animations="disabled"))).convert("RGB")
            frames.append(img.resize((args.width, round(img.height * args.width / img.width)), Image.LANCZOS))
        browser.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            for k, f in enumerate(frames):
                f.save(Path(tmp) / f"{k:04d}.png")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{1000 / args.ms:g}", "-i", str(Path(tmp) / "%04d.png"),
                 "-vf", "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
                 "-loop", "0", str(out)],
                check=True)
    else:
        # a colour table per frame keeps the gradients accurate without frame-to-frame shimmer
        q = [f.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], duration=args.ms, loop=0)
    w, h = frames[0].size
    print(f"{out} ({out.stat().st_size / 1024 / 1024:.1f} MB, {len(frames)} frames, {w}×{h})")


if __name__ == "__main__":
    main()
