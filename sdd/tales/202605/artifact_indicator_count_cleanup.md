---
create_time: 2026-05-06 00:46:57
status: done
---
# Artifact Indicator Count Cleanup Plan

## Context

After closing `sase-24.4`, `just pyvision` reported one unused public symbol: `ArtifactIndicatorCount` in
`src/sase/ace/tui/models/artifact_indicator.py`. The class is an internal implementation detail of `ArtifactIndicator`
and is not referenced outside that module.

## Plan

1. Rename `ArtifactIndicatorCount` to `_ArtifactIndicatorCount` so pyvision no longer treats it as public API.
2. Update internal type annotations and constructors in `artifact_indicator.py`.
3. Remove the class from `__all__`.
4. Rerun `just pyvision`, the focused artifact-indicator tests, and `just check`.
