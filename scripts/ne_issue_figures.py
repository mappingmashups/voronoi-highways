"""Annotated zoom-in figures of Natural Earth roads data problems (drawn from the raw data)."""
import html
from pathlib import Path

import geopandas as gpd
from playwright.sync_api import sync_playwright
from shapely.geometry import Point, box

from svgmap import launch_browser

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "natural-earth-issues"
CRS = "EPSG:5070"
SIZE = 760  # map panel, px

BAD = "#d6246e"  # the problem feature
GOOD = "#1f6fd1"  # related, correctly-labelled features
GAP = "#f08c00"  # where a missing road should be

# Each highlight: (name or None, (lat, lon) of one endpoint, colour, label)
# Each gap: ((lat, lon), (lat, lon), label) -- drawn dashed between two dangling ends
ISSUES = [
    dict(slug="01_portland_i84_labelled_5", title="I-84 labelled as \"5\" east of Portland, OR",
         center=(45.55, -122.45), radius_km=35,
         highlight=[("5", [(45.517, -122.677), (45.531, -122.557)], BAD, 'name="5" (should be 84)'),
                    ("5", (45.548, -122.222), BAD, 'name="5" (should be 84)'),
                    ("5", [(45.617, -122.666), (45.517, -122.677)], GOOD, "I-5"), ("84", (45.548, -122.222), GOOD, "I-84")]),
    dict(slug="02_seattle_i90_labelled_5", title="I-90 (Mercer Island bridge) labelled as \"5\", Seattle, WA",
         center=(47.58, -122.25), radius_km=18,
         highlight=[("5", (47.580, -122.176), BAD, 'name="5" (should be 90)'),
                    ("5", [(47.592, -122.322), (47.831, -122.267)], GOOD, "I-5"), ("90", (47.509, -121.865), GOOD, "I-90")]),
    dict(slug="03_chicago_i94_i57_labelled_55", title="I-94 (Dan Ryan / Bishop Ford) and I-57 labelled as \"55\", Chicago, IL",
         center=(41.70, -87.72), radius_km=30,
         highlight=[("55", (41.647, -87.524), BAD, 'name="55" (should be 94 / 90)'),
                    ("55", (41.627, -87.696), BAD, 'name="55" (should be 57)'),
                    ("55", (41.755, -87.856), GOOD, "I-55 (Stevenson)")]),
    dict(slug="04_chicago_i55_missing", title="I-55 missing between I-294 and I-80, SW Chicago suburbs, IL",
         center=(41.63, -88.03), radius_km=30,
         highlight=[("55", (41.755, -87.856), GOOD, "I-55 ends here"), ("55", (40.536, -89.027), GOOD, "I-55 resumes")],
         gap=[((41.755, -87.856), (41.488, -88.196), "missing I-55 (~40 km)")]),
    dict(slug="05_atlanta_i20_labelled_85_and_i85_missing", title="I-20 labelled \"85\" and I-85 missing south of downtown Atlanta, GA",
         center=(33.70, -84.43), radius_km=16,
         highlight=[("85", (33.763, -84.491), BAD, 'name="85" (should be 20)'),
                    ("20", (33.605, -85.829), GOOD, "I-20"), ("85", (33.062, -84.944), GOOD, "I-85"),
                    ("75", (32.850, -83.678), GOOD, "I-75 (shares I-85 here)")],
         gap=[((33.739, -84.388), (33.619, -84.485), "missing I-85 (I-75/85 to airport)")]),
    dict(slug="06_wichita_kansas_turnpike_labelled_235", title="Kansas Turnpike (I-35) labelled as \"235\", Wichita, KS",
         center=(37.72, -97.10), radius_km=35,
         highlight=[("235", (37.903, -96.846), BAD, 'name="235" (should be 35)'),
                    ("35", (37.091, -97.336), GOOD, "I-35"), ("235", (37.678, -97.183), GOOD, "I-235"),
                    ("135", (38.376, -97.621), GOOD, "I-135")]),
    dict(slug="07_tulsa_i44_labelled_75_and_244", title="I-44 through Tulsa, OK labelled as \"75\" and \"244\"",
         center=(36.30, -95.65), radius_km=45,
         highlight=[("75", [(36.146, -95.987), (36.162, -95.975)], BAD, 'name="75" (no I-75 in OK)'),
                    ("75", [(36.113, -96.008), (36.146, -95.987)], BAD, ""),
                    ("244", (36.561, -95.219), BAD, 'name="244" (Will Rogers Tpk = I-44)'),
                    ("44", (35.599, -97.426), GOOD, "I-44"), ("44", (36.997, -94.618), GOOD, "I-44")]),
    dict(slug="08_nashville_i65_gap", title="I-65 doesn't connect north of downtown Nashville, TN",
         center=(36.21, -86.76), radius_km=12,
         highlight=[("65", (36.269, -86.731), GOOD, "I-65 starts here"), ("24", (36.248, -86.788), GOOD, "I-24 (shared with I-65)")],
         gap=[((36.248, -86.788), (36.269, -86.731), "missing I-65 link (~6 km)")]),
    dict(slug="09_cincinnati_i71_i75_no_name", title="I-71/I-75 segment with no route number, Cincinnati, OH / KY",
         center=(38.97, -84.58), radius_km=18,
         highlight=[(None, (39.062, -84.537), BAD, "level=Interstate, name empty (I-71/75)"),
                    ("75", (38.878, -84.621), GOOD, "I-75"), ("71", (38.878, -84.621), GOOD, "I-71")]),
    dict(slug="10_greensboro_i40_i85_no_level", title="I-40/I-85 link with no level or name, Greensboro, NC",
         center=(36.05, -79.80), radius_km=12,
         highlight=[(None, (36.045, -79.774), BAD, "level & name empty (I-40/85)"),
                    ("85", (35.793, -80.300), GOOD, "I-85"), ("40", (36.059, -79.166), GOOD, "I-40 (also I-85 east of here)"),
                    ("40", (36.097, -80.234), GOOD, "I-40")]),
    dict(slug="11_nebraska_i80_labelled_70", title="I-80 near York, NE labelled as \"70\"",
         center=(40.82, -97.6), radius_km=60,
         highlight=[("70", [(40.821, -97.595), (40.823, -97.044)], BAD, 'name="70" (should be 80)'),
                    ("80", [(40.807, -98.385), (40.821, -97.595)], GOOD, "I-80"),
                    ("80", [(40.823, -97.044), (41.239, -95.905)], GOOD, "I-80")]),
    dict(slug="12_fort_smith_i40_labelled_44", title="I-40 at Fort Smith, AR labelled as \"44\"",
         center=(35.48, -94.33), radius_km=20,
         highlight=[("44", [(35.472, -94.325), (35.467, -94.440)], BAD, 'name="44" (should be 40)'),
                    ("44", [(35.472, -94.325), (35.524, -94.222)], BAD, 'name="44" (should be 40)'),
                    ("40", (35.486, -95.176), GOOD, "I-40"), ("40", (35.107, -92.423), GOOD, "I-40"),
                    ("540", (36.422, -94.224), GOOD, "I-540")]),
    dict(slug="13_wenatchee_us2_namealt_95", title="US 2/97 near Wenatchee, WA has namealt \"95\"",
         center=(47.6, -120.4), radius_km=30,
         highlight=[("2", [(47.561, -120.600), (47.623, -120.235)], BAD, 'US 2, namealt="95" (should be 97)'),
                    ("97", [(47.561, -120.600), (46.970, -120.532)], GOOD, "US 97"),
                    ("97", [(47.625, -120.233), (47.833, -119.980)], GOOD, "US 97"),
                    ("2", (47.981, -122.194), GOOD, "US 2")]),
    dict(slug="14_kentucky_state_route_15_as_us", title="KY 15 (state route) classed as US highway, eastern Kentucky",
         center=(37.3, -83.15), radius_km=35,
         highlight=[("15", [(37.219, -83.056), (37.113, -82.802)], BAD, 'level=Federal name="15"'),
                    ("15", [(37.219, -83.056), (37.227, -83.163)], BAD, ""),
                    ("15", (37.732, -83.551), GOOD, "KY 15 (level=State)")]),
]


