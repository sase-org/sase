---
create_time: 2026-06-19 08:58:02
status: done
prompt: sdd/prompts/202606/project_creation_logging.md
---
# Plan: Diagnostic logging for SASE project-file creation

## Problem & motivation

A `bob` SASE project keeps getting (re)created and collides with the `bob` **alias** that the `bob-cli` project owns.
Once a real `bob` project exists, `load_project_alias_map()` rejects `PROJECT_ALIASES: bob` on `bob-cli` (an alias may
not equal a real project name), breaking alias resolution until the stray `bob` project is deleted.

### Root cause (already traced)

- `/home/bryan/bob` is the Obsidian vault — its **own** git repo (`git@github.com:bbugyi200/bob.git`), distinct from
  `bob-cli` (`github.com/bbugyi200/bob-cli`).
- `get_workspace_name("/home/bryan/bob")` returns `"bob"` from the remote basename.
- The `home` project registers the vault as the `obsidian` sibling (`workspace_strategy: none`), so `home`-project
  agents edit and **commit directly inside `/home/bryan/bob`**. `build_commit_details()` runs per sibling dir and
  instructs a commit there.
- At commit time the project is resolved purely from the cwd, with **no alias resolution and no guard**, via
  `get_project_from_workspace()` (`src/sase/workflows/utils.py:39`) → `create_project_file("bob")` (called from
  `compute_suffixed_cl_name` / `add_changespec_to_project_file` in
  `src/sase/workflows/commit/changespec_operations.py`).
- A prior June 15 fix (`5bc999d04`, "stop creating CWD project on bare sase run") only guarded the **launch /
  `sase run`** path (`create_missing=False` in `ensure_project_file_and_get_workspace_num`). It did **not** touch the
  **commit path**, which is the leading suspect for the continued recurrence.

### Why logging (not a blind fix) now

The mechanism is understood, but no instrument records _which_ invocation fires each time, and project specs are not
git-tracked, so there is no history to inspect. A prior "confident fix" already failed to stop the recurrence. The
robust move is to instrument the **single chokepoint every creation path funnels through**, so the next occurrence names
the exact culprit (commit vs launch vs ace vs bead) with a full stack trace. **This change is logging-only — no behavior
change** to project creation/resolution. A real fix (resolve the alias before creating, or record sibling commits under
the launching project) is a deliberate follow-up, out of scope here.

## Scope

- **In scope:** durable, best-effort diagnostic logging emitted whenever a brand-new project ProjectSpec file is created
  via `create_project_file()`, plus an explicit warning for the harmful alias-collision case.
- **Out of scope:** changing how the project name is resolved; fixing the commit path; the secondary sibling-spec
  creation path in `workspace_handler_context` (noted below as optional follow-up).

## Design

### 1. New module: `src/sase/logs/project_creation_log.py`

