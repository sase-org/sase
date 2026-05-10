---
create_time: 2026-04-17 20:24:36
status: wip
prompt: sdd/prompts/202604/commit_resume.md
---

# Plan: Resumable `sase commit` After Agent-Resolved Merge Conflicts

## Background

When an agent runs its `/sase_git_commit` or `/sase_hg_commit` skill, the command invokes `sase commit`, which calls
`CommitWorkflow.run()` (`src/sase/workflows/commit/workflow.py:61`). That `run()` dispatches to a VCS-specific provider
hook (`vcs_create_commit` / `vcs_create_proposal` / `vcs_create_pull_request`), then runs a series of post-dispatch
"tracking" steps:

1. `create_changespec` (PR only)
2. `write_result_marker` — `commit_result.json` for downstream xprompt steps
3. `append_commits_entry` — adds the `(N) <note>` line to the project `.gp` file
4. (For PR / commit dispatch) `_post_commit_bead_amend` and `_push_with_retry` happen _inside_ the dispatch

If anything inside dispatch raises a merge conflict (git `_merge_with_master` aborting, hg `evolve` mid-commit), the
dispatch returns `(False, err)` and `CommitWorkflow.run()` returns `False` at `workflow.py:154`. All five tracking steps
are then silently skipped. The agent (which is good at resolving conflicts — see attached `sase ace` snapshot in
`sdd/research/202604/commit_conflict_resume.md`) resolves the conflict and ends up with a clean local commit, but no ChangeSpec
row, no COMMITS entry, no push, and no `commit_result.json` for the xprompt post-steps.

The agent has no affordance today for finishing the bookkeeping, so the user-visible "I committed your changes" message
is a false positive from sase's perspective.

This plan implements **Solution A** from `sdd/research/202604/commit_conflict_resume.md`: a resumable `CommitWorkflow` with a JSON
checkpoint file, surfaced via `sase commit --resume` and explicit per-VCS skill instructions modeled on
`src/sase/xprompts/sync.yml`.

## Goal

After this change:

1. When `sase commit` hits a merge conflict, it persists a JSON checkpoint and exits with a **distinct non-zero exit
   code (2)** so the calling agent can recognize "conflict needs manual resolution" vs. "generic failure".
2. The agent's commit skill (`/sase_git_commit`, `/sase_hg_commit`) gains a "## Conflict Resolution" section that
   instructs the agent to (a) resolve conflicts using VCS-specific steps from `sync.yml`, (b) verify the local commit
   exists, then (c) run `sase commit --resume`.
3. `sase commit --resume` reads the checkpoint, probes current VCS state, runs only the missing tracking steps
   (idempotently), and deletes the checkpoint on success.
4. The fresh-run path is unchanged when no conflict occurs: same return value, same behavior, same tests.
5. New unit tests cover checkpoint round-tripping, the resume entry point, and the new exit code.

## Non-goals

- We do NOT change conflict-resolution authority — the agent still resolves the conflict itself, just like in
  `sync.yml`.
- We do NOT add a post-completion hook that auto-finalizes (Solution E from the research). It can be layered on top of A
  later if the agent forgets `--resume` in practice.
- We do NOT split `sase commit` into separate `--vcs-only` / `--finalize` subcommands (Solution B). The one-shot UX on
  the no-conflict path stays one shot.
- We do NOT change anything inside the VCS dispatch hooks. The dispatch contract (`(bool, str | None)`) is unchanged.
  Conflict detection happens in `CommitWorkflow.run()` _after_ dispatch returns `False`, by probing
  `provider.is_sync_in_progress(cwd)` and the working tree.
- We do NOT introduce dispatch-substep idempotency (Solution F). The resume path re-runs only the tracking steps and any
  provider-level finalization (e.g. `_push_with_retry`, `_post_commit_bead_amend`) that wasn't reached.

## Files to Add or Modify

### New files

#### `src/sase/workflows/commit/checkpoint.py` (~120 lines)

A small module that owns the checkpoint dataclass and its persistence. Responsibilities:

