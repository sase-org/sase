---
create_time: 2026-04-24 09:10:26
status: done
prompt: sdd/prompts/202604/tui_activity_tmp_race.md
---
# Plan: Fix cross-process race in `tui_activity` atomic writes + isolate TUI tests from `~/.sase/`

## Goal

`just test-cov` intermittently fails with `tests/test_ace_tui_app.py::test_navigation_next_key -- assert 0 == 1`. The
root cause is a cross-process race in the "atomic" file-writers in `src/sase/ace/tui_activity.py`: all writers use a
fixed tmp filename (`<final>.tmp`) and `os.replace(tmp, final)`, so concurrent xdist workers clobber each other's tmp
file and one of them hits `FileNotFoundError` from inside `AceApp.on_mount()`. When that exception surfaces mid-mount,
the Textual event loop is left in an inconsistent state; depending on timing, the reported symptom is either a raw
`FileNotFoundError` or a silent failure where `press("j")` no longer drives a navigation increment.

This plan fixes the underlying production bug (two real sase ace sessions started in the same second would race the same
way) and separately isolates the TUI tests from the developer's real `~/.sase/` directory.

## Root cause (verified)

`AceApp.on_mount()` (`src/sase/ace/tui/app.py:511`) calls five writers that all follow the same unsafe pattern:

```python
tmp = FINAL.with_suffix(".tmp")   # e.g. ~/.sase/tui_pid.tmp — shared across processes
tmp.write_text(...)
os.replace(tmp, FINAL)            # fails with FileNotFoundError if another process already replaced tmp
```

The five affected writers in `src/sase/ace/tui_activity.py`:

| Function                   | Line | Final path                  |
| -------------------------- | ---- | --------------------------- |
| `write_activity_timestamp` | 33   | `~/.sase/tui_last_activity` |
| `write_last_keypress`      | 45   | `~/.sase/tui_last_keypress` |
| `write_tui_pid`            | 76   | `~/.sase/tui_pid`           |
| `write_idle_state`         | 95   | `~/.sase/tui_idle_state`    |
| `write_pinned_idle`        | 124  | `~/.sase/tui_pinned_idle`   |

Reproducer (smaller parallel subset than the full suite):

```
uv run pytest tests/test_ace_tui_app.py tests/test_keymaps_e2e.py \
              tests/test_ace_testing.py tests/test_ace_tui_widgets.py -n auto
```

yields the raw race directly:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '/home/bryan/.sase/tui_pid.tmp' -> '/home/bryan/.sase/tui_pid'
  File "src/sase/ace/tui_activity.py", line 84, in write_tui_pid
  File "src/sase/ace/tui/app.py", line 560, in on_mount
```

In the full 4485-test run, the same race occasionally presents as `assert 0 == 1` in `test_navigation_next_key` because
the mid-mount exception leaves the Textual app partially initialized — the pre-exception `_load_changespecs()` call
already populated `changespecs` (so `idx == 0` passes), but the post-exception binding/activity state is inconsistent,
and the `j` press does not drive the increment.

Separately: TUI tests write to the developer's real `~/.sase/` directory on every test run because no autouse fixture
redirects `Path.home() / ".sase"`. `tests/conftest.py:17` defines a `redirect_sase_home()` helper but it is only opt-in.

## Design

Do both fixes. They address distinct concerns and compose cleanly:

- **Fix A** — per-process-unique tmp filenames in `tui_activity.py`. This is the real production bug: two concurrent
  `sase ace` invocations on the same machine would race the same way. Fixing it removes the race for tests _and_
  production.
- **Fix B** — autouse fixture in `tests/conftest.py` that redirects `~/.sase/` to `tmp_path` for every test that
  instantiates `AcePage` / `AceApp`. Even after Fix A, tests still pollute the developer's real `~/.sase/` (saved
  queries, last selection, query history, dismissed agents, etc.) and can cross-contaminate each other through shared
  state. Isolating them is worth doing regardless.

Sequencing: land Fix A first (tiny, local, zero blast radius) and confirm the flake is gone. Then land Fix B (touches
test infrastructure, may surface other tests that implicitly depend on developer state).

### Why not just redirect `~/.sase/` (Fix B alone)?

Fix B would paper over the race in tests but leave the production race unaddressed. The race is not hypothetical — a
user who opens two `sase ace` windows at the same time (or starts one immediately after another crashes) can hit it.
Fixing it at the source in `tui_activity.py` is a ~10-line change.

### Why not only per-process tmp names (Fix A alone)?

Fix A removes the race but tests still mutate real developer state. Symptoms we've seen downstream:

- `~/.sase/last_selection.txt` contains a name from a previous real session and feeds back into
  `_restore_last_selection()` during tests.
- Tests can leak state into each other through `~/.sase/last_query.txt`, `saved_queries.json`, `query_history.json`,
  `query_selections.json`, `tui_pinned_idle`, etc.

Fix B pins tests down to a clean per-test `~/.sase/`.

## Phases

### Phase 1 — Fix A: per-process-unique tmp filenames in `tui_activity.py`

**File to modify**

- `src/sase/ace/tui_activity.py`

**What to change**

Replace the five occurrences of `tmp = FINAL.with_suffix(".tmp")` with a per-process-unique tmp name. Two viable
implementations, pick one:

1. Embed PID: `tmp = FINAL.with_suffix(f".{os.getpid()}.tmp")`. Simple, readable, good enough — PID uniquely identifies
   the writer for the duration of any one TUI session. (If we ever had in-process concurrent writers to the same file,
   PID alone wouldn't suffice — but we don't; each writer is called synchronously from the single- threaded asyncio
   loop.)
2. Use `tempfile.mkstemp(prefix=FINAL.name + ".", suffix=".tmp", dir=FINAL.parent)` and then `os.replace`. More
   defensive, slightly more ceremony.

**Recommendation**: option 1 (PID suffix). It's a one-line change per writer, it keeps the tmp file's parent directory
clean, and it preserves the current code shape.

Apply the same change to all five writers at lines 40, 54, 82, 103, and 130.

**Tests**

Add a regression test to `tests/test_tui_activity.py` that spawns two threads/processes both calling `write_tui_pid()` N
times and asserts no `FileNotFoundError` surfaces. A cheap version: run two concurrent `threading.Thread`s each calling
`write_tui_pid()` 200 times; assert all calls succeeded. (Thread-level concurrency is enough to demonstrate the fix
because the bug is tmp-filename collision, independent of process vs thread.)

### Phase 2 — Validate

Run the smaller reproducer and the full suite:

```
uv run pytest tests/test_ace_tui_app.py tests/test_keymaps_e2e.py \
              tests/test_ace_testing.py tests/test_ace_tui_widgets.py -n auto
