---
create_time: 2026-05-11 13:03:47
status: wip
prompt: sdd/prompts/202605/codex_commit_stop_hook_fallback.md
---
# Codex Commit Stop Hook Fallback Plan

## Root Cause

The failing agent was a SASE-launched Codex `exec` session in workspace `/home/bryan/projects/github/sase-org/sase_106`.
Its Codex session transcript goes directly from the final answer to `task_complete`; there is no `<hook_prompt>` event
and `~/.sase_commit_stop_hook.jsonl` has no `script_start` entry near the agent's `END` time of 2026-05-11 12:04:45. The
code changes were still uncommitted when the agent ended, so the problem was not that the agent ignored a commit
request. Codex never received one.

This explains the difference from many other successful runs today: most successful commit handoffs were Claude stop
hooks or agents that explicitly committed as part of bead/epic workflows. The target agent was a plain Codex coding
follow-up after a plan approval, and it relied entirely on Codex's native stop hook delivery. That delivery did not
happen for the `codex exec` session.

The `install_sase_github` script is plausibly related only indirectly. It stops and restarts axe and refreshes the
uv-tool SASE install, but it does not edit Codex hook config. A restart/version/config boundary can expose the Codex
native hook delivery gap, but the on-disk evidence points to missing Codex hook delivery rather than
`sase_commit_stop_hook` itself failing.

## Goal

Make SASE-launched Codex agents reliably get one commit follow-up turn whenever they return with uncommitted changes,
without depending solely on the external Codex CLI Stop hook machinery.

## Design

Add a SASE-managed fallback in `src/sase/llm_provider/codex.py` after a successful Codex subprocess turn:

- Inspect the current project directory for uncommitted changes using the same helper logic as `sase_commit_stop_hook`.
- If no changes remain, return the Codex response as today.
- If changes remain, append the response to the accumulated transcript and run one additional Codex turn whose prompt
  contains the same ownership-gated commit instruction from `sase_commit_stop_hook`.
- Include the changed-file list and the resolved commit skill (`/sase_git_commit` for GitHub/git) so the agent sees the
  same actionable request it would have seen from the Stop hook.
- Do this at most once per provider invocation. If the agent determines the dirty files were not its changes, it can
  ignore the warning and SASE will not trap it in a loop.
- Respect `SASE_DISABLE_COMMIT_STOP_HOOK` so emergency opt-out still works.

This intentionally leaves Claude/Gemini alone; their native hook paths are already observable in the hook log and use
runtime-specific block protocols.

## Implementation Steps

1. Add small helper functions in `src/sase/llm_provider/codex.py` to build the fallback commit follow-up message from
   `sase.scripts.sase_commit_stop_hook`.
2. Thread that helper into `CodexProvider.invoke()` after successful subprocess output is accumulated and before
   returning.
3. Add focused tests in `tests/test_llm_provider_codex.py`:
   - clean worktree: Codex is invoked once.
   - dirty worktree: Codex is invoked twice and the second prompt includes uncommitted files plus `/sase_git_commit`.
   - `SASE_DISABLE_COMMIT_STOP_HOOK=1`: dirty worktree still invokes once.
   - one-shot behavior: if changes remain after the follow-up, the provider returns instead of looping forever.
4. Run focused Codex provider and stop-hook tests, then run the required repo checks.

## Validation

Run:

```bash
just install
pytest tests/test_llm_provider_codex.py tests/test_commit_stop_hook.py
just check
```

Also inspect the failing agent artifacts again to confirm the diagnosis is reflected in the final explanation:

- target Codex session has no `<hook_prompt>`;
- hook log has no 12:04 entry for workspace `sase_106`;
- the later `ff65cddb` code commit happened after the agent's recorded `END` time and was not the stop hook handoff.
