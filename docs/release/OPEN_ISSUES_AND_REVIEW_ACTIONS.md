# Open issues and review actions

This register consolidates unresolved research/release items. It does not silently upgrade older master-control statuses.

## Independent source and reference review

| Action | Owner | Required evidence |
|---|---|---|
| Verify all bibliography entries against original sources | Agent 1 | Checked author/title/venue/year/DOI register |
| Confirm CDMP 2026 and IWMI 2015 grey-literature metadata | Agent 1 | Verified title, issuing body, date and stable URL |
| Resolve E39–E51 evidence references | Agent 1 | Recovered source or explicit unavailable status |
| Continue NRSC/ISRO/ALOS-2/Cartosat acquisition research | Agent 1 | Original files or documented acquisition failure, metadata and provenance |
| Decide whether any event reference qualifies for quantitative validation | Agent 1 + project owner | Written qualification / no-go decision |

## DEP2

- Reconcile acquired-source manifest with copied-file manifest.
- Review 72 lost and 36+42 relabelled depth-class rows; document extraction rules and verified subset (1,312/1,401).
- Confirm the meaning and geographic filters behind 2,350 crowd features, 43 outside-region features and 34,355 road polygons.
- Confirm the recurrence definition behind 96 wards in both years and seven exact recurring names.
- Preserve source-specific R0/R1 statuses and redistribution restrictions.

## Study area and upstream methods

- AOI remains provisional OSM-derived; obtain/verify official GCC boundary if available.
- If boundary changes, rerun affected spatial outputs in a new versioned directory and compare against the current baseline.
- Keep CHIRPS daily IST convention unresolved until verified.
- Disclose DSM, HAND proxy, provisional water exclusion, fill-depth and correlated-indicator limitations.
- Keep NoData/excluded cells explicitly not assessed.

## Integrated risk and prediction

- Define integrated risk only after upstream hazard/susceptibility and exposure evidence are accepted.
- Assess prediction feasibility only after qualified temporal labels and independent evaluation design exist.
- Do not proceed merely because exploratory ML scripts exist.

## Release and publication

- Run final tests on the exact release candidate.
- Review all staged files and scan for credentials, restricted documents, large/raw data and local paths.
- Verify references and evidence wording.
- Obtain supervisor approval for author details and acknowledgements.
- Check target venue page limit, template, anonymisation and copyright.
- Create PR and review before merge; do not merge without owner approval.
