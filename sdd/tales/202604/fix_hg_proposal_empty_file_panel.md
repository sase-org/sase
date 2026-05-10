---
create_time: 2026-04-24 17:57:44
status: done
prompt: sdd/prompts/202604/fix_hg_proposal_empty_file_panel.md
---
# Fix empty file panel in `sase ace` after Mercurial proposal

## Problem Statement

In `sase ace`, when a Mercurial agent (Gemini + retired Mercurial plugin plugin) successfully creates a proposal via the
`/sase_hg_commit` skill, the agent's **file panel is empty** (bottom status bar shows `○ files`). This happens even
though:

- The agent's chat reports a successful proposal was created
- The `Proposal Id` meta field is populated in the agent detail pane
- `commit_result.json` on disk contains a valid `diff_path`
- A ChangeSpec `COMMITS` drawer entry was written with the diff path

The same flow on GitHub / bare-git _also_ suffers from this silently (diff path is never round-tripped into
`workflow_state.json`), but the bug is most visible on the hg path because that is the only path the user observed. The
fix should cover both.

## Root Cause

The `diff_path` produced by `sase commit` is stranded in `commit_result.json` and never flows into the workflow state
JSON that the TUI reads for the file panel. Step-by-step:

1. **During agent execution**, `/sase_hg_commit` → `sase commit` runs. Inside
   `src/sase/workflows/commit/commit_tracking.py`:
   - `capture_pre_commit_diff()` (lines 48–84) writes the working-tree diff to `<SASE_ARTIFACTS_DIR>/commit_diff.diff`.
   - `write_result_marker()` (lines 205–231) writes a JSON marker `commit_result.json` including the `diff_path` field.
   - The proposal is then created via the retired Mercurial plugin plugin's `vcs_create_proposal` hook, and the workspace is cleaned.

2. **After the agent finishes**, the `#propose` embedded workflow's post-steps run. The plugin's
   `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/propose.yml` overrides the in-repo `src/sase/xprompts/propose.yml`. The
   plugin version gates every post-step (`save_response`, `propose`, `report`) on `{{ check_changes.has_changes }}`. But
   the skill already committed and cleaned the workspace, so `has_changes` is `false` and **every post-step is
   skipped**. The `report` step (which already emits `diff_path: path`) never runs.

3. **In the executor**, `src/sase/xprompt/workflow_executor_steps_prompt.py` lines 480–518 collect a `diff_path` from
   the _last_ post-step via `_collect_embedded_step_outputs()` (lines 38–77). Because the `report` step was skipped,
   `embedded_diff_path` is `None`. Line 498's branch then **overwrites** the initially-captured `diff_path` (from
   `capture_vcs_diff()` at line 390) with `None`; the trailing comment even reads `# May be None → hides file panel`.

4. **In the TUI loader**, `_workflow_loaders.py:163–186` searches step outputs for a `diff_path` or a `path`-typed
   field. None is found, so the parent `WorkflowEntry.diff_path` is `None`, and `Agent.diff_path` is `None`.

5. **In the file panel**, `file_panel/_diff.py:26–38` returns `None` for DONE agents whose `diff_path` is unset (no
   workspace fallback — workspaces are recycled, so falling back to `hg diff` would be unsafe).

Net result: a valid proposal diff exists on disk, but the TUI has no pointer to it.

### Secondary observation

The in-repo `src/sase/xprompts/propose.yml` already added a `_has_commit_result.exists` probe so its `propose` /
`report` steps do run even when the agent pre-committed. But that file:

- Is overridden by the retired Mercurial plugin plugin copy on hg workspaces.
- Still never emits `diff_path: path` as an output field, so even when its post-steps run, the diff path is not
  surfaced.

The same secondary gap exists in `src/sase/xprompts/commit.yml` and `src/sase/xprompts/pr.yml`.

## Goals

1. On Mercurial / retired Mercurial plugin, the file panel populates after `/sase_hg_commit` creates a proposal.
2. On GitHub / bare-git, the file panel populates after a `#commit` or `#pr` workflow that went through the skill path.
3. The fix must not regress the case where the agent leaves uncommitted changes and the xprompt post-steps do the
   committing themselves (legacy path).
4. Keep the two propose.yml files (in-repo vs. retired Mercurial plugin plugin) consistent in spirit so future edits don't drift.

## Non-Goals

- Reworking the `_collect_embedded_step_outputs()` contract. The existing contract (take the path-typed output of the
  last post-step) is fine; we just need the last post-step to actually produce a value.
- Adding a workspace-based fallback in `file_panel/_diff.py`. The existing comment there (workspaces are recycled) is a
  deliberate design choice.
- Backfilling diffs for already-completed agents. Fix is forward-only.

## Design

### Canonical source of truth

`commit_result.json` in `SASE_ARTIFACTS_DIR` is the canonical post-hoc record of what `sase commit` did. It already
contains `diff_path`. The xprompt `report` steps should read from it and emit `diff_path` (typed as `path`) so the
embedded-output collector and the TUI loader can both pick it up.

### Changes

