---
create_time: 2026-05-27 13:54:28
status: done
prompt: sdd/prompts/202605/sase_home_path_isolation.md
---
# Fix SASE Home Path Isolation

## Context

The `just_check_speed_research.md` note identifies a correctness and performance bug in test isolation: tests intend to
redirect `~/.sase` to temp state, but many production call sites use `Path.home() / ".sase"` directly. Those call sites
bypass the current `tests/conftest.py::redirect_sase_home()` implementation, which only patches `Path.expanduser()` and
`os.path.expanduser()` for `~/.sase` strings.

The hottest current impact is the agent-name registry. Launch-path tests repeatedly call `load_name_registry()`, which
rebuilds from the live `~/.sase/projects` tree when no isolated registry exists. On this machine, the live tree is large
enough to dominate `just test`.

This plan fixes the isolation issue without changing the semantics of SASE state locations for normal users.

## Goals

- Ensure tests never read or write the developer's real `~/.sase` state unless an individual test explicitly opts into a
  real path.
- Make `SASE_HOME` the canonical override for SASE state roots.
- Replace direct `Path.home() / ".sase"` path construction in the high-impact and import-time call sites with a shared
  helper.
- Preserve existing tests that patch module-level path constants where possible, and migrate those tests only where lazy
  accessors make the old patch target obsolete.
- Add regression coverage that fails if the agent-name registry escapes the isolated SASE home.
- Verify with targeted tests first, then `just check` after implementation changes.

## Non-Goals

- Do not parallelize `just check` stages in this change.
- Do not change user-facing SASE directory defaults. With no `SASE_HOME`, the default remains `Path.home() / ".sase"`.
- Do not migrate every display-only use of `Path.home()` that merely shortens paths to `~`.
- Do not move backend domain behavior into Rust for this task. This is Python process-local path resolution and test
  isolation glue, not shared domain logic.

## Design

### Canonical SASE Home Helper

Add a canonical helper in `src/sase/core/paths.py`:

```python
def sase_home() -> Path:
    return Path(os.environ.get("SASE_HOME") or Path.home() / ".sase").expanduser()
```

Add small companion helpers if they reduce duplication without creating churn:

```python
def sase_subdir(subdir: str) -> Path:
    return sase_home() / subdir

def sase_projects_dir() -> Path:
    return sase_home() / "projects"
```

Update existing `get_sase_directory()`, `ensure_sase_directory()`, and the private `_sase_subdir()` used by sharded
paths to use this helper so `SASE_HOME` covers plan/history/sharded writes too.

Then update the existing mobile helper definitions in `src/sase/integrations/_mobile_agent_paths.py` and
`src/sase/integrations/_mobile_helper_common.py` to delegate to `sase.core.paths.sase_home()` rather than maintaining
duplicate implementations.

### Test Isolation Fixture

Preserve the current public contract of `tests.conftest.redirect_sase_home(monkeypatch, home)`: callers pass the
directory that should behave as `~/.sase`, and the helper returns that directory.

Enhance it to:

- Capture the ambient `HOME` before any helper changes.
- Create the passed SASE home directory.
- Set `SASE_HOME` to the passed directory.
- Set `HOME` when the passed directory can naturally be represented as `HOME/.sase`, most importantly when the autouse
  fixture passes `<fake_home>/.sase`.
- Keep the existing `expanduser()` patch as compatibility for code still using literal `~/.sase`.

Change the autouse fixture to create a fake user home and pass its `.sase` child:

```python
fake_home = tmp_path_factory.mktemp("home")
redirect_sase_home(monkeypatch, fake_home / ".sase")
```

That makes `Path.home() / ".sase"` and `sase_home()` converge for ordinary tests.

For tests that call `redirect_sase_home()` with an arbitrary path that is not named `.sase`, `SASE_HOME` and the
expanduser patch remain authoritative for migrated code. If any remaining raw `Path.home() / ".sase"` caller matters to
those tests, either migrate that caller or adjust the test to pass `<tmp_path>/.sase`.

### Migration Priority

Migrate in focused batches:

1. Agent-name registry and adjacent name modules.
   - `src/sase/agent/names/_registry.py`
   - `_lookup.py`, `_claim.py`, `_auto.py`, `_resume.py`, `_wipe.py`, `_migration.py` as needed where they resolve
     `~/.sase/projects`, dismissed bundles, lock files, or history files.

