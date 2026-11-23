"""Every .py compiles and every src module imports."""
import importlib
import py_compile
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class T(unittest.TestCase):
    def test_compile_all(self):
        for p in list(ROOT.glob("scripts/*.py")) + list(ROOT.glob("src/**/*.py")) + [ROOT / "dashboard" / "app.py"]:
            py_compile.compile(str(p), doraise=True)

    def test_import_src(self):
        for p in ROOT.glob("src/**/*.py"):
            if p.name == "__init__.py":
                continue
            mod = ".".join(p.relative_to(ROOT).with_suffix("").parts)
            importlib.import_module(mod)


if __name__ == "__main__":
    unittest.main()
