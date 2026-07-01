---
create_time: 2026-07-01 09:13:40
status: done
prompt: sdd/prompts/202607/chezmoi_apply_target_path_and_force.md
---
# Plan: Fix `chezmoi apply` "not in source state" on config/model-alias edits, and always use `--force`

## Summary

Two related changes to how SASE invokes `chezmoi apply`:

1. **Bug fix.** Writing a model-alias edit (or any config edit) from the TUI while `use_chezmoi` is enabled fails with:

   ```
   chezmoi apply failed: chezmoi: /home/<user>/.local/share/chezmoi/home/dot_config/sase/sase.yml: not in source state
   ```

   The code writes the edit to the chezmoi **source** file (correct), but then hands that **source** path to
   `chezmoi apply`. `chezmoi apply` expects **target** (home) paths, so it rejects the source path as "not in source
   state". Fix: apply the **target** path instead.

2. **Enhancement.** Make every `chezmoi apply` invocation in SASE pass `--force`, so applies are non-interactive and
   never stall or fail on a confirmation prompt.

## Background

When `use_chezmoi` is on, a config edit is _source-preserving_: instead of editing the applied copy in `~/.config/...`,
SASE edits the chezmoi source under `~/.local/share/chezmoi/home/...` and then runs `chezmoi apply` to propagate the
change back out to the home target.

The path translation lives in `src/sase/config/targets.py`:

