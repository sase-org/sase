---
create_time: 2026-05-08 18:06:27
status: done
prompt: sdd/prompts/202605/artifact_viewer_runpy_warning.md
---
# Artifact Viewer `runpy` Warning Plan

## Problem

Launching the artifact viewer through the tmux pane helper builds this command:

```bash
python -m sase.ace.tui.graphics.viewer ...
```

Running that command in the project virtualenv currently emits:

```text
<frozen runpy>:128: RuntimeWarning: 'sase.ace.tui.graphics.viewer' found in sys.modules after import of package 'sase.ace.tui.graphics', but prior to execution of 'sase.ace.tui.graphics.viewer'; this may result in unpredictable behaviour
```

The warning appears before the first image because it is emitted by Python module startup, before viewer argument
parsing or rendering.

## Root Cause

`python -m sase.ace.tui.graphics.viewer` asks `runpy` to import the parent package `sase.ace.tui.graphics` before
executing the `viewer` submodule as `__main__`.

`src/sase/ace/tui/graphics/__init__.py` currently imports many public viewer symbols from `.viewer` for package-level
re-export. That means the target module `sase.ace.tui.graphics.viewer` is imported as a side effect of importing the
parent package. When `runpy` then tries to execute that same module name, it detects that it is already present in
`sys.modules` and emits the warning.

The viewer code is already split into private implementation modules:

- `_viewer_types.py`
- `_viewer_render.py`
- `_viewer_loop.py`
- `_viewer_launch.py`

So the parent package does not need to import the executable `viewer.py` module just to expose the public graphics API.

## Implementation Plan

1. Update `src/sase/ace/tui/graphics/__init__.py` so package-level exports come from the private implementation modules
   instead of from `viewer.py`.
   - Import public types from `_viewer_types.py`.
   - Import launch helpers from `_viewer_launch.py`.
   - Import render helpers from `_viewer_render.py`.
   - Import loop/navigation helpers from `_viewer_loop.py`.
   - Preserve the existing `__all__` names so callers using `from sase.ace.tui.graphics import ...` keep working.

2. Keep `src/sase/ace/tui/graphics/viewer.py` as the module entrypoint and direct test/compatibility facade.
   - The direct `sase.ace.tui.graphics.viewer` import path should continue to expose `main()` and the existing viewer
     helper symbols.
   - Avoid changing the tmux launch command unless the import decoupling proves insufficient.

3. Add regression coverage in `tests/ace/tui/test_artifact_viewer.py`.
   - Run a fresh subprocess with `sys.executable -Wdefault -m sase.ace.tui.graphics.viewer --help`.
   - Assert it exits successfully.
   - Assert stderr does not contain `RuntimeWarning` or the `found in sys.modules` warning text.
   - Keep the test dependency-free by using `--help`, which does not require `kitten`, `tmux`, `pandoc`, or image files.

4. Verify the fix.
   - Re-run the exact reproduction command: `./.venv/bin/python -Wdefault -m sase.ace.tui.graphics.viewer --help`
   - Run the focused artifact viewer tests: `./.venv/bin/pytest tests/ace/tui/test_artifact_viewer.py`
   - Because this repo requires it after file changes, run: `just check`

## Risk

The main compatibility risk is package-level monkeypatching in tests or callers that rely on
`sase.ace.tui.graphics.<name>` resolving to the wrapper functions from `viewer.py` rather than the underlying
implementation modules. The public launch helpers are already implemented in `_viewer_launch.py`, and production callers
that import from the package use those launch helpers, so the expected blast radius is small. The focused test suite
will catch the known artifact viewer behavior, and `just check` will catch broader package export regressions.
