"""Download the Natural Earth layers this project uses into data/raw/.

Pinned to one commit of nvkelso/natural-earth-vector (v5.2.0-pre GeoJSON) and checked by
SHA-256, because the label fixes in prepare.py match specific features in this exact data.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{COMMIT}/geojson"
FILES = {
    "ne_10m_roads.geojson": "66a0c7b438e92fd124822cc5921cfa11042f48c294ade5e0f03f2c6640fd0248",
    "ne_10m_admin_1_states_provinces_lakes.geojson": "ff5e330cf097a639cc413ab849814d605ba76307235e3a9eba5d1aa0491beba1",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, expected in FILES.items():
        path = RAW / name
        if path.exists() and sha256(path) == expected:
            print(f"have {name}")
            continue
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(f"{BASE}/{name}", path)
        if sha256(path) != expected:
            print(f"  checksum mismatch for {name}", file=sys.stderr)
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
