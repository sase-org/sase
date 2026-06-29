---
create_time: 2026-06-29 12:02:21
status: done
prompt: sdd/prompts/202606/fix_commit_delta_summary_cwd_ci_failure.md
---
# Fix CI failure: `test_agents_commit_messages_panel_png_snapshot` times out

## Summary

The `sase-org/sase` CI workflow has been failing on `master` since commit
`9b93600a4 feat(tui): surface persisted commit diffs`. The single failing test is:

```
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot
       - AssertionError: Timed out waiting for commit delta summary
```

The failure is **deterministic in CI** (every run since `9b93600a4`) but the test **passes in the isolated visual lane**
(`just test-visual`). The root cause is that the test exercises the new "persisted commit diffs" code path using
**relative diff-file paths** that are read on a background worker thread and resolved against the process working
directory. In the full `just test-cov` run the working directory is not the repo root when that thread runs, so the
diffs read empty and the new wait-assertion never sees the delta summary it requires.

## Background: how the failing test works

`test_agents_commit_messages_panel_png_snapshot` builds an agent whose persisted `step_output` contains `meta_commits`
entries, each with a `diff_path` pointing at a fixture file. After opening the Agents tab it calls
`_wait_for_commit_delta_summary(page, agent)`, which polls the prompt panel's cached detail-header summary for up to 30
seconds and only returns once:

```python
summary is not None and summary.delta_entries and summary.linked_delta_groups
```

The summary is produced off the UI thread. On each render, `_agent_display` starts a Textual worker
(`run_worker(..., thread=True)`) that runs `build_detail_header_summary(agent)`. That builder calls:

- `agent_delta_entries(agent)` -> reads the **primary** commit diff files, and
- `agent_commit_linked_delta_groups(agent)` -> reads the **linked-repo** commit diff files.

Both ultimately call `_read_commit_diff_text(diff_path)` which does `open(os.path.expanduser(diff_path))`. For a
relative `diff_path`, `expanduser` is a no-op, so the file is opened **relative to the current working directory**. When
the diff files cannot be read, both lists come back empty, the summary is cached with empty deltas, and the poll loop
times out.

The sibling test in the same file (`test_agents_linked_repo_diff_file_panel_png_snapshot`) does **not** hit this path:
it seeds the linked-delta cache in memory with inline diff text, so it never reads files and is CWD-independent. That is
why only the commits test fails.

## Root cause

The fixtures are defined with a **relative** base path:

```python
# tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py
_COMMIT_DIFF_FIXTURES = Path("tests/ace/tui/visual/fixtures/commit_diffs")
```

Every `diff_path` in the failing test's agent derives from this relative path (`primary_001.diff`, `primary_002.diff`,
`linked_001.diff`).

- In `just test-visual`, the visual lane runs alone. The pytest launcher (`tools/run_pytest`) does `os.chdir(REPO_ROOT)`
  at startup, so the working directory stays the repo root and the relative paths resolve. The test passes.
- In `just test-cov`, the visual tests run interleaved with the full ~14.8k-test suite under xdist (`--dist=loadfile`).
  Some other test in the suite changes the process working directory and does not restore it for the rest of that
  worker's run (the isolated visual lane contains no such test). Because the commit-diff files are read on a background
  worker thread via **relative** paths, they resolve against the wrong directory, both delta lists come back empty, and
  the new `_wait_for_commit_delta_summary` assertion times out after 30 seconds.

This is a **test-only artifact**. In production, persisted `diff_path` values are always **absolute**:
`commit_tracking.py` builds them from `os.path.join(SASE_ARTIFACTS_DIR, "commit_diffs", ...)` or from
`sase_subdir("diffs")` (under `~/.sase/`). The production reader is correct for absolute paths; only the test fixtures
rely on the working directory.

### Evidence gathered

- CI history: the `test_agents_commit_messages_panel_png_snapshot` timeout first appears in the run for `9b93600a4` and
  recurs on every subsequent run. Earlier failures were an unrelated flaky test
  (`test_stop_axe_daemon_targets_inherited_lock_daemon`, a SIGTERM/`-15` flake), not this test.
- The wait helper `_wait_for_commit_delta_summary` and the relative-path commit-diff reading were both added by
  `9b93600a4`.
- Reproduced the CWD dependence directly by constructing the test's agent and calling the delta helpers: from the repo
  root `delta_entries=2, linked_delta_groups=1`; after `os.chdir("/tmp")` both are `0`.
- Verified the fix: with **absolute** fixture paths the same calls return `delta_entries=2, linked_delta_groups=1` even
  from `/tmp`.
- The test passes locally in the isolated visual lane (`just test-visual`, 126 items), matching CI's isolated-vs-full
  split.

## Goals / Non-goals

**Goals**

- Make CI green by removing the working-directory dependence from the failing visual test.
- Keep the test exercising the real persisted-commit-diff reading path (that is the point of the feature added in
  `9b93600a4`); do not weaken it into a cache-seeding test.
- Keep the PNG snapshot unchanged and machine-independent.

**Non-goals**

- No production code change. The production reader already handles absolute paths and persists absolute paths; nothing
  in `src/` is broken.
- Not hunting down and fixing the unrelated sibling test that leaves the working directory changed (see Follow-ups). It
  is a latent test-isolation issue, but it is not required to green CI and the visual test should be CWD-independent
  regardless.

## Proposed fix

Make the visual test's fixture base path **absolute and anchored to the test file** so every derived `diff_path` is
absolute and independent of the working directory:

```python
# tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py
_COMMIT_DIFF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "commit_diffs"
```

This is a single-line change. All three `diff_path` values in `_linked_repo_commits_agent()` derive from
`_COMMIT_DIFF_FIXTURES`, so anchoring the base fixes them all.

### Why this is safe for the snapshot

The file panel renders a **basename / short label**, never the full diff path (`current_source_label()` returns
`os.path.basename(...)` for plain paths, and `repo_name short_sha` for commit slots). Switching the fixtures from
relative to absolute therefore does not change any rendered text or pixels, and the assertions that match on
`primary_001.diff` (a basename substring) and the per-commit labels continue to hold. Anchoring to `__file__` also keeps
the value identical across machines/CI (no machine-specific absolute prefix is ever rendered).

### Scope check

`_COMMIT_DIFF_FIXTURES` / the `commit_diffs/` fixtures are referenced only by this one test file; no other test builds
an agent from relative diff-path fixtures. The fix is fully localized.

## Verification plan

1. `just install` (ephemeral workspace requires it before other recipes).
2. `just test-visual` — the visual lane still passes, including both linked-repo tests.
3. `just test-cov` — the full suite passes; `test_agents_commit_messages_panel_png_snapshot` no longer times out. (This
   is the lane CI runs; it is the real confirmation, since the bug only manifests under the full suite.)
4. `just check` (format/lint/test) before completion, per repo policy.
5. Optional extra confidence: confirm the fixture-derived `diff_path` values are absolute and resolve from an arbitrary
   working directory.

## Risks

- **Low.** Test-only change; production untouched; rendering and snapshot unchanged.
- The only residual risk is that the underlying working-directory pollution from another test could surface elsewhere in
  the future. That is captured as a follow-up rather than fixed here, because the correct invariant for this test is to
  be CWD-independent.

## Follow-ups (separate, optional)

- Investigate which suite test changes the process working directory without restoring it under the full `test-cov` run,
  and either fix that test or add an autouse conftest guard that restores the working directory after each test. This
  hardens the whole suite against the same class of flake but is not required to green CI. Track as its own bead.
