"""Acquire DEP-2 source files from pinned commits / release assets and verify SHA-256.

Originals are written once into data/external/dep2_sources/ and never modified.
A file whose hash differs from the manifest stops the run (no silent replacement).
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from .common import LOG, read_json, sha256_file, utcnow, write_json


def _download(url: str, dest: Path, timeout=300):
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "dep2-acquire/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)


def acquire(sources_json: Path, raw_root: Path, cache_dirs: list[Path] | None = None, include_pdfs=True) -> dict:
    cfg = read_json(sources_json)
    raw_root = Path(raw_root)
    records = []
    entries = list(cfg["files"]) + (list(cfg.get("release_assets", [])) if include_pdfs else [])
    for e in entries:
        dest = raw_root / e["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        action = "present"
        if dest.exists():
            got = sha256_file(dest)
            if got != e["sha256"]:
                raise SystemExit(f"STOP: existing original {dest} has SHA-256 {got}, manifest {e['sha256']} (originals are immutable)")
        else:
            cached = None
            for c in cache_dirs or []:
                cand = Path(c) / Path(e["dest"]).name
                if cand.is_file() and sha256_file(cand) == e["sha256"]:
                    cached = cand
                    break
            if cached:
                shutil.copyfile(cached, dest)
                action = f"copied from verified cache {cached.name}"
            else:
                LOG.info("download %s", e["url"])
                _download(e["url"], dest)
                action = "downloaded"
            got = sha256_file(dest)
            if got != e["sha256"]:
                bad = dest.with_name(dest.name + ".REJECTED")
                dest.replace(bad)
                raise SystemExit(f"STOP: {e['url']} SHA-256 {got} != manifest {e['sha256']} (moved to {bad.name})")
        dest.chmod(0o444)
        records.append({**e, "local_path": dest.relative_to(raw_root).as_posix(), "action": action, "verified_utc": utcnow()})
    log = {"verified_utc": utcnow(), "n_files": len(records), "all_hashes_verified": True, "records": records}
    write_json(raw_root / "ACQUISITION_LOG.json", log)
    LOG.info("acquired/verified %d files", len(records))
    return log