def load():
    r = gpd.read_file(RAW / "ne_10m_roads.geojson")
    r = r[r.sov_a3 == "USA"].to_crs(CRS)
    land = gpd.read_file(RAW / "ne_10m_admin_1_states_provinces_lakes.geojson")
    land = land[land.iso_a2 == "US"].to_crs(CRS)
    return r, land


def proj(lat, lon):
    return gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(CRS).iloc[0]


def find(roads, name, latlon):
    """Segment with this name that has an endpoint at latlon (or at every point if a list)."""
    pts = [proj(*ll) for ll in (latlon if isinstance(latlon, list) else [latlon])]
    same = roads.name.isna() if name is None else roads.name == name
    cand = roads[same]

    def near_ends(g):
        g = g.geoms[0] if g.geom_type.startswith("Multi") else g
        ends = [Point(g.coords[0]), Point(g.coords[-1])]
        return all(min(e.distance(p) for e in ends) < 1500 for p in pts)

    hit = cand[cand.geometry.map(near_ends)]
    if hit.empty:
        raise ValueError(f"{name} @ {latlon}: no match")
    return hit


def figure(issue, roads, land):
    c = proj(*issue["center"])
    R = issue["radius_km"] * 1000
    bb = box(c.x - R, c.y - R, c.x + R, c.y + R)
    k = SIZE / (2 * R)
    X = lambda x: (x - c.x + R) * k
    Y = lambda y: (c.y + R - y) * k

    def d(geom):
        out = []
        parts = getattr(geom, "geoms", [geom])
        for g in parts:
            rings = [g.exterior, *g.interiors] if g.geom_type == "Polygon" else [g]
            for ring in rings:
                out.append("M" + "L".join(f"{X(x):.1f},{Y(y):.1f}" for x, y, *_ in ring.coords))
        return "".join(out)

    svg = [f'<rect width="{SIZE}" height="{SIZE}" fill="#dfe9f2"/>']
    for g in land.geometry[land.intersects(bb)]:
        svg.append(f'<path d="{d(g.intersection(bb))}" fill="#f4f1ea" stroke="#b5b0a5" stroke-width="0.8"/>')
    near = roads[roads.intersects(bb)]
    for _, s in near[near.level == "Federal"].iterrows():
        svg.append(f'<path d="{d(s.geometry)}" fill="none" stroke="#d9cbb1" stroke-width="1"/>')
    labelled = set()
    for _, s in near[near.level == "State"].iterrows():
        svg.append(f'<path d="{d(s.geometry)}" fill="none" stroke="#e2e2e2" stroke-width="0.8"/>')
    for _, s in near[near.level.isna() | (near.level == "Interstate")].iterrows():
        svg.append(f'<path d="{d(s.geometry)}" fill="none" stroke="#8d8d8d" stroke-width="1.6"/>')
        name = s["name"] if isinstance(s["name"], str) else "∅"
        m = s.geometry.intersection(bb).representative_point() if not s.geometry.intersection(bb).is_empty else None
        if m is not None and (name, round(m.x, -4), round(m.y, -4)) not in labelled:
            labelled.add((name, round(m.x, -4), round(m.y, -4)))
            svg.append(f'<text x="{X(m.x):.0f}" y="{Y(m.y):.0f}" class="ctx">{html.escape(name)}</text>')

    labels = []
    for name, latlon, colour, label in issue.get("highlight", []):
        hits = find(roads, name, latlon)
        if colour == BAD and len(hits) != 1:
            raise ValueError(f"problem feature {name} @ {latlon}: {len(hits)} matches")
        w = 5 if colour == BAD else 3.5
        for geom in hits.geometry:
            svg.append(f'<path d="{d(geom)}" fill="none" stroke="{colour}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>')
        if label:
            g = hits.geometry.union_all().intersection(bb)
            if g.is_empty:
                continue
            g = max(getattr(g, "geoms", [g]), key=lambda part: part.length)
            m = g.interpolate(0.5, normalized=True) if g.geom_type == "LineString" else g.representative_point()
            labels.append((X(m.x), Y(m.y), colour, label))
    for a, b, label in issue.get("gap", []):
        pa, pb = proj(*a), proj(*b)
        svg.append(f'<path d="M{X(pa.x):.1f},{Y(pa.y):.1f}L{X(pb.x):.1f},{Y(pb.y):.1f}" stroke="{GAP}" stroke-width="4" stroke-dasharray="8 6" fill="none"/>')
        for p in (pa, pb):
            svg.append(f'<circle cx="{X(p.x):.1f}" cy="{Y(p.y):.1f}" r="7" fill="none" stroke="{GAP}" stroke-width="3"/>')
        labels.append(((X(pa.x) + X(pb.x)) / 2, (Y(pa.y) + Y(pb.y)) / 2, GAP, label))
    for x, y, colour, label in labels:
        x = min(max(x, 10), SIZE - 10)
        anchor = "end" if x > SIZE * 0.6 else "start"
        dx = -10 if anchor == "end" else 10
        svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4" fill="{colour}" stroke="#fff" stroke-width="1.5"/>')
        svg.append(f'<text x="{x + dx:.0f}" y="{y + 5:.0f}" text-anchor="{anchor}" class="lab" fill="{colour}">{html.escape(label)}</text>')

    lat, lon = issue["center"]
    legend = (f'<span style="color:{BAD}">■ problem feature</span> '
              f'<span style="color:{GOOD}">■ related routes</span> '
              f'<span style="color:{GAP}">┅ missing road</span> '
              f'<span style="color:#8d8d8d">■ other Interstates (gray labels = name field, ∅ = empty)</span> '
              f'<span style="color:#c9b48f">■ US highways</span> '
              f'<span style="color:#bbb">■ state routes</span>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font:14px/1.35 -apple-system,Helvetica,Arial,sans-serif;width:{SIZE + 40}px;background:#fff}}
.wrap{{padding:16px 20px}} h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#666;font-size:12px;margin-bottom:10px}}
.legend{{font-size:12px;margin-top:8px;line-height:1.6}} .legend span{{margin-right:10px;white-space:nowrap}}
text.ctx{{font-size:11px;fill:#666;paint-order:stroke;stroke:#fff;stroke-width:3px}}
text.lab{{font-size:13px;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}}
</style></head><body><div class="wrap"><h1>{html.escape(issue['title'])}</h1>
<div class="sub">ne_10m_roads (v5.2.0-pre) · centred {lat:.2f}, {lon:.2f} · {2 * issue['radius_km']} km across</div>
<svg width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}" style="border:1px solid #ccc">{''.join(svg)}</svg>
<div class="legend">{legend}</div></div></body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    roads, land = load()
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(viewport={"width": SIZE + 40, "height": 400}, device_scale_factor=2)
        for issue in ISSUES:
            page.set_content(figure(issue, roads, land))
            page.screenshot(path=OUT / f"{issue['slug']}.png", full_page=True)
            print("wrote", issue["slug"])
        browser.close()


if __name__ == "__main__":
    main()
