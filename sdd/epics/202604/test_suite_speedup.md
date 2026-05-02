---
create_time: 2026-04-23 20:32:20
status: done
bead_id: sase-l
prompt: sdd/prompts/202604/test_suite_speedup.md
---
# Speed up `just test` — Implementation Plan

Research source: `sdd/research/202604/test_suite_speedup.md` (commit `43741c5e`).

Implement options **A** (turn on `pytest-xdist` by default), **B** (split test vs test-cov, move coverage out of
`addopts`), and **C** (fix the slow tests in `tests/test_agent_launch_repeat.py`). Target outcome per the research:
`just test` goes from ~6 minutes → ~15 seconds (~24× faster).

## Constraints

- **Override knob required**: users must have an easy way to fall back to defaults (serial, with coverage) from a `just`
  target. The mechanism is the existing `*args` passthrough: a trailing `-n 0` disables xdist, and users can always call
  `just test-cov` to get coverage back. No env vars, no new sub-commands beyond `test` / `test-cov`.
- **CI parity**: `just check` and CI must still enforce `--cov-fail-under=50` and produce HTML+XML coverage artifacts.
  Only the _default local dev loop_ gets leaner.
- **Uniform agent runtimes**: no runtime-specific branching; this is purely a Justfile + pyproject.toml + test-file
  change.
- **Phase independence**: each phase is picked up by a fresh agent instance with no prior conversation context, so each
  phase must be self-contained and its acceptance criteria must be verifiable from `git diff` + `just check`.

## Phase breakdown (3 phases)

Split chosen for minimum context per agent and low merge-conflict risk: Phase 1 is Justfile-only; Phase 2 is
pyproject.toml + Justfile + `tools/run_silent` wiring; Phase 3 is a single test file + possibly one production file.
Each phase delivers a measurable speedup independently.

---

### Phase 1 — Enable `pytest-xdist` by default (option A)

**Goal**: `just test` runs `pytest -n auto --dist=loadfile` by default while keeping every existing flag intact. Drops
wall time from ~6 min → ~2 min (coverage still in `addopts` at this point). Zero risk to coverage gating.

**Scope**:

