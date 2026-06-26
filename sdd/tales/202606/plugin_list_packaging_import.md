---
create_time: 2026-06-26 08:46:56
status: done
prompt: sdd/prompts/202606/plugin_list_packaging_import.md
---
# Plan: Fix `sase plugin list` crash when `packaging` is absent

## Problem

`sase plugin list` crashes before it can render anything:

```text
ModuleNotFoundError: No module named 'packaging'
```

The installed executable is a `uv tool` environment at `~/.local/share/uv/tools/sase`, but it imports editable source
from `/home/bryan/projects/github/sase-org/sase`. That source now imports `packaging.version` from
`sase.plugins.latest`, while the tool environment's installed `sase` metadata predates the new dependency and does not
include `packaging`.

The repo has already been updated correctly at the packaging level: `pyproject.toml` and `uv.lock` both include
`packaging`. The remaining product bug is resilience: latest-version enrichment is best-effort, but its eager import
path can prevent the read-only catalog command from starting at all.

## Proposed Fix

Keep `packaging` as a declared runtime dependency because PEP 440 comparison is the correct behavior when the
environment is consistent.

Make `sase.plugins.latest.is_newer()` import `packaging.version` lazily inside the comparison function. If `packaging`
is unavailable, return `False` conservatively so SASE does not claim an update is available without a valid PEP 440
comparison. Invalid version strings should continue to degrade to `False`.

This keeps `sase.plugins.latest`, `sase.plugins.catalog`, `sase plugin list`, and `sase plugin show` importable in a
stale editable tool environment. The latest-version lookup may still populate `latest.version`, but the update arrow and
update count are suppressed until the environment is reinstalled or upgraded.

## Tests

Add a focused unit test for the missing dependency path by monkeypatching import behavior around `is_newer()` and
asserting it returns `False` instead of raising.

Run targeted plugin tests first:

```bash
just install
just test tests/test_plugin_latest.py tests/test_plugin_cli_list.py tests/test_plugin_cli_show.py tests/test_plugin_catalog.py
```

Because implementation files will change, run the required full check before finishing:

```bash
just check
```

Also verify the originally failing command. If the global `sase` executable still points at the editable checkout with
stale metadata, it should no longer crash after the lazy import fix is present in that checkout; in this workspace,
verify the same command through the workspace venv:

```bash
.venv/bin/sase plugin list --offline
```

## Risks

The fallback can hide update indicators in a stale or broken Python environment, but that is preferable to breaking the
catalog command. A normal install still uses `packaging` and preserves exact PEP 440 behavior.
