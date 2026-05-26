---
create_time: 2026-05-26 19:10:57
status: done
prompt: sdd/prompts/202605/commit_finalizer_cross_workspace.md
---
# Plan: Commit Finalizer Cross-Workspace Dirty State

## Root Cause

The failed run was agent `bht`, launched in workspace `/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_16/`
with artifacts at `~/.sase/projects/sase/artifacts/ace-run/20260526185142`.

Its finalizer result was:

```json
{
  "status": "clean",
  "reason": "no_changes",
  "project_dir": "/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_16/"
}
```

That was technically true for `sase_16`, but the agent created
`sdd/epics/202605/structured_episodic_memory_mvp_infographic.png` in the separate checkout
`/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_17/`. The tool log records those writes via absolute paths
to `sase_17`, and `git -C .../sase_17 status --short --branch` still shows the PNG as untracked.

The current commit finalizer only inspects the resolved active project directory plus configured sibling repositories
for the active workspace number. It does not inspect same-repository checkout variants that the agent explicitly touched
during the run. That leaves a gap for cross-workspace same-repo edits: the agent can write to `sase_17`, but the
finalizer checks only `sase_16` and exits cleanly.

## Design

Extend the provider-neutral commit finalizer so its dirty-state collection includes "observed workspaces": git
repositories outside the active project directory that are:

1. Explicitly referenced in the current run's tool-call artifacts;
2. The same git repository as the active project, based on git root and remote identity;
3. Dirty at finalization time; and
4. Tied to the current run by either exact dirty-file path evidence in the tool log or file mtimes after the agent's
   recorded `run_started_at`.

This avoids scanning every numbered checkout and avoids pulling unrelated dirty workspaces into the finalizer just
because they exist. The finalizer will still use the same bounded pass loop and the same `/sase_git_commit` instruction
model, but the prompt will include an explicit `cd <observed-workspace>` instruction like sibling repos do.

## Implementation Steps

1. Add artifact-aware dirty-state collection in `src/sase/llm_provider/commit_finalizer.py`.
   - Thread the existing `artifact_root` into `_collect_dirty_state`.
   - Read `tool_calls.jsonl` and `agent_meta.json` best-effort.
   - Extract absolute path candidates from tool-call summaries and optional `cwd` fields.
   - Resolve candidate git roots, exclude the active project and configured siblings, and keep only same-remote repos.
   - Filter dirty files to changes plausibly made in this run.

2. Represent observed workspaces distinctly in finalizer details.
   - Extend `_DirtyRepo.kind` with an observed-workspace value.
   - Label them separately from configured sibling repos.
   - Reuse `/sase_git_commit` instructions with `cd <path>` guidance.

3. Add focused regression tests.
   - A dirty same-repo workspace referenced by tool calls triggers a follow-up finalizer turn.
   - An old dirty same-repo workspace that was merely referenced is ignored.
   - A dirty referenced repo with a different remote is ignored.

4. Verify.
   - Run focused finalizer tests.
   - Run `just install` first if needed, then `just check` because this changes repo code.

## Expected Outcome

The previous `sase_16`/`sase_17` infographic case would no longer report `clean`. The finalizer would detect the dirty
observed workspace, instruct the agent to `cd` into `sase_17`, and force the normal commit workflow before allowing the
run to finish cleanly.
