---
create_time: 2026-05-08 16:29:17
status: done
prompt: sdd/prompts/202605/paused_runtime_emoji.md
---
# Plan: Paused Runtime Emoji In Agent Rows

## Goal

Add a small visual marker next to the right-side runtime suffix for agent rows that are paused awaiting user action,
matching the existing suffix-marker pattern:

- running/ticking rows use `🏃‍♂️`
- unread completed rows use `🎉`
- paused-for-user rows should get their own marker in the same runtime suffix area

This should make paused rows scannable without changing agent lifecycle semantics, status bucketing, runtime
calculation, or backend/core behavior.

## Current Shape

Relevant code:

- `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
  - owns `build_runtime_suffix()`
  - already prepends suffix markers for live runtime (`🏃‍♂️`) and unread completed rows (`🎉`)
- `src/sase/ace/tui/models/agent_time.py`
  - owns runtime calculation and ticking decisions
  - paused statuses such as `PLANNING`, `QUESTION`, and `WAITING INPUT` deliberately do not tick
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py`
  - row render cache key already includes `agent.status` through `_runtime_signature()`
- Tests:
  - `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
  - `tests/ace/tui/widgets/test_agent_list_runtime_model.py`
  - `tests/ace/tui/widgets/test_agent_list_runtime_patching.py`

Existing semantics discovered:

- `PLANNING` means a plan is waiting for manual review.
- `QUESTION` means the agent asked the user a question.
- `WAITING INPUT` means a workflow is paused for HITL input.
- `PLAN APPROVED` can require/allow user action in some UI paths, but runtime code treats it as potentially active when
  follow-up execution is running, so it should not receive a paused marker while it has active/ticking runtime.

## Design

Add a dedicated suffix marker for user-paused rows in `_agent_list_render_layout.py`.

Candidate marker: `🙋 `

Reasoning:

- It is visually distinct from the active runner and completed celebration.
- It reads as "user attention/input" rather than "waiting on time/dependency".
- It is compact and works in the same suffix slot as the existing markers.

Add a small helper near the suffix rendering code, for example:

```python
_RUNTIME_USER_PAUSED_MARKER = "🙋 "
_RUNTIME_USER_PAUSED_MARKER_STYLE = "#FFAF00"
_USER_PAUSED_STATUSES = frozenset({"PLANNING", "QUESTION", "WAITING INPUT"})

def _runtime_suffix_user_paused(agent: Agent) -> bool:
    return agent.status in _USER_PAUSED_STATUSES and not runtime_suffix_ticks(agent)
```

Then update `build_runtime_suffix()` so paused rows get the marker:

- If the row has a stable elapsed runtime, prepend `🙋 ` before elapsed, like unread completed rows do.
- If the row has no runtime suffix at all, render just `🙋` so rows like `QUESTION` or `WAITING INPUT` without timing
  data still get the visible marker next to the runtime column.
- Do not show the paused marker when a row is ticking; the running marker wins.
- Do not show the paused marker on unread completed rows; `🎉` wins for unread terminal rows.

This keeps all marker arbitration in one place:

1. ticking rows: `🏃‍♂️`
2. unread non-ticking completed rows: `🎉`
3. paused user-input rows: `🙋`

## Test Plan

Add focused rendering tests in `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`:

- `PLANNING` with a submitted plan time renders timestamp, `🙋`, and elapsed runtime.
- `QUESTION` with no question timestamp renders just `🙋`.
- `WAITING INPUT` with no runtime renders just `🙋`.
- `PLAN APPROVED` with active segmented runtime still renders `🏃‍♂️`, not `🙋`.
- Unread terminal rows continue to render `🎉`, not the paused marker.

No changes are needed in `runtime_suffix_ticks()` unless tests expose a mismatch, because this feature is display-only
and should not change ticking behavior.

## Verification

After implementation:

1. Run the focused runtime-rendering tests:
   `uv run pytest tests/ace/tui/widgets/test_agent_list_runtime_rendering.py tests/ace/tui/widgets/test_agent_list_runtime_model.py tests/ace/tui/widgets/test_agent_list_runtime_patching.py`
2. Because this repo requires it after file changes, run: `just install` `just check`

## Risks

- Emoji cell width can vary by terminal, but the suffix layout already uses emoji markers and Rich `cell_len`, so this
  follows the existing pattern.
- The exact paused-status set is product semantics. This plan intentionally starts with clear paused-for-user statuses
  (`PLANNING`, `QUESTION`, `WAITING INPUT`) and avoids marking active follow-up states such as `PLAN APPROVED`.
