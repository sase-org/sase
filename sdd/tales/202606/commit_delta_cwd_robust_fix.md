---
create_time: 2026-06-29 13:24:48
status: done
prompt: sdd/prompts/202606/commit_delta_cwd_robust_fix.md
---
# Make the commit-delta visual test robustly CWD-independent and harden the suite against CWD leaks

## TL;DR

CI on `sase-org/sase` has been red on `master` for ~20 consecutive runs, alternating between **two** flaky/deterministic
test failures:

1. `tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon` — `AssertionError: assert -15 == 0`
   (SIGTERM-handler-install race). **Already fixed** by the previous change (the child now installs its `SIGTERM`
   handler before announcing readiness). Verified locally (40/40 passes under heavy CPU load) and confirmed by **three
   consecutive green CI runs** on the commits that followed it.

2. `tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot`
   — `AssertionError: Timed out waiting for commit delta summary`. This is the **dominant** historical red (8 of the
   last 10 failed runs). A fix landed for it, **but the landed fix diverged from its own approved plan**: it kept the
   fragile relative fixture path and added a `monkeypatch.chdir(...)` band-aid, instead of the approved change that made
   the fixture paths absolute. The band-aid works today, but it relies on mutating the global process working directory
   and leaves the underlying root cause — a sibling suite test that changes the process CWD without restoring it —
   unaddressed.

This plan restores the **approved, robust** fix for #2 (absolute fixture paths → the test no longer depends on the
process CWD at all), removes the divergent `chdir` band-aid, and closes the root-cause follow-up the prior plan
explicitly deferred by adding an autouse test guard that restores the working directory after every test.

No production code changes. This is test-only hardening that makes an already-green-but-fragile CI lane durably green.

## Background: why the commit-delta test times out

`test_agents_commit_messages_panel_png_snapshot` builds an agent whose persisted `step_output.meta_commits` entries each
carry a `diff_path` pointing at a fixture file, then polls the prompt panel for up to 30 seconds until the cached
detail-header summary reports both `delta_entries` and `linked_delta_groups`.

The summary is produced **off the UI thread**: on render, the prompt panel starts a Textual worker
(`run_worker(..., thread=True)`) that runs `build_detail_header_summary(agent)`. That builder reads each commit diff via
`_read_commit_diff_text(diff_path)`, which does `open(os.path.expanduser(diff_path))`. For a **relative** `diff_path`,
`expanduser` is a no-op, so the file is opened **relative to the current working directory**. If the files cannot be
read, both delta lists come back empty, an empty summary is cached, and the 30-second poll times out.

The fixtures are defined with a **relative** base path:

```python
# tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py
_COMMIT_DIFF_FIXTURES = Path("tests/ace/tui/visual/fixtures/commit_diffs")
```

In the isolated visual lane the working directory stays the repo root, so these resolve and the test passes. In the full
`test-cov` run (xdist, `--dist=loadfile`) some other test changes the process working directory and does not restore it
for the rest of that worker's run; the worker thread then reads the relative diff paths from the wrong directory and the
assertion times out.

This is a **test-only artifact**. In production, persisted `diff_path` values are always **absolute** (built under the
SASE artifacts / `~/.sase` directories), so the reader is correct; only the test fixtures rely on the working directory.

### Evidence gathered

- CI history (last 10 failed `master` runs): exactly two distinct failing tests — the commit-delta timeout (×8) and the
  axe SIGTERM `-15` flake (×5). No third failure.
- The SIGTERM fix is solid: the targeted test passed 40/40 under 2× CPU oversubscription, and the three commits after it
  all show **green** CI.
- The CWD dependence of the commit-delta path is real and reproduced directly: constructing the test's own agent and
  calling `agent_delta_entries` / `agent_commit_linked_delta_groups` returns `delta_entries=2, linked_groups=1` from the
  repo root, and `0, 0` after `os.chdir("/tmp")`.
- The approved (absolute-path) fix is verified robust: with the fixture base anchored to the test file
  (`Path(__file__).resolve().parent / "fixtures" / "commit_diffs"`), the same three fixture files read successfully even
  with the process CWD set to `/tmp`.
- The landed band-aid (`monkeypatch.chdir(_REPO_ROOT)`, with `_REPO_ROOT = Path(__file__).resolve().parents[4]`) keeps
  the relative fixture path and does defend this one test in isolation (it passes when pytest is launched from `/tmp`),
  but it does not match the approved plan and does not address the suite-wide CWD leak.

## Root cause and what the landed fix got wrong

Root cause of #2: a visual test reads fixture files via **relative** paths on a background worker thread, while a
**different** suite test leaks the process working directory under the full xdist run. The correct invariant — stated in
the original approved plan — is that this test must be **CWD-independent**.

