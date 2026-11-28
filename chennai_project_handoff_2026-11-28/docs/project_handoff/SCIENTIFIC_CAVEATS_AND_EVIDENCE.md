# Scientific Caveats and Evidence Rules

## Core terminology

- **Susceptibility:** relative spatial tendency inferred from conditioning factors; not an observed flood event or probability.
- **Candidate water-related SAR signal:** a remotely sensed signal that may be water-related; not automatically confirmed floodwater.
- **Exposure:** people, assets, infrastructure or other elements located in potentially affected areas.
- **Vulnerability:** propensity to experience harm, conditional on exposure and hazard.
- **Risk:** requires a defensible relationship among hazard, exposure and vulnerability; do not create a numerical risk score by simply multiplying arbitrary layers.
- **Independent validation:** comparison against observations not used to construct, tune or select the evaluated product.

## Evidence status vocabulary

Use consistently:
- VERIFIED
- VERIFIED_WITH_LIMITATIONS
- PARTIALLY_VERIFIED
- REPORTED_UNVERIFIED
- QUALITATIVE_ONLY
- PRESENCE_ONLY
- NOT_VERIFIED
- NOT_AVAILABLE
- NOT_APPLICABLE

Do not upgrade a status because a file exists.

## Known limitations to preserve

1. AOI boundary is provisional.
2. GLO-30 is a DSM, not bare-earth DTM.
3. HAND is a Euclidean-nearest-drainage proxy.
4. TWI and other wetness indicators are correlated.
5. Sentinel-1 class 1 is candidate water-related signal.
6. Eight dates are insufficient for broad rainfall-response inference.
7. DEP2 references have warning/fail/presence-only/qualitative-only classifications.
8. Acquisition and copied-file manifests need reconciliation.
9. Some source PDFs are not redistributable.
10. ML results are exploratory and do not establish robust supervised flood prediction.
11. Clusters are indicator-profile groups, not flood-severity classes.
12. No calibrated flood probabilities have been established.
13. No validated operational flood prediction accuracy has been established.

## Required checks before claiming validation

- Independent source provenance.
- Time and spatial alignment.
- Valid positive and negative labels or defensible sampling design.
- No training/validation leakage.
- No reuse of the same source as both construction and independent validation.
- Spatial and temporal dependence addressed.
- Suitable metrics for the reference data.
- Uncertainty and limitations reported.
- Shared inputs and correlated errors disclosed.

If these conditions cannot be met, report a validation gap rather than manufacturing a metric.

## Reproducibility record for every new experiment

Record input paths and SHA256 hashes, code commit, environment, command, parameters, random seeds, runtime, outputs, output hashes and limitations.