#### 1. retired Mercurial plugin plugin: `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/propose.yml`

- Insert a hidden `_has_commit_result` probe step (same shape as the in-repo `propose.yml`) that sets `exists: bool`
  based on `commit_result.json` presence.
- Widen every post-step gate from `{{ check_changes.has_changes }}` to
  `{{ check_changes.has_changes or _has_commit_result.exists }}`.
- When `_has_commit_result.exists` is true, the `propose` bash step MUST NOT re-run `sase_propose_workflow --create`
  (that would create a duplicate proposal). Split into two alternative steps (or branch with `if:`):
  - Legacy path (`has_changes` true, no marker): invoke `sase_propose_workflow --create` as today; schema unchanged.
  - Skill path (`_has_commit_result.exists` true): read `proposal_id`, `cl_name`, `diff_path` from `commit_result.json`.
- Ensure the final `report` step reads `diff_path` from either source and always emits `diff_path: path` (non-empty when
  the proposal succeeded).
- Preserve the existing `meta_proposal_id` emission.

#### 2. In-repo `src/sase/xprompts/propose.yml`

- Extend the `report` step to emit `diff_path: path` read from `commit_result.json["diff_path"]`.
- Keep the existing `meta_commit_message`, `meta_proposal_id` fields.

#### 3. In-repo `src/sase/xprompts/commit.yml`

- Extend the `report` step to emit `diff_path: path` read from `commit_result.json["diff_path"]`.

#### 4. In-repo `src/sase/xprompts/pr.yml`

- Extend the `report` step to emit `diff_path: path` read from `commit_result.json["diff_path"]`.

### Why `diff_path: path` on the `report` step (not a new dedicated step)

`_collect_embedded_step_outputs()` inspects the **last** post-step. Adding a new tail step would require all three
xprompts to grow the same tail. Keeping the emission on the existing `report` step (already the tail of each workflow)
means no ordering risk and minimal churn.

### Risk: duplicate proposal creation

The current retired Mercurial plugin `propose.yml` calls `sase_propose_workflow --create` unconditionally when `has_changes` is true.
If a future skill path somehow left `has_changes=true` _and_ wrote `commit_result.json`, we'd double-propose. Guarding
the legacy branch with `if: "{{ check_changes.has_changes and not _has_commit_result.exists }}"` makes the two branches
mutually exclusive.

### Risk: stale `commit_result.json` from a prior run

`SASE_ARTIFACTS_DIR` is per-agent-run, so each run starts with a fresh artifacts directory. No stale-marker risk in
normal operation.

## Test Plan

### Unit / integration tests in `sase_100`

1. `tests/xprompt/test_propose_yml.py` (new or existing file):
   - Simulate a run where `commit_result.json` is pre-written (skill path). Assert the `report` step output contains
     `diff_path` equal to the marker's value.
   - Simulate a run where `has_changes=true` and no marker. Assert the existing legacy emission still works.
2. `tests/xprompt/test_commit_yml.py` and `tests/xprompt/test_pr_yml.py`: analogous coverage for the `diff_path`
   emission in `report`.
3. `tests/xprompt/test_workflow_executor_embedded.py`:
   - End-to-end: run a mock embedded workflow whose last post-step emits a `path` field. Assert
     `_collect_embedded_step_outputs` returns that path and `step_state.output["diff_path"]` is populated.

### Tests in `retired Mercurial plugin`

1. `tests/xprompts/test_propose_yml.py`:
   - Skill path: marker present, `has_changes=false`. Assert `report.diff_path` equals the marker's value and that
     `sase_propose_workflow --create` was NOT invoked.
   - Legacy path: marker absent, `has_changes=true`. Assert the bash step invokes `sase_propose_workflow --create`
     exactly once and the report step emits its `diff_path`.

### Manual verification

1. On an hg workspace, trigger `sase ace` with a `#propose` workflow that uses `/sase_hg_commit` during execution.
2. After the agent completes, open the agent in `sase ace`, switch to file view (`v`), and confirm the proposal's diff
   renders.
3. Repeat on a git workspace with `#commit` / `#pr`.

## Files to Change

| File                                                  | Type                              |
| ----------------------------------------------------- | --------------------------------- |
| `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/propose.yml` | rework gates + split commit path  |
| `src/sase/xprompts/propose.yml`                       | add `diff_path: path` to `report` |
| `src/sase/xprompts/commit.yml`                        | add `diff_path: path` to `report` |
| `src/sase/xprompts/pr.yml`                            | add `diff_path: path` to `report` |
| `tests/xprompt/test_*_yml.py` (sase)                  | new/extended coverage             |
| `../retired Mercurial plugin/tests/xprompts/test_propose_yml.py`   | new/extended coverage             |

## Post-Implementation

- Run `just check` in `sase_100` (required before reporting).
- Run `just check` in `../retired Mercurial plugin` (plugin repo).
- If any chezmoi skill files consume the `diff_path` output (unlikely but check `src/sase/xprompts/skills/`), run
  `sase init-skills --force` + `chezmoi apply` per memory/long-generated-skills.
