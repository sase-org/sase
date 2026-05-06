---
plan: sdd/epics/202605/artifacts_panel_epic1.md
status: completed
bead_id: sase-24.1.6
---

# Artifacts Panel Epic 1 Phase 6 Completion

Phase 6 validates the landed Epic 1 artifact semantics and documents the final operator contract for later artifacts
panel work.

Completed work:

- Confirmed the Rust, PyO3, Python wire, CLI, and TUI startup surfaces expose semantic file artifact types through
  `metadata.artifact_type` while preserving `kind = "file"`.
- Clarified `docs/artifacts.md` and `/sase_artifact` skill guidance for `sase artifact sync`, targeted refresh paths,
  canonical file types, sparse directory artifacts, and `orphan_directory` diagnostics.
- Kept historical migration explicit: `sase ace` startup and artifact panel open paths do not run broad sync.

Compatibility notes:

- Existing file rows without `metadata.artifact_type`, or with unknown values, read and filter as `misc`.
- Directory artifacts are limited to `/` and containers for visible non-directory artifacts. Old directory-only rows are
  reported by doctor instead of being silently deleted.
- `sase artifact rebuild` remains the low-level command; `sase artifact sync` is the friendlier historical backfill
  alias with the same safe defaults.
