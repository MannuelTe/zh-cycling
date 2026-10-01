"""Download raw sources and keep a manifest (url, sha256, size, retrieval time)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import requests

from . import config as C

MANIFEST = C.RAW / "manifest.json"


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def fetch(name: str, url: str, meta: dict | None = None, force: bool = False) -> dict:
    C.RAW.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    path = C.RAW / name
    if path.exists() and name in manifest and not force:
        print(f"  cached  {name}")
        return manifest[name]
    print(f"  fetch   {name}")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        tmp = path.with_suffix(path.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    head = tmp.read_bytes()[:200].lower()
    if b"<html" in head or b"<!doctype html" in head:
        tmp.unlink()
        raise RuntimeError(f"{name}: server returned HTML instead of data ({url})")
    tmp.rename(path)
    entry = {
        "url": url,
        "final_content_type": ctype,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **(meta or {}),
    }
    manifest[name] = entry
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return entry


def download_all(force: bool = False, cantonal: bool = False) -> None:
    print("Downloading sources ->", C.RAW)
    for name, src in C.SOURCES.items():
        fetch(name, src["url"], {k: v for k, v in src.items() if k != "url"}, force=force)
    if cantonal:
        download_cantonal(force=force)


def download_cantonal(force: bool = False) -> None:
    for year, url in C.CANTONAL_DISTRIBUTIONS.items():
        meta = {"dataset": "https://datenkatalog.statistik.zh.ch/datasets/3062%40tiefbauamt-kanton-zuerich"}
        try:
            fetch(f"cantonal_velo_{year}.csv", url, meta, force=force)
        except Exception as e:  # must not block the city pipeline
            print(f"  ! cantonal {year}: {e}")
