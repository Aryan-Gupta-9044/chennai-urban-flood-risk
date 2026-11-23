"""Independent-reference readiness logic (pure Python; unit-tested). Statuses are conservative: nothing is 'accessible' until a file has actually been obtained and inspected."""
UNK = "UNCONFIRMED"


def status_of(d):
    if d.get("independent_of_s1") is False:
        return "NOT SUITABLE FOR QUANTITATIVE VALIDATION (Sentinel-1-derived: not independent of a Sentinel-1 proxy; usable only as a consistency comparison)"
    if d.get("access") != "VERIFIED AND ACCESSIBLE":
        base = d.get("access", "NOT YET OBTAINED")
    else:
        base = "VERIFIED AND ACCESSIBLE"
    unknowns = [k for k in ("format", "crs", "extent", "kind", "licence", "obs_date") if UNK in str(d.get(k, UNK))]
    if base != "VERIFIED AND ACCESSIBLE":
        return f"{base}; suitability cannot be assessed until obtained (unconfirmed: {', '.join(unknowns) or 'none'})"
    return "SUITABLE SUBJECT TO CHECKS" if unknowns else "SUITABLE SUBJECT TO CHECKS (run check_ingest)"


def check_ingest(meta):
    """meta of an ACTUAL obtained file -> list of failed requirements (empty = technically ready, licence still to be read)."""
    fails = []
    if meta.get("kind") not in ("raster", "vector", "point"):
        fails.append("not a georeferenceable raster/vector/point dataset (PDF/JPEG/map service?) -> qualitative only")
    if not meta.get("crs"):
        fails.append("CRS missing")
    if not meta.get("obs_date"):
        fails.append("observation date missing")
    if not meta.get("classes_documented"):
        fails.append("class meaning not documented")
    if meta.get("extent_covers_aoi") is not True:
        fails.append("extent does not (fully) cover the study area or is unknown")
    if not meta.get("method_documented"):
        fails.append("production method undocumented -> independence from Sentinel-1 unknown")
    if meta.get("licence_ok") is not True:
        fails.append("licence not confirmed")
    return fails
