---
create_time: 2026-05-13 15:12:02
status: done
prompt: sdd/prompts/202605/jump_to_stopped_agent_fix.md
---
# Plan: Fix `,J` Stopped-Agent Navigation

## Problem

The `,J` Agents-tab leader key is intended to jump through rows in the visible **Stopped** bucket, such as a `PLAN`
agent waiting for approval. The current implementation does not do that. It reuses the unread-completed-agent predicate,
which defines candidates through `DISMISSABLE_STATUSES` (`DONE`, `FAILED`, `PLAN DONE`, `TALE DONE`, etc.).

That makes `,J` search completed/dismissable rows, not stopped rows. In a snapshot where the only stopped row is `PLAN`,
`,J` can ignore that row even though the UI clearly renders it under `▲ Stopped`.

## Root Cause

There are two different status concepts in the code:

- completed/unread/dismissable rows are defined by `DISMISSABLE_STATUSES` and `is_unread_completed_status()`
- stopped rows in the status grouping UI are defined by the shared status-bucket semantics in
  `sase.agent.status_buckets`, where `PLAN` and `QUESTION` map to `Stopped`

The original `,J` implementation chose the completed/unread definition, so it diverged from the status bucket shown in
the Agents tab.

## Design

Align `,J` with the same semantics the UI uses for the Stopped bucket.

1. Introduce small local helpers in the Agents unread/navigation mixin:
   - `is_stopped_agent_status(status)` returns true when the status maps to the `Stopped` bucket
   - `_stopped_agent_jump_time(agent)` returns the timestamp that best represents when the row became stopped: latest
     `plan_times` for `PLAN`, latest `questions_times` for `QUESTION`, then `stop_time`, then `start_time`

2. Update `_has_stopped_agent()` and `_jump_to_next_stopped_agent()` to use the stopped-status helper instead of
   `is_unread_completed_status()`.

3. Keep the shared jump mechanics intact:
   - candidate discovery still respects visible rows and panel focus
   - jumps still clear banner focus and reset attempt selection
   - repeated `,J` presses still cycle because no unread/read state is mutated
   - cross-panel refresh behavior remains unchanged

4. Keep `,j` unread-completed behavior unchanged. It should continue using completed/dismissable status semantics and
   notification acknowledgement.

5. Update command palette availability to track actual stopped rows rather than completed rows, so command visibility
   matches the new behavior.

## Tests

Update focused tests to cover the regression and prevent this mismatch from returning:

- `,J` jumps to `PLAN` rows
- `,J` jumps to `QUESTION` rows
- `,J` orders stopped rows by `plan_times` / `questions_times` recency before falling back to row start time
- `,J` ignores completed rows such as `DONE` and `FAILED`
- command availability uses stopped-agent count, not completed-agent count
- context extraction exposes stopped-agent count independently of completed-agent count

Run focused tests first:

```bash
pytest tests/ace/tui/test_agent_unread_navigation.py tests/test_command_availability.py tests/test_command_palette_wiring.py
```

Then follow repo instructions after code changes:

```bash
just install
just check
```
