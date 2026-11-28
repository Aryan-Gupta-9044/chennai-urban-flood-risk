# GitHub and Release Checklist

## Existing release

- Repository URL: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk
- PR #1: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk/pull/1
- Merge commit: `64c77c6676ec0270f1d8d81a7540ace1f82f0fad`
- Baseline branch: `milestone-2-3-4-checkpoint`
- Release branch: `release/2026-11-28-final-documentation`

## Before adding handoff files

1. Confirm current branch and commit.
2. Confirm no user changes are at risk.
3. Confirm the package destination does not overwrite existing documents.
4. Add only the new documentation paths.
5. Review staged names, sizes and diffs.
6. Ensure no raw restricted data, local paths, secrets, virtual environment or backups are staged.

## Suggested destination

```text
PROJECT_ROOT/
├── PROJECT_STATUS_2026-11-28.md
├── AGENT_MASTER_HANDOFF_2026-11-28.md
└── docs/
    └── project_handoff/
        ├── README_HANDOFF_PACKAGE.md
        ├── PROJECT_CONTEXT.md
        ├── CURRENT_STATUS_AND_PENDING_WORK.md
        ├── REPOSITORY_MAP.md
        ├── WINDOWS_RUNBOOK.md
        ├── AGENT_ROLES_AND_WORKFLOW.md
        ├── SCIENTIFIC_CAVEATS_AND_EVIDENCE.md
        ├── INTEGRATION_AND_VALIDATION_PLAN.md
        ├── GITHUB_AND_RELEASE_CHECKLIST.md
        ├── HANDOFF_MANIFEST.csv
        └── SOURCE_AND_OUTPUT_REGISTER_TEMPLATE.csv
```

## Suggested branch

`docs/2026-11-28-complete-project-handoff`

Create it only from the verified baseline after checking for existing branch and uncommitted/untracked conflicts.

## Stage explicitly

```powershell
git add docs/project_handoff
git add PROJECT_STATUS_2026-11-28.md AGENT_MASTER_HANDOFF_2026-11-28.md
git status --short
git diff --cached --stat
git diff --cached --name-status
```

Do not commit until the staged list is reviewed.

## Pull request

Use a documentation-only PR. Explain that the package records status as of 28 November 2026 and must be reconciled with the live repository before future execution. Do not merge without approval.

## Never include by default

- `.venv/`
- local `config/dep2.local.json`
- harness-specific `config/dep2.cloud_run.json`
- restricted CDMP PDFs
- backups
- raw archives or duplicate source bundles
- large generated rasters unless intentionally approved
- secrets, tokens or credentials
