---
create_time: 2026-07-02 05:55:40
status: done
prompt: sdd/prompts/202607/fix_config_schema_wheel_packaging.md
---
# Fix Config Center schema-load error on wheel installs (uv tool install)

## Problem

The "Config" tab of the SASE Admin Center TUI panel fails with:

```
Could not load configuration:
could not load config schema at
/Users/bbugyi/.local/share/uv/tools/sase/lib/python3.12/config/sase.schema.json:
[Errno 2] No such file or directory
```

This happens only on machines where sase is installed as a wheel (`uv tool install sase`, per the newly-recommended
INSTALL.md flow). Dev machines using editable installs (`just install`) are unaffected, which is why the bug was
invisible until now.

## Root Cause (two compounding defects)

1. **The schema is not packaged.** The canonical schema lives at repo root `config/sase.schema.json`, _outside_ the
   `sase` package. The build config in `pyproject.toml` ships only the package
   (`[tool.hatch.build.targets.wheel] packages = ["src/sase"]`; sdist `only-include = ["src/sase"]`), so no wheel
   install has ever contained the schema file.

2. **Path resolution assumes a source checkout.** Both consumers resolve the schema as
   `importlib.resources.files("sase") / ".." / ".." / "config" / "sase.schema.json"`:
   - `_config_schema_path()` in `src/sase/config/inventory.py` (feeds `load_config_schema()`, which the Config Center
     panel calls), and
   - the `sase path config-schema` subcommand in `src/sase/main/entry.py`.

   In an editable install, `files("sase")` is `<repo>/src/sase`, so `../..` lands on the repo root and the file is
   found. In a wheel install, `files("sase")` is `<venv>/lib/python3.12/site-packages/sase`, so `../..` resolves to
   `<venv>/lib/python3.12/` — producing exactly the broken `.../lib/python3.12/config/sase.schema.json` path from the
   error message.

No other code consumers exist (verified by grep across `src/`); no chezmoi config or user `sase.yml` embeds the old
absolute path either. The `~/.config/sase/sase.schema.json` path mentioned in `docs/vcs.md` has no code behind it (stale
doc).

## Fix: ship the schema inside the package

Follow the existing precedent for bundled resources: the xprompt schemas (`workflow.schema.json`,
`xprompts.schema.json`) live _inside_ the package and are resolved via `get_sase_package_xprompts_dir()` using
`importlib.resources.files("sase")`, which works "for both wheel and editable installs" (its own docstring). Apply the
same pattern to the config schema.

### 1. Move the schema into the package

- `git mv config/sase.schema.json src/sase/config/sase.schema.json` (the `src/sase/config/` Python package already
  exists; hatchling includes non-Python files inside the package by default, and the sdist `only-include = ["src/sase"]`
  covers it automatically).
- Remove the now-empty repo-root `config/` directory (the schema is its only content). No symlink back-compat shim is
  needed: no external references to the old path were found in chezmoi, user config, or editor headers, and
  `sase path config-schema` consumers resolve the path dynamically.

### 2. Update the two resolvers

- `src/sase/config/inventory.py` — `_config_schema_path()` becomes
  `importlib.resources.files("sase") / "config" / "sase.schema.json"` (no `..` traversal). Update its docstring and the
  `build_config_inventory()` docstring reference to the new location.
- `src/sase/main/entry.py` — the `sase path config-schema` branch uses the same package-relative resolution (consider
  sharing `_config_schema_path()` from `sase.config.inventory` — or a small public accessor — instead of duplicating the
  logic in both places, since divergence is what let this bug hide).

### 3. Update references to the old path

- `tests/test_config_schema.py` — 10 occurrences of `REPO_ROOT / "config/sase.schema.json"` → the new in-package path
  (or, better, load through the production resolver so the tests exercise it).
- `sase.yml` — the `config_schema_sync` mentor focus description references `config/sase.schema.json`; update to
  `src/sase/config/sase.schema.json`.
- `docs/configuration.md` — "Source: ... `config/sase.schema.json`" line.
- `docs/vcs.md` — replace the stale `~/.config/sase/sase.schema.json` claim with the real resolution
  (`sase path config-schema`).
- Sweep `rg -n "config/sase.schema.json"` across `src/`, `tests/`, `docs/`, and repo-root configs for stragglers
  (historical `sdd/` documents stay untouched).

### 4. Regression coverage

Add a test asserting that the production resolver finds the schema _inside_ the installed `sase` package:
`_config_schema_path()` (or its public wrapper) must exist, parse as JSON, and be a descendant of
`Path(importlib.resources.files("sase"))`. This fails on any future regression to parent-relative traversal and
simultaneously guarantees the file ships wherever the package does — no slow wheel-build test needed.

## Explicitly out of scope

- No Rust core (`sase-core`) changes: schema JSON loading is deliberately Python-side file IO per the `inventory.py`
  module docstring; the Rust side receives the already-loaded schema document over the wire.
- No changes to xprompt schema handling (already correct).
- Sibling repos (sase-github, sase-telegram, sase-nvim) do not consume this schema path.

## Verification

1. `just install` then `just check` (note: full-suite runs can be killed by the sandbox; fall back to static gates plus
   targeted `pytest tests/test_config_schema.py tests/test_config_inventory.py` and the new regression test if that
   happens).
2. `sase path config-schema` prints an existing in-package path.
3. Build a wheel (`uv build`) and confirm `sase/config/sase.schema.json` is in the archive
   (`unzip -l dist/*.whl | grep schema`); this validates the packaging half of the fix without waiting for a release.
4. Final confirmation on the MacBook after the next release: `uv tool upgrade sase`, open the Admin Center Config tab.
