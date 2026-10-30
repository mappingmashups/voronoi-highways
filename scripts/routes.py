"""Assign route numbers to highway segments, including concurrent (shared) stretches.

Natural Earth gives each segment a single `name`, so where two Interstates share
pavement (e.g. I-55/I-70 through St. Louis) only one of them is recorded and the
other appears to have a gap. We bridge such gaps by finding the shortest path
between a route's dangling ends through the rest of the same-level network, and
tag every segment on that path with the route number too.
"""
import re

import networkx as nx
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import substring

SNAP_M = 100  # endpoints closer than this are treated as the same node
MAX_GAP_M = 80_000  # default: only try to bridge gaps up to this straight-line distance
MAX_DETOUR = 1.2  # bridge path may be at most this much longer than the gap (+10 km)
JOIN_M = 8_000  # loose network ends this close to another node get a straight connector
MIN_PIECE_M = 25_000  # isolated fragments shorter than this are dropped (unless it's the route's longest piece)


def route_number(name):
    """'35' -> '35', '35E' -> '35' (I-35 splits count as I-35); business loops etc. -> None."""
    m = re.fullmatch(r"(\d+)[EW]?", name) if isinstance(name, str) else None
    return m.group(1) if m else None


def _node_ids(points):
    """Cluster endpoints within SNAP_M of each other; return a node id per point."""
    tree = shapely.STRtree(points)
    left, right = tree.query(points, predicate="dwithin", distance=SNAP_M)
    g = nx.Graph()
    g.add_nodes_from(range(len(points)))
    g.add_edges_from(zip(left, right))
    ids = np.empty(len(points), dtype=int)
    for cid, comp in enumerate(nx.connected_components(g)):
        ids[list(comp)] = cid
    return ids


def split_at_junctions(segs):
    """Split lines where another line's endpoint touches their interior (T-junctions),
    so the network graph connects there."""
    geoms = segs.geometry.values
    ends = np.concatenate([shapely.get_point(geoms, 0), shapely.get_point(geoms, -1)])
    tree = shapely.STRtree(geoms)
    pt_idx, line_idx = tree.query(ends, predicate="dwithin", distance=SNAP_M)
    cuts = {}
    for p, l in zip(pt_idx, line_idx):
        line = geoms[l]
        d = line.project(ends[p])
        if SNAP_M < d < line.length - SNAP_M:
            cuts.setdefault(l, set()).add(round(d))
    rows = []
    for i, row in enumerate(segs.itertuples(index=False)):
        line = geoms[i]
        stops = [0, *sorted(cuts.get(i, ())), line.length]
        for a, b in zip(stops, stops[1:]):
            rows.append({**row._asdict(), "geometry": substring(line, a, b)})
    return segs.__class__(pd.DataFrame(rows), geometry="geometry", crs=segs.crs)


def assign_routes(segs, max_gap=MAX_GAP_M):
    """segs: projected (metres) GeoDataFrame of LineStrings with `name` (and optional
    `namealt`). Returns a list of sets of route numbers, one per row, and a bridge log."""
    segs = segs.reset_index(drop=True)
    routes = [set() for _ in range(len(segs))]
    for i, row in segs.iterrows():
        for col in ("name", "namealt"):
            if (n := route_number(row.get(col))):
                routes[i].add(n)

    starts = shapely.get_point(segs.geometry.values, 0)
    ends = shapely.get_point(segs.geometry.values, -1)
    ids = _node_ids(np.concatenate([starts, ends]))
    u, v = ids[: len(segs)], ids[len(segs):]
    node_xy = {}
    for nid, p in zip(ids, np.concatenate([starts, ends])):
        node_xy.setdefault(nid, (p.x, p.y))

    net = nx.MultiGraph()
    for i, (a, b) in enumerate(zip(u, v)):
        net.add_edge(a, b, key=i, weight=segs.geometry.iloc[i].length)

    # Connector edges: Natural Earth often stops a route a few km short of the road it
    # joins. Link each loose end to the nearest node of another part of the network.
    connectors = {}  # edge key -> LineString
    nodes = list(node_xy)
    node_pts = shapely.points([node_xy[n] for n in nodes])
    tree = shapely.STRtree(node_pts)
    for a in [n for n in net.nodes if net.degree(n) == 1]:
        pa = Point(node_xy[a])
        best = None
        for j in tree.query(pa, predicate="dwithin", distance=JOIN_M):
            b = nodes[j]
            if b == a or b in net[a]:
                continue
            d = pa.distance(node_pts[j])
            if best is None or d < best[0]:
                best = (d, b)
        if best:
            k = len(segs) + len(connectors)
            connectors[k] = LineString([node_xy[a], node_xy[best[1]]])
            net.add_edge(a, best[1], key=k, weight=best[0] * 1.5)  # discourage vs real roads
    routes += [set() for _ in connectors]
    u = np.concatenate([u, [None] * len(connectors)])
    v = np.concatenate([v, [None] * len(connectors)])
    for k in connectors:
        (u[k], v[k]), = [(x, y) for x, y, kk in net.edges(keys=True) if kk == k]
    seg_len = lambda k: connectors[k].length if k in connectors else segs.geometry.iloc[k].length

    log = []
    for num in sorted({n for r in routes for n in r}, key=int):
        sub = nx.MultiGraph()
        sub.add_edges_from((u[i], v[i], i) for i in range(len(segs)) if num in routes[i])
        dangling = [n for n in sub.nodes if sub.degree(n) == 1]
        pairs = []
        for a_i, a in enumerate(dangling):
            for b in dangling[a_i + 1:]:
                d = Point(node_xy[a]).distance(Point(node_xy[b]))
                if d < max_gap:
                    pairs.append((d, a, b))
        for d, a, b in sorted(pairs):
            if nx.has_path(sub, a, b) or sub.degree(a) != 1 or sub.degree(b) != 1:
                continue
            try:
                length, path = nx.single_source_dijkstra(net, a, b, cutoff=d * MAX_DETOUR + 10_000)
            except nx.NetworkXNoPath:
                continue
            added = []
            for x, y in zip(path, path[1:]):
                k = min(net[x][y], key=lambda k: net[x][y][k]["weight"])
                if num not in routes[k]:
                    routes[k].add(num)
                    added.append(k)
                sub.add_edge(x, y, k)
            if added:
                via = sorted({n for k in added for n in routes[k] if n != num}, key=int)
                x, y = node_xy[a]
                log.append((num, d, length, via, (x, y)))

        # drop tiny isolated fragments (e.g. a mislabelled stub far from the real route),
        # but never a short route's only / longest piece
        pieces = [{k for _, _, k in sub.subgraph(c).edges(keys=True)} for c in nx.connected_components(sub)]
        lengths = [sum(seg_len(k) for k in keys) for keys in pieces]
        for keys, total in zip(pieces, lengths):
            if total < MIN_PIECE_M and total < max(lengths):
                for k in keys:
                    routes[k].discard(num)
    return routes, connectors, log
