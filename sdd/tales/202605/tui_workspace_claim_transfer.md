---
create_time: 2026-05-13 10:58:47
status: done
prompt: sdd/prompts/202605/tui_workspace_claim_transfer.md
---
# Fix TUI Workspace Claim Transfer

## Problem

Normal TUI-launched agents are failing to claim real workspaces after the shared launch executor was changed to preclaim
axe workspaces in the parent process. The executor builds a `LaunchSpawnRequest` with `transfer_from_pid` set to the
parent PID, expecting the low-level spawn layer to transfer that existing RUNNING-field claim to the child PID
atomically.

The TUI bridge drops that field:

- `src/sase/agent/launch_executor.py` creates `LaunchSpawnRequest.transfer_from_pid`.
- `src/sase/agent/launch_spawn.py` accepts it as `retry_transfer_from_pid` and transfers the claim when present.
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` and `_launch_repeat.py` unwrap the request manually and call
  `_launch_background_agent(...)` without forwarding the transfer PID.
- `src/sase/ace/tui/actions/agent_workflow/_launch_background.py` also has no `retry_transfer_from_pid` parameter, so
  even a correct caller could not forward it.

That produces a deterministic self-conflict: the parent has already claimed workspace `#N`, the child tries to claim
workspace `#N` as a fresh claim, core rejects it as already claimed, the executor releases/retries, and the same failure
repeats until launch exhaustion. Deferred `%wait` agents can still appear with placeholder workspace `#0`, which makes
the visible symptom look like agents are defaulting to workspace zero rather than moving to a claimed workspace.

## Scope

Implement a narrow propagation fix for the TUI spawn bridge. Keep existing Rust-backed claim logic, retry behavior,
workspace range behavior, and runner deferred-workspace behavior intact unless tests expose a second bug.

## Implementation

1. Extend `_launch_background_agent(...)` in `src/sase/ace/tui/actions/agent_workflow/_launch_background.py` with an
   optional `retry_transfer_from_pid: int | None = None` parameter.

2. Forward that parameter to `spawn_agent_subprocess(...)` as `retry_transfer_from_pid=retry_transfer_from_pid`.

3. Update TUI executor adapters that manually unpack `LaunchSpawnRequest`:
   - `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
   - `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py`

   Each should pass `retry_transfer_from_pid=request.transfer_from_pid` when calling `_launch_background_agent(...)`.

4. Review adjacent launch paths:
   - Multi-prompt and prompt fan-out use `launch_multi_prompt_agents()` and the executor's default spawn path, so they
     already preserve transfer metadata.
   - Bulk launch still uses the older preflight allocation path. Do not refactor it in this fix unless a focused test
     shows it is part of the reported "all agents" failure; changing it would broaden the patch beyond the diagnosed
     regression.

## Tests

Add focused tests that fail on the current code and pass with the propagation fix:

1. TUI single-launch adapter test:
   - Use the existing `_LaunchBodyApp` harness.
   - Patch `claim_next_axe_workspace` and `get_workspace_directory_for_num`.
   - Launch a normal non-home, non-deferred prompt.
   - Assert the captured `_launch_background_agent` kwargs include `retry_transfer_from_pid == os.getpid()`.

2. TUI repeat-launch adapter test:
   - Use the repeat launch harness with a non-home context so the executor preclaims.
   - Patch `claim_next_axe_workspace` and `get_workspace_directory_for_num`.
   - Assert every captured launch includes `retry_transfer_from_pid == os.getpid()`.

3. Preserve fixed-workspace behavior:
   - Existing executor tests already cover home/deferred/preallocated modes not using transfer retry.
   - Existing TUI VCS tests should continue to pass; they can assert transfer metadata only on non-preallocated paths.

## Verification

Run:

```bash
just install
just test tests/ace/tui/test_agent_launch_vcs.py tests/test_agent_launch_repeat.py tests/test_agent_launch_executor.py
just check
```

If `just install` or `just check` is blocked by environment state, run the focused pytest targets directly and report
the blocker.
