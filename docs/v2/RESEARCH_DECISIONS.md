# Research decisions (with reasons; revisit when evidence changes)
1. **Labels are SAR proxies**, never ground truth. Every output carries `SAR PROXY - UNVALIDATED` until agreement with independent products is documented.
2. **One orbit per event** for pre and post: backscatter depends on viewing geometry; mixing orbits creates false change.
3. **Median baseline of >=3 pre scenes**: reduces speckle and single-date moisture effects. Fewer scenes => verdict MARGINAL.
4. **Post scene must be within 10 days after peak** or water may already have receded (verdict MARGINAL).
5. **Thresholds (-3 dB change, < -15 dB, slope <= 5 deg)** are literature-style starting values, not tuned for Chennai. Tune on the first event with sensitivity analysis, freeze, then test on a different event.
6. **Event-level temporal validation may not be possible with S1 alone** (2015 peak and 2023 coverage unconfirmed); alternatives are documented in V2_PLAN.md section 1.
7. **Independent validation uses other sensors/products** (ALOS-2 L-band, RISAT-1A, EOS-04) and point observations (IITM logs). Sentinel-1-derived products (e.g. UNOSAT, MBRSC) are NOT independent of our S1 labels and are comparisons only.
8. **Existing datasets are not replaced automatically**; any replacement needs a recorded reason and before/after comparison.
9. **Urban recall bias** (double-bounce) is reported, not hidden; urban and non-urban metrics are separated.
10. **Relative orbit: catalogue first, ESA-formula fallback, Earth Engine as arbiter.** Pairing uses (direction, relative orbit); unknown orbits are never paired. Plain `absolute mod 175` is not accepted as a relative orbit. S1C/S1D are not derived (offsets change/provisional). The 2015 November event stays EXPLORATORY and is not independently validated (its only S1-based reference, UNOSAT, is not independent of S1).

## V2.2 S1B decisions
- Scenes are pinned by ID (not date windows) so the run is reproducible; same relative orbit 92 / DESCENDING for all five.
- Speckle: 30 m circular focal median per scene before compositing (simple, transparent). Pre composite = per-pixel median of 4 scenes; temporal std dev is kept as a diagnostic (optional std test off by default).
- Change rule: (post - pre_median) < -3 dB AND post < -15 dB. Starting values from SAR flood-mapping literature; NOT tuned here.
- Masks: previously dark (pre median < -18 dB, catches permanent water/smooth surfaces), JRC occurrence >= 10 %, slope > 5 deg (NASADEM). HAND is exported as a diagnostic (not applied by default; set `--set max_hand_m=15` to apply).
- Terrain: EE GRD is orthorectified but not radiometrically terrain-flattened; flat Chennai makes this a minor, but reported, limitation.
- Processing at 10 m, aggregated to the 30 m master grid (a cell is proxy if >= 50 % of its valid 10 m pixels are proxy); minimum connected cluster 8 pixels (10 m).
