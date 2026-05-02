---
create_time: 2026-04-29 11:32:22
status: done
prompt: sdd/prompts/202604/unreadable_artifact_scan.md
---
# Plan: Harden Artifact Scan Against Unreadable Timestamp Directories

## Problem

GitHub Actions fails in `tests/test_core_agent_scan.py::test_unreadable_artifact_dir_is_counted` with:

```text
PermissionError: [Errno 13] Permission denied: '.../artifacts/ace-run/20260427120000/done.json'
```

The test creates an artifact timestamp directory, writes `agent_meta.json`, then changes the timestamp directory to
`0o000`. The scanner contract says unreadable directories are soft errors: the scan should not raise, and
`snapshot.stats.os_errors` should count the failure.

The Python scanner already catches `OSError` when reading marker JSON, listing artifact dirs, globbing prompt steps, and
reading raw prompts. The gap is `done_path.exists()` in `_scan_artifact_dir()`. On some Python versions and filesystem
conditions, `Path.exists()` can raise `PermissionError` when the parent directory lacks search permission. Local Python
3.14 does not reproduce the failure because newer `pathlib` behavior is more forgiving, but CI does.

## Intended Fix

Add a small helper in `src/sase/core/agent_scan_facade.py` for marker existence checks that:

- returns `True` or `False` for normal cases;
- catches `OSError`, increments `stats["os_errors"]`, and returns `False` for inaccessible paths;
- preserves existing `has_done_marker` behavior when `done.json` is visible but unreadable: if existence succeeds and
  JSON loading fails, the scanner still emits a default `DoneMarkerWire`.

Use this helper for `done_path` in `_scan_artifact_dir()`. Keep the change narrow so scan behavior for all other marker
files remains unchanged.

## Test Plan

1. Run the focused failing test: `just test tests/test_core_agent_scan.py::test_unreadable_artifact_dir_is_counted`
2. Run the full agent scan contract tests: `just test tests/test_core_agent_scan.py`
3. Because this repo requires it after edits, run: `just check`

## Notes

This is a cross-version robustness issue, not a data issue. The artifact scanner's documented behavior is that
filesystem soft errors are absorbed and counted, so the fix belongs in the scanner rather than in the test.
