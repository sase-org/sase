---
create_time: 2026-04-27 10:30:55
status: done
prompt: sdd/prompts/202604/fix_keymaps_cache_mutation.md
---
# Plan: Fix `load_builtin_app_defaults` cache-mutation flake

## Problem

CI fails intermittently with:

```
FAILED tests/test_keybinding_footer_status.py::test_keybinding_footer_axe_bindings
AssertionError: assert ('K', 'start axe') == ('x', 'start axe')
```

The expected default key for `kill_agent` is `"x"`, but the test sees `"K"`. `K` is the value used in
`tests/test_keybinding_footer_core.py::test_keybinding_footer_custom_registry_axe_key` — which is the smoking gun for
state leak.

## Root Cause

`src/sase/ace/tui/keymaps/loader.py:37-55`:

```python
@functools.cache
def load_builtin_app_defaults() -> dict[str, str]:
    ...
    return {k: str(v) for k, v in app.items()}
```

`@functools.cache` memoizes the dict **object**, not a snapshot. Three test sites do:

- `tests/test_keymaps.py:23` — `kwargs = load_builtin_app_defaults(); kwargs.update(overrides)`
- `tests/test_keybinding_footer_core.py:106` — `kwargs.update(accept_proposal="Z", show_diff="D")`
- `tests/test_keybinding_footer_core.py:132` — `kwargs.update(kill_agent="K")`

Each of these mutates the cached dict in place. Any later caller in the same Python process (i.e., the same xdist
worker) reads the polluted defaults.

`just test` and `just test-cov` both run with `pytest -n auto --dist=loadfile`. `loadfile` keeps tests within a file on
the same worker, but **multiple files can land on the same worker**. When `test_keybinding_footer_core.py` runs before
`test_keybinding_footer_status.py` on the same worker, the `kill_agent="K"` mutation leaks and the axe-bindings test
fails.

Reproduced locally:

```
$ .venv/bin/pytest tests/test_keybinding_footer_core.py tests/test_keybinding_footer_status.py
FAILED tests/test_keybinding_footer_status.py::test_keybinding_footer_axe_bindings
```

This is also why the failure is flaky in CI but typically not seen on full local runs — it depends on the worker
assignment order.

## Fix

Make `load_builtin_app_defaults()` return a fresh `dict` per call while keeping the YAML parse cached. The cleanest
shape is to push the cache one level down onto a helper that returns an immutable `MappingProxyType`, then have the
public function copy it.

```python
import functools
from types import MappingProxyType
from typing import Mapping

@functools.cache
def _builtin_app_defaults() -> Mapping[str, str]:
    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise RuntimeError("default_config.yml is not a valid YAML mapping")
    app = data.get("ace", {}).get("keymaps", {}).get("app", {})
    if not isinstance(app, dict):
        raise RuntimeError("default_config.yml missing ace.keymaps.app section")
    return MappingProxyType({k: str(v) for k, v in app.items()})


def load_builtin_app_defaults() -> dict[str, str]:
    """Load app-level keymap defaults from the bundled ``default_config.yml``.

    Returns a fresh ``dict`` per call; callers may freely mutate it.
    """
    return dict(_builtin_app_defaults())
```

Properties:

- Production hot path still avoids YAML re-parse (the perf goal of the cache from the `ace_startup_perf` work).
- Callers that mutate the returned dict can no longer corrupt shared state.
- The `MappingProxyType` makes accidental mutation of the underlying cached object fail loudly (catches future
  regressions at the source).

No changes needed at call sites; the public signature and behavior (mutability of returned dict) are preserved.

## Scope

- Edit: `src/sase/ace/tui/keymaps/loader.py` — replace `load_builtin_app_defaults()` with the two-function shape above.
- No test changes required. Existing tests that mutate the result will keep working and now serve as regression
  coverage.

## Verification

1. Reproduce the failure on master:
   `.venv/bin/pytest tests/test_keybinding_footer_core.py tests/test_keybinding_footer_status.py` → fails.
2. Apply the fix, re-run the same command → passes.
3. Run the full suite via `just check` to confirm no other call sites depended on the cached object identity.

## Out of Scope

- Auditing other `@functools.cache`-decorated functions in the repo for the same footgun. Worth a follow-up grep but not
  necessary to unblock CI.
- Adding a generic `tests/conftest.py` fixture to clear keymap caches between tests; the source-level fix removes the
  root cause and makes such a fixture unnecessary.
