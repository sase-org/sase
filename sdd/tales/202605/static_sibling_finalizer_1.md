---
create_time: 2026-05-28 09:37:50
status: done
prompt: sdd/prompts/202605/static_sibling_finalizer_1.md
---
# Plan: Advisory Finalizer Checks for Static Sibling Repositories

## Goal

Fix the commit finalizer so SASE-launched agents are alerted about dirty configured sibling repositories even when the
sibling has `workspace.strategy: none`, while preserving the intended non-blocking behavior for those static siblings.

The finalizer should still fail on uncommitted main-workspace changes and normal workspace-matched sibling changes. It
should not fail only because a static sibling such as chezmoi remains dirty after the agent decides the changes were not
made by that agent, or intentionally leaves them for the human.

## Evidence and Root Cause

The user-level SASE config in `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml` declares:

```yaml
sibling_repos:
  - name: chezmoi
    path: ~/.local/share/chezmoi
    workspace:
      strategy: none
```

The `bm6` agent metadata confirms this was resolved and passed to the agent:

```json
{
  "name": "chezmoi",
  "workspace_dir": "/home/bryan/.local/share/chezmoi",
  "workspace_strategy": "none"
}
```

The `bm6` chat says it edited and applied chezmoi files, but
`/home/bryan/.sase/projects/sase/artifacts/ace-run/20260528090737/commit_finalizer_result.json` recorded:

```json
{
  "status": "clean",
  "reason": "no_changes",
  "passes": 0
}
```

The code path explains that result. `collect_dirty_state()` resolves sibling targets, then
`_dirty_configured_sibling_repos()` immediately skips every target whose `workspace_strategy == "none"`. Existing tests
also encode that behavior by expecting dirty static siblings to be ignored entirely. That made the finalizer unable to
warn `bm6` about its own chezmoi edits.

## Target Behavior

Treat dirty repositories in two categories:

- **Blocking dirty repos:** main workspace and configured workspace-matched siblings. These continue to require cleanup
  and can fail the finalizer after the configured pass limit.
- **Advisory dirty repos:** configured static siblings with `workspace.strategy: none`. These should be listed in a
  follow-up prompt, with instructions to commit them if the agent made the changes, but should not make the finalizer
  fail if they remain dirty.

If only advisory repos are dirty, run a bounded follow-up prompt so the agent sees the warning. If the advisory repo is
still dirty after that prompt, finish successfully with an explicit artifact reason that advisory changes remain.

If both blocking and advisory repos are dirty, include both in the follow-up prompt. Rechecking and failure decisions
should be based only on blocking repos.

## Implementation Plan

1. Extend the commit-finalizer dirty-state model to carry advisory static sibling repositories separately from blocking
   repositories.
   - Keep existing `DirtyState.repos` semantics for blocking repos where possible to minimize blast radius.
   - Add an advisory/static sibling field or equivalent helper accessors rather than changing sibling resolution itself.

2. Change sibling dirty discovery in `src/sase/llm_provider/commit_finalizer_state.py`.
   - Normal `suffix` siblings still go into blocking dirty repos.
   - `none` strategy siblings are checked with `git_changed_files()` and collected as advisory dirty repos instead of
     being skipped.
   - Non-git or unreadable static siblings remain non-fatal and absent, matching current best-effort behavior.

3. Update prompt construction in `commit_finalizer_prompting.py`.
   - Show advisory static sibling repos in a clearly labeled section.
   - Reuse the existing ownership gate: first decide whether the listed changes were made by this session.
   - Tell the agent to `cd` into the static sibling and use the commit skill only if it made the changes.
   - State that leaving advisory static sibling changes uncommitted will not fail the finalizer.

4. Update `run_commit_finalizer()`.
   - Clean means no blocking repos and no advisory repos.
   - If advisory repos are present, invoke the follow-up prompt even when there are no blocking repos.
   - After each pass, return success if blocking repos are clean, regardless of remaining advisory repos.
   - Preserve the current failure path for blocking repos after `max_passes`.

5. Improve finalizer artifacts.
   - Keep `commit_finalizer_result.json` backward-compatible enough for existing consumers.
   - Add an explicit reason such as `advisory_dirty_remaining` or `advisory_clean_after_pass` when static siblings were
     involved.
   - Include advisory changed files in a separate field if practical, so this case is visible during future debugging.

6. Replace and add focused tests in `tests/llm_provider/test_commit_finalizer_siblings.py`.
   - Update current "none strategy dirty sibling is ignored" tests to expect a non-failing advisory follow-up prompt.
   - Add coverage for advisory-only dirty siblings where the provider leaves the repo dirty and the result is
     successful.
   - Add coverage where the provider cleans/commits the advisory repo.
   - Add mixed blocking plus advisory coverage proving static sibling dirtiness is included in the prompt but cannot
     cause failure once blocking repos are clean.
   - Keep existing suffix-sibling failure/finalization behavior intact.

7. Verify.
   - Run the focused finalizer sibling tests first.
   - Run related commit-finalizer tests if the shared prompt/type behavior changes.
   - Run `just install` if needed, then `just check` because this task changes SASE repo files.

## Non-Goals

- Do not change sibling workspace resolution or `workspace.strategy: none`; static siblings must still resolve to their
  primary path.
- Do not force commits in chezmoi or any static sibling.
- Do not modify memory files.
- Do not rewrite the `bm6` historical artifacts.