1. Edit `Justfile` `test` recipe:
   - Insert `-n auto --dist=loadfile` before `{{ args }}` so users can still override with a trailing `-n 0`
     (pytest-xdist's last-wins semantics).
   - Keep the `_setup`, `_header "test"`, and printf banner unchanged.
2. Update the recipe's comment from "Run tests with coverage" to something accurate (e.g., "Run tests in parallel
   (coverage still on — see test-cov)"). This comment will be rewritten again in Phase 2; keep it minimal.
3. Do **not** touch `pyproject.toml` in this phase.
4. Do **not** touch `tests/test_agent_launch_repeat.py` in this phase.

**Verification**:

- `just test` runs to completion with `passed` (coverage terminal report still prints because `addopts` is unchanged).
- `just test -n 0` runs serially — prove the override works.
- `just test tests/test_keymaps.py -n 0` scopes and disables xdist.
- `just check` still passes.
- Commit with a message that references option A and cites the research doc.

**Out of scope for Phase 1**: pyproject.toml edits, removing `-v`, removing the `--cov*` flags, introducing `test-cov`,
touching test files.

**Risk / gotchas for the Phase-1 agent**:

- A handful of tests may expose ordering assumptions under xdist. If any test fails only under parallel execution,
  triage per-test (mark xdist_group, fix the shared state, or — only as a last resort — add `--dist=loadscope`). Do not
  silently skip.
- `--dist=loadfile` groups tests-per-file onto one worker; this is the right default for this suite per the research doc
  (minimizes duplicate module imports). Don't use `--dist=load` which scatters tests.
- Workspace `sase_<N>` directory: run `just install` first in case deps drifted.

---

### Phase 2 — Make coverage opt-in via `just test-cov` (option B)

**Goal**: `just test` becomes coverage-free (fast dev loop). A new `just test-cov` recipe runs the full coverage
pipeline and is what `just check` + CI call. Drops `just test` wall time from ~2 min → ~50 s. Coverage gating on CI is
preserved; the 50 % floor still blocks merges.

**Scope**:

1. Edit `pyproject.toml` `[tool.pytest.ini_options].addopts`:
   - Remove `--cov=src/sase`, `--cov-report=term-missing:skip-covered`, `--cov-report=html`, `--cov-report=xml`,
     `--cov-branch`, `--cov-fail-under=50`, and `-v`.
   - Keep `--import-mode=importlib`, `--strict-markers`, `--strict-config`.
   - Add `--durations=20` so slowest-test signal is still visible per-run.
2. Edit `Justfile`:
   - Rewrite `test` comment to reflect the fast-lane semantics ("Fast parallel test run, no coverage").
   - Add a new `test-cov *args` recipe that runs:
     `pytest -n auto --dist=loadfile --cov=src/sase --cov-branch --cov-report=term-missing:skip-covered --cov-report=html --cov-report=xml --cov-fail-under=50 {{ args }}`.
   - Update the `check` recipe: change `@tools/run_silent "test" just test` → `@tools/run_silent "test" just test-cov`
     so `just check` (and by extension CI) still enforces the 50 % gate.
3. Confirm no other Justfile target or CI script depends on `just test` producing coverage artifacts. Grep `.github/`,
   `tools/`, and any `pre-push` / `pre-commit` hooks. If any do, point them at `test-cov` instead.
4. Update relevant docs if any user-facing doc (CLAUDE.md, README.md, research doc itself) mentions "just test runs with
   coverage" — rewrite to reflect the split. Keep updates minimal.

**Verification**:

- `just test` is noticeably faster (no `--cov` banner, no `htmlcov/` regeneration, no XML file written).
- `just test-cov` produces `htmlcov/index.html`, `coverage.xml`, and prints a coverage summary; exits non-zero if
  coverage drops below 50 %.
- `just check` still prints a PASS for `test` and internally uses `test-cov`.
- `just test -v` (user-supplied override) re-enables verbose test IDs.
- `just test --cov=src/sase` (user-supplied override) re-enables coverage for one-off local verification.
- `tools/run_silent` continues to work with the new target name (it just shells out; no coupling).

**Out of scope for Phase 2**: any performance work on individual tests, xdist-related dist-mode changes, marker-based
test selection.

**Risk / gotchas for the Phase-2 agent**:

- Some tests (e.g., pyvision, pyscripts) may introspect the `.coverage` file. Verify `just lint-pyvision` still works
  without a fresh `.coverage` produced by `just test`.
- `[tool.coverage.run] parallel = true` + `source_pkgs = ["sase"]` can be left as-is; they only kick in when `--cov` is
  passed.
- `--strict-config` plus removed `-v` is fine; `-v` is not a config key.
- Removing `-v` means pytest no longer prints one line per test — this is deliberate (see research doc). If the user
  prefers verbose locally, they can alias `just test -v`.

---

### Phase 3 — Investigate and fix slow tests in `tests/test_agent_launch_repeat.py` (option C)

**Goal**: Eliminate the parallel-tail bottleneck identified in the research doc. After this phase, full-suite wall time
should drop from ~50 s → ~15 s.

**Scope**:

1. **Measure first, don't assume**. Run these independently under the post-Phase-2 configuration and record actual wall
   times:
   - `just test tests/test_agent_launch_repeat.py -n 0` (serial, no cov)
   - `just test tests/test_agent_launch_repeat.py` (parallel, no cov)
   - `just test -n auto --dist=loadfile` (full suite; capture `--durations=20`) The research doc reported 40 s per test;
     a casual local serial run shows ~3.5 s total. The gap is real and needs to be reconciled _before_ editing — the
     slowness may only manifest when loaded alongside the rest of the suite on an xdist worker, or it may have already
     self-resolved. Do not skip this step.
2. **Identify the actual blocker** among these candidates:
   - `spawn_repeat_batch(..., sleep_between=1.0)` in `src/sase/agent/repeat_launcher.py:153` — adds `1.0 s × (N-1)` per
     test. For N=3 that's 2 s per test (6 s across the three tests). This alone should be neutralised via dependency
     injection (pass `sleep_between=0.0` from the mixin's test seam, or make the default injectable).
   - `_join_threads()` in the test file joins every non-main thread with `timeout=5`. If the test leaves orphan daemon
     threads from prior tests in the same worker, this accumulates.
   - `reserve_repeat_name_base` walks `~/.sase/projects/` and calls `is_process_alive` (reads `/proc/<pid>/cmdline`) —
     if an earlier repeat test leaks state into a sibling test's `tmp_path` Home, this can spin.
   - `_schedule_agents_async_refresh` is _not_ defined on `_FakeApp`; currently the exception is swallowed by the broad
     `except Exception` in `_launch_repeat.py`. Verify this swallowing is actually happening and isn't introducing
     log-processing delay.
3. **Apply the minimal fix** that takes the three tests down to <1 s each:
   - Prefer injecting `sleep_between=0.0` via a test seam (e.g., an optional kwarg on `_launch_repeat_agents` or a
     module-level constant patched via `monkeypatch`) over `time.sleep = lambda *_: None`-style patches.
   - If threads are the root cause, consider running `_run()` synchronously in tests by mocking `threading.Thread` to a
     dummy that invokes `target()` inline — this also removes the need for `_join_threads()`.
   - Do **not** weaken production behavior. `sleep_between=1.0` exists to give agents distinct timestamps — keep the
     default, inject the test-only zero.
4. **Re-measure**. Record post-fix timings for the same three commands as in step 1, and update
   `sdd/research/202604/test_suite_speedup.md` in-place at the bottom with an "Outcome" section (date, before/after numbers, list
   the phases that shipped). Do not rewrite the historical content — append.

**Verification**:

- `tests/test_agent_launch_repeat.py` runs in under 3 s total (serial).
- `--durations=20` no longer lists any test from `test_agent_launch_repeat.py`.
- Full suite `just test` wall time is close to the research prediction (~15 s on a comparable box; document the measured
  number regardless).
- `just test-cov` still passes the 50 % coverage gate — tests still exercise the real `_launch_repeat_agents` code path,
  just without the artificial sleep.
- No changes to public API of `spawn_repeat_batch` or `_launch_repeat_agents` that affect non-test callers.

**Out of scope for Phase 3**: marker-based test tiering, Textual Pilot optimizations, coverage-context surgery — these
are options D/F/G in the research doc and are explicitly deferred.

**Risk / gotchas for the Phase-3 agent**:

- The research doc's "40 s per test" number may be stale or harness-specific. Trust your measurements; treat the
  research as a hypothesis, not a spec.
- Production uniformity: the uniform-runtimes rule in `memory/short/gotchas.md` is irrelevant here (no runtime
  branching), but do not introduce test-only code paths that diverge production behavior — inject timing parameters,
  don't fork the control flow.
- If Phase 3 reveals the slowness is actually in a different test file (e.g., Textual Pilot tests dominate the tail
  under xdist), stop and report back — don't scope-creep into retuning the whole suite.

---

## Handoff summary (for phase agents)

- Phase 1 agent: edit `Justfile` `test` recipe only. Commit. `just check` must pass. Nothing else.
- Phase 2 agent: edit `pyproject.toml` `[tool.pytest.ini_options].addopts` and `Justfile` (`test` comment, new
  `test-cov`, `check` wiring). Grep CI for any other caller of `just test` that expects coverage. Commit.
- Phase 3 agent: measure, diagnose, fix `tests/test_agent_launch_repeat.py` (and minimal production seam in
  `src/sase/agent/repeat_launcher.py` or `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py` if needed). Append
  outcome to `sdd/research/202604/test_suite_speedup.md`. Commit.

Each phase should produce exactly one commit. Commits must build on each other cleanly — no phase should leave `master`
broken.
