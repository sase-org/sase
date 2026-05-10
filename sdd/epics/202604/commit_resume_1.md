---
create_time: 2026-04-17 21:21:28
status: done
bead_id: sase-j
prompt: sdd/prompts/202604/commit_resume_1.md
---

# Plan: Resumable `sase commit` After Agent-Resolved Merge Conflicts (Phased)

## Background

When an agent runs its `/sase_git_commit` or `/sase_hg_commit` skill, the command invokes `sase commit`, which calls
`CommitWorkflow.run()` (`src/sase/workflows/commit/workflow.py:61`). That `run()` dispatches to a VCS-specific provider
hook (`vcs_create_commit` / `vcs_create_proposal` / `vcs_create_pull_request`), then runs a series of post-dispatch
"tracking" steps:

1. `create_changespec` (PR only) — `commit_tracking.py:181`
2. `write_result_marker` — `commit_result.json` for downstream xprompt steps — `commit_tracking.py:152`
3. `append_commits_entry` — adds the `(N) <note>` line to the project `.gp` file — `commit_tracking.py:86`
4. (For commit / PR dispatch) `_post_commit_bead_amend` and `_push_with_retry` happen _inside_ the dispatch — see
   `_git_commit_dispatch.py:120–140` and `:89–118`

If anything inside dispatch raises a merge conflict (git `_merge_with_master` aborting, hg `evolve` mid-commit), the
dispatch returns `(False, err)` and `CommitWorkflow.run()` returns `False` at `workflow.py:154`. All post-dispatch
tracking steps are then silently skipped. The agent (which is good at resolving conflicts — see the `sase ace` snapshot
attached to the user's request and referenced in `sdd/research/202604/commit_conflict_resume.md`) resolves the conflict and ends up
with a clean local commit, but no ChangeSpec row, no COMMITS entry, no push, and no `commit_result.json` for the xprompt
post-steps.

The agent has no affordance today for finishing the bookkeeping, so the user-visible "I committed your changes" message
is a false positive from sase's perspective.

This plan implements **Solution A** from `sdd/research/202604/commit_conflict_resume.md`: a resumable `CommitWorkflow` with a JSON
checkpoint file, surfaced via `sase commit --resume` and explicit per-VCS skill instructions modeled on
`src/sase/xprompts/sync.yml`.

The work is split into **four phases** because each phase will be implemented by a distinct agent instance (a distinct
`claude` / `gemini` / `codex` command). Each phase is self-contained, leaves the codebase green (`just check` passes),
and has a "Verification" checklist the next agent can audit before starting its own phase. Phases land in strict order
(P1 → P2 → P3 → P4); earlier phases MUST be merged / applied before a later phase begins.

## Goal

After all four phases land:

1. When `sase commit` hits a merge conflict, it persists a JSON checkpoint and exits with a **distinct non-zero exit
   code (2)** so the calling agent can recognize "conflict needs manual resolution" vs. "generic failure".
2. The agent's commit skill (`/sase_git_commit`, `/sase_hg_commit`) gains a `## On Merge Conflict` section that
   instructs the agent to (a) resolve conflicts using VCS-specific steps from `sync.yml`, (b) verify the local commit
   exists, then (c) run `sase commit --resume`.
3. `sase commit --resume` reads the checkpoint, probes current VCS state, runs only the missing tracking steps
   (idempotently), and deletes the checkpoint on success.
4. The fresh-run path is unchanged when no conflict occurs: same exit code, same behavior, same observable side effects.
5. New unit tests cover checkpoint round-tripping, the resume entry point, and the new exit code.

## Non-goals

- We do NOT change conflict-resolution authority — the agent still resolves the conflict itself, just like in
  `sync.yml`.
- We do NOT add a post-completion hook that auto-finalizes (Solution E from the research). It can be layered on top of A
  later if the agent forgets `--resume` in practice.
- We do NOT split `sase commit` into separate `--vcs-only` / `--finalize` subcommands (Solution B). The one-shot UX on
  the no-conflict path stays one shot.
- We do NOT change anything inside the VCS dispatch hooks beyond adding a new `vcs_finalize_commit` hook. The existing
  dispatch contract (`(bool, str | None)`) is unchanged. Conflict detection happens in `CommitWorkflow.run()` _after_
  dispatch returns `False`, by probing `provider.is_sync_in_progress(cwd)` and the working tree.
- We do NOT introduce dispatch-substep idempotency (Solution F). The resume path re-runs only the tracking steps and
  provider-level finalization (`_push_with_retry`, `_post_commit_bead_amend`) that wasn't reached.
- Hg-side `vcs_finalize_commit` (re-mailing, re-uploading) is out of scope for this plan — it lives in the `retired Mercurial plugin`
  plugin repo (see `memory/long/external_repos.md`). The hg code path intentionally tolerates a missing finalize step in
  Phase 3.

## Files to Add or Modify (full inventory, for reference across phases)

**New files**

- `src/sase/workflows/commit/checkpoint.py` — Phase 1
- `tests/test_commit_workflow_checkpoint.py` — Phase 1
- `tests/test_commit_workflow_resume.py` — Phase 3
- `tests/test_commit_cli_resume_flag.py` — Phase 4

**Modified files**

- `src/sase/workflows/commit/workflow.py` — Phases 1, 2, 3
- `src/sase/workflows/commit/commit_tracking.py` — Phase 2 (idempotency only)
- `src/sase/main/cl_handler.py` — Phases 1 (enum mapping), 2 (conflict exit code), 4 (resume branch)
- `src/sase/main/parser_commands.py` — Phase 4
- `src/sase/vcs_provider/_base.py` — Phase 3
- `src/sase/vcs_provider/_hookspec.py` — Phase 3
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` — Phase 3
- `tests/test_commit_workflow_dispatch.py` — Phase 1 (RunResult migration) + Phase 2 (conflict test)
- `tests/workflows/test_commit_workflow.py` — Phase 1 (RunResult migration)
- Other existing commit tests as discovered by the phase agent — Phase 1
- `src/sase/xprompts/skills/sase_git_commit.md` — Phase 4
- `src/sase/xprompts/skills/sase_hg_commit.md` — Phase 4

---

## Phase 1: Foundation — Checkpoint Module + `RunResult` Tri-State

**Goal.** Introduce the pure-infrastructure building blocks used by later phases: a checkpoint persistence module and a
tri-state return value. No user-visible behavior changes. All existing tests still pass, and new checkpoint tests pass.

### Context a fresh agent needs

- The user's request and the `sase ace` snapshot that motivated the work are in `sdd/research/202604/commit_conflict_resume.md`.
- Per `memory/short/workspaces.md`, run `just install` first — the workspace may be stale.

### Changes

#### 1. `src/sase/workflows/commit/checkpoint.py` (new, ~120 lines)

Owns the checkpoint dataclass and its persistence. Responsibilities:

- Define `_CommitCheckpoint` as a `@dataclass` with these JSON-serializable fields:
  - `version: int = 1` — schema version for forward-compat.
  - `method: str` — one of `create_commit`, `create_proposal`, `create_pull_request`.
  - `payload: dict` — the **mutated** payload (after `handle_beads`, `handle_sase_plan`, `apply_project_pr_prefix`,
    `append_pr_tags`, `build_pr_body`). This is what the resume path replays from.
  - `cwd: str`
  - `cl_name: str | None = None`
  - `project_file: str | None = None`
  - `diff_path: str | None = None`
  - `base_cl_name: str | None = None`
  - `reserved_name: str | None = None`
  - `parent_cl_name: str | None = None`
  - `dispatch_result: str | None = None` — commit hash or PR URL, populated only after dispatch succeeds.
  - `cs_name: str | None = None`
  - `entry_id: str | None = None`
  - `completed_steps: list[str] = field(default_factory=list)` — names of finished post-dispatch steps: `"dispatch"`,
    `"create_changespec"`, `"write_result_marker"`, `"append_commits_entry"`, `"final_result_marker"`.
  - `created_at: float = field(default_factory=time.time)` — for stale-checkpoint debugging.

- `def get_checkpoint_path() -> str`:
  - Prefer `os.path.join(os.environ["SASE_ARTIFACTS_DIR"], "commit_state.json")` when the env var is set.
  - Fall back to `os.path.expanduser(f"~/.sase/commit_state/{session_id}.json")` where `session_id` is
    `os.environ.get("SASE_AGENT_TIMESTAMP") or str(os.getpid())`. Mirrors the dedup-key pattern at
    `src/sase/scripts/sase_commit_stop_hook.py:279`.
  - Create the parent directory if it doesn't exist.

- `def save(cp: _CommitCheckpoint, path: str | None = None) -> str | None`:
  - Atomic write: `json.dump(dataclasses.asdict(cp), ...)` to `path + ".tmp"` → `os.replace(tmp, path)`.
  - **Must tolerate failure to write** (`print_status(..., "warning")` and return `None`) — losing the checkpoint must
    not abort the workflow. Returns the path written on success.

- `def load(path: str | None = None) -> _CommitCheckpoint | None`:
  - Read the file and `json.loads` → dataclass. Returns `None` if missing, malformed, or has an unknown `version`
    (future versions log a warning and refuse to resume — forward-compat).

- `def delete(path: str | None = None) -> None`:
  - Best-effort `os.remove`, swallow `FileNotFoundError`.

No pickle; JSON-only.

#### 2. `src/sase/workflows/commit/workflow.py` (modify)

- Add `from enum import IntEnum` and at module level:

  ```python
  class RunResult(IntEnum):
      OK = 0
      FAILED = 1
      CONFLICT = 2


  EXIT_CODE_CONFLICT = 2
  ```

  Add `RunResult` and `EXIT_CODE_CONFLICT` to any `__all__` if the module has one.

- Change `CommitWorkflow.run(self) -> bool` to `CommitWorkflow.run(self) -> RunResult`. In this phase, the function
  returns **only** `RunResult.OK` or `RunResult.FAILED` (replace `return True` with `return RunResult.OK` and
  `return False` with `return RunResult.FAILED`). `RunResult.CONFLICT` is wired in Phase 2. Do NOT add checkpoint-save
  calls yet — that lands in Phase 2.

#### 3. `src/sase/main/cl_handler.py` (modify)

- Import `RunResult` from `sase.workflows.commit.workflow`.
- In `handle_commit_command`, replace `sys.exit(0 if success else 1)` with:

  ```python
  result = workflow.run()
  if result == RunResult.OK:
      try:
          from sase.logs.run_log import log_event

          log_event(event="commit_created", method=method)
      except Exception:
          pass
      sys.exit(0)
  sys.exit(int(result))
  ```

  Since `RunResult` is an `IntEnum`, `int(RunResult.FAILED) == 1` and the mapping is natural. `CONFLICT` → 2 becomes
  effective in Phase 2 when `run()` starts returning it.

#### 4. Update existing tests for the new return type

Find every test that asserts `wf.run() is True`, `wf.run() is False`, `assert wf.run()`, or `assert not wf.run()` under
`tests/`. Known hits (per exploration): `tests/test_commit_workflow_dispatch.py`,
`tests/workflows/test_commit_workflow.py`. Also grep for any other hits the phase agent discovers:

```
rg "wf\.run\(\)|workflow\.run\(\)|CommitWorkflow.*\.run\(\)" tests/
```

Update each to `assert wf.run() == RunResult.OK` or `assert wf.run() == RunResult.FAILED` (import from
`sase.workflows.commit.workflow`). Do NOT add conflict assertions yet — those arrive in Phase 2.

#### 5. `tests/test_commit_workflow_checkpoint.py` (new, ~80 lines)

- `test_save_and_load_round_trip` — write a populated dataclass, read it back, assert field equality.
- `test_load_returns_none_when_missing` — `load("/nonexistent/path.json")` → `None`.
- `test_load_returns_none_for_unknown_version` — write `{"version": 999, ...}` JSON → `load()` returns `None`.
- `test_get_checkpoint_path_uses_artifacts_dir` — monkeypatch `SASE_ARTIFACTS_DIR`; path lives inside it and filename is
  `commit_state.json`.
- `test_get_checkpoint_path_falls_back_to_session_timestamp` — unset `SASE_ARTIFACTS_DIR`, set `SASE_AGENT_TIMESTAMP`;
  path is `~/.sase/commit_state/<timestamp>.json`. Use `monkeypatch.setenv` and `tmp_path`-scoped HOME to keep the test
  hermetic.
- `test_get_checkpoint_path_falls_back_to_pid_when_no_timestamp` — unset both env vars; path uses `str(os.getpid())`.
- `test_delete_is_idempotent` — calling `delete()` twice does not raise.
- `test_save_writes_atomically` — pre-create `<path>.tmp` with junk text, call `save()`, assert the final file is the
  new JSON (validates `os.replace` semantics).
- `test_save_tolerates_unwritable_path` — point to a directory without write permission (or use `monkeypatch` on `open`
  to raise `OSError`); assert `save()` returns `None` and does NOT raise.

### Verification

- `just install && just check` passes from the workspace root (per `memory/short/build_and_run.md`).
- `pytest tests/test_commit_workflow_checkpoint.py -v` passes (8 tests).
- `pytest tests/test_commit_workflow_dispatch.py tests/workflows/test_commit_workflow.py -v` passes after the
  `RunResult` migration.
- `rg "assert wf\.run\(\) is (True|False)" tests/` returns **no matches** — migration is complete.
- `rg "return True|return False" src/sase/workflows/commit/workflow.py` returns **no matches** — all exit points in
  `run()` return `RunResult.*`.
- Diff confirms **no** changes to `src/sase/xprompts/skills/`, `src/sase/main/parser_commands.py`,
  `src/sase/vcs_provider/`. Phase 1 touches `workflow.py`, `cl_handler.py`, the new checkpoint module, and tests only.

---

## Phase 2: Write Checkpoints + Detect Conflicts in `run()`

**Goal.** Wire the checkpoint module from Phase 1 into `CommitWorkflow.run()` so every successful step is persisted and
merge-conflict failures are mapped to `RunResult.CONFLICT` (exit code 2). The resume side of the feature still does not
exist; a checkpoint left on disk is simply dead data until Phase 3 lands. Fresh-run behavior with no conflict is
observably unchanged.

### Context a fresh agent needs

- Phase 1 introduced `src/sase/workflows/commit/checkpoint.py` and `RunResult`. Read them before starting.
- The VCS conflict-probe primitives already exist on `VCSProvider` (`src/sase/vcs_provider/_base.py:188–206`):
  `is_sync_in_progress()`, `get_conflicted_files()`, `continue_sync()`, `abort_sync()`. Concrete git/hg providers
  implement them (used by the existing `sync.yml` workflow).
- Telemetry pattern to mirror: `_git_commit_dispatch.py:188–191`. The `VCS_OPERATIONS` counter is already imported
  there; we'll use the same counter with a new `operation` label value.
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/workflows/commit/workflow.py` (modify)

Refactor `CommitWorkflow.run()` to checkpoint-and-probe. Concrete edits:

- Import the checkpoint module: `from sase.workflows.commit import checkpoint`.

- After all pre-dispatch payload mutations (current lines 87–134) but **before** `dispatch(...)` (currently line 150),
  build a `_CommitCheckpoint` snapshot:

  ```python
  cp = checkpoint._CommitCheckpoint(
      method=self._method,
      payload=self._payload,  # post-mutation
      cwd=cwd,
      cl_name=self._cl_name,
      project_file=self._project_file,
      diff_path=self._diff_path,
      base_cl_name=self._base_cl_name,
      reserved_name=self._reserved_name,
      parent_cl_name=self._parent_cl_name,
  )
  checkpoint.save(cp)
  ```

- After `ok, result = dispatch(...)` (current line 150):
  - On `ok is False`: probe `provider.is_sync_in_progress(cwd)` (wrap in `try/except NotImplementedError` — treat
    `NotImplementedError` as "not in a conflict state" so providers without the primitive still fall through to FAILED).
    As a belt-and-suspenders backup, if `get_conflicted_files(cwd)` returns a non-empty list without raising, also treat
    it as conflict. If in conflict:

    ```python
    VCS_OPERATIONS.labels(
        provider=provider._provider_name,
        operation="commit_conflict_detected",
        status="ok",
    ).inc()
    print_status(
        f"{self._method} hit a merge conflict: {result}. "
        "Resolve the conflict, then run `sase commit --resume` to finish.",
        "warning",
    )
    return RunResult.CONFLICT
    ```

    **Do NOT** call `cleanup_reservation` and **do NOT** delete the checkpoint — we need it for the resume.

    Otherwise (non-conflict failure) keep existing behavior: `cleanup_reservation(self._reserved_name)`,
    `checkpoint.delete()`, and `return RunResult.FAILED`.

  - On `ok is True`: update `cp.dispatch_result = result`, append `"dispatch"` to `cp.completed_steps`,
    `checkpoint.save(cp)`, then proceed into the existing tracking sequence.

- For each tracking step, after it runs, update the corresponding field on `cp`, append the step name to
  `cp.completed_steps`, and call `checkpoint.save(cp)`:

  | Step name              | Field on `cp` | Notes                                                           |
  | ---------------------- | ------------- | --------------------------------------------------------------- |
  | `create_changespec`    | `cs_name`     | PR method only. Skip the step-save when `cs_name is None`.      |
  | `write_result_marker`  | —             | Idempotent file write; append step name unconditionally.        |
  | `append_commits_entry` | `entry_id`    | commit/proposal only. Skip the step-save if `entry_id is None`. |
  | `final_result_marker`  | —             | The second `write_result_marker` call with `entry_id`.          |

- On full success: `checkpoint.delete()` BEFORE `return RunResult.OK` so a happy-path `sase commit` leaves no checkpoint
  file behind.

- Provide a shared helper `_run_tracking_steps(self, cp, result) -> RunResult` that runs the four-step tracking sequence
  from the current `run()` body. `run()` becomes "pre-dispatch → dispatch → `_run_tracking_steps(cp, result)` → delete
  checkpoint → return OK". `resume()` (Phase 3) will call the same helper.

  The helper takes `cp` as a parameter so it can update the checkpoint as each step completes. It can re-enter with a
  partial `cp.completed_steps` list and skip steps already marked done (this skip logic matters for Phase 3, but writing
  the helper to support it here makes Phase 3 smaller).

#### 2. `src/sase/main/cl_handler.py` (modify)

Update the exit-code mapping from Phase 1 to honor `RunResult.CONFLICT`:

- Phase 1 mapping of `sys.exit(int(result))` already returns 2 for `RunResult.CONFLICT` due to the `IntEnum` values. Add
  a log line for conflict to distinguish it in run logs:

  ```python
  result = workflow.run()
  if result == RunResult.OK:
      try:
          from sase.logs.run_log import log_event

          log_event(event="commit_created", method=method)
      except Exception:
          pass
      sys.exit(0)
  if result == RunResult.CONFLICT:
      try:
          from sase.logs.run_log import log_event

          log_event(event="commit_conflict", method=method)
      except Exception:
          pass
      sys.exit(EXIT_CODE_CONFLICT)
  sys.exit(int(result))
  ```

  Import `EXIT_CODE_CONFLICT` alongside `RunResult`.

#### 3. `src/sase/workflows/commit/commit_tracking.py` (modify)

Make `append_commits_entry` idempotent so Phase 3's resume can replay it safely:

- Add an optional kwarg `expected_entry_id: str | None = None` to the signature.
- Before calling `add_commit_entry_with_id` / `add_proposed_commit_entry`, if `expected_entry_id` is provided, read the
  COMMITS drawer for `cl_name` in `project_file` and scan for a line beginning with `(<expected_entry_id>) `. If
  present, return `expected_entry_id` immediately without appending.
- Use the existing `sase.workflows.commit_utils.entries` helpers or add a small reader — whichever is lighter. Do NOT
  add a brand-new parser; look for a helper named something like `find_commit_entry_id` or `read_commits_drawer` in
  `commit_utils/` and use it, or inline a three-line read-and-regex. Keep the change surgical.
- In this phase, nothing calls `append_commits_entry` with `expected_entry_id` yet (`run()` does not know an `entry_id`
  until after the call). The kwarg is added here purely as setup for Phase 3's resume.

#### 4. Tests (extend)

In `tests/test_commit_workflow_dispatch.py` (or a new `tests/test_commit_workflow_checkpointing.py` if it keeps the file
focused — phase agent's call):

- `test_run_writes_pre_dispatch_checkpoint` — mock provider's `create_commit` to return `(False, "err")` AND
  `is_sync_in_progress` to return `False`. After `run()`, assert the checkpoint file **does not exist** (non-conflict
  failure deletes it).
- `test_run_detects_conflict_and_returns_conflict_code` — mock provider's `create_commit` to return
  `(False, "merge conflict")` AND `is_sync_in_progress(cwd)` to return `True`. Assert `run()` returns
  `RunResult.CONFLICT` AND the checkpoint file exists with `completed_steps == []` and the post-mutation payload.
- `test_run_failure_without_conflict_deletes_checkpoint` — variant of the above where `is_sync_in_progress` returns
  `False`; assert `run()` returns `RunResult.FAILED` and the checkpoint file does NOT exist.
- `test_run_success_deletes_checkpoint` — happy path; assert no checkpoint remains after a successful `run()`.
- `test_run_records_completed_steps_in_order` — happy path; assert the in-memory `cp.completed_steps` (via a spy on
  `checkpoint.save`) progresses
  `["dispatch", "create_changespec"?, "write_result_marker", "append_commits_entry"?, "final_result_marker"?]` in order.
  Parametrize on `method`.

In `tests/test_commit_workflow_artifacts.py` or a new targeted test:

- `test_append_commits_entry_idempotent_with_expected_entry_id` — seed a COMMITS drawer with a `(99) existing note` line
  for CL `test-cl`; call `append_commits_entry(..., expected_entry_id="99")`; assert the return value is `"99"` and the
  drawer was NOT modified (file mtime / content unchanged).

### Verification

- `just install && just check` passes from the workspace root.
- `pytest tests/test_commit_workflow_dispatch.py tests/test_commit_workflow_checkpoint.py tests/workflows/test_commit_workflow.py tests/test_commit_workflow_artifacts.py -v`
  passes.
- `pytest tests/ -k "checkpoint or conflict_detected" -v` shows the new tests running.
- Manual smoke (optional but recommended): in a throwaway git repo, engineer a `_merge_with_master` conflict (pre-commit
  a file that collides with `origin/master`), run `sase commit -m "smoke"`, observe **exit code 2** and a
  `commit_state.json` in `$SASE_ARTIFACTS_DIR` (or `~/.sase/commit_state/<ts>.json` when run outside a sase agent). The
  local commit and COMMITS entry do NOT exist yet — that is expected until Phase 3 + Phase 4.
- `git diff` confirms changes are limited to `src/sase/workflows/commit/workflow.py`,
  `src/sase/workflows/commit/commit_tracking.py`, `src/sase/main/cl_handler.py`, and tests. No skill, parser, or VCS
  provider changes in Phase 2.

---

## Phase 3: Resume Path — `vcs_finalize_commit` Hook + `CommitWorkflow.resume()`

**Goal.** Add the resume mechanism: a new provider hook for idempotent post-commit finalization and a
`CommitWorkflow.resume()` classmethod that loads the checkpoint, verifies VCS state, and replays unfinished work. The
resume method exists only as a Python API here — the `--resume` CLI flag lands in Phase 4.

### Context a fresh agent needs

- Phase 1 + Phase 2 have landed: checkpoint writes are live, conflict detection returns `RunResult.CONFLICT`,
  `append_commits_entry` accepts `expected_entry_id`, and `_run_tracking_steps(self, cp, result)` is factored out and
  reusable.
- `VCSProvider` base: `src/sase/vcs_provider/_base.py`. Sync primitives (`is_sync_in_progress` etc.) live at lines
  182–206. `mail`/`upload` live at lines 261–271. Commit dispatch at lines 285–299.
- Git commit dispatch mixin: `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`. Relevant idempotent helpers:
  `_post_commit_bead_amend` (lines 120–140) and `_push_with_retry` (lines 89–118).
- ChangeSpec query helper likely at `src/sase/workflows/commit/changespec_queries.py` — the phase agent should grep for
  a "does ChangeSpec exist by name" function; if none exists, inline a tiny one using
  `sase.ace.changespec.find_all_changespecs` (used in `cl_handler.py:118`).
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/vcs_provider/_hookspec.py` (modify)

Add a new hookspec next to the existing commit hookspecs:

```python
@hookspec(firstresult=True)
def vcs_finalize_commit(payload: dict, cwd: str) -> tuple[bool, str | None]:
    """Re-run idempotent post-commit operations (push, bead amend) after a resume."""
```

Match the formatting / wrapping of surrounding hookspecs. Confirm the pluggy-based dispatcher forwards to this hook the
same way it does for `vcs_create_commit` — the existing pattern should require no wiring changes.

#### 2. `src/sase/vcs_provider/_base.py` (modify)

Add in the commit-dispatch section (near line 285):

```python
def finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    """Re-run idempotent post-commit operations after a resumed workflow."""
    raise NotImplementedError(
        "finalize_commit is not supported by this VCS provider"
    )
```

#### 3. `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` (modify)

Implement `vcs_finalize_commit` on `GitCommitDispatchMixin` in the `--- Dispatch ---` section:

```python
@hookimpl
def vcs_finalize_commit(
    self, payload: dict, cwd: str
) -> tuple[bool, str | None]:
    """Re-run idempotent post-commit operations after a resumed workflow."""
    if not payload.get("_skip_bead_amend"):
        self._post_commit_bead_amend(payload, cwd)
    return self._push_with_retry(cwd)
```

Both inner helpers are already idempotent: `_post_commit_bead_amend` checks for `sdd/beads/` changes before amending,
and `_push_with_retry` does a `git push` (a no-op exit 0 when HEAD matches `origin/<branch>`).

Add telemetry mirroring the existing pattern at `_git_commit_dispatch.py:188–191`:

```python
VCS_OPERATIONS.labels(
    provider=self._provider_name,
    operation="finalize_commit",
    status="ok",
).inc()
```

Emit on the success path before `return self._push_with_retry(cwd)` — or wrap the return to include a status label for
failure. Keep it simple: one success increment at the end of the happy path.

#### 4. `src/sase/workflows/commit/workflow.py` (modify)

Add `CommitWorkflow.resume()` as a classmethod:

```python
@classmethod
def resume(cls) -> RunResult:
    """Resume a previously-checkpointed commit workflow after manual conflict resolution."""
```

Behavior:

1. `cp = checkpoint.load()`. If `None`, print a friendly error (`"No commit checkpoint found — nothing to resume"`) and
   return `RunResult.FAILED`.

2. Construct the workflow instance: `wf = cls(payload=cp.payload, method=cp.method)`. Manually populate the private
   fields that `_run_tracking_steps` relies on:

   ```python
   wf._base_cl_name = cp.base_cl_name
   wf._reserved_name = cp.reserved_name
   wf._parent_cl_name = cp.parent_cl_name
   wf._diff_path = cp.diff_path
   wf._cl_name = cp.cl_name
   wf._project_file = cp.project_file
   ```

3. `provider = get_vcs_provider(cp.cwd)`. If `provider.is_sync_in_progress(cp.cwd)` (wrap in
   `try/except NotImplementedError`, treating `NotImplementedError` as `False`) returns `True`, print a friendly error
   (`"Conflicts are still in progress — complete the rebase/merge first, then re-run sase commit --resume"`) and return
   `RunResult.CONFLICT` (leaving the checkpoint on disk).

4. Verify the HEAD commit subject matches `cp.payload["message"].splitlines()[0]`:
   - For git: run `git log -1 --format=%s` via `provider._run(["git", "log", "-1", "--format=%s"], cp.cwd)`.
   - For hg: try `provider.get_description("HEAD", cp.cwd, short=True)`; fall back to the `%s`-equivalent raw command if
     `get_description` raises.
   - Compare `strip()` vs `strip()`. On mismatch, print
     `"Could not find the expected commit at HEAD (subject mismatch). Re-run sase commit from scratch."` and return
     `RunResult.FAILED`. Leave the checkpoint on disk so the user can inspect or manually clean up.

   Keep this verification logic as a small local helper inside `resume()` — do not thread it through a new abstract
   method on `VCSProvider`. The existing `_run` subprocess helper is sufficient.

5. Call `provider.finalize_commit(cp.payload, cp.cwd)` for methods that have post-dispatch provider work
   (`create_commit`, `create_pull_request`). Wrap in `try/except NotImplementedError` — for hg providers this is
   expected and handled as a no-op with a warning log (the hg-side follow-up is deferred per the plan's "Risks and
   Follow-ups"). On `(False, err)`, print the error and return `RunResult.FAILED`.

6. Call `wf._run_tracking_steps(cp, cp.dispatch_result)` — the shared helper from Phase 2 that executes
   `create_changespec`, `write_result_marker`, `append_commits_entry`, and the final `write_result_marker`-with-entry-id
   in order. The helper already skips steps whose name is in `cp.completed_steps` — but also make it **observation-level
   idempotent**:
   - For `create_changespec`: before calling, probe whether a ChangeSpec named `cp.cs_name` (or the computed
     `reserved_name`) already exists via the project file. If yes, skip.
   - For `append_commits_entry`: pass `expected_entry_id=cp.entry_id` (now meaningful thanks to Phase 2's kwarg).

7. On full success: `checkpoint.delete()` and `return RunResult.OK`. Emit telemetry:

   ```python
   VCS_OPERATIONS.labels(
       provider=provider._provider_name,
       operation="commit_resume",
       status="ok",
   ).inc()
   ```

   On the failure paths emit `status="failed"` / `status="conflict"` analogously.

The classmethod signature is `classmethod` because there is no outer payload/method to construct it from — those come
from the checkpoint.

#### 5. `tests/test_commit_workflow_resume.py` (new, ~180 lines)

End-to-end tests for the resume path, all using `MagicMock` for the VCS provider so we do not need a real repo. Use
`pytest` fixtures to set up a temporary `SASE_ARTIFACTS_DIR` and monkeypatch `get_vcs_provider`.

- `test_resume_returns_failed_when_no_checkpoint` — no checkpoint on disk → `RunResult.FAILED`, no side effects.
- `test_resume_returns_conflict_when_sync_still_in_progress` — checkpoint exists; provider's `is_sync_in_progress`
  returns `True` → `RunResult.CONFLICT` AND the checkpoint file **is not deleted**.
- `test_resume_returns_failed_on_subject_mismatch` — checkpoint message = `"feat: original"`, but mocked `git log`
  returns `"feat: different"` → `RunResult.FAILED` AND checkpoint NOT deleted.
- `test_resume_replays_tracking_after_conflict_resolution` — checkpoint with `completed_steps=[]`; mock
  `vcs_finalize_commit` to succeed; all four tracking steps are called in order; final exit is `RunResult.OK` AND
  checkpoint is deleted.
- `test_resume_skips_already_completed_tracking_steps` — checkpoint with
  `completed_steps=["dispatch", "create_changespec", "write_result_marker"]`; only `append_commits_entry` and the final
  marker write are invoked. Use MagicMock `call_args_list` to verify.
- `test_resume_handles_pull_request_path` — checkpoint with `method="create_pull_request"`; `create_changespec` is
  called; `append_commits_entry` is NOT called (PR path uses ChangeSpec, not COMMITS entry).
- `test_resume_is_idempotent_across_repeated_invocations` — first `resume()` succeeds and deletes checkpoint; a second
  `resume()` returns `RunResult.FAILED` ("nothing to resume") without side effects.
- `test_resume_tolerates_hg_missing_finalize_commit` — mock provider's `finalize_commit` to raise `NotImplementedError`;
  resume still replays tracking and returns `RunResult.OK`. This validates the hg-deferral contract.
- `test_append_commits_entry_idempotent_on_resume` — pre-populate COMMITS drawer with `(99) note` and pass
  `expected_entry_id="99"` via the resume path; assert no duplicate entry is added and `"99"` is returned.

### Verification

- `just install && just check` passes from the workspace root.
- `pytest tests/test_commit_workflow_resume.py -v` passes.
- `pytest tests/test_commit_workflow_dispatch.py tests/test_commit_workflow_checkpoint.py tests/workflows/test_commit_workflow.py -v`
  still passes (no regression in Phase 1/Phase 2 tests).
- `rg "def resume" src/sase/workflows/commit/workflow.py` → one match (the new classmethod).
- `rg "finalize_commit" src/sase/vcs_provider/` → matches in `_hookspec.py`, `_base.py`, and the git dispatch plugin.
- No changes to `src/sase/main/parser_commands.py`, `src/sase/main/cl_handler.py` (beyond what Phase 2 left), or
  `src/sase/xprompts/skills/` in this phase. Diff check to confirm.

---

## Phase 4: Surface — CLI Flag + Skill Instructions + End-to-End Wiring

**Goal.** Expose the resume path to users and agents via `sase commit --resume` and per-VCS skill instructions. This
phase makes the feature fully functional from an agent's point of view.

### Context a fresh agent needs

- Phases 1–3 have landed: checkpoints are written, `RunResult.CONFLICT` is returned + exit code 2 is emitted,
  `CommitWorkflow.resume()` exists as a Python API, and `vcs_finalize_commit` is implemented for git.
- Per `.sase/memory/long-generated-skills.md`: the chezmoi `SKILL.md` files are **generated**, not hand-edited. After
  editing any source under `src/sase/xprompts/skills/`, run `sase init-skills --force`. `chezmoi apply` is the user's
  responsibility — mention it in the verification section but do NOT run it as part of this change.
- Claude does NOT have `/sase_hg_commit` installed (`skill: [gemini]` in the hg source file) — do NOT re-add it to
  Claude. Treat all runtimes uniformly beyond that frontmatter scope — do not branch on provider name in the skill body
  (beyond the existing Jinja conditionals that are already there).
- Per `memory/short/gotchas.md`, every sase CLI option needs both a short AND a long form. `-r/--resume`, not just
  `--resume`.
- The sync-style conflict-resolution recipe lives at `src/sase/xprompts/sync.yml:29–53` — base the git recipe on lines
  29–41 and the hg recipe on lines 42–53.
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/main/parser_commands.py` (modify)

Extend `register_commit_parser` with a new flag:

```python
commit_parser.add_argument(
    "-r",
    "--resume",
    action="store_true",
    help=(
        "Resume a previously-checkpointed commit after manual conflict "
        "resolution. When set, -m/-M/-f and other commit args are ignored."
    ),
)
```

Place it after the existing `-t/--type` argument. Do not attempt to declare any `required=False` conditional logic in
argparse — validation that "resume + message" is not useful is a soft warning at most; argparse itself accepts both.

#### 2. `src/sase/main/cl_handler.py` (modify)

Update `handle_commit_command` to handle the resume branch:

```python
if args.resume:
    from sase.workflows.commit.workflow import (
        CommitWorkflow,
        EXIT_CODE_CONFLICT,
        RunResult,
    )

    result = CommitWorkflow.resume()
    if result == RunResult.OK:
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_resumed")
        except Exception:
            pass
        sys.exit(0)
    if result == RunResult.CONFLICT:
        sys.exit(EXIT_CODE_CONFLICT)
    sys.exit(int(result))
```

Place this guard **before** any payload assembly — `--resume` ignores `-m`/`-M`/`-f`/etc. entirely.

#### 3. `src/sase/xprompts/skills/sase_git_commit.md` (modify)

Append a new section after the existing `## Example` section:

````markdown
## On Merge Conflict

If `sase commit` exits with code **2** and prints a "merge conflict" message, the local working tree is in a paused
rebase/merge state and the post-commit bookkeeping has been deferred. Do NOT re-run the original `sase commit` command —
that would attempt to re-stage and re-commit on top of the already-resolved state. Instead, resolve the conflict and
finalize:

1. **Find conflicted files**: Run `git diff --name-only --diff-filter=U`.
2. **Read each file** and resolve conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`):
   - Content between `<<<<<<< HEAD` and `=======` is YOUR version.
   - Content between `=======` and `>>>>>>> <commit>` is the INCOMING version.
   - Prefer the INCOMING version when uncertain — it's the more recent change.
   - NEVER leave conflict markers in any file.
3. **Stage resolved files**: Run `git add <file>` for each.
4. **Continue the rebase/merge**: Run `git -c core.editor=true rebase --continue` (or `git merge --continue` for a
   non-rebase merge). If this produces more conflicts, repeat steps 1–4 until clean.
5. **Verify the working tree is clean**: `git status` should show "nothing to commit, working tree clean".
6. **Finalize the sase commit**: Run `sase commit --resume`. This replays the post-commit bookkeeping (push, ChangeSpec
   row, COMMITS entry, result marker) and exits 0 on success.

```bash
sase commit --resume
```
````

Base the wording on `src/sase/xprompts/sync.yml:29–41`, adapted for the commit-resume flow. The Jinja frontmatter /
conditionals used elsewhere in this file are untouched.

#### 4. `src/sase/xprompts/skills/sase_hg_commit.md` (modify)

Append an analogous section after the existing `## Example` section:

```markdown
## On Merge Conflict

If `sase commit` exits with code **2** and prints a "merge conflict" message, the local repository is in a paused
evolve/rebase state and the post-commit bookkeeping has been deferred. Do NOT re-run the original `sase commit` command.
Instead, resolve the conflict and finalize:

1. **Find conflicted files**: Run `hg resolve --list` (lines starting with `U` are unresolved).
2. **Read each file** and resolve conflict markers. Prefer the INCOMING version when uncertain.
3. **Mark resolved**: Run `hg resolve --mark <file>` for each.
4. **Continue the rebase/evolve**: Run `hg rebase --continue` (or `hg evolve --continue`). Repeat steps 1–4 until clean.
5. **Verify the working tree is clean**: `hg status` should be empty.
6. **Finalize the sase commit**: Run `sase commit --resume`.
```

Base the wording on `src/sase/xprompts/sync.yml:42–53`. Keep the Gemini-only `skill: [gemini]` frontmatter as-is — do
NOT add `claude` to the provider list.

#### 5. Regenerate deployed SKILL.md files

After editing the two source files above, run:

```bash
sase init-skills --force
```

Per `.sase/memory/long-generated-skills.md`, this regenerates `~/.claude/skills/sase_git_commit/SKILL.md`,
`~/.gemini/skills/sase_git_commit/SKILL.md`, `~/.codex/skills/sase_git_commit/SKILL.md`, and
`~/.gemini/skills/sase_hg_commit/SKILL.md` (hg is Gemini-only — Claude does NOT get it). Do NOT run `chezmoi apply` —
that is the user's responsibility. Mention it in the verification section below so the user knows to run it when
deploying.

#### 6. `tests/test_commit_cli_resume_flag.py` (new, ~60 lines)

- `test_parser_exposes_resume_flag` — construct the parser (via the same entry point other CLI tests use, likely
  `sase.main.parser.create_parser` or similar — match existing patterns in `tests/test_commit_cli.py`); assert
  `-r`/`--resume` is accepted; `args.resume` is `True` when present and `False` when absent.
- `test_resume_flag_invokes_workflow_resume` — monkeypatch `CommitWorkflow.resume` to return `RunResult.OK`; invoke
  `handle_commit_command` with `args.resume=True`; assert `CommitWorkflow.resume` was called exactly once with no
  positional args; assert `sys.exit(0)`.
- `test_resume_flag_maps_conflict_to_exit_2` — monkeypatch `CommitWorkflow.resume` to return `RunResult.CONFLICT`;
  assert `sys.exit(2)`.
- `test_resume_flag_skips_payload_assembly` — monkeypatch `CommitWorkflow.__init__` to fail; `args.resume=True`; assert
  no `CommitWorkflow(...)` instance is constructed — the resume branch calls the classmethod directly.

### Verification

- `just install && just check` passes from the workspace root.
- `pytest tests/test_commit_cli_resume_flag.py -v` passes.
- `pytest tests/test_commit_workflow_resume.py tests/test_commit_workflow_dispatch.py tests/test_commit_workflow_checkpoint.py tests/workflows/test_commit_workflow.py -v`
  still passes.
- `sase commit --help` shows `-r, --resume` in the output.
- `sase init-skills --force` regenerates the deployed `SKILL.md` files. Diff against the prior versions shows the new
  `## On Merge Conflict` section has been added to:
  - `~/.claude/skills/sase_git_commit/SKILL.md` (chezmoi path: `dot_claude/...`)
  - `~/.gemini/skills/sase_git_commit/SKILL.md`
  - `~/.codex/skills/sase_git_commit/SKILL.md`
  - `~/.gemini/skills/sase_hg_commit/SKILL.md` (Gemini only — `~/.claude/skills/sase_hg_commit/` MUST NOT exist)

- **Manual smoke test — conflict path**: in a throwaway git repo wired to a remote, force a `_merge_with_master`
  conflict by pre-committing a file that clashes with `origin/master`. Run `sase commit -m "smoke"`. Observe:
  - exit code **2**
  - `commit_state.json` exists in `$SASE_ARTIFACTS_DIR` (or `~/.sase/commit_state/<ts>.json` outside an agent)
  - console prints the "merge conflict … run `sase commit --resume` to finish" warning

  Resolve manually (`git add <file>` for each conflict, `git -c core.editor=true rebase --continue`), then run
  `sase commit --resume`. Observe:
  - exit code **0**
  - COMMITS entry appended to the project `.gp` file
  - local HEAD pushed to `origin`
  - `commit_state.json` is gone

- **Manual smoke test — no-conflict path**: run a normal `sase commit -m "happy"` and confirm exit code 0 and no
  leftover `commit_state.json`. (Phase 2 guarantees the pre-dispatch checkpoint is deleted on success.)

- **`chezmoi apply` (user action, not automated)**: remind the user to run `chezmoi apply` to push the regenerated
  `SKILL.md` files to their live locations. Call this out in the phase report.

---

## Cross-Phase Constraints

- **Skill generation contract** — per `.sase/memory/long-generated-skills.md`, after editing any source file under
  `src/sase/xprompts/skills/`, run `sase init-skills --force`. Do NOT hand-edit chezmoi skill files. Claude does NOT
  have `/sase_hg_commit` installed; do not re-add it (see the skill matrix in that memory file).
- **CLI options** — per `memory/short/gotchas.md`, every sase CLI option must have both a short AND a long form. Use
  `-r/--resume` (Phase 4), not just `--resume`.
- **Build gate** — per `memory/short/build_and_run.md` + `memory/short/workspaces.md`, each phase must run
  `just install && just check` before closing. If the workspace is stale, `just install` first.
- **Treat all runtimes uniformly** — per `memory/short/gotchas.md`, do NOT branch on Claude vs Gemini vs Codex in skill
  bodies or workflow code. The `/sase_hg_commit` frontmatter-level scoping is the only permitted runtime-specific
  divergence in this plan.
- **Strict phase ordering** — P1 must land before P2 starts, and so on. Each phase's "Verification" is the handoff
  contract: the next agent relies on the listed invariants being true before beginning.

---

## Risks and Follow-ups

- **Hg `vcs_finalize_commit` not implemented here.** The git mixin is the only plugin that implements
  `vcs_finalize_commit` in Phase 3. The hg plugin lives in `retired Mercurial plugin` (see `memory/long/external_repos.md`) and needs
  an analogous implementation that re-runs `mail` / `upload` idempotently. Phase 3's `resume()` tolerates a
  `NotImplementedError` from `finalize_commit` so the hg-flavored bookkeeping (ChangeSpec, COMMITS entry,
  `commit_result.json`) is still recovered even without hg-side push/mail. File a follow-up bead during Phase 3; the hg
  skill language already describes the intended end-state so it does not need re-editing when the hg plugin catches up.
- **Stale checkpoint files.** If the agent dies between the conflict and `--resume`, the checkpoint outlives the
  session. The fallback path `~/.sase/commit_state/<SASE_AGENT_TIMESTAMP>.json` uses a per-session id (mirrors
  `sase_commit_stop_hook.py:279`) so collisions across concurrent agents are impossible. A monthly cron-style cleanup of
  files older than 7 days could be added as a follow-up but is not required.
- **Checkpoint schema evolution.** The dataclass has a `version: int = 1` field. Future schema changes bump the version;
  `load()` returns `None` for unknown versions and logs a warning. No automatic migration is planned in this iteration.
- **Partial-write recovery.** The atomic write (`.tmp` + `os.replace`) guarantees any checkpoint on disk is the prior
  version or the new version — never partial. Tracking steps are individually idempotent (each is a function of `cp`
  plus current VCS state), so re-running after a crash mid-step is safe.
- **`CommitWorkflow.run()` return type change.** Going from `bool` to `IntEnum` is a breaking change for any external
  caller. A grep for `CommitWorkflow().run()` before this plan returned only `cl_handler.py` + test files + one stale
  `__pycache__` entry — no plugin repo invokes this workflow directly (plugins implement `vcs_*` hooks, not workflow
  classes). Phase 1 migrates the only known callers.
- **Pre-dispatch checkpoint on happy path is wasted I/O.** One JSON write of ~1 KB per `sase commit` call. Acceptable —
  the workflow already writes `commit_diff.diff` before dispatch (`commit_tracking.py:79`), so we are not adding a new
  I/O class, just a second small file.
- **Telemetry rollout.** The new `commit_resume`, `commit_conflict_detected`, and `finalize_commit` operation labels
  show up in the existing `VCS_OPERATIONS` counter automatically. No Grafana panel changes are required for visibility;
  a follow-up could add a "conflict resume rate" panel slice.
- **Skill rollout coupling.** The skill changes take effect only after `sase init-skills --force` runs (Phase 4) and the
  user runs `chezmoi apply`. Until then, agents will not know about `--resume` and will continue to silently leave
  checkpoints behind. This is not a correctness regression — the fresh-run path is unchanged — just a rollout
  coordination note.

## Out of Scope

- Solution E (post-completion hook auto-finalization). Can be layered on top of A in a follow-up.
- Changing the VCS dispatch `(bool, str | None)` contract.
- Hg-side `vcs_finalize_commit` (lives in `retired Mercurial plugin`, separate change).
- A general "list / clean" CLI for stale checkpoints (`sase commit --list-checkpoints`).
- Resuming `sase commit` after a non-conflict failure (e.g. push rejected by server hook). This iteration's resume
  contract is "the commit exists locally; finish the bookkeeping". A failed push without a local commit has no
  meaningful resume target.