- Define the `_CommitCheckpoint` dataclass with fields:
  - `version: int = 1` — schema version for forward-compat.
  - `method: str` — one of `create_commit`, `create_proposal`, `create_pull_request`.
  - `payload: dict` — the **mutated** payload (after `handle_beads`, `handle_sase_plan`, `apply_project_pr_prefix`,
    `append_pr_tags`, `build_pr_body`). This is what the resume path replays from.
  - `cwd: str`
  - `cl_name: str | None`
  - `project_file: str | None`
  - `diff_path: str | None`
  - `base_cl_name: str | None`
  - `reserved_name: str | None`
  - `parent_cl_name: str | None`
  - `dispatch_result: str | None` — commit hash or PR URL, populated only after dispatch succeeds.
  - `cs_name: str | None`
  - `entry_id: str | None`
  - `completed_steps: list[str]` — names of finished post-dispatch steps: `"dispatch"`, `"create_changespec"`,
    `"write_result_marker"`, `"append_commits_entry"`, `"final_result_marker"`.
  - `created_at: float` — `time.time()` when first written, for stale-checkpoint debugging.

- `def get_checkpoint_path() -> str`:
  - Prefer `os.path.join(os.environ["SASE_ARTIFACTS_DIR"], "commit_state.json")` when the env var is set.
  - Fall back to `os.path.expanduser("~/.sase/commit_state/<session>.json")` where `<session>` is
    `os.environ.get("SASE_AGENT_TIMESTAMP") or str(os.getpid())`. Mirrors the dedup-key pattern at
    `src/sase/scripts/sase_commit_stop_hook.py:279`.
  - Create the parent directory if it doesn't exist.

- `def save(cp: _CommitCheckpoint) -> str`: write JSON atomically (write to `path + ".tmp"` → `os.replace`). Returns the
  path written. **Must tolerate failure to write** (just `print_status("warning", ...)` and continue) — losing the
  checkpoint must not abort the workflow.

- `def load(path: str | None = None) -> _CommitCheckpoint | None`: read and `json.loads` → dataclass. Returns `None` if
  the file is missing, malformed, or has an unknown `version` (forward-compat: future versions log a warning and refuse
  to resume).

- `def delete(path: str | None = None) -> None`: best-effort `os.remove`, swallow `FileNotFoundError`.

The dataclass uses simple JSON-serializable types so we can `dataclasses.asdict` → `json.dump`. No pickle.

#### `tests/test_commit_workflow_checkpoint.py` (~80 lines)

Unit tests for the new module:

- `test_save_and_load_round_trip` — write a populated dataclass, read it back, assert field equality.
- `test_load_returns_none_when_missing` — `load("/nonexistent")` → `None`.
- `test_load_returns_none_for_unknown_version` — write `{"version": 999, ...}` → `load()` returns `None`.
- `test_get_checkpoint_path_uses_artifacts_dir` — when `SASE_ARTIFACTS_DIR` is set, path lives inside it.
- `test_get_checkpoint_path_falls_back_to_session` — when not set, uses
  `~/.sase/commit_state/<SASE_AGENT_TIMESTAMP>.json`.
- `test_delete_is_idempotent` — calling `delete()` twice does not raise.
- `test_save_writes_atomically` — pre-create a `.tmp` file with junk, call `save()`, assert the final file content is
  correct (validates the rename semantics).

### Modified files

#### `src/sase/workflows/commit/workflow.py`

The biggest change. Three concrete edits:

1. **Add a module-level constant** `EXIT_CODE_CONFLICT = 2` (exported via `__all__`). Document that `EXIT_CODE_CONFLICT`
   is returned to the CLI when the workflow detects a merge-conflict state mid-dispatch.