just check
```

The `FileNotFoundError` traces should be gone; `test_navigation_next_key` should pass reliably.

If `just check` is still flaky after Phase 1, investigate additional non-atomic writers — the `~/.sase/` tree has other
state files (`query_history.json`, `saved_queries.json`, etc.) that are written with plain `write_text` and could also
race. But those are less likely to cause hard failures because their readers tolerate `JSONDecodeError` and missing
files. We only fix them if Phase 1 doesn't fully resolve the flake.

### Phase 3 — Fix B: autouse `~/.sase/` redirect for TUI tests

**File to modify**

- `tests/conftest.py`

**What to add**

An autouse fixture (global) that applies `redirect_sase_home(monkeypatch, tmp_path)` before each test. Global is
preferable to per-file because:

- The four test files that instantiate `AcePage` (`test_ace_tui_app.py`, `test_ace_testing.py`,
  `test_ace_tui_widgets.py`, `test_keymaps_e2e.py`) aren't the only ones that touch `~/.sase/`; any test that imports
  code that reads `last_query.txt`, `saved_queries.json`, etc. is affected.
- The existing `redirect_sase_home()` helper uses `monkeypatch.setattr(Path, "expanduser", _fake)` and only rewrites
  `~/.sase/` — other home-relative paths (`~/.config/sase/`, `~/.gemini/`, etc.) are untouched. Blast radius is narrow.

**Important caveats to validate during implementation**

- Some existing tests in `test_tui_activity.py` and `test_last_selection.py` already patch these paths explicitly. The
  autouse redirect should be compatible with those (monkeypatch ordering: autouse fixture runs first, test's own `patch`
  runs second, test's `patch` wins for the duration of the `with` block).
- A few tests may have been silently relying on developer state (e.g. a saved query in slot 1). Those will surface as
  new failures and should be fixed to set up their own fixtures — they're latent bugs, not regressions caused by the
  redirect.
- Confirm `redirect_sase_home` is compatible with `tmp_path` (pytest builtin, per-test tmpdir). If pytest's autouse
  - `tmp_path` + `monkeypatch` combination has any ordering quirks, document them in the fixture.

**Sketch**

```python
@pytest.fixture(autouse=True)
def _isolate_sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect ~/.sase/ to a per-test tmpdir so tests never touch real state."""
    redirect_sase_home(monkeypatch, tmp_path / "sase_home")
```

### Phase 4 — Validate end-to-end

- `just check` (full suite with coverage gate) passes reliably across at least 3 consecutive runs.
- No test writes to the real `~/.sase/` — spot-check by deleting a file there before running tests and confirming it
  stays deleted.
- No regressions in test duration (the redirect is cheap: just changes a Path method).

## Out of scope

- Fixing other non-atomic writers outside `tui_activity.py` (revisit only if Phase 1 doesn't fully resolve the flake).
- Rethinking `~/.sase/` layout or moving state to a different location.
- Converting more TUI tests to polling-based `expect_state` instead of direct `assert`. The direct-assert tests are not
  wrong — `pilot.press` does flush pending messages — and the flake resolves once the mount-time exception is
  eliminated.

## Risk

- **Low** for Phase 1: five-line change, localized, thread/process-concurrency regression test proves the fix.
- **Medium** for Phase 3: autouse fixture with global scope. Risk of surfacing latent test dependencies on developer
  state. Mitigation: land Phase 1 separately so the flake is fixed even if Phase 3 needs iteration.

## Acceptance criteria

- `test_navigation_next_key` passes reliably (≥ 5 consecutive full-suite runs).
- No `FileNotFoundError` from `tui_activity.py` anywhere in CI logs.
- `~/.sase/` is untouched after running the full test suite (Phase 3).
- New regression test in `test_tui_activity.py` for concurrent writers passes.
