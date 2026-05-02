---
create_time: 2026-04-17 23:18:40
status: done
prompt: sdd/prompts/202604/fix_commit_workflow_test_reservation_leak.md
---

# Fix Test-Caused `sase_child_cl_N` Reservation Leak Into Real User Project File

## Problem

Every `pytest` run leaks 2 `STATUS: Reserved` ChangeSpec entries into the user's real `~/.sase/projects/sase/sase.gp`,
plus 2 stale JSON files into `~/.sase/commit_state/`. After four pytest runs the user saw 8 leaked `sase_child_cl_1` …
`sase_child_cl_8` reservations in the `sase ace` CLs tab.

The culprits are two tests in `tests/workflows/test_commit_workflow.py`:

- `test_explicit_parent_overrides_auto_detect` (lines 275–300)
- `test_explicit_parent_skips_auto_detect` (lines 303–326)

## Root Cause

Commit `18a04c80` ("feat: write commit checkpoints + detect merge conflicts in run()") introduced a conflict-detection
branch in `CommitWorkflow.run()` at `src/sase/workflows/commit/workflow.py:178-195`:

```python
if not ok:
    if _is_conflict_state(provider, cwd):
        ...
        return RunResult.CONFLICT          # <-- returns WITHOUT cleanup
    ...
    cleanup_reservation(self._reserved_name)
    checkpoint.delete()
    return RunResult.FAILED
```

`_is_conflict_state()` (workflow.py:278-295) calls `provider.is_sync_in_progress(cwd)` and treats a truthy return as
"conflict in progress". This is correct for production — when there's a real merge conflict the user resolves and calls
`sase commit --resume`, so the reservation must survive.

But in the two affected tests the provider is a bare `MagicMock()`. A bare MagicMock method call returns a new
MagicMock, which is **truthy**. So every test run takes the CONFLICT path:

1. `compute_suffixed_cl_name("sase", "child_cl")` is called (imported inline inside `run()`, so outer patches don't
   intercept it). It writes `NAME: sase_child_cl_N` + `STATUS: Reserved` to the real `~/.sase/projects/sase/sase.gp`
   because the pytest cwd (the `sase_100` workspace) resolves to the real `"sase"` project via
   `get_project_from_workspace()`.
2. `checkpoint.save()` writes `~/.sase/commit_state/<pid>.json` with `reserved_name: sase_child_cl_N` and
   `completed_steps: []`.
3. `dispatch()` returns `(False, "stopped")`.
4. `_is_conflict_state()` returns `True` (false positive from bare MagicMock).
5. `run()` returns `RunResult.CONFLICT` — **`cleanup_reservation()` and `checkpoint.delete()` are skipped**.
6. Per pytest run: 2 tests × 1 leaked reservation + 1 leaked checkpoint state file = permanent pollution of the user's
   real sase home directory.

The sibling test `test_provider_failure_returns_false` at `tests/test_commit_workflow_dispatch.py:86-87` was updated in
commit `18a04c80` to defuse the same issue:

```python
mock_provider.is_sync_in_progress.return_value = False
mock_provider.get_conflicted_files.return_value = []
```

But the two tests in `tests/workflows/test_commit_workflow.py` were missed. They were written in commit `85132744`
(Apr 10) — well before the conflict probe existed — so the originals had no reason to set those returns.

Additionally, the two broken tests never mock `get_project_from_workspace` or `compute_suffixed_cl_name`. Even if the
CONFLICT false-positive were fixed, the tests would still momentarily write and then remove entries from the real user
project file. `test_commit_workflow_dispatch.py` avoids this via `@patch(_PROJECT_NAME_TARGET, return_value=None)`
(lines 62, 109) — the `get_project_from_workspace` → `None` sentinel skips the suffixing/reservation path entirely.

## Fix

Apply the same two-part pattern the sibling test in `test_commit_workflow_dispatch.py` already uses:

1. **Neutralize the conflict probe.** Set `mock_provider.is_sync_in_progress.return_value = False` and
   `mock_provider.get_conflicted_files.return_value = []`. Now the dispatch-failure path takes the `RunResult.FAILED`
   branch and `cleanup_reservation()` + `checkpoint.delete()` fire.
