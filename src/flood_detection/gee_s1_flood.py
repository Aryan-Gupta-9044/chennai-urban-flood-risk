"""Sentinel-1 flood extent in Google Earth Engine (V2). SAR change detection -> PROXY flood label (unvalidated).
Design choices (all documented in docs/v2/RESEARCH_DECISIONS.md):
 * ONE orbit (direction + relative orbit) for pre and post - never mixed.
 * Baseline = median of several pre-event scenes (suppresses speckle and single-date wetness).
 * Rule: (post - pre < diff_db) AND (post < post_max_db), after focal-median speckle reduction.
 * Masks: permanent/seasonal water (JRC occurrence and pre-event dark pixels), steep slope, tiny clusters.
 * Known blind spot: flooded buildings/dense urban areas (double bounce) are under-detected -> recall is biased low there.
NOT executed during packaging (no Earth Engine access in the build sandbox)."""
import ee  # imported lazily by callers via try/except


def s1_collection(geom, start, end, direction, rel_orbit):
    return (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate(start, end)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .filter(ee.Filter.eq("orbitProperties_pass", direction))
            .filter(ee.Filter.eq("relativeOrbitNumber_start", int(rel_orbit)))
            .select("VV"))


def scene_ids(col):
    return col.aggregate_array("system:index").getInfo()


def build_flood_image(geom, pre, post, direction, rel_orbit, p):
    """pre/post = (start, end) with END EXCLUSIVE in GEE, so callers pass end+1 day."""
    pre_c = s1_collection(geom, pre[0], pre[1], direction, rel_orbit)
    post_c = s1_collection(geom, post[0], post[1], direction, rel_orbit)
    rad = p["speckle_radius_m"]
    pre_img = pre_c.median().focal_median(rad, "circle", "meters")
    post_img = post_c.median().focal_median(rad, "circle", "meters")
    diff = post_img.subtract(pre_img).rename("diff_db")
    flood = diff.lt(p["diff_threshold_db"]).And(post_img.lt(p["post_max_db"]))
    slope = ee.Terrain.slope(ee.Image("NASA/NASADEM_HGT/001").select("elevation"))
    flood = flood.And(slope.lte(p["max_slope_deg"]))
    occ = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    flood = flood.And(occ.lt(p["min_water_occurrence_pct"]))
    flood = flood.And(pre_img.gt(p["pre_water_db"]))          # drop pixels already dark before the event
    flood = flood.selfMask()
    flood = flood.updateMask(flood.connectedPixelCount(100, True).gte(p["min_cluster_pixels"]))
    flood_b = flood.unmask(0).rename("flood").toByte()
    return flood_b.clip(geom), diff.clip(geom), pre_c, post_c
