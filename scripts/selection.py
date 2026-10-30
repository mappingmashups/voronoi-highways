"""Which routes to show, and the colour each route number gets."""
import colorsys

# Each selection: which road level, which route numbers, and a title.
# Interstates and US highways are never mixed.
SELECTIONS = {
    "x5_odd": dict(level="Interstate", title="Nearest Interstate: odd, divisible by 5",
                   keep=lambda n: n < 100 and n % 2 == 1 and n % 5 == 0),
    "odd": dict(level="Interstate", title="Nearest north–south Interstate (odd numbers)",
                keep=lambda n: n < 100 and n % 2 == 1),
    "us_odd": dict(level="Federal", title="Nearest north–south US highway (odd numbers, to US 101)",
                   keep=lambda n: n <= 101 and n % 2 == 1),
    "x10": dict(level="Interstate", title="Nearest Interstate: divisible by 10",
                keep=lambda n: n < 100 and n % 10 == 0),
    "even": dict(level="Interstate", title="Nearest east–west Interstate (even numbers)",
                 keep=lambda n: n < 100 and n % 2 == 0),
    "us_even": dict(level="Federal", title="Nearest east–west US highway (even numbers)",
                    keep=lambda n: n < 100 and n % 2 == 0),
}
PREFIX = {"Interstate": "I-", "Federal": "US "}

# the plain highway map (render_svg.py) uses this one
keep_interstate = SELECTIONS["x5_odd"]["keep"]


def route_numbers(routes):
    """'55,70' -> [55, 70]"""
    return [int(n) for n in routes.split(",")] if isinstance(routes, str) and routes else []


# Rainbow: route number on a fixed 0-100 scale -> hue from red (0) to violet (100).
# A lookup by number, not by rank, so uneven subsets keep consistent colours.
SCALE = (0, 100)
HUE_RANGE = (0, 285)  # degrees: red ... violet


def hue_for(n):
    lo, hi = SCALE
    t = min(max((n - lo) / (hi - lo), 0), 1)
    return HUE_RANGE[0] + t * (HUE_RANGE[1] - HUE_RANGE[0])


def hsl_hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def fill_color(n):
    """Light tint for areas."""
    return hsl_hex(hue_for(n), 0.80, 0.72)


def line_color(n):
    """Darker shade for the route line itself."""
    return hsl_hex(hue_for(n), 0.85, 0.36)
