"""Easter egg: treat the 54 zones of the fives map (I-5 … I-95 × I-10 … I-90) as states,
give them populations and electoral votes, and replay the 2024 presidential election.

Usage: python scripts/electoral.py
Reads results/bivariate_x5_odd__x10.geojson and writes results/electoral_x5_odd__x10.csv.

- Population: Census 2020 block-group centres of population, each assigned to the zone it
  falls in (or the nearest zone, for points just off the clipped coastline).
- Votes: 2024 county results, shared out to each county's block groups by population. Where
  a state's vote units don't match Census counties (Connecticut's planning regions, DC's
  wards), the state's whole vote is shared out instead.
- Electoral votes: like the real thing, 2 per zone plus House seats by Huntington–Hill
  (at least 1 each), keeping the total at 538: 54 × 2 + 430. Alaska and Hawaii aren't on
  the map, so their votes go to the lower 48.
- Winner takes all in every zone.
- Each zone is named after its largest city: the Natural Earth populated place with the
  biggest POP_MAX (roughly metro population) inside it, or the nearest one if none is.
"""
import heapq
import math
import sys
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

from download_data import BASE as NE_BASE, sha256
from svgmap import CRS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
ZONES = RESULTS / "bivariate_x5_odd__x10.geojson"
OUT = RESULTS / "electoral_x5_odd__x10.csv"

VOTES_COMMIT = "8cccc82f9235dced94a76d143c59a43f4a6bf979"
SOURCES = {
    "CenPop2020_Mean_BG.txt": (
        "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt",
        "e4a7ebbf07a8a8d846cea9d2daeb600dea50b1ec2d7703909e40d45c013cd63a"),
    "2024_US_County_Level_Presidential_Results.csv": (
        f"https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/{VOTES_COMMIT}"
        "/2024_US_County_Level_Presidential_Results.csv",
        "538a8fbe2d7a20524b049dd1b3b9ec7e215c4433d99f91fbd7b0dea05270136a"),
    "ne_10m_populated_places.geojson": (
        f"{NE_BASE}/ne_10m_populated_places.geojson",
        "9b8e3de09048ef00dfc70357dbb9fa324493f214b5e0ae4daf1aa79a8d10116b"),
}
NOT_LOWER48 = {"02", "15", "72"}  # Alaska, Hawaii, Puerto Rico
TOTAL_EV = 538


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in SOURCES.items():
        path = RAW / name
        if not (path.exists() and sha256(path) == expected):
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, path)
            if sha256(path) != expected:
                sys.exit(f"checksum mismatch for {name}")
    return (RAW / "CenPop2020_Mean_BG.txt", RAW / "2024_US_County_Level_Presidential_Results.csv",
            RAW / "ne_10m_populated_places.geojson")


def block_groups(path):
    bg = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    bg = bg[~bg.STATEFP.isin(NOT_LOWER48)].copy()
    bg["county"] = bg.STATEFP + bg.COUNTYFP
    bg["population"] = bg.POPULATION.astype(int)
    pts = gpd.points_from_xy(bg.LONGITUDE.astype(float), bg.LATITUDE.astype(float), crs=4326)
    return gpd.GeoDataFrame(bg[["STATEFP", "county", "population"]], geometry=pts).to_crs(CRS)


def add_votes(bg, path):
    """Share each county's votes out to its block groups by population."""
    v = pd.read_csv(path, dtype={"county_fips": str})
    v["STATEFP"] = v.county_fips.str[:2]
    v = v[~v.STATEFP.isin(NOT_LOWER48)]
    cols = ["votes_gop", "votes_dem", "total_votes"]
    # states whose vote units aren't Census counties are shared out state-wide
    statewide = sorted(s for s, g in v.groupby("STATEFP")
                       if set(g.county_fips) != set(bg.county[bg.STATEFP == s]))
    print(f"shared out state-wide: {', '.join(sorted(set(v.state_name[v.STATEFP.isin(statewide)])))}")
    bg["unit"] = bg.county.where(~bg.STATEFP.isin(statewide), bg.STATEFP)
    v["unit"] = v.county_fips.where(~v.STATEFP.isin(statewide), v.STATEFP)
    totals = v.groupby("unit")[cols].sum()
    share = bg.population / bg.groupby("unit").population.transform("sum")
    for c in cols:
        bg[c] = share * bg.unit.map(totals[c])
    missing = totals.index.difference(bg.unit)
    if len(missing):
        print(f"  no block groups for {len(missing)} vote units: {', '.join(missing)}", file=sys.stderr)
    return bg


