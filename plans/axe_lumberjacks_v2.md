---
bead_id: sase-bta
status: done
---

# Axe Lumberjack/Chops v2: Executable Scripts + Default Config

## Context

The `sase axe` lumberjack/chops system currently uses Python functions decorated with `@register_chop` to define chops,
with hardcoded default lumberjack configuration in `src/sase/axe/config.py`. This refactoring:

1. **Converts chops to executable scripts** - Each chop becomes a subprocess-invoked script that can be defined anywhere
2. **Creates `default_config.yml`** - ALL hardcoded defaults move to a single YAML file, merged as the base layer before
   user config
3. **Removes `--exclude-decorator`** from the pyvision Justfile target

---

## Phase 1: Default Config File + Config Loading Infrastructure

**Goal**: Create `src/sase/default_config.yml` with all project defaults, and update config loading to use it as the
base layer.

### Create `src/sase/default_config.yml`

Consolidate all scattered defaults:

```yaml
axe:
  max_runners: 5
  zombie_timeout_seconds: 7200
  query: ""
  lumberjacks:
    hooks:
      interval: 1
      chops:
        - hook_checks
        - mentor_checks
        - workflow_checks
        - pending_checks_poll
        - comment_zombie_checks
        - suffix_transforms
        - orphan_cleanup
        - wait_checks
    checks:
      interval: 300
      chops:
        - cl_submitted_checks
        - stale_running_cleanup
    comments:
      interval: 60
      chops:
        - comment_checks
    housekeeping:
      interval: 3600
      chops:
        - error_digest

llm_provider:
  provider: "gemini"

vcs_provider:
  provider: "auto"
```

### Modify `src/sase/config.py`