2. **Refactor `CommitWorkflow.run()` to write a checkpoint after each post-dispatch step** and to detect conflicts:
   - After all pre-dispatch mutations to the payload (lines 87–134) but **before** calling the provider dispatch (line
     150), build a `_CommitCheckpoint` snapshot with `completed_steps=[]` and `dispatch_result=None`. Call
     `checkpoint.save(cp)`. This guarantees that even if dispatch fails immediately we have a recoverable checkpoint
     reflecting the post-mutation payload.

   - After dispatch returns `(ok, result)`:
     - If `ok` is `False`: probe `provider.is_sync_in_progress(cwd)` (and, as a belt-and-suspenders backup, the presence
       of any `<<<<<<< ` markers in `provider.get_conflicted_files(cwd)` results when available). If a conflict is in
       progress, return a new sentinel `RunResult.CONFLICT` (or use a tri-state) so the caller can map it to exit
       code 2. If not a conflict, fall through to existing failure handling — call `cleanup_reservation` and delete the
       checkpoint, then return `RunResult.FAILED` (mapped to exit 1).
     - If `ok` is `True`: update `cp.dispatch_result = result`, append `"dispatch"` to `cp.completed_steps`, and
       `checkpoint.save(cp)`.

   - For each tracking step (`create_changespec`, `write_result_marker`, `append_commits_entry`, `write_result_marker`
     again with `entry_id`), record the resulting field on `cp` and append the step name to `cp.completed_steps`, then
     `checkpoint.save(cp)`.

   - On full success: `checkpoint.delete()` and return `RunResult.OK` (mapped to exit 0).

   The existing return-type signature `def run(self) -> bool` widens to `def run(self) -> "RunResult"` (an `IntEnum`
   defined in `workflow.py`). The callers in `cl_handler.py` and the existing tests update accordingly. This is a small
   breaking change limited to internal callers, but it's the cleanest way to get a third exit-code path without
   overloading `bool`.