- `chezmoi_source_path(target)` maps a home target (e.g. `~/.config/sase/sase.yml`) to its chezmoi source
  (`~/.local/share/chezmoi/home/dot_config/sase/sase.yml`, using chezmoi's `dot_` encoding).
- `resolve_write_path(file, use_chezmoi=True)` returns that source path as the write target.
- `apply_chezmoi(path=None)` is a thin wrapper that runs `chezmoi apply [path]`.

The planning/execution data flow (`src/sase/config/edit.py`):

- `ConfigWritePlan.file` — the **original home target** path (verified absolute; e.g.
  `/home/<user>/.config/sase/sase.yml`).
- `EditPlanResult.target_path` — the **remapped write path** (the chezmoi _source_ when `use_chezmoi` is on).
- `apply_config_edit(plan)` writes `plan.new_text` to `plan.target_path` (the source) and returns `AppliedResult.path` =
  that same **source** path.

## Root cause

Both edit modals feed the **source** path into `chezmoi apply`:

- `src/sase/ace/tui/modals/models_panel_edit.py:214` — `apply_chezmoi(applied.path)`
- `src/sase/ace/tui/modals/config_edit_modal.py:300` — `apply_chezmoi(result.path)`

`applied.path` / `result.path` is the chezmoi **source** path. `chezmoi apply` interprets its positional argument as a
**target** (home) path; a source path is not a managed target, so chezmoi errors with "not in source state". The correct
argument is the original home target, which is already available in scope as `plan.write_plan.file`.

Because `plan.write_plan.file` is guaranteed non-`None` whenever `used_chezmoi` is true and the write succeeded (a
`None` file yields a `None` `target_path`, which makes `apply_config_edit` raise before ever reaching the
`apply_chezmoi` call), this is a safe substitution.

## Goals / scope

- **G1** — Config/model-alias edits with `use_chezmoi` enabled apply cleanly instead of failing "not in source state".
- **G2** — Every `chezmoi apply` invocation in SASE uses `--force`.
- **Non-goals** — No change to the _source-preserving write_ behavior, the diff preview, or the git commit/push flow. No
  change to chezmoi's `dot_` path encoding.

## Part 1 — Fix the source-vs-target path bug

Pass the **home target** path (not the source path) to `chezmoi apply` in both modals.

- `src/sase/ace/tui/modals/models_panel_edit.py` (`action_confirm` apply worker): replace `apply_chezmoi(applied.path)`
  with a call that passes the original target, `plan.write_plan.file` (the `plan` object is already captured in the
  worker closure).
- `src/sase/ace/tui/modals/config_edit_modal.py` (`_start_apply` apply worker): same substitution,
  `apply_chezmoi(result.path)` → target `plan.write_plan.file`.

The chezmoi apply now runs **scoped to the single edited target** (e.g.
`chezmoi apply --force /home/<user>/.config/sase/sase.yml`), preserving the original intent of a narrow, one-file apply
rather than a repo-wide apply that could clobber unrelated pending chezmoi diffs.

### Edge-case hardening (optional but recommended)

When the edited file is _not_ under `$HOME`, `chezmoi_source_path` returns it unchanged, so no real source→target remap
happened even though `used_chezmoi` is true. Applying chezmoi to such a file would also fail "not in source state". SASE
config targets always live under `~/.config`, so this does not occur in practice today, but to be robust the apply
branch should only run when a remap actually occurred (i.e. the resolved write path differs from the original target).
Implement as a small guard rather than new plumbing.

## Part 2 — Always use `--force` for `chezmoi apply`

Centralize on the shared wrapper and make `--force` the standard.

### 2a. Make the wrapper force by default

- `src/sase/config/targets.py` `apply_chezmoi(path=None)`: build the command as
  `["chezmoi", "apply", "--force", <path?>]`. Expand `~` in the path (`Path(path).expanduser()`) so a target is always
  an absolute home path chezmoi can resolve. Keep returning the `CompletedProcess` and not raising on non-zero. (A
  keyword like `force=True` may be added for symmetry, but the default is always-force.)

This automatically covers both edit modals (they call `apply_chezmoi`).

### 2b. Route the two ad-hoc invocations through the wrapper

Both currently build `["chezmoi", "apply"]` inline; refactor them to call `apply_chezmoi()` (no path → full apply, now
forced), keeping their existing `FileNotFoundError` handling and result/notify logic:

- `src/sase/ace/tui/modals/xprompt_browser_actions.py` `_run_chezmoi_apply`.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt_git.py` `run_git_commit_push_sync`.

### 2c. Init deploy path

- `src/sase/main/_init_chezmoi_deploy.py` `deploy_to_chezmoi`: the apply command is already conditionally forced via
  `behavior.apply_force`. Make it **unconditionally** `--force` and simplify the failure label to always read "chezmoi
  apply --force failed".
- Remove the now-redundant `apply_force` toggle so no dead switch is left behind:
  - Drop the `apply_force` field from `ChezmoiDeployBehavior` and `_DeferredChezmoiDeploy`, the OR-merge in
    `_DeferredChezmoiDeploy.add`, the `apply_force` parameter of `defer_chezmoi_paths`, and the pass-through in
    `deploy_deferred_chezmoi`.
  - `src/sase/main/init_memory_handler.py`: drop the two `apply_force=True` keyword args.

  (Lower-churn fallback if we'd rather keep the struct stable: leave the field in place but make the command always
  append `--force` regardless of it. Recommended path is the clean removal, since the toggle becomes meaningless once
  every apply is forced.)

### Rationale for `--force`

These applies run as captured subprocesses with no interactive stdin. Without `--force`, chezmoi can pause for
confirmation when a destination file has diverged, which would hang or fail the call. `--force` makes every apply
deterministic and non-interactive — which is the desired behavior for automation-driven applies.

## Testing plan

- **Regression for the bug (new):** add a modal apply-worker test with `used_chezmoi=True` that monkeypatches the
  module-level `apply_chezmoi` (imported into both `models_panel_edit` and `config_edit_modal`) and asserts it is called
  with the **home target** path (`plan.write_plan.file`), never the chezmoi source path. Existing apply-flow modal tests
  use `used_chezmoi=False` and won't exercise this branch, so this new coverage is what guards the fix.
- **Wrapper (new):** a `targets.apply_chezmoi` unit test asserting the built command includes `--force` and that a
  `~`-prefixed path is expanded.
- **Update existing tests affected by always-force:**
  - `tests/main/test_init_skills_deploy.py` — the failure-label assertion currently checks `"chezmoi apply failed"`;
    update to `"chezmoi apply --force failed"`.
  - `tests/main/test_init_onboarding_flow.py` — remove the `apply_force` fixture parameter usage now that
    `defer_chezmoi_paths` drops it; the existing `assert apply == ["chezmoi", "apply", "--force"]` assertion still
    holds.
  - `tests/main/test_init_memory_chezmoi.py` — remove the `deferred.apply_force is True` assertion (field removed).
- **Repo checks:** run `just install` then `just check` (this repo requires it after file changes). No Rust core changes
  are needed — all `chezmoi` execution lives in the Python layer — so the Rust backend boundary is not crossed.

## Risks and considerations

- **Scoped vs. full apply.** The bug fix keeps the modal applies scoped to the single edited target, which is safer than
  a repo-wide apply. The two ad-hoc sites remain full applies (unchanged in scope, only gaining `--force`).
- **Force semantics.** `--force` will overwrite a diverged destination without prompting. This is the intended,
  explicitly requested behavior and matches the non-interactive context of these calls.
- **Test breakage is bounded** to the three init test files enumerated above; a grep for `apply_force` and
  `chezmoi.*apply` confirmed there are no other assertions on the command shape.

## Out of scope

- Reworking chezmoi source/target path encoding.
- Changing the git commit/push behavior around chezmoi.
- Any interactive/confirmation UX for applies (we are intentionally making them non-interactive).
