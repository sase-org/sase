---
create_time: 2026-05-24 11:42:07
status: done
prompt: sdd/prompts/202605/static_sibling_finalizer.md
---
# Plan: Ignore Static Sibling Repos in Commit Finalizer Failures

## Goal

Prevent the commit finalizer from failing an otherwise successful agent when the only remaining sibling-repository
changes are in configured static siblings whose `workspace.strategy` is `none`.

Static siblings, such as a shared chezmoi checkout, are not per-agent workspaces. They can legitimately contain changes
from another still-running agent, so the finalizer cannot safely treat their dirty state as proof that the current agent
failed to commit its own work.

## Current Behavior

The finalizer discovers configured sibling repositories from `SASE_SIBLING_REPOS_JSON` when available, or falls back to
resolving `SASE_AGENT_PROJECT_FILE` config. In both paths it keeps only a sibling `name` and `workspace_dir`, then
checks every resolved sibling with `git status --porcelain`.

That loses `workspace_strategy`, even though sibling resolution already computes and exports it. As a result, static
siblings using `workspace.strategy: none` are treated the same as numbered sibling workspaces using the default `suffix`
strategy. Dirty static siblings can trigger follow-up commit-finalizer passes and then fail with:

```text
Commit finalizer failed: uncommitted changes remain after ...
```

## Design

1. Preserve workspace strategy in finalizer sibling targets.
   - Extend the finalizer's internal sibling target model to include `workspace_strategy`.
   - When reading `SASE_SIBLING_REPOS_JSON`, read `workspace_strategy` from the exported metadata.
   - Treat missing or invalid strategy metadata as `suffix` to preserve compatibility with older/minimal env payloads.
   - When falling back to config resolution, pass through each resolved repo's `workspace_strategy`.

2. Exclude static siblings from finalizer-enforced dirty state.
   - Skip dirty checks for targets whose `workspace_strategy` is `none`.
   - Keep main-workspace dirty handling unchanged.
   - Keep default/suffix sibling dirty handling unchanged.
   - This means a dirty static sibling does not trigger follow-up finalizer passes, and if a suffix sibling is cleaned
     while a static sibling remains dirty, the finalizer still succeeds.

3. Keep user-facing errors scoped to actionable repositories.
   - Failure details, `changed_files`, and commit instructions should only mention the main workspace and sibling repos
     whose strategy is not `none`.
   - Do not ask the agent to commit shared static sibling changes from the finalizer, because ownership is ambiguous.

## Tests

Add focused tests in `tests/llm_provider/test_commit_finalizer_siblings.py`:

- Env-provided dirty sibling with `workspace_strategy: "none"` is ignored; the provider is not invoked and the dirty
  static file can remain.
- Config-fallback dirty sibling with `workspace.strategy: none` is ignored.
- Mixed dirty siblings only include the non-`none` sibling in the follow-up prompt, and the finalizer succeeds after
  that sibling is cleaned even if the static sibling is still dirty.

Existing tests should continue to prove that suffix/default siblings still trigger finalizer follow-up and failure
behavior.

## Verification

Run the targeted finalizer tests first:

```bash
python -m pytest tests/llm_provider/test_commit_finalizer_siblings.py
```

Then run the broader relevant checks if the focused tests pass:

```bash
python -m pytest tests/test_sibling_repos.py tests/llm_provider/test_commit_finalizer_siblings.py
```

If time permits, run the repo's standard check command:

```bash
just check
```
