---
create_time: 2026-04-24 10:30:17
status: done
bead_id: sase-m
prompt: sdd/prompts/202604/speed_up_slow_tests.md
---
# Plan: Speed Up the 20 Slowest Tests

## Context

`pytest --durations=20` on the sase suite surfaces a repeating shape: TUI Pilot tests at 4–8 s, `CommitWorkflow` tests
at 4–11 s, and one PDF-rendering integration test at 5.6 s. Together they account for roughly 119 s of the 56 s
parallelized wall-clock (they dominate the slowest-file shards). Making them fast has a disproportionate payoff for
`just test` / `just check` iteration loops.

The root causes are narrow and well-localized:

- **Textual Pilot polling** (`src/sase/ace/testing.py`): the `expect_state`, `expect_modal`, `expect_screen_contains`,
  `expect_screen_not_contains`, and `wait_for` helpers sleep `interval=0.05 s` **in addition to**
  `await self._pilot.pause()` on every iteration. `pilot.pause()` already awaits a frame tick, so the extra 50 ms sleep
  is straight dead time. A Pilot test that converges after ~10 polls pays ~500 ms for nothing, on top of the 2 s fixed
  app-startup overhead.

- **CommitWorkflow run()** (`src/sase/workflows/commit/workflow.py`): each affected test already `autouse`-patches
  `load_merged_config` so the shell `precommit_command` doesn't execute, but `handle_beads()`, `handle_sase_plan()`, and
  `capture_pre_commit_diff()` are **not** mocked. They shell out to `sase bead …`, `git rev-parse …`, and
  `provider.diff()` even though the provider is a `MagicMock`. The bead subprocess in particular incurs a ~500 ms import
  cost per call on the test host, multiplied across every run.

- **PDF integration test** (`tests/test_xprompt_catalog.py::test_build_integration_produces_pdf`): actually invokes
  `pandoc` (or `wkhtmltopdf`) to produce a real PDF. It already has a `skipif` guard but that guard is false on
  developer machines and CI, so it runs every time. The fix is to mark it slow and exclude it from the default run.

## Goal

Reduce the wall-clock of `just test` by cutting the slowest-20 durations by ≥60 % without losing test coverage or
introducing flakiness. Every affected test must still exercise the same behavior — we are removing incidental overhead,
not trimming scope.

## Non-Goals

- Rewriting the commit-workflow architecture.
- Replacing Textual Pilot with a smaller harness.
- Generalized parallelism tuning (`-n auto --dist=loadfile` is already set).
- Speeding up tests not in the slowest-20 set (stretch goal only, via whatever spillover these changes produce).

## Phase Structure

Each phase is a self-contained, independently reviewable commit scoped to a single agent instance. Phases 1 and 2 are
**logically independent** and could run in either order or in parallel on separate branches; Phase 3 should run last
because its verification step measures the aggregate win.

---

### Phase 1 — Eliminate subprocess work in CommitWorkflow tests (Group B)

**Agent scope:** one commit, roughly 50–100 LOC of test-fixture plumbing.

**Affected test files (all share the same root cause):**

- `tests/test_commit_workflow_changespec.py`
- `tests/test_commit_workflow_checkpointing.py`
- `tests/test_commit_workflow_dispatch.py`
- `tests/test_pr_tags.py`
- `tests/test_project_pr_prefix.py`

Each already defines a local `_no_precommit` autouse fixture that patches
`sase.workflows.commit.precommit_hooks.load_merged_config`. That handles `run_precommit` but leaves three expensive call
sites untouched in `src/sase/workflows/commit/workflow.py`:

- Line 107 — `handle_beads(self._payload, cwd)` → `subprocess.run(["sase", "bead", …])`.
- Line 108 — `handle_sase_plan(self._payload, cwd)` → reads `$SASE_PLAN`, runs `git rev-parse --show-toplevel`,
  optionally copies files, runs `sed -i`, and imports `format_with_prettier` which spawns prettier.
- Line 173 — `capture_pre_commit_diff(provider, cwd, self._cl_name)` → calls `provider.diff(...)` on the mocked
  provider, but also writes a diff artifact file.

**Concrete edits:**

