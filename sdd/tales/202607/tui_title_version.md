---
create_time: 2026-07-03 14:43:12
status: wip
prompt: sdd/prompts/202607/tui_title_version.md
---
# Show sase Version Instead of PID in the ace TUI Title

## Goal

The ace TUI header currently reads `sase ace (PID: 9539)`. Replace the PID with the running sase version, e.g.
`sase ace (v0.7.1)`. Editable/dev installs must show a meaningful git-derived dev version (e.g.
`v0.8.0+3.g084a6a2.dirty`) rather than a stale or bare release number.

## Current State (research findings)

- The title is set in `AceApp.__init__` at `src/sase/ace/tui/app.py:220`:
  `self.title = f"sase ace (PID: {os.getpid()})"`. (The `os` import is still needed afterwards for the `sys.path` setup
  at the top of the file.)
- A complete version-resolution stack already exists in `src/sase/version/` and is used by `sase version` and the
  dev-update flows:
  - `collect_package_record(HOST_DISTRIBUTION_NAME, role="host", import_module="sase", source_kind="python")`
    (`_collector.py`) returns a `VersionPackageRecord` whose `display_version` already covers every install shape:
    - wheel/uv-tool installs → distribution version (no git probe; `source_root` is `None`);
    - editable installs → source version from `pyproject.toml` plus a git-derived suffix via `derive_display_version()`
      (`_display.py`): clean tagged HEAD → `X.Y.Z`, otherwise `X.Y.Z+<distance>.g<shortsha>[.dirty]` /
      `X.Y.Z+untagged.g<shortsha>[.dirty]`.
  - `sase.__version__` (`src/sase/__init__.py`, release-please managed) is the cheap, I/O-free fallback.
- **Perf constraint** (`memory/tui_perf.md`): never run synchronous subprocess/disk work on the Textual event loop or
  the startup path. `collect_package_record` runs git subprocesses for editable installs, so it must NOT be called
  synchronously from `__init__`. Mount-time startup work is off-threaded via `asyncio.to_thread(...)` in
  `src/sase/ace/tui/actions/_startup_mount.py` (`on_mount`).
- Affected tests:
  - `tests/ace/tui/test_app_title.py` asserts the exact PID-based title.
  - `tests/ace/tui/visual/conftest.py` pins `os.getpid()` → `12345` solely to keep the header title byte-stable in PNG
    snapshots.
  - All ~117 goldens in `tests/ace/tui/visual/snapshots/png/` render the header, so every golden changes when the title
    changes.
- Rust core boundary: version derivation inspects Python distribution metadata and the local git checkout; it is
  inherently host-Python-specific and already lives in this repo's `src/sase/version/`. No `sase-core` change is needed.

## Design

### 1. Version resolution helper (reuse existing machinery)

Add `host_display_version() -> str | None` to the `sase.version` package (small new module, e.g.
`src/sase/version/_host.py`, exported from `sase/version/__init__.py`):

- Returns
  `collect_package_record(HOST_DISTRIBUTION_NAME, role="host", import_module="sase", source_kind="python").display_version`.
- Normalizes the `"<unknown>"` sentinel to `None` so callers can fall back cleanly.
- Docstring notes it may block on git subprocesses (editable installs) and must be called off-thread from UI code.

### 2. TUI seam

New `src/sase/ace/tui/util/app_version.py`:

- `initial_app_version() -> str` — returns `sase.__version__` (no I/O; safe for `__init__`).
- `resolved_app_version() -> str | None` — calls `sase.version.host_display_version()`, catching all exceptions → `None`
  (title refinement is best-effort and must never break startup).
- `format_app_title(version: str) -> str` — returns `f"sase ace (v{version})"` so both title writers share one format.

### 3. Two-phase title in `AceApp`

- `__init__` (`app.py:220`): `self.title = format_app_title(initial_app_version())`. Instant, and already correct for
  the common case.
- `on_mount` (`_startup_mount.py`): add one more off-thread step following the existing pattern —
  `version = await asyncio.to_thread(resolved_app_version)`; if it is truthy and differs from the initial version,
  assign `self.title = format_app_title(version)` (Textual repaints the header on title assignment). Place it after the
  existing critical startup reads so it never delays first paint of the lists. If `resolved_app_version()` returns
  `None`, keep the `__version__`-based title.

This upgrades editable installs from `v0.8.0` to e.g. `v0.8.0+untagged.g084a6a2.dirty` moments after mount, while wheel
installs typically resolve to the same string and see no visible change.

## Test Plan

1. **`tests/ace/tui/test_app_title.py`** — update/extend:
   - Initial title equals `f"sase ace (v{sase.__version__})"`; keep the `startswith("sase ace ")`/`endswith(")")`
     assertions.
   - Unit tests for `app_version.py`: `resolved_app_version()` returns the record's display version; returns `None` when
     the resolver raises or yields `<unknown>`.
   - Mount-refinement test (async `run_test()`), monkeypatching `resolved_app_version` to a fixed dev string and
     asserting `app.title` updates; and a no-downgrade case where `None` leaves the initial title intact.
2. **`tests/ace/tui/visual/conftest.py`** — replace the `os.getpid` pin with monkeypatches of `initial_app_version` and
   `resolved_app_version` (both → a fixed value such as `"0.7.1"`), so every snapshot renders a byte-stable
   `sase ace (v0.7.1)` and the async refinement cannot change the title mid-capture.
3. **Regenerate all PNG goldens** with `--sase-update-visual-snapshots` via the dedicated visual suite, then re-run
   `just test-visual` to confirm a clean pass. Note: goldens were recently adopted as CI-canonical (commit `084a6a2c6`);
   if CI disagrees with locally regenerated goldens beyond its drift tolerance, adopt the CI-canonical artifacts the
   same way.

## Verification

- `just check` (lint + mypy + full test suite).
- `just test-visual` after golden regeneration.
- Manual smoke: launch `sase ace` from an editable checkout and confirm the title shows the git-derived dev version
  shortly after startup; confirm a wheel-installed sase shows `vX.Y.Z`.

## Out of Scope

- Per-agent PID displays elsewhere in the TUI (detail panel `PID:` field, runners modal, kill/wait action descriptions)
  — these remain unchanged; only the app title loses the PID.
- Plugin/core version display in the title (the `sase version` command already covers those).