2. Import-time path constants that freeze `Path.home()` before fixtures can run.
   - `src/sase/history/{prompt,command,hook,file_references}.py`
   - `src/sase/integrations/chat_install.py`
   - High-risk top-level constants such as `notifications/pending_actions.py`, `axe/state.py`, and frequently patched
     ACE state/history files.

3. Shared core path utilities and sharded `~/.sase` paths.
   - `src/sase/core/paths.py`
   - callers that use `get_sase_directory()`, `sharded_path()`, `find_sharded_file()`, and `iter_sharded_files()`.

4. Remaining runtime `Path.home() / ".sase"` call sites that can affect tests or real state writes.
   - Workspace provider project roots, memory read/proposal paths, notifications, bead project resolution, and TUI
     loaders.

Do not mechanically change `Path.home()` uses for `.config/sase`, `.codex`, `.cache`, display shortening, or generic
user-home behavior unless they are part of SASE state isolation.

### Lazy Accessors for Former Constants

Where modules currently expose constants such as `_PROMPT_HISTORY_FILE`, prefer a low-churn compatibility pattern:

```python
_PROMPT_HISTORY_FILE: Path | None = None

def _prompt_history_file() -> Path:
    return _PROMPT_HISTORY_FILE or sase_home() / "prompt_history.json"
```

Then update module internals to call the accessor. Existing tests that patch `_PROMPT_HISTORY_FILE` keep working, while
the default path becomes lazy and honors `SASE_HOME`.

For grouped constants, use base-dir accessors:

```python
_STATE_DIR: Path | None = None

def _state_dir() -> Path:
    return _STATE_DIR or sase_home() / "chat_install"
```

Then derive `_log_dir()`, `_jobs_dir()`, and `_lock_path()` from `_state_dir()` lazily. This avoids import-time capture
while preserving the existing patch target.

## Tests

Add focused regression tests before relying on full-suite timing:

- A `tests/test_sase_home_isolation.py` test for `sase.core.paths.sase_home()`:
  - honors `SASE_HOME`
  - defaults to `Path.home() / ".sase"` when `SASE_HOME` is absent
  - `get_sase_directory()` and `sharded_path()` stay under `SASE_HOME`

- A `tests/agent/names/test_registry_home_isolation.py` or nearby test that:
  - creates fake real-home state and isolated SASE home state
  - sets `SASE_HOME` to the isolated path
  - verifies `_registry_path()`, `_source_signature_paths()`, and a registry load/rebuild stay under the isolated path

- A conftest behavior test or targeted existing test update that verifies the autouse fixture makes
  `Path.home() / ".sase"` differ from the real developer home during tests.

- Keep or adjust existing tests that patch module constants after converting constants to lazy accessors.

## Validation

Run a staged validation sequence:

1. `just install` if the workspace venv is stale or dependencies are missing.
2. Targeted tests:
   - `just test tests/test_sase_home_isolation.py`
   - `just test tests/agent/names` or the closest existing agent-name test module
   - representative launch tests from the research hotspot, especially `tests/test_cd_launch_from_cwd.py`
   - representative history/chat-install tests that patch former constants
3. Search guard:
   - `rg 'Path\.home\(\) / "\.sase"' src/sase`
   - remaining matches must be intentional and documented in the final summary if not migrated.
4. Full validation:
   - `just check`

If `just check` fails because tests depended on real home state, triage those tests by making their fixtures create the
needed state under the isolated home. Do not weaken the isolation fixture to accommodate hidden real-home dependencies.

## Risks

- Some tests may have implicitly depended on the developer's real `~/.sase` contents. The fix should surface those
  tests; they need local fixture setup.
- Changing import-time constants to accessors can break tests that patch exact constants. The compatibility
  `Path | None` pattern reduces this risk.
- A broad mechanical migration could touch too much code at once. Keep the first implementation centered on the
  registry, import-time constants, and shared path utilities, then migrate remaining runtime call sites as
  straightforward follow-up within the same change if tests stay green.
- Setting `HOME` globally in tests can affect tests for non-SASE home behavior. The plan limits the autouse fixture to a
  fake home whose `.sase` path is isolated and relies on existing per-test monkeypatches to override `HOME` where a test
  needs a specific value.

## Rollback

The rollback path is straightforward:

- Revert the conftest `HOME`/`SASE_HOME` additions if they cause broad unrelated failures.
- Keep the `sase_home()` helper if introduced and only revert migrated call sites that caused regressions.
- The registry migration can be reverted independently from history/chat-install migrations because the helper has no
  side effects without `SASE_HOME`.