1. Extend each file's existing `_no_precommit` autouse fixture to additionally patch:

   ```python
   patch("sase.workflows.commit.workflow.handle_beads", return_value=None),
   patch("sase.workflows.commit.workflow.handle_sase_plan", return_value=None),
   patch("sase.workflows.commit.workflow.capture_pre_commit_diff", return_value=None),
   ```

   Patch at the **workflow** import site (where `CommitWorkflow.run` uses them), not at the definition site — this
   leaves unit tests that exercise the real `handle_beads` / `handle_sase_plan` / `capture_pre_commit_diff` untouched.

2. To avoid copying the same fixture into five files, consolidate into a shared fixture. The cleanest location is a new
   `tests/_commit_workflow_fixtures.py` module (not a conftest, to avoid accidentally applying to unrelated tests) that
   defines `no_precommit_hooks` as a plain fixture, and each test file re-exports it as its own `_no_precommit` autouse
   fixture. Alternatively, add a single fixture to `tests/conftest.py` that is opt-in via a pytest marker — but the
   focused-helper approach is less invasive.

3. Rename the local fixture body to reflect expanded scope (e.g. `_no_precommit_or_hooks`) so a future reader can see at
   a glance why workflow subprocesses don't fire.

**Verification:**

- Run the five affected files alone with `-v --durations=10` and confirm each target test drops to ≤1 s. Representative
  target: `test_creates_changespec_on_pr_success` from 11.07 s → under 1 s.
- Run `just check` from the workspace (note: remember to run `just install` first in an ephemeral `sase_<N>` worktree).
- Spot-check that `tests/test_commit_workflow_*` tests which _should_ exercise the real precommit hooks (e.g. anything
  directly importing `handle_beads`) still pass — none exist today, but scan for calls to
  `handle_beads`/`handle_sase_plan` in the test tree before finalizing.

**Risk / rollback:** low. The patches are scoped to tests; if they mask a regression, the dedicated tests for those
helpers (e.g. `test_commit_workflow_*` files that specifically exercise bead handling, if any) would catch it. Rollback
= revert the commit.

---

### Phase 2 — Remove redundant polling sleep in Textual Pilot helpers (Group A)

**Agent scope:** one commit, ~10 LOC change in `src/sase/ace/testing.py` plus a verification pass.

**Affected tests:**

- `tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query`
- `tests/test_ace_tui_app.py::test_navigation_next_key`
- `tests/test_ace_tui_app.py::test_unmark_navigates_to_next_spec`
- `tests/test_ace_tui_widgets.py::test_tab_bar_integration_tab_key`
- `tests/test_ace_testing.py::test_ace_page_press`
- `tests/test_keymaps_e2e.py::test_remapped_navigation_key`
- `tests/test_keymaps_e2e.py::test_default_keys_still_work`

**Root cause (verified in `src/sase/ace/testing.py`):** every polling helper has the pattern

```python
await self._pilot.pause()
await asyncio.sleep(interval)   # interval defaults to 0.05
```

