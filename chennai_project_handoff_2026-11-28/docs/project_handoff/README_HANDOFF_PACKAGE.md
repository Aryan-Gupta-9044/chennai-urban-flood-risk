# Chennai Urban Flood-Risk Project — Handoff Package

**Prepared:** 28 November 2026  
**Project:** Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data  
**Study area:** Chennai, Tamil Nadu, India  
**Verified software baseline:** `64c77c6676ec0270f1d8d81a7540ace1f82f0fad`  
**Branch at baseline:** `milestone-2-3-4-checkpoint`

## Purpose

This package consolidates the known project context, release status, scientific caveats, run commands, agent responsibilities, pending work, and GitHub handoff instructions. It is designed to be added to the repository without overwriting existing project files.

## Suggested installation

Copy the entire `docs/project_handoff/` directory into the repository. Also copy the two root-level convenience files:

- `PROJECT_STATUS_2026-11-28.md`
- `AGENT_MASTER_HANDOFF_2026-11-28.md`

The archive deliberately does not include source datasets, generated analytical outputs, restricted reports, local environment files, or backups.

## Important limitation

This package is based on the verified conversation/project status supplied up to 28 November 2026. It is not a fresh filesystem audit of the user's current Windows checkout. Before treating every path, command or status as current, compare it with the actual repository. Paths explicitly labelled "verify" must be checked locally.

## Contents

| File | Purpose |
|---|---|
| `PROJECT_CONTEXT.md` | Complete project overview, architecture and scientific context |
| `CURRENT_STATUS_AND_PENDING_WORK.md` | Completed, pending, blocked and later tasks |
| `REPOSITORY_MAP.md` | Known repository locations and what to inspect |
| `WINDOWS_RUNBOOK.md` | Environment setup, tests, pipeline and dashboard commands |
| `AGENT_ROLES_AND_WORKFLOW.md` | Pro agent / Agent 1 responsibilities and gates |
| `SCIENTIFIC_CAVEATS_AND_EVIDENCE.md` | Accepted numbers, limitations and claim restrictions |
| `GITHUB_AND_RELEASE_CHECKLIST.md` | Safe branch, commit, PR and release procedure |
| `INTEGRATION_AND_VALIDATION_PLAN.md` | DEP2–SUS1, independent validation and ML review plan |
| `HANDOFF_MANIFEST.csv` | Machine-readable deliverables and status |
| `SOURCE_AND_OUTPUT_REGISTER_TEMPLATE.csv` | Template for reconciling source files and analytical outputs |

## Do not

- Do not claim validated flood prediction accuracy or calibrated flood probabilities.
- Do not overwrite the verified release branch or accepted outputs.
- Do not run `git clean`, `git reset --hard`, force-push, or broad cleanup.
- Do not use `git add .` without inspecting the staged file list.
- Do not redistribute any source marked `redistribute:false`.
