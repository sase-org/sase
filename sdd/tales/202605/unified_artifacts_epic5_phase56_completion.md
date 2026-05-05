---
plan: sdd/epics/202605/unified_artifacts_epic5_migration.md
status: completed
bead_id: sase-23.5.6
---

# Unified Artifacts Epic 5 Phase 5.6 Completion

Phase 5.6 documents the unified artifact graph migration path and adds the final Python smoke coverage for migrated
fixture data.

Completed work:

- Expanded `docs/artifacts.md` with the product model, artifact ID contract, link direction, manual vs derived rows,
  tombstone semantics, default and targeted rebuild guidance, doctor issue interpretation, and an operator migration
  runbook.
- Updated `src/sase/xprompts/skills/sase_artifact.md` so generated `/sase_artifact` skills give agents the same graph
  model and troubleshooting order as the docs.
- Added a real-extension CLI migration smoke test that builds a temporary project, bead store, named agent marker set,
  response file, and thought log; runs `sase artifact rebuild`; validates `doctor`; and exercises `list`, `show`, and
  `graph` against the migrated index.

Compatibility notes:

- The default rebuild path indexes existing state without deleting source files or rewriting historical marker files.
- Legacy unnamed agents keep deterministic fallback IDs of the form `agent:<project>:<workflow>:<timestamp>`.
- The old `~/.sase/agent_artifact_index.sqlite` remains intentionally available for fast agent startup and compatibility
  loading paths. It is not removed by this migration.
- Live agent detail, file, and thinking surfaces may remain where they still serve active monitoring. Historical
  artifact discovery should use the unified artifact panel and `sase artifact`.

Residual risks:

- Fallback agent IDs and unresolved timestamp links can still appear for incomplete historical marker sets. Doctor now
  reports these as migration diagnostics; operators should repair marker metadata only when a stable real agent name or
  missing source root is known.
- The generated skill deployment depends on `sase init-skills`; the source has been updated here, and the generation
  workflow should be used rather than hand-editing deployed provider copies.
