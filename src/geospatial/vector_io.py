from pathlib import Path
import geopandas as gpd

VECTOR_EXT = (".geojson", ".json", ".gpkg", ".shp", ".zip")


def find_vector_files(folder):
    folder = Path(folder)
    if not folder.exists():
        return []
    order = {e: i for i, e in enumerate(VECTOR_EXT)}
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in VECTOR_EXT]
    return sorted(files, key=lambda p: (order[p.suffix.lower()], p.name))


def read_vector(path):
    p = Path(path)
    if p.suffix.lower() == ".zip":
        return gpd.read_file(f"zip://{p.resolve().as_posix()}")
    return gpd.read_file(p)