3. **Add `CommitWorkflow.resume()`** as a new entry point:

   ```python
   @classmethod
   def resume(cls) -> "RunResult":
       """Resume a previously-checkpointed commit workflow."""
   ```

   Behavior:
   - Read checkpoint at `checkpoint.get_checkpoint_path()`. If missing, print a friendly error ("No commit checkpoint
     found — nothing to resume") and return `RunResult.FAILED`.
   - Construct a `CommitWorkflow` from `cp.method` and `cp.payload`, manually populate `_base_cl_name`,
     `_reserved_name`, `_parent_cl_name`, `_diff_path`, `_cl_name`, `_project_file` from `cp`.
   - **Probe VCS state** via the provider:
     - For `create_commit` / `create_pull_request`: ensure `is_sync_in_progress(cwd) == False` (conflict was resolved);
       if still in progress, print "Conflicts not yet resolved — run `git rebase --continue` / `hg rebase --continue`
       first" and return `EXIT_CODE_CONFLICT`.
     - Confirm a commit exists at HEAD whose subject matches `cp.payload["message"].splitlines()[0]`. If not, print
       "Could not find resumable commit at HEAD — please re-run `sase commit` from scratch" and return
       `RunResult.FAILED`. Use `provider.get_description("HEAD", cwd)` if the method exists (hg) or
       `git log -1 --format=%s` for git. Provide a small helper in the workflow module rather than threading a new
       abstract method.
   - **Re-run any unfinished provider work** that the original dispatch didn't reach. Concretely, for git
     `vcs_create_commit`: if HEAD is committed but `_push_with_retry` likely never ran (we infer this from
     `cp.completed_steps`, which won't contain `"dispatch"` because dispatch returned `False`), call a new tiny helper
     `provider.finalize_commit(cwd, payload)` that:
     - Re-runs `_post_commit_bead_amend` (idempotent — it checks for changes before amending) and
     - Re-runs `_push_with_retry` (idempotent — `git push` of nothing-new is a no-op exit 0).

     This helper is added to the git mixin only as part of this plan; hg's equivalent (re-mailing, re-uploading) can be
     added as a later iteration since the immediate motivating scenario is `git`-flavored. For hg, the resume path skips
     provider finalization and only replays tracking steps. (See "Risks and Follow-ups".)

   - **Replay missing tracking steps** in order (`create_changespec` for PR, then `write_result_marker`, then
     `append_commits_entry` for commit/proposal, then a final `write_result_marker` with `entry_id`). For each step,
     skip if its name is already in `cp.completed_steps` AND the side effect is observable (e.g. ChangeSpec already
     exists, COMMITS entry with this `entry_id` already present). After each step succeeds, append to `completed_steps`
     and re-save the checkpoint.
   - On full success: `checkpoint.delete()` and return `RunResult.OK`.

   The replay order mirrors the `run()` order so a single helper `_run_tracking_steps(cp)` can be shared between `run()`
   and `resume()` to keep both paths in lockstep.

#### `src/sase/workflows/commit/commit_tracking.py`

Make tracking steps **idempotent** so resume can replay them safely:

- `write_result_marker(...)` — already idempotent (overwrites `commit_result.json` unconditionally). No change.
- `append_commits_entry(...)` — currently appends a new entry every call. Add an early-return:
  - If `entry_id` from a prior call is already present in the COMMITS drawer of `cl_name` (look for line
    `(<entry_id>) `), return that existing `entry_id` without re-appending. This requires accepting an optional
    `expected_entry_id: str | None = None` argument that the resume path passes.
- `create_changespec(...)` — currently calls `create_changespec_for_workflow`, which itself uses
  `compute_suffixed_cl_name` with a reservation. The resume path should call `create_changespec(...)` only when no
  ChangeSpec named `cp.cs_name` exists; add a small `changespec_exists(...)` probe (we already have one at
  `src/sase/workflows/commit/changespec_queries.py`). The probe lives in `resume()`, not inside `create_changespec`, so
  we don't change the fresh-run signature.

Concretely, only `append_commits_entry` gains a new optional kwarg; the others stay the same shape.

#### `src/sase/main/cl_handler.py`

- Import `RunResult` from `sase.workflows.commit.workflow`.
- In `handle_commit_command`:
  - If `args.resume` is truthy:
    - Skip all payload assembly. Call `CommitWorkflow.resume()`.
    - Map `RunResult.OK → 0`, `RunResult.CONFLICT → 2`, `RunResult.FAILED → 1`.
    - `sys.exit(...)`.
  - Otherwise, the existing path: build payload, create `CommitWorkflow(payload, method)`, call `run()`, map the new
    tri-state to exit codes (success → log + exit 0; conflict → exit 2; failed → exit 1).

#### `src/sase/main/parser_commands.py`

- Add a new optional flag to `register_commit_parser`:

  ```python
  commit_parser.add_argument(
      "-r",
      "--resume",
      action="store_true",
      help="Resume a previously-checkpointed commit after manual conflict resolution",
  )
  ```

  Per `memory/short/gotchas.md`, every CLI option must have both a short and long form, hence `-r/--resume`.

  Also: when `--resume` is set, `-m`/`-M`/`-f`/etc. are ignored. Document this in the `--resume` help text.

#### `src/sase/xprompts/skills/sase_git_commit.md`

Add a new section after the existing `## Example` section:

```md
## On Merge Conflict

If `sase commit` exits with code 2 and prints a "merge conflict" message, the local working tree is in a paused
rebase/merge state and the post-commit bookkeeping has been deferred. Resolve the conflict and finalize:

1. **Find conflicted files**: `git diff --name-only --diff-filter=U`
2. **Read each file** and resolve markers (`<<<<<<<`, `=======`, `>>>>>>>`):
   - Content between `<<<<<<< HEAD` and `=======` is YOUR version.
   - Content between `=======` and `>>>>>>> <commit>` is the INCOMING version.
   - Prefer the INCOMING version when uncertain — it's the more recent change.
3. **Stage resolved files**: `git add <file>` for each.
4. **Continue the rebase/merge**: `git -c core.editor=true rebase --continue` (or `git merge --continue` for a
   non-rebase merge). Repeat steps 1–4 if more conflicts surface.
5. **Verify the working tree is clean**: `git status` should show "nothing to commit, working tree clean".
6. **Finalize the sase commit**: `sase commit --resume`. This runs the post-commit bookkeeping (push, ChangeSpec row,
   COMMITS entry, result marker) and exits 0 on success. Do NOT re-run the original `sase commit` command — that would
   attempt to re-stage and re-commit on top of the already-resolved state.
```

#### `src/sase/xprompts/skills/sase_hg_commit.md`

Add an analogous section for hg, mirroring the conflict-resolution recipe in `src/sase/xprompts/sync.yml:42–53`:

```md
## On Merge Conflict

If `sase commit` exits with code 2 and prints a "merge conflict" message, the local repository is in a paused
evolve/rebase state and the post-commit bookkeeping has been deferred. Resolve the conflict and finalize:

1. **Find conflicted files**: `hg resolve --list` (lines starting with `U` are unresolved).
2. **Read each file** and resolve conflict markers.
3. **Mark resolved**: `hg resolve --mark <file>` for each.
4. **Continue the rebase/evolve**: `hg rebase --continue` (or `hg evolve --continue`). Repeat steps 1–4 if more
   conflicts surface.
5. **Verify the working tree is clean**: `hg status` should be empty.
6. **Finalize the sase commit**: `sase commit --resume`. This runs the post-commit bookkeeping (mail/upload, ChangeSpec
   row, COMMITS entry, result marker) and exits 0 on success.
```

(Note: hg `mail`/`upload` resume isn't fully wired in this iteration — see "Risks and Follow-ups". The skill sentence
still describes the intended end-state so it doesn't need to change in the follow-up.)

#### Skill regeneration

Per `.sase/memory/long-generated-skills.md`, after editing the source `.md` files we must run:

```bash
sase init-skills --force
```

`chezmoi apply` is the user's responsibility (the init-skills handler does NOT auto-run it). The plan's verification
step lists this. The handler discovers source skills from `src/sase/xprompts/skills/`, renders Jinja2, and writes to
`~/.<provider>/skills/<name>/SKILL.md` (or chezmoi-managed path when `get_use_chezmoi()` returns `True`). Both
`sase_git_commit.md` and `sase_hg_commit.md` already exist in the source dir so no new skill registration is needed.

#### `src/sase/vcs_provider/_base.py` and `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`

Add one new optional method to `VCSProvider`:

```python
def finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    """Re-run idempotent post-commit operations (push, bead amend) after a resume."""
    raise NotImplementedError("finalize_commit is not supported by this VCS provider")
```

Also add a corresponding `vcs_finalize_commit` hookspec in `_hookspec.py` (matching the existing pattern with
`firstresult=True`).

Implement in `GitCommitDispatchMixin`:

```python
@hookimpl
def vcs_finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    if not payload.get("_skip_bead_amend"):
        self._post_commit_bead_amend(payload, cwd)
    return self._push_with_retry(cwd)
```

`_push_with_retry` and `_post_commit_bead_amend` are already idempotent (push is a no-op if up-to-date; amend skips when
there are no `sdd/beads/` changes).

#### Telemetry

In `CommitWorkflow.run()` and `resume()`, increment `VCS_OPERATIONS` (already imported in `_git_commit_dispatch.py`)
with new operation labels:

- `operation="commit_resume", status="ok" | "conflict" | "failed"` from inside `resume()`.
- `operation="commit_conflict_detected"` from inside `run()` when we map dispatch failure → conflict.

This matches the existing telemetry pattern at `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:188–191`. We do
NOT need to add a new metric in `src/sase/telemetry/metrics.py` — the labels live within the existing
`sase_vcs_operations_total` counter.

### Test additions

#### `tests/test_commit_workflow_resume.py` (new, ~150 lines)

End-to-end tests for the resume path, all using `MagicMock` for the VCS provider so we don't need a real repo:

- `test_run_writes_pre_dispatch_checkpoint` — call `run()` with a provider that fails at dispatch; assert a checkpoint
  file exists with `completed_steps=[]` and the post-mutation payload.
- `test_run_detects_conflict_and_returns_conflict_code` — provider returns `(False, "merge conflict")` AND
  `is_sync_in_progress(cwd)` returns `True`; `run()` returns `RunResult.CONFLICT`. Checkpoint persists.
- `test_run_failure_without_conflict_deletes_checkpoint` — provider returns `(False, "auth error")` AND
  `is_sync_in_progress(cwd)` returns `False`; `run()` returns `RunResult.FAILED` AND checkpoint is deleted.
- `test_run_success_deletes_checkpoint` — happy path; no checkpoint file remains after a successful run.
- `test_resume_returns_failed_when_no_checkpoint` — call `resume()` with no checkpoint file → `RunResult.FAILED`.
- `test_resume_returns_conflict_when_sync_still_in_progress` — checkpoint exists; `is_sync_in_progress(cwd)` → `True`;
  `resume()` returns `RunResult.CONFLICT` without touching tracking.
- `test_resume_replays_tracking_after_conflict_resolution` — checkpoint with `completed_steps=[]`; provider's
  `finalize_commit` succeeds; tracking steps are called in order; final exit is `RunResult.OK`.
- `test_resume_skips_already_completed_tracking_steps` — checkpoint with
  `completed_steps=["dispatch", "create_changespec", "write_result_marker"]`; only `append_commits_entry` and the final
  marker write are invoked.
- `test_append_commits_entry_idempotent_on_resume` — pre-populate the COMMITS drawer with `(99) note` and pass
  `expected_entry_id="99"`; assert no duplicate entry is added and `"99"` is returned.
- `test_resume_handles_pull_request_path` — checkpoint with `method="create_pull_request"`; `create_changespec` called;
  `append_commits_entry` NOT called (PR path uses ChangeSpec).

#### Update existing tests

- `tests/test_commit_workflow_dispatch.py`:
  - The `wf.run()` tri-state breaks anything that asserts `is True`/`is False`. Update each affected test to compare to
    `RunResult.OK` / `RunResult.FAILED`. (Roughly 8 assertions across this file.)
  - Add `test_provider_failure_with_conflict_returns_conflict_code` — variant of `test_provider_failure_returns_false`
    where `is_sync_in_progress` returns `True`.
- `tests/workflows/test_commit_workflow.py`:
  - Same `wf.run() is True/False` → `RunResult` updates in `test_explicit_parent_*` (lines 297, 322).
- `tests/test_commit_workflow_artifacts.py`:
  - No interface changes here; only verify nothing regresses (these tests don't call `run()`).

#### CLI parser test (optional but recommended)

Add `tests/test_commit_cli_resume_flag.py` that constructs the parser via `parser.create_parser()` (or equivalent) and
asserts `--resume` is a valid flag whose presence triggers the resume codepath. Mock `CommitWorkflow.resume()` and check
it was called with no payload args.

## Implementation Order

1. **Add `checkpoint.py` + tests** — pure module, no dependencies on the rest of the workflow. Verify with
   `pytest tests/test_commit_workflow_checkpoint.py -v`.

2. **Add `RunResult` enum + `EXIT_CODE_CONFLICT` constant** to `workflow.py`. Update `cl_handler.py` and existing tests
   to consume the enum. Run `just test` and confirm everything still passes (no behavior change yet — `RunResult.OK` is
   true-ish, `RunResult.FAILED` is false-ish via `IntEnum(0/1)`, but make tests explicit anyway to set up for step 3).

3. **Wire checkpoint writes into `run()`** — pre-dispatch save, post-dispatch save (on success only — on conflict the
   pre-dispatch checkpoint is already on disk), per-tracking-step save, success-deletes-checkpoint. Run the full test
   suite. The conflict-detection branch in `run()` lands here too (returning `RunResult.CONFLICT` when
   `is_sync_in_progress` after dispatch failure).

4. **Add `vcs_finalize_commit` hookspec + `VCSProvider.finalize_commit` + git impl**. Run
   `pytest tests/test_vcs_provider_bare_git_plugin.py -v` to confirm the existing git test surface still passes.

5. **Implement `CommitWorkflow.resume()` + idempotency tweaks** to `commit_tracking.py` (`append_commits_entry` only).
   Add the new `tests/test_commit_workflow_resume.py`. Run `just test`.

6. **Wire `--resume` into the parser + CLI handler**. Add the parser test.

7. **Update the two skill source files** with the "## On Merge Conflict" section. Run `sase init-skills --force` to
   regenerate the deployed `SKILL.md` files. (`chezmoi apply` is on the user — call it out in the verification plan but
   don't run it as part of this change.)

8. **Run `just check`** (per `memory/short/build_and_run.md`, this is the gate before terminating). If the workspace is
   stale, `just install` first per `memory/short/workspaces.md`.

## Verification

1. `just install && just check` passes from the workspace root.
2. New tests:
   - `pytest tests/test_commit_workflow_checkpoint.py -v`
   - `pytest tests/test_commit_workflow_resume.py -v`
3. Existing commit-workflow tests still pass with the `RunResult` migration:
   - `pytest tests/test_commit_workflow_dispatch.py tests/test_commit_workflow_artifacts.py tests/workflows/test_commit_workflow.py -v`
4. `sase init-skills --force` regenerates `~/.claude/skills/sase_git_commit/SKILL.md` and
   `~/.gemini/skills/sase_git_commit/SKILL.md` (and `sase_hg_commit/SKILL.md` for gemini only — Claude does not have
   `sase_hg_commit` per `.sase/memory/long-generated-skills.md`).
5. **Manual smoke test (git)** — in a scratch repo, force a merge conflict during `_merge_with_master` (e.g. by
   pre-modifying a file to clash with `origin/master`), invoke `sase commit -m "test"`, observe exit code 2 and a
   `commit_state.json` in `SASE_ARTIFACTS_DIR`. Resolve manually (`git rebase --continue`), then run
   `sase commit --resume` and assert exit code 0, the COMMITS entry is appended, and the checkpoint file is gone.
6. **Manual smoke test (no conflict)** — confirm normal `sase commit -m "test"` still exits 0 and leaves no checkpoint
   behind. (The pre-dispatch save followed by success-deletes-checkpoint should be invisible to the user.)

## Risks and Follow-ups

- **Hg `mail`/`upload` resume isn't covered.** This first iteration adds `vcs_finalize_commit` only on the git mixin.
  The hg dispatch (in the `retired Mercurial plugin` plugin repo, not in `sase_100`) needs an equivalent override that re-runs `mail`
  and `upload` idempotently. Tracked as a follow-up because: (a) the conflict in the snapshot was hg-flavored
  (`hg evolve`), but the user's report says the agent successfully landed the commit locally and only the bookkeeping
  was missing — so a no-op `vcs_finalize_commit` on hg still recovers the bookkeeping; (b) the hg-side push/mail
  re-issue requires editing a separate plugin repo per `memory/long/external_repos.md`. File the follow-up bead during
  this work and reference it from the skill `## On Merge Conflict` section so users know the hg mail/upload step may
  still need a manual `hg uploadchain` after `--resume`.
- **Stale checkpoint files.** If the agent dies between the conflict and `--resume`, the checkpoint outlives the
  session. The `~/.sase/commit_state/<session>.json` fallback uses `SASE_AGENT_TIMESTAMP`, which is unique per agent
  session, so collisions across concurrent agents are not a concern. A monthly cron-style cleanup of files older than 7
  days could be a follow-up but is not required.
- **Checkpoint schema evolution.** The dataclass has a `version: int = 1` field. Future schema changes bump the version;
  `load()` returns `None` for unknown versions and prints a warning. No automatic migration in this iteration.
- **Partial-write recovery.** The atomic write (`.tmp` + rename) means a checkpoint on disk is always either the prior
  version or the new version — never partial. Tracking steps are individually idempotent (each is a function of `cp`
  plus current VCS state), so re-running after a crash mid-step is safe.
- **`CommitWorkflow.run()` return type change.** Going from `bool` to `IntEnum` is a breaking change for any external
  caller. A grep for `CommitWorkflow().run()` returns only `cl_handler.py`, the test files listed above, and a stale
  `_pycache_` entry — no other internal or external callers. Plugin repos do not invoke this workflow directly (they
  implement `vcs_*` hooks).
- **Pre-dispatch checkpoint on a happy path is wasted I/O.** One JSON write of ~1 KB per `sase commit` call. Acceptable
  — the workflow already writes `commit_diff.diff` before dispatch (`commit_tracking.py:79`), so we're not adding a new
  I/O class.
- **Telemetry rollout.** The new `commit_resume` and `commit_conflict_detected` operation labels show up in the existing
  `VCS_OPERATIONS` counter automatically. No Grafana panel changes are required for visibility, but a follow-up could
  add a panel slice for "conflict resume rate".
- **Skill rollout coupling.** The skill changes only take effect after `sase init-skills --force` runs and (for chezmoi
  users) `chezmoi apply` runs. Until then, agents won't know about `--resume` and will continue to silently leave
  checkpoints behind. Not a correctness regression — the fresh-run path is unchanged — just a rollout coordination note.

## Out of Scope

- Solution E (post-completion hook auto-finalization). Can be layered on top of A in a follow-up.
- Changing the VCS dispatch `(bool, str | None)` contract.
- Hg-side `vcs_finalize_commit` (lives in `retired Mercurial plugin`, separate change).
- A general "list / clean" CLI for stale checkpoints (`sase commit --list-checkpoints`). Not needed for the motivating
  bug.
- Resuming `sase commit` after a non-conflict failure (e.g. push rejected by server hook). This iteration's resume
  contract is "the commit exists locally; finish the bookkeeping". A failed push without a local commit doesn't have a
  meaningful resume target.