- Add `load_default_config()` that loads `default_config.yml` via `importlib.resources.files("sase")`
- Add `list_strategy` parameter to `_deep_merge()`: `"concatenate"` (default, current behavior for overlay merges) or
  `"replace"` (for default→user merge, so user's chop lists replace defaults rather than appending)
- Update `load_merged_config()` merge chain: `default_config.yml` → `sase.yml` (replace lists) → `sase_*.yml` overlays
  (concatenate lists)

### Modify `src/sase/axe/config.py`

- Remove `_DEFAULT_JACKS` dict and `_default_lumberjacks()` function
- Simplify `load_axe_config()` — defaults are now guaranteed by the base config layer, so the fallback logic simplifies.
  Keep inline `.get("key", default)` as safety nets.

### Update tests

- `tests/test_config.py` — add tests for `load_default_config()`, 3-layer merge chain, list replace vs concatenate
  semantics
- `tests/test_axe_lumberjack_config.py` — remove refs to `_default_lumberjacks`, update fallback tests

### Verification

```bash
just test -k "test_config or test_axe_lumberjack_config"
just lint
.venv/bin/sase axe lumberjack list   # still shows 4 lumberjacks
```

---

## Phase 2: Chop Script Execution Infrastructure

**Goal**: Build the subprocess-based chop runner. Define how scripts receive context. No changes to the lumberjack
execution path yet (that's Phase 3).

### Create `src/sase/axe/chop_script_context.py`

Defines the serializable context format:

- `ChopScriptContext` dataclass with fields: `max_runners`, `zombie_timeout_seconds`, `query`, `lumberjack_name`,
  `state_dir`, `all_changespecs_file`, `filtered_changespecs_file`
- `write_chop_context(ctx, path)` — serialize context to JSON file
- `read_chop_context(path)` — deserialize from JSON
- `serialize_changespecs(changespecs, path)` — serialize `list[ChangeSpec]` to JSON via `dataclasses.asdict()`
- `load_changespecs_from_file(path)` — deserialize back to `list[ChangeSpec]` (reconstruct nested dataclasses:
  `CommitEntry`, `HookEntry`, `CommentEntry`, `MentorEntry`, etc.)

**Key files**: `src/sase/ace/changespec/models.py` defines `ChangeSpec` and all nested types. All are plain dataclasses,
so `asdict()` works for serialization. Deserialization needs manual reconstruction or a helper.

### Create `src/sase/axe/chop_script_runner.py`

Script discovery and execution:

- `discover_chop_script(name, search_dirs)` — search configured dirs for executable file named `name`, then fall back to
  `shutil.which(f"sase_chop_{name}")`
- `run_chop_script(script_path, context_file, timeout)` — invoke script as subprocess with `--context <path>` arg,
  capture stdout/stderr
- `list_chop_scripts(search_dirs)` — discover all available chop scripts for `sase axe chop list`

### Add `chop_script_dirs` to config

- `src/sase/axe/config.py` — add `chop_script_dirs: list[str]` field to `AxeConfig`, parse from config
- `src/sase/default_config.yml` — add empty `chop_script_dirs: []` to axe section

### Create tests

- `tests/test_axe_chop_script_context.py` — round-trip serialization tests for context and changespecs
- `tests/test_axe_chop_script_runner.py` — discovery tests (finds script in dir, finds on PATH, returns None for
  missing), execution tests (runs a simple script, captures output)

### Verification

```bash
just test -k "test_axe_chop_script"
just lint
```

---

## Phase 3: Convert 12 Chops to Scripts + Wire Into Lumberjack

**Goal**: Create 12 chop scripts, modify the lumberjack to invoke them as subprocesses, remove old chop registry and
chops package.

### Create 12 Python scripts in `src/sase/scripts/`

Each script follows this pattern:

1. `#!/usr/bin/env python3` shebang
2. Parse `--context <path>` CLI arg via `argparse`
3. Load context with `read_chop_context()`
4. Load changespecs with `load_changespecs_from_file()`
5. Construct its own `RunnerPool(max_runners)` and `AxeMetrics()`
6. Create a log callback that prints to stdout
7. Call the appropriate runner method
8. Exit 0 on success, non-zero on error

Scripts to create (naming: `sase_chop_<name>`):

| Script                            | Runner             | Method                                 |
| --------------------------------- | ------------------ | -------------------------------------- |
| `sase_chop_hook_checks`           | `HookJobRunner`    | `run_hook_checks(filtered)`            |
| `sase_chop_mentor_checks`         | `HookJobRunner`    | `run_mentor_checks(filtered)`          |
| `sase_chop_workflow_checks`       | `HookJobRunner`    | `run_workflow_checks(filtered)`        |
| `sase_chop_pending_checks_poll`   | `HookJobRunner`    | `run_pending_checks_poll(filtered)`    |
| `sase_chop_comment_zombie_checks` | `HookJobRunner`    | `run_comment_zombie_checks(filtered)`  |
| `sase_chop_suffix_transforms`     | `HookJobRunner`    | `run_suffix_transforms(all, filtered)` |
| `sase_chop_orphan_cleanup`        | `HookJobRunner`    | `run_orphan_cleanup(all)`              |
| `sase_chop_stale_running_cleanup` | `HookJobRunner`    | `run_stale_running_cleanup()`          |
| `sase_chop_wait_checks`           | inline logic       | scans waiting.json, writes ready.json  |
| `sase_chop_cl_submitted_checks`   | `CheckCycleRunner` | `run_full_check_cycle()`               |
| `sase_chop_comment_checks`        | `CheckCycleRunner` | `run_comment_check_cycle()`            |
| `sase_chop_error_digest`          | inline logic       | reads errors, sends notification       |

### Register as entry points

- `pyproject.toml` — add 12 `sase_chop_*` entries to `[project.scripts]`
- `src/sase/scripts/__init__.py` — add 12 wrapper functions (use `from sase.scripts.sase_chop_X import main; main()`
  pattern, not `_exec_script` since these are Python modules)

### Modify `src/sase/axe/lumberjack.py`

Rewrite `_run_tick()`:

1. Get changespecs (same as now)
2. Serialize changespecs + context to JSON files in `state_dir/tick/`
3. For each chop: `discover_chop_script()` → `run_chop_script()` → capture output → track metrics
4. Import `discover_chop_script`, `run_chop_script` from `chop_script_runner`
5. Import `serialize_changespecs`, `write_chop_context`, `ChopScriptContext` from `chop_script_context`

### Update `src/sase/axe/cli.py`

- `handle_axe_chop_list()` — use `list_chop_scripts()` instead of `list_chops()` from registry
- `handle_axe_chop_run()` — use `discover_chop_script()` + `run_chop_script()` instead of `get_chop()`

### Delete old infrastructure

- Delete entire `src/sase/axe/chops/` directory (12 modules + `__init__.py`)
- Delete or gut `src/sase/axe/chop_registry.py` — keep only `ChopContext` dataclass if anything still references it,
  remove `@register_chop`, `get_chop`, `list_chops`, `_CHOPS`, etc.

### Update tests

- `tests/test_axe_lumberjack.py` — mock `discover_chop_script` + `run_chop_script` instead of `get_chop`
- `tests/test_axe_chop_registry.py` — delete (replaced by Phase 2's script runner tests)
- `tests/test_axe_cli.py` — update for new script-based chop list/run

### Verification

```bash
just install          # re-install to register new entry points
just test
just lint
.venv/bin/sase axe chop list
.venv/bin/sase axe chop run hook_checks
timeout 5 .venv/bin/sase axe lumberjack run hooks || true
```

---

## Phase 4: Justfile Cleanup + Final Stabilization

**Goal**: Remove `--exclude-decorator` from Justfile, run full checks, fix any remaining issues.

### Modify `Justfile`

Remove `--exclude-decorator register_chop` from the `pyvision` target (lines 80-82). Change from:

```
BD_COMMAND=tools/sase_bd {{ venv_bin }}/python tools/pyvision-260225 src/sase \
    --exclude-decorator register_chop \
    {{ args }}
```

to:

```
BD_COMMAND=tools/sase_bd {{ venv_bin }}/python tools/pyvision-260225 src/sase \
    {{ args }}
```

### Final cleanup

- Remove any remaining dead imports from deleted chop modules
- Update `config/sase.schema.json` to document `lumberjacks` and `chop_script_dirs`
- Verify no remaining references to `chop_registry` functions (grep for `register_chop`, `get_chop`, `list_chops`,
  `_CHOPS`)

### Verification

```bash
just all              # fmt + lint + pylimit + pyvision + test
just check            # fmt-check + lint + test
.venv/bin/sase axe chop list
.venv/bin/sase axe lumberjack list
```

---

## Key Design Decisions

1. **List merge semantics**: `_deep_merge` gets a `list_strategy` param. Default→user merges use `"replace"` (user's
   chop lists replace defaults). Overlay merges keep `"concatenate"` (overlay metahooks append to base).

2. **Context passing**: Lumberjack writes a JSON context file to `state_dir/tick/context.json` with changespecs in
   separate files. Scripts receive `--context <path>` arg.

3. **Script discovery**: Search configured `chop_script_dirs` first, then `shutil.which("sase_chop_<name>")` for
   PATH-installed scripts.

4. **`default_config.yml` location**: Lives at `src/sase/default_config.yml` (inside the package, accessible via
   `importlib.resources`). It's inside the source tree so it's automatically included in the wheel.

5. **Non-serializable context**: Scripts construct their own `RunnerPool`, `AxeMetrics`, and log callback. Lumberjack
   tracks metrics externally via exit codes.

## Phase Dependencies

```
Phase 1 → Phase 2 → Phase 3 → Phase 4
```
