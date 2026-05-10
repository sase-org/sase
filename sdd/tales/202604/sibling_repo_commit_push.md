---
create_time: 2026-04-29 12:23:30
status: done
prompt: sdd/prompts/202604/sibling_repo_commit_push.md
---
# Plan: Fix sibling repo commit/push guidance

## Problem

Agents launched from a `sase_<N>` workspace can edit a primary sibling repo such as `../sase-core`. The workspace-level
`sase_commit_stop_hook` only checks the current workspace, so the repo-local `tools/sase_sibling_commit_stop_hook` is
responsible for catching those sibling edits.

The sibling hook is wired for Codex in `~/.codex/hooks.json` and for Claude/Gemini in the tracked project settings. A
manual smoke run against the current dirty `../sase-core` repo confirms the hook blocks and emits:

```text
Uncommitted changes detected in sibling repo(s): sase-core.
Did you make these changes? If so, please commit them using your /sase_git_commit skill before continuing.
```

That message identifies the repo by basename but does not tell the agent to `cd` into the dirty sibling repo before
using the commit skill. Since slash skills operate in the agent's current workspace unless explicitly redirected, an
agent can reasonably inspect/commit the main `sase_<N>` checkout instead of `../sase-core`, or skip the sibling repo's
push verification entirely.

There is a second clarity issue: the `/sase_git_commit` skill correctly uses `sase commit`, and the git provider's
`create_commit` path does call `git push` internally via `_push_with_retry()`. But neither the sibling-hook message nor
the skill requires an explicit post-command check that the sibling branch is no longer ahead of its upstream. If
`sase commit` is not run from the sibling repo, or if an agent falls back to raw git commands, the workflow can leave
local commits unpushed.

## Goals

1. Make the sibling hook's block message unambiguous for dirty sibling repos like `../sase-core`.
2. Require agents to change into each listed sibling repo before invoking `/sase_git_commit`.
3. Make the expected push outcome explicit: after the commit workflow, the sibling repo should be clean and not ahead of
   its upstream; if it is ahead, run `git push` or fix/report the push failure.
4. Preserve existing once-per-session deduplication and runtime-specific hook protocols.
5. Add regression coverage for the new actionable message, including the Codex JSON path.

## Implementation

### Phase 1: Improve sibling hook message construction

Update `tools/sase_sibling_commit_stop_hook`:

- Track dirty sibling repos as paths relative to the project workspace, e.g. `../sase-core`, not only basenames.
- Include a concrete workflow in the block message:
  - `cd ../sase-core`
  - use `/sase_git_commit` from inside that repo
  - after `sase commit`, run `git status --short --branch`
  - if the branch is ahead of upstream, run `git push`
- Keep the Gemini-specific text command-oriented, but also make it change into the sibling repo and verify/push.
- Continue to list all dirty sibling repos if more than one is dirty, with a clear "repeat for each repo" instruction.

### Phase 2: Strengthen commit skill verification

Update `src/sase/xprompts/skills/sase_git_commit.md` so the generated skill tells all runtimes:

- `sase commit` normally handles the push for git repos.
- After it exits successfully, run `git status --short --branch`.
- If the branch is still ahead of upstream, run `git push`.
- Do not declare the commit finished while the repo is dirty or ahead unless there is a real push failure to report.

Because skill files are generated, run `sase init-skills --force --no-commit --no-push --no-apply` after editing the
source template to verify generation without touching chezmoi deployment.

### Phase 3: Tests

Update `tests/test_sibling_commit_stop_hook.py`:

- Existing dirty sibling tests should assert the message includes `../retired chat plugin` and `cd ../retired chat plugin`.
- Codex JSON test should assert the JSON reason includes the same path-aware instructions and push verification.
- Add a multiple-sibling test if practical, to verify the "repeat for each repo" wording.

Add or update skill-template coverage if there is an existing suitable test surface; otherwise rely on the generation
smoke command and targeted hook tests.

### Phase 4: Verification

Run:

- `just install`
- targeted hook tests, e.g. `pytest tests/test_sibling_commit_stop_hook.py`
- `sase init-skills --force --no-commit --no-push --no-apply`
- `just check`

Also manually rerun the sibling hook with `CODEX_PROJECT_DIR=$PWD` while `../sase-core` is dirty and confirm the block
message says to work from `../sase-core` and verify/push that repo.

## Expected outcome

When a stop hook catches dirty `../sase-core` changes, the agent receives instructions that point at the actual sibling
repo and explicitly close the push loop. The commit workflow remains centralized in `sase commit`, while the prompt
surface prevents agents from committing the wrong checkout or treating an unpushed local commit as complete.