def largest_cities(path, zones):
    """('City, State', lon, lat) of the biggest populated place in each zone, keyed by (ns, ew).
    Zones with no place inside get ('near …', None, None)."""
    places = gpd.read_file(path)
    places = places[places.ADM0_A3 == "USA"].to_crs(CRS)
    name = lambda r: " ".join(r.NAME.split()) if "," in r.NAME else f"{r.NAME}, {r.ADM1NAME}"  # "Washington, D.C."
    # nearest zone within 2 km: some points sit just off the clipped shoreline (Detroit, Duluth)
    hit = gpd.sjoin_nearest(places, zones, max_distance=2000).sort_values("POP_MAX", ascending=False)
    out = {(int(r.ns), int(r.ew)): (name(r), r.LONGITUDE, r.LATITUDE)
           for _, r in hit.drop_duplicates(["ns", "ew"]).iterrows()}
    # a few small zones have no place inside: use the nearest one
    for _, z in zones.iterrows():
        if (int(z.ns), int(z.ew)) not in out:
            out[(int(z.ns), int(z.ew))] = ("near " + name(places.loc[places.distance(z.geometry).idxmin()]), None, None)
    return out


def apportion(pops, seats):
    """Huntington–Hill: everyone starts with 1 seat; each next seat goes to the highest
    population / sqrt(n (n + 1))."""
    n = [1] * len(pops)
    heap = [(-p / math.sqrt(2), i) for i, p in enumerate(pops)]
    heapq.heapify(heap)
    for _ in range(seats - len(pops)):
        _, i = heapq.heappop(heap)
        n[i] += 1
        heapq.heappush(heap, (-pops[i] / math.sqrt(n[i] * (n[i] + 1)), i))
    return n


def main():
    bg_path, votes_path, places_path = fetch()
    zones = gpd.read_file(ZONES).to_crs(CRS).dissolve(by=["ns", "ew"], as_index=False)[["ns", "ew", "geometry"]]
    bg = add_votes(block_groups(bg_path), votes_path)

    hit = gpd.sjoin(bg, zones, how="left", predicate="within").drop(columns="index_right")
    off = hit.ns.isna()
    near = gpd.sjoin_nearest(bg[off.values], zones, how="left").drop(columns="index_right")
    near = near[~near.index.duplicated()]
    hit.loc[off, ["ns", "ew"]] = near[["ns", "ew"]].values
    print(f"{len(bg):,} block groups, {off.sum()} off the map snapped to the nearest zone "
          f"({hit.population[off].sum():,} people)")

    z = hit.groupby(["ns", "ew"])[["population", "votes_gop", "votes_dem", "total_votes"]].sum().reset_index()
    z[["ns", "ew"]] = z[["ns", "ew"]].astype(int)
    z = z.sort_values(["ns", "ew"]).reset_index(drop=True)
    z["house"] = apportion(z.population.tolist(), TOTAL_EV - 2 * len(z))
    z["ev"] = z.house + 2
    z["winner"] = (z.votes_dem > z.votes_gop).map({True: "D", False: "R"})
    cities = largest_cities(places_path, zones)
    z[["city", "city_lon", "city_lat"]] = [cities[(r.ns, r.ew)] for r in z.itertuples()]
    z = z[["ns", "ew", "city", "city_lon", "city_lat"] + [c for c in z.columns if c not in ("ns", "ew", "city", "city_lon", "city_lat")]]
    for c in ["votes_gop", "votes_dem", "total_votes"]:
        z[c] = z[c].round().astype(int)
    RESULTS.mkdir(exist_ok=True)
    z.to_csv(OUT, index=False)

    ev = z.groupby("winner").ev.sum()
    print(f"{len(z)} zones, {z.population.sum():,} people, {z.ev.sum()} electoral votes "
          f"({z.ev.min()}–{z.ev.max()} per zone)")
    print(f"result: R {ev.get('R', 0)} – D {ev.get('D', 0)}  "
          f"(popular vote R {z.votes_gop.sum():,} – D {z.votes_dem.sum():,})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