Model it directly on the existing `src/sase/logs/launch_log.py` (same conventions: `fcntl`-locked append,
`sase_subdir("logs")` for the canonical dir, module-level path overrides for tests, `get_timezone()` timestamps, "never
raises" contract).

Public surface:

- `project_creation_log_path() -> Path` → `~/.sase/logs/project_creation.log` (human-readable block per creation).
- `project_creation_jsonl_path() -> Path` → `~/.sase/logs/project_creation.jsonl` (one structured record per creation;
  machine-readable).
- Module-level overrides `LOGS_DIR`, `PROJECT_CREATION_LOG`, `PROJECT_CREATION_JSONL` (mirrors `launch_log`) so tests
  can redirect if needed — though the autouse `_isolate_sase_home` fixture already redirects `SASE_HOME`, so
  `sase_subdir("logs")` lands in tmp automatically.
- `log_project_creation(*, project: str, project_file: str) -> None` — the entry point. Wrapped in `try/except` that
  swallows everything and surfaces via the module logger (`log.warning(..., exc_info=True)`), exactly like
  `log_launch_failure`.

Record fields (captured inside the logger, all best-effort):

- `timestamp` — `get_timezone()`-aware, same `%y%m%d_%H%M%S` (jsonl) / `%Y-%m-%d %H:%M:%S %Z` (human) formatting as
  `launch_log`.
- `project` — the name being created.
- `project_file` — destination path.
- `cwd` — `os.getcwd()`.
- `resolved_workspace_name` — best-effort `get_workspace_name(os.getcwd())` (imported lazily from
  `sase.workspace_provider`; `None` on any error). This is the field that will show `bob` and prove the vault-cwd
  theory.
- `alias_conflict` (bool) + `alias_conflict_owner` (str | None) — whether the new `project` name collides with an
  existing project **alias**, and which project owns that alias. See §3 for how to compute this without tripping over
  the already-broken alias map.
- `argv` — `list(sys.argv)` (identifies `sase commit` vs `sase run` vs ace).
- `sase_env` — subset of `os.environ` whose keys start with `SASE_` (e.g. `SASE_COMMIT_METHOD`, `SASE_BEAD_ID`,
  `SASE_HOME`), to disambiguate the invocation context.
- `stack` — `"".join(traceback.format_stack())` (excluding the logger frame). This is the decisive field: it shows the
  full call path (commit → `compute_suffixed_cl_name` → `create_project_file`, vs the launch/ace paths).

Human-readable block mirrors `_append_human_block`: a `=`\*72 separator, a header line with timestamp + project + a
`⚠ ALIAS CONFLICT with <owner>` marker when applicable, the scalar fields, then an indented `stack:` dump.

### 2. Hook the chokepoint: `create_project_file()`

In `src/sase/workflows/commit/project_file_utils.py`, inside the existing `if not os.path.isfile(project_file):` branch,
**after** the successful `write_changespec_atomic(...)` (so we only log genuinely new files, never already-existing
ones), call:

```python
from sase.logs.project_creation_log import log_project_creation
log_project_creation(project=project, project_file=project_file)
```

The call is itself best-effort (the logger never raises), but keep it positioned so a logging regression can never
affect the return value. No other call sites change — `create_project_file` is the single function that
`compute_suffixed_cl_name`, `add_changespec_to_project_file`, `ensure_project_file_and_get_workspace_num`, and the ace
`_prompt_bar_mount` path all route through.

### 3. Alias-collision detection (the harmful-case signal)

The whole point is to flag when the created name shadows an existing alias. Do **not** call `load_project_alias_map()`
directly to decide this: once the `bob` project file exists on disk, that function raises `ValueError` (alias equals
real project). Compute the answer defensively instead:

- Read project records via `list_project_records(sase_projects_dir(), "all", include_home=False)` (same source
  `project_aliases` uses).
- Build `alias -> owning_project` by iterating non-system records **other than the one being created**, collecting each
  record's `aliases`.
- If `project` appears as a key, set `alias_conflict=True` and `alias_conflict_owner` to that project (e.g. `bob-cli`).
- Any exception → `alias_conflict=None`, logged but ignored.

When `alias_conflict` is true, **also** emit a user-visible warning at creation time via the existing
`print_status(...)` helper, e.g.:

```
print_status(
    f"Created project {project!r}, which collides with an alias owned by "
    f"{owner!r}; this will break alias resolution. See "
    f"~/.sase/logs/project_creation.log.",
    "warning",
)
```

This makes the bad event observable immediately, not just post-hoc in the log. Keep this warning inside the same
best-effort guard so it never breaks creation.

### 4. Re-export (optional, for consistency)

Add `project_creation_log_path`, `project_creation_jsonl_path`, and `log_project_creation` to
`src/sase/logs/__init__.py` alongside the existing `launch_log` / `run_log` re-exports, so the new log is discoverable
with the others.

## Tests

New `tests/logs/test_project_creation_log.py` (mirrors `tests/logs/test_launch_log.py`; relies on the autouse
`_isolate_sase_home` fixture):

- `log_project_creation(project="bob", project_file=...)` writes **both** `project_creation.jsonl` and
  `project_creation.log`.
- JSONL record contains the expected fields: `project == "bob"`, a non-empty `stack`, `cwd`, `argv`, and `sase_env`
  present.
- Alias-conflict path: seed a `bob-cli` ProjectSpec with `PROJECT_ALIASES: bob` under the isolated projects dir, then
  log creation of `project="bob"`; assert the record has `alias_conflict is True` and
  `alias_conflict_owner == "bob-cli"`.
- No-conflict path: logging `project="bob-cli"` (or any non-aliased name) yields `alias_conflict` falsey.
- Robustness: monkeypatch the internal append helper to raise and assert `log_project_creation(...)` does **not**
  propagate (logging must never break a caller).

Extend project-file-utils coverage (e.g. in `tests/test_changespec_suffix_operations.py` or a small new test): with the
projects dir isolated, call `create_project_file("newproj")` and assert `project_creation_log_path()` now exists; call
it again for the same project and assert no second record is appended (the already-exists branch must not log).

## Files touched

- **New:** `src/sase/logs/project_creation_log.py` (logger, modeled on `launch_log.py`).
- **Edit:** `src/sase/workflows/commit/project_file_utils.py` (call logger + warning in the new-file branch; best-effort
  guarded).
- **Edit (optional):** `src/sase/logs/__init__.py` (re-export the new helpers).
- **New:** `tests/logs/test_project_creation_log.py`.
- **Edit:** an existing project-file-utils test module for the create/no-recreate assertion.

## Validation

- `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + tests) per repo policy.
- Manually confirm shape: in an isolated `SASE_HOME`, create a project file and inspect
  `~/.sase/logs/project_creation.{log,jsonl}` for a populated stack + fields.

## Follow-ups (not in this plan)

- The actual fix for the recurrence: make the commit path resolve the project through the alias map (or record sibling
  commits under the launching `home` project / a dedicated `obsidian` project) so committing inside `/home/bryan/bob`
  stops materializing a `bob` project. The new log will confirm this path before we change it.
- Optional: extend the same logging to the secondary spec-creation path `_ensure_sibling_project_spec` in
  `src/sase/main/workspace_handler_context.py`, which writes a ProjectSpec without going through `create_project_file`.