2. **Isolate from real user state.** Patch `sase.workflows.commit.workflow.get_project_from_workspace` to return `None`.
   This short-circuits the suffix-and-reserve block at workflow.py:115-131 so the test never writes to the real `.gp`
   file in the first place. This is defense in depth — even if future refactors reorder cleanup, the tests remain
   isolated.

Both fixes together match the hygiene of `test_commit_workflow_dispatch.py`.

## Files to Modify

- **`tests/workflows/test_commit_workflow.py`** — update the two tests at lines 275–326. No production code changes.

## Files Explicitly NOT Modified

- `src/sase/workflows/commit/workflow.py` — the CONFLICT branch skipping cleanup is **intentional** production behavior.
  Real conflicts need the reservation to persist across `sase commit --resume`.
- `src/sase/workflows/commit/commit_tracking.py` — `cleanup_reservation()` itself is correct.
- `~/.sase/projects/sase/sase-archive.gp` — the 16 archived `sase_child_cl_N_M` entries are already `STATUS: Reverted`
  and inert. Leaving them in the archive is consistent with how every other reverted ChangeSpec is preserved.

## Phases

### Phase 1: Fix the two leaky tests

**File:** `tests/workflows/test_commit_workflow.py`

For each of `test_explicit_parent_overrides_auto_detect` (line 275) and `test_explicit_parent_skips_auto_detect` (line
303):

1. Add to the `mock_provider` setup:
   ```python
   mock_provider.is_sync_in_progress.return_value = False
   mock_provider.get_conflicted_files.return_value = []
   ```
2. Add to the `with` block:
   ```python
   patch(
       "sase.workflows.commit.workflow.get_project_from_workspace",
       return_value=None,
   ),
   ```

No other assertions change. Both tests should still pass and still exercise the same code paths they were written to
exercise (explicit-parent precedence; auto-detect skip).

**Verification:**

1. Run just the two fixed tests and confirm they pass:
   ```bash
   just test tests/workflows/test_commit_workflow.py::test_explicit_parent_overrides_auto_detect \
             tests/workflows/test_commit_workflow.py::test_explicit_parent_skips_auto_detect
   ```
2. **Critically**, after the test run, confirm the following are untouched:
   ```bash
   grep -c "sase_child_cl" ~/.sase/projects/sase/sase.gp          # must output 0
   ls ~/.sase/commit_state/ | wc -l                                # must not have grown
   ```
3. Run `just check` — lint, mypy, full test suite must pass.

### Phase 2: Clean up existing leaked user state

This phase cleans up the residue already on disk in the user's environment. It is a one-shot housekeeping step — there
is no production code change, no test change, no PR needed. It's separated into its own phase because (a) it touches
files outside the repo, and (b) it can be safely skipped if the user prefers to clean up manually.

1. Delete leaked commit-state files whose payload contains a `child_cl` name:
   ```bash
   for f in ~/.sase/commit_state/*.json; do
       if grep -q '"name": "child_cl"\|"name": "sase_child_cl_' "$f"; then
           rm -v "$f"
       fi
   done
   ```
2. Inspect `~/.sase/projects/sase/sase.gp` for any lingering `NAME: sase_child_cl_N` + `STATUS: Reserved` blocks. The
   snapshot from the user's question showed eight of these; recent file reads show the live file no longer contains
   them, but verify with:
   ```bash
   grep -n "sase_child_cl" ~/.sase/projects/sase/sase.gp
   ```
   If any are still present, remove only `STATUS: Reserved` blocks (leave any that have been promoted to a real status).
   The archive file (`sase-archive.gp`) is left untouched — its `Reverted` entries are terminal and harmless.

**Verification:**

After Phase 2:

```bash
grep -c "child_cl" ~/.sase/commit_state/*.json 2>/dev/null  # must output 0 (or "No such file")
grep -c "sase_child_cl" ~/.sase/projects/sase/sase.gp        # must output 0
```

And after a fresh `just test` run, neither count should grow.

## Out of Scope

- Tightening `_is_conflict_state()` itself. In production with real VCS providers it behaves correctly; the false
  positive is purely a test-fixture issue.
- Auditing every other test that constructs a `CommitWorkflow` directly. A quick scan shows only the two tests
  identified above exhibit the symptom. The tests in `test_commit_workflow_dispatch.py`,
  `test_commit_workflow_checkpointing.py`, and `test_commit_workflow_changespec.py` already use the correct mocking
  pattern.
- Any CLI changes. No new flags or options — nothing to document in SKILL.md files.
