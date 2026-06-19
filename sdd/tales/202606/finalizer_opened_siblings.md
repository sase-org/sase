---
create_time: 2026-06-19 17:08:44
status: done
prompt: sdd/prompts/202606/finalizer_opened_siblings.md
---
# Plan: Commit finalizer only checks sibling repos the agent actually opened

## Problem

The commit finalizer currently inspects **every configured** sibling repo for uncommitted changes when an agent run
ends. For siblings with `workspace_strategy == "suffix"` (numbered workspace clones such as `sase-nvim_10`), a dirty
working tree is treated as **required** and forces follow-up commit passes / a finalizer failure. For
`workspace_strategy == "none"` (static repos such as the chezmoi dotfiles checkout), it is only **advisory**.

This produces **false positives**. The `research.u.image` agent failed at finalization because `sase-nvim_10` was dirty
— but that agent never touched `sase-nvim`. The dirt was left behind by a _different_, unexpectedly-terminated agent run
that had opened `sase-nvim`. Because the finalizer checks all configured suffix siblings for the agent's workspace
number regardless of whether _this_ run touched them, leftover dirt in a shared numbered workspace fails an unrelated
agent. Today the only workaround is to manually clean up stray sibling workspaces.

### Why "opened" is the right signal

Per the generated agent memory (`init_memory/roots.py`), agents **MUST** run
`sase workspace open -p <sibling_repo> <workspace_num>` before touching a numbered-workspace sibling. So "opened via
`sase workspace open`" is, by construction, the set of numbered siblings an agent could legitimately have modified. If
the finalizer restricts its required checks to that set, leftover dirt in siblings the run never opened can no longer
fail it.

## Goal

Make the commit finalizer check a **suffix-strategy** sibling repo for required dirty state **only if the current agent
run opened it** via `sase workspace open`. Siblings the run never opened are ignored, eliminating the cross-run false
positives and removing the need to manually clean stray sibling workspaces.

Advisory (`none`-strategy) siblings are **out of scope** for gating — see "Decisions" below.

## Key findings from code exploration

- **Finalizer dirty scan**: `src/sase/llm_provider/commit_finalizer_state.py`.
  - `collect_dirty_state(project_dir, *, artifact_root)` builds `sibling_targets` via `_configured_sibling_targets`
    (from `SASE_SIBLING_REPOS_JSON` env, else config resolution), then splits them into required
    (`_dirty_configured_sibling_repos`) and advisory (`_dirty_configured_advisory_sibling_repos`).
  - `_dirty_configured_sibling_repos_for_strategy(...)` (lines ~94-114) is the single loop that iterates **all**
    `sibling_targets` and runs `git_changed_files` on each. Required vs advisory is selected by
    `(target.workspace_strategy == "none") != advisory`.
  - `collect_dirty_state` already receives `artifact_root: Path | None` — the per-run artifacts directory — so it can
    read a per-run marker without new plumbing.
  - Each `SiblingTarget` carries `name`, `workspace_dir`, `workspace_strategy`.

- **Artifacts dir resolution**: `commit_finalizer_artifacts.artifact_root(artifacts_dir)` returns
  `artifacts_dir or os.environ["SASE_ARTIFACTS_DIR"]`. The finalizer already writes `commit_finalizer_result.json` here.
  This dir is **per agent run** (timestamped), so it is the correct scope for "what did _this run_ open" — unlike the
  shared numbered workspace, which is a reused slot, and unlike the sibling's `registry.json`, which persists across
  runs.

- **`sase workspace open` for a sibling**: `src/sase/main/workspace_handler_list.py` `handle_open_clean`.
  `ctx = resolve_project_context(args.project)`; for a sibling this is produced by
  `_materialize_sibling_project_context` in `src/sase/main/workspace_handler_context.py`, which returns a
  `ProjectContext` whose `project_name` is the sibling's configured `name`. The materialized checkout path is
  `path = resolve_checkout(ctx, workspace_num, materialize=True)`, then `prepare_workspace(path, ...)`. There is
  currently **no flag** distinguishing a sibling-open from a primary-open.

- **Env inheritance**: `sase workspace open` is run by the agent through its Bash tool, so the subprocess inherits the
  run's `SASE_ARTIFACTS_DIR` (set via `publish_phase_env`). When `sase workspace open` is run manually (outside an
  agent), `SASE_ARTIFACTS_DIR` is unset.

- **Existing tests**: `tests/llm_provider/test_commit_finalizer_siblings.py` exercises suffix and none strategies (env-
  and config-sourced); several tests create a dirty **suffix** sibling and expect a follow-up pass.
  `tests/main/test_workspace_handler_list_path.py` covers `handle_open_clean` (`test_open_*`).

- **Rust core boundary**: the finalizer (`llm_provider/commit_finalizer*`) and `sase workspace open`
  (`main/workspace_handler_*`) are entirely Python; the "which siblings did this run open" state is part of the Python
  agent-run lifecycle (the artifacts dir). No other frontend needs to mirror this behavior, so per the boundary litmus
  test this stays in Python — no `sase-core` change.

## Design

### 1. Record opened siblings to a per-run marker

Introduce a small marker file, `opened_siblings.json`, in the agent run's artifacts directory. Shape:

```json
{
  "schema_version": 1,
  "siblings": [{ "name": "sase-nvim", "workspace_dir": "/abs/path/to/sase-nvim_10" }]
}
```

Add two best-effort helpers (home: **`src/sase/sibling_repos.py`**, already imported by both the finalizer state module
and the workspace CLI, so there is one source of truth for the filename and format):

- `record_opened_sibling(name, workspace_dir)` — resolve the artifacts dir from `SASE_ARTIFACTS_DIR`; if unset, no-op
  (covers manual / non-agent invocations). Otherwise read-modify-write the marker, **unioning by `name`** (idempotent
  across repeated opens), with an atomic write. Swallow IO errors like the other finalizer artifact writers.
