"""Verify files against a SHA-256 manifest (read-only). Paths in the manifest are relative to the CURRENT directory,
so run it from the project root.

  .\\.venv\\Scripts\\python.exe scripts\\verify_overlay.py docs\\final02\\PACKAGE_SHA256SUMS.txt
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path.cwd()


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    sums = Path(argv[0]) if argv else ROOT / "docs" / "final02" / "PACKAGE_SHA256SUMS.txt"
    sums = sums if sums.is_absolute() else ROOT / sums
    ok = bad = missing = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        p = ROOT / rel.strip().lstrip("*")
        if not p.exists():
            missing += 1
            print("MISSING ", rel)
        elif sha(p) != digest:
            bad += 1
            print("CHANGED ", rel)
        else:
            ok += 1
    print(f"ok={ok} changed={bad} missing={missing}")
    return 0 if bad == missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