The approved plan proposed making the fixture base absolute (anchored to `__file__`) so every derived `diff_path` is
absolute and resolves from any working directory. The change that actually landed instead kept the relative base and
added `monkeypatch.chdir(_REPO_ROOT)`. Consequences of the divergence:

- It relies on mutating global process state (the CWD) for the duration of the test rather than making the test
  self-contained, so the test still implicitly depends on "what is the CWD right now."
- It leaves the underlying CWD leak in place. Any future relative-path fixture, or any other code that reads
  CWD-relative paths on a worker thread, can flake the same way. The prior plan flagged exactly this as a deferred
  follow-up.

## Goals / Non-goals

**Goals**

- Replace the divergent `chdir` band-aid with the approved absolute-fixture-path fix so the commit-delta test is truly
  CWD-independent, keeping it exercising the real persisted-commit-diff reading path (do not weaken it into a
  cache-seeding test, and do not relax the 30-second wait).
- Keep the PNG snapshot and all `assert_page_svg_contains` text assertions unchanged and machine-independent.
- Harden the whole test suite against the root-cause class of flake (a test leaving the working directory changed),
  closing the follow-up the prior plan deferred.

**Non-goals**

- No production code change. `_read_commit_diff_text` already handles absolute paths and production persists absolute
  paths; nothing in `src/` is broken.
- Not re-touching the already-fixed SIGTERM test.
- Not chasing the separate `sase-org/sase-github` CI red (different repo / different workflow); noted only so it is not
  conflated with this work.

## Proposed changes

### 1. Make the commit-delta fixtures absolute (restore the approved fix)

In `tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py`:

- Change the fixture base to an absolute path anchored to the test file:

  ```python
  _COMMIT_DIFF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "commit_diffs"
  ```

- Remove the now-unnecessary `_REPO_ROOT = Path(__file__).resolve().parents[4]` constant and the
  `monkeypatch.chdir(_REPO_ROOT)` line at the top of `test_agents_commit_messages_panel_png_snapshot`. (If `monkeypatch`
  is then unused by that test, drop the parameter as well — confirm during implementation.)

All three `diff_path` values in `_linked_repo_commits_agent()` derive from `_COMMIT_DIFF_FIXTURES`, so anchoring the
base fixes them all. Because the file panel renders only basenames / short labels (never the full diff path), switching
from relative to absolute changes no rendered text or pixels; the existing substring assertions (e.g.
`primary_001.diff`) and the PNG golden remain valid, and anchoring to `__file__` keeps the value identical across
machines/CI.

### 2. Add an autouse working-directory guard for the whole suite (root-cause hardening)

Add an `autouse` fixture to the root `tests/conftest.py` that records the process working directory before each test and
restores it afterward, so a test that changes the CWD without restoring it can no longer poison subsequent tests in the
same (xdist) worker. To make the latent offender discoverable rather than silently masked, the guard should also emit a
warning naming the test when it had to restore a changed CWD.

This eliminates the entire class of flake suite-wide, independent of which specific test is the offender (the exact
offender was not pinned down locally because reproducing it requires the project's own xdist test harness; the warning
added here will surface it on the next full run so it can be fixed at the source as a cheap follow-up).

## Verification plan

1. `just install` (ephemeral workspace requires it before other recipes).
2. Confirm the fixture-derived `diff_path` values are absolute and the delta helpers return
   `delta_entries=2, linked_groups=1` from an arbitrary working directory (e.g. `/tmp`).
3. `just test-visual` — the visual lane still passes, including both linked-repo tests; the commit-delta PNG golden is
   unchanged.
4. Run `test_agents_commit_messages_panel_png_snapshot` repeatedly under CPU load and from a non-repo-root working
   directory; confirm it no longer depends on the CWD.
5. `just test-cov` (the lane CI runs) — the full suite passes; the commit-delta test no longer times out. Inspect the
   run for any CWD-guard warnings to identify the offending leaker for a follow-up.
6. `just check` (format/lint/test) before completion, per repo policy.
7. Real confirmation is CI: the `test-cov` lane stays green across runs with no commit-delta timeout.

## Risks

- **Low.** Test-only change; production untouched; rendering and PNG snapshot unchanged. The absolute-path change is
  strictly more robust than the `chdir` band-aid it replaces (it removes a dependency rather than adding one). The
  autouse CWD guard only restores state between tests and cannot affect production behavior; its one observable effect
  is an added warning when a test leaks the CWD.

## Follow-ups (separate, optional)

- Use the CWD-guard warning from the next full `test-cov` run to identify and fix the specific test that changes the
  process working directory without restoring it, so the guard becomes a backstop rather than a load-bearing fix.
- Consider a tiny shared helper so future visual fixtures are always anchored absolutely, encoding the CWD-independence
  invariant once.