- `opened_sibling_names(artifact_root)` — read the marker under the given artifacts dir and return the set of opened
  sibling names; return an empty set if the file is missing/unreadable.

### 2. Mark sibling-open contexts and record on open

- Add `is_sibling: bool = False` to `ProjectContext` (`src/sase/main/workspace_handler_context.py`). The default keeps
  every existing constructor (primary path, `_current_project_context`) unchanged;
  `_materialize_sibling_project_context` sets `is_sibling=True`.
- In `handle_open_clean` (`workspace_handler_list.py`), after `prepare_workspace` succeeds and before `print(path)`,
  call `record_opened_sibling(ctx.project_name, path)` when `ctx.is_sibling`. This records the **final materialized
  checkout path** for the requested workspace number and only persists when invoked inside an agent run (env present).

### 3. Gate required sibling checks on the opened set

In `commit_finalizer_state.py`:

- In `collect_dirty_state`, compute `opened = opened_sibling_names(artifact_root)` once.
- Thread `opened` into the **required** scan (`_dirty_configured_sibling_repos` →
  `_dirty_configured_sibling_repos_for_strategy` with `advisory=False`): skip any suffix target whose `name` is not in
  `opened`. Matching is by sibling **name** (stable config identity; the agent opens at its own workspace number, so the
  resolved `workspace_dir` already matches).
- Leave the **advisory** scan (`advisory=True`, `none` strategy) unchanged.

Net effect: a suffix sibling is required-checked only if the run opened it; if the run opened nothing (no marker), no
suffix siblings are required-checked.

## Decisions (call out for review)

1. **Only gate suffix-strategy siblings; leave `none`-strategy advisory checks unchanged.** Rationale: `none`-strategy
   siblings (e.g. chezmoi) are exposed at their real primary path and are never opened via `sase workspace open`; they
   are advisory-only and never block. The reported pain (`sase-nvim_10`) is a suffix sibling. Gating advisory checks on
   a marker that is never written for them would silently drop them. _Alternative if desired: also require advisory
   siblings to be opened — not recommended._

2. **Default when no marker exists → check no suffix siblings.** This is the intent-matching, false-positive-free
   default. Tradeoff: if recording ever fails for a sibling the agent did modify, the finalizer won't catch its
   uncommitted changes (a potential false negative). This is acceptable because (a) the user explicitly wants to stop
   worrying about stray sibling dirt, and (b) the "agents MUST `sase workspace open`" policy makes opened ≡ touched, so
   recording happens exactly when the agent legitimately modifies a numbered sibling. Recording is best-effort but
   robust (atomic, union, error-swallowing).

3. **Marker scope = per-run artifacts dir.** Chosen over the numbered workspace dir or the sibling's `registry.json`,
   both of which persist across runs and would re-introduce the cross-run false positive.

## Risks / edge cases

- **Artifacts-dir consistency.** The writer (`sase workspace open` subprocess) keys off `SASE_ARTIFACTS_DIR`; the reader
  (finalizer) uses `artifact_root(artifacts_dir)`, which falls back to the same env var and is the same dir the
  finalizer already writes its result into. Confirm during implementation that the prompt-execution phase's
  `SASE_ARTIFACTS_DIR` equals the `artifacts_dir` passed to `run_commit_finalizer` (expected: yes, set together by the
  runner).
- **Agent modifies a numbered sibling without opening it.** Out of policy; would no longer be caught. Acceptable per
  Decision 2.
- **Manual `sase workspace open`.** `SASE_ARTIFACTS_DIR` unset → recording is a no-op; finalizer behavior outside an
  agent run is unaffected.
- **Repeated opens of the same sibling.** Union-by-name keeps the marker idempotent.

## Files to change

- `src/sase/sibling_repos.py` — marker filename + `record_opened_sibling` / `opened_sibling_names` helpers.
- `src/sase/main/workspace_handler_context.py` — `ProjectContext.is_sibling` flag; set it in
  `_materialize_sibling_project_context`.
- `src/sase/main/workspace_handler_list.py` — record opened sibling in `handle_open_clean`.
- `src/sase/llm_provider/commit_finalizer_state.py` — load opened set in `collect_dirty_state` and filter the required
  suffix scan by it.

## Tests

- `tests/llm_provider/test_commit_finalizer_siblings.py`:
  - **Regression (core fix):** dirty suffix sibling with **no** opened marker → ignored, finalizer reports clean, no
    follow-up pass.
  - Dirty suffix sibling **with** opened marker → triggers follow-up (existing behavior preserved).
  - Multiple suffix siblings, only a subset opened → only opened ones are checked.
  - `none`-strategy advisory sibling still reported regardless of marker presence.
  - **Update existing** dirty-suffix-sibling tests to write the opened marker so they still assert a follow-up (the
    behavior they cover now requires the sibling to have been opened).
- `tests/test_sibling_repos.py`: `record_opened_sibling` union/idempotency, `opened_sibling_names` read, missing-file
  and unset-env (no-op) behavior.
- `tests/main/test_workspace_handler_list_path.py`: `handle_open_clean` records the opened sibling when `ctx.is_sibling`
  and `SASE_ARTIFACTS_DIR` is set; does **not** record for a primary open or when the env var is unset.

## Out of scope

- Changing `none`-strategy / advisory behavior.
- Cleaning up or garbage-collecting stale sibling workspaces (this change makes that unnecessary for finalization
  correctness; physical cleanup remains a separate concern).
- Any `sase-core` / Rust changes.

## Validation

- `just install` (ephemeral workspace) then `just check` (lint + mypy + tests) before handing back.
