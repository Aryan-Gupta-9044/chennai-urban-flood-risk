"""Verify the FINAL-01 overlay files against docs/final/PACKAGE_SHA256SUMS.txt (read-only)."""
from __future__ import annotations
import hashlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMS = ROOT / "docs" / "final" / "PACKAGE_SHA256SUMS.txt"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    bad = missing = ok = 0
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        p = ROOT / rel.strip().lstrip("*")
        if not p.exists():
            missing += 1; print("MISSING ", rel)
        elif sha(p) != digest:
            bad += 1; print("CHANGED ", rel)
        else:
            ok += 1
    print(f"ok={ok} changed={bad} missing={missing}")
    return 0 if bad == missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