`pilot.pause()` already yields one full frame tick (Textual's own event-loop advance), so the explicit
`asyncio.sleep(0.05)` is pure overhead. Each iteration is effectively capped at 20 Hz when it should be running at
whatever rate the Textual scheduler ticks.

**Concrete edits (all in `src/sase/ace/testing.py`):**

1. In `expect_state` (line 206), `expect_screen_contains` (line 243), `expect_screen_not_contains` (line 261), and
   `wait_for` (line 279):
   - Drop the default `interval=0.05` parameter entirely, OR lower it to a token value like `0.005` and keep it as an
     escape hatch.
   - Replace the `await self._pilot.pause(); await asyncio.sleep(interval)` pair with a single
     `await self._pilot.pause()`. If we want a minimum backoff, call `await self._pilot.pause(delay=interval)` which is
     Textual's native API (confirm signature before committing — Textual ≥0.50 exposes it; older versions may not).

2. Keep the `timeout=2.0` default for now. A passing test never approaches that deadline, so it does not contribute to
   runtime of the slow-20 set. Tightening it is out of scope and risks masking real Textual hangs.

3. Leave `expect_modal` / `expect_no_modal` untouched — they delegate to `expect_state`.

**Verification:**

- Run the seven listed tests with `-v --durations=10` and confirm each drops by ≥1 s. Representative targets:
  `test_remapped_navigation_key` 7.67 s → ≤3 s, `test_query_edit_modal_invalid_query` 7.63 s → ≤3 s.
- Run the full `tests/test_ace_*` + `tests/test_keymaps_*` suites 3× to detect flakiness introduced by tighter polling.
  If any test becomes flaky, restore the `asyncio.sleep(interval)` but with `interval=0.005` instead of `0.05`.
- Run `just check`.

**Risk / rollback:** moderate — Textual's Pilot.pause behavior differs between versions, and a too-aggressive poll could
starve the event loop in edge cases. Rollback is a one-line revert. The 3× flake check is the important guardrail.

---

### Phase 3 — Gate the PDF integration test + verification sweep (Group C + wrap-up)

**Agent scope:** one commit; small edits plus a re-measurement.

**Affected test:** `tests/test_xprompt_catalog.py::test_build_integration_produces_pdf`.

**Root cause:** the test really invokes `pandoc` or `wkhtmltopdf`. Its `skipif` only triggers when neither binary is
installed, which is false on CI and most developer machines, so it runs every time.

**Concrete edits:**

1. Register a `slow` marker in `pyproject.toml` under `[tool.pytest.ini_options]` (`--strict-markers` is enabled, so
   this registration is required):

   ```toml
   markers = [
     "slow: marks tests as slow (deselect with '-m \"not slow\"')",
   ]
   ```

2. Apply `@pytest.mark.slow` to `test_build_integration_produces_pdf` in `tests/test_xprompt_catalog.py:294` alongside
   the existing `skipif`.

3. Add `-m "not slow"` to the `addopts` list in `[tool.pytest.ini_options]` so the default `pytest` invocation (and
   therefore `just test` and `just test-cov`) skips slow tests. Alternatively, update the `test` and `test-cov` recipes
   in `Justfile` (lines 94 and 99) to pass `-m "not slow"` explicitly. The `pyproject.toml` route is preferred because
   it also protects direct `pytest` invocations.

4. Add a `just test-slow` recipe (or extend `just check`) so the PDF test still runs in at least one place. Minimal
   form:

   ```make
   test-slow *args: _setup (_header "test-slow")
       {{ venv_bin }}/pytest -n auto --dist=loadfile -m slow {{ args }}
   ```

   Leave `just check` invoking only the fast subset; slow tests can be a separate gate (optional, not required for this
   phase).

**Verification sweep (the "is the whole thing actually faster" step):**

- Run `just test -- --durations=20` on a clean workspace and capture the new top-20.
- Compare against the original top-20 in the task description. Expected outcome:
  - Commit workflow tests ≤1 s each.
  - TUI tests ≤3 s each.
  - PDF test absent from the list (skipped by default).
  - Total slowest-20 sum at least ~60 % smaller.
- If any test not previously in the list has surfaced as a new outlier, note it in the commit message as a follow-up but
  do not address it in this phase.
- Run `just check`.

**Risk / rollback:** very low. The marker change is opt-in; the `skipif` guard is preserved as a belt-and-braces
fallback.

---

## Open Questions / Things to Verify Before Each Phase

- **Phase 1**: Before patching `handle_beads` at the workflow import site, confirm no test _currently_ relies on the
  real function. `grep -n "handle_beads\|handle_sase_plan" tests/` is sufficient.
- **Phase 2**: Confirm the installed Textual version exposes `pilot.pause(delay=…)`. If not, fall back to
  `interval=0.005` rather than invoking an unavailable API.
- **Phase 3**: Confirm `--strict-markers` rejects unregistered markers (it does in this repo per `pyproject.toml`), so
  the marker registration is mandatory.

## Success Criteria

- `pytest --durations=20` no longer shows any test at ≥ 5 s on a warm workspace.
- `just check` total wall-clock reduced measurably (aim: 10–20 s off the test phase).
- No new flakiness: each phase's affected test files pass 3 consecutive runs.
- No behavior changes observable outside tests (the production code paths for `handle_beads`, `handle_sase_plan`,
  `capture_pre_commit_diff`, and the PDF builder remain exactly as they are).
