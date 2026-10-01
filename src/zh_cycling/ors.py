"""Optional openrouteservice cycling-regular matrix, cached on disk.

Only used with ``zh-cycling graph --router ors``; requires ORS_API_KEY in the
environment. Coordinates are sent as lon/lat (EPSG:4326). Each response is
cached with the request body, profile and retrieval time so reruns never hit
the API again.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import numpy as np
import requests
from pyproj import Transformer

from . import config as C

ORS_URL = os.environ.get("ORS_URL", "https://api.openrouteservice.org")
PROFILE = "cycling-regular"


def duration_matrix(xy_lv95: np.ndarray) -> np.ndarray:
    key = os.environ.get("ORS_API_KEY")
    if not key:
        raise RuntimeError("router=ors needs ORS_API_KEY in the environment")
    tr = Transformer.from_crs(C.CRS_CH, C.CRS_WGS, always_xy=True)
    lon, lat = tr.transform(xy_lv95[:, 0], xy_lv95[:, 1])
    body = {"locations": [[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)], "metrics": ["duration", "distance"]}
    h = hashlib.sha256(json.dumps([PROFILE, body], sort_keys=True).encode()).hexdigest()[:16]
    cache = C.CACHE / "ors" / f"matrix_{PROFILE}_{h}.json"
    if cache.exists():
        return np.array(json.loads(cache.read_text())["response"]["durations"], dtype=float)
    r = requests.post(
        f"{ORS_URL}/v2/matrix/{PROFILE}",
        json=body,
        headers={"Authorization": key, "Content-Type": "application/json"},
        timeout=120,
    )
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "profile": PROFILE,
                "endpoint": f"{ORS_URL}/v2/matrix/{PROFILE}",
                "request": body,
                "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "response": r.json(),
            }
        )
    )
    return np.array(r.json()["durations"], dtype=float)
