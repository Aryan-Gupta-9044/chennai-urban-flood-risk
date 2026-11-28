# Data sources, provenance and licensing

## Purpose

This document describes how source provenance should be recorded. It is not a substitute for the detailed source registers in `config/`, DEP2 documentation, evidence registers or Agent 1's independent checks.

## Required provenance fields

For every source, record:
- Source title and provider.
- Original URL / repository and exact version or commit.
- Acquisition date and retrieval method.
- Observation period and temporal meaning.
- Native spatial resolution and coordinate reference system.
- Processing/resampling/aggregation applied.
- Licence, redistribution permission and attribution requirements.
- Local file path, file size and SHA-256 checksum.
- Known omissions, uncertainty and fitness for intended use.
- Evidence status and reviewer.

## Source families represented

| Source family | Role | Important caveat |
|---|---|---|
| OSM-derived AOI / road / facilities | Study-area geometry and crowd-sourced exposure features | Temporal completeness and positional/attribute quality vary |
| GLO-30 | Terrain/surface elevation context | DSM, not bare-earth DTM |
| CHIRPS | Rainfall context | Coarse native grid; not ward-scale independent rainfall |
| IMD rainfall | Rainfall context / comparison | Availability and spatial/temporal support must be documented per product |
| Sentinel-1 | Radar observations and water-related candidate signals | Radar response is not direct floodwater ground truth |
| CDMP reports / tables | Reported flood evidence and reference context | Evidence quality, temporal precision and redistribution permissions vary |
| OSM-IN / other reported sources | Reported event/location context | Not automatically independent or event-specific ground truth |
| WorldCover / GHSL and other built-environment layers | Land-cover / built-up context | Product version, epoch, grid and aggregation decisions must be explicit |

## DEP2 provenance facts requiring explicit handling

- DEP2 package SHA-256: `F17EA48000F731D6A8786ECE911AEFF4947C2907803CBE68C165C900A851EED8`
- DEP2.1 package SHA-256: `D219A5A5E14961623187282322C30D4E0E80D50CB0C210DCB8D732BCDFFB130A`
- Recorded pinned source commits:
  - `reclaimchennai/chennai-monsoon-map`: `56c3a6a20f93b8f301cfab474cdbafb94a525ef4`
  - `osm-in/flood-map`: `5790681fc356b53d03d86642c155bd6c96665c6a`
  - `datameet/Municipal_Spatial_Data`: `9b4d1c2ece54cdeb6f5e8bad9ccad7844f783b17`
  - `km658/Multi-Hazard-Climate-Exposure-and-Screening-Level-Risk-among-Slum-Settlements-in-Chennai`: `e9abb981240bbc006281e34ca6d9cbfa22aa5719`

The package integration record reports 146 files integrated and 62 sources acquired/verified. Acquisition-manifest versus copied-file-manifest reconciliation is incomplete; do not state that all 62 sources were integrated.

## Redistribution restriction

CDMP 2026/2024 PDFs identified with `redistribute:false` must not be committed, mirrored or bundled for public redistribution. Keep only permitted metadata, citations, source URLs and derived outputs where the licence allows. Review every source-specific licence before publishing.

## Reference evidence classes

Examples recorded in the current project baseline:
- 2021 CDMP: R0 WARNING, R1 WARNING, PRESENCE_ONLY.
- 2015 CDMP: R0 WARNING, R1 FAIL, QUALITATIVE_ONLY.
- 2015 OSM-IN (2 December): R0 WARNING, R1 FAIL, QUALITATIVE_ONLY.

Preserve exact evidence labels from `docs/final/EVIDENCE_DECISION_LOG.md`. Do not convert a warning/fail into a pass through paraphrasing.

## Open provenance work

1. Agent 1 must verify every paper bibliography entry against the original publication/source, including author order, title, venue, year and DOI/URL.
2. Confirm grey-literature metadata for `gcc2026cdmp` and `iwmi2015chennai`.
3. Reconcile acquired-source and copied-file manifests.
4. Resolve licensing/redistribution for each source.
5. Continue the NRSC/ISRO/ALOS-2/Cartosat reference-acquisition work and document failures as carefully as successful acquisition.
6. Recover or explicitly mark unavailable evidence references E39–E51.
