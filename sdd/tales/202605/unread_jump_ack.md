---
create_time: 2026-05-08 17:17:57
status: done
prompt: sdd/prompts/202605/unread_jump_ack.md
---
# Plan: Acknowledge unread agent on leader jump

## Context

The Agents tab tracks unread completed agents in `_unread_completed_agent_ids`. Normal row navigation through `j`/`k`
eventually calls `_acknowledge_agent_unread()`, which removes the selected agent from that set and patches or refreshes
the rendered row immediately.

The leader `,j` key path is different:

- `LeaderModeMixin._handle_leader_key()` dispatches `jump_to_next_unread_done_agent` to
  `AgentsMixinCore._jump_to_next_unread_done_agent()`.
- `_jump_to_next_unread_done_agent()` locates the next visible unread terminal agent by completion recency and moves
  focus to it.
- That method currently documents that it intentionally preserves unread state, and it explicitly calls
  `unread_ids.add(target_agent.identity)` after moving selection.
- `tests/ace/tui/test_agent_unread_indicator.py` includes
  `test_jump_to_next_unread_done_agent_preserves_target_unread_state`, so the current behavior is locked in by tests.

This explains the observed mismatch: `j`/`k` acknowledges the row, while `,j` leaves the row unread. I am interpreting
the prompt's "marked as unread immediately" as "marked as read immediately" because that is the behavior described as
already working with `j`/`k`; if literal unread preservation were desired, the current implementation already does that.

## Implementation

1. Update `_jump_to_next_unread_done_agent()` so selecting the target uses the same acknowledgement behavior as normal
   row navigation.
2. Preserve existing jump behavior:
   - visible-only candidate filtering
   - completion-recency ordering and wraparound
   - panel focus switching
   - banner focus clearing
   - attempt-view reset
   - full refresh when the target is in a different panel or when row patching cannot land
3. Remove the explicit unread re-add and replace the stale comment/docstring with the new contract.
4. Update focused tests in `tests/ace/tui/test_agent_unread_indicator.py`:
   - replace the preservation test with an acknowledgement test
   - adjust any expectations that currently require `,j` to keep unread state
   - keep coverage for patch fallback and cross-panel refresh behavior

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/test_agent_unread_indicator.py
```

Then run the repository check required by the local memory after code changes:

```bash
just install
just check
```
