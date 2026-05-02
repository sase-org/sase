---
create_time: 2026-05-01 02:46:16
status: done
prompt: sdd/prompts/202605/datetime_timezone_crash.md
---
# Datetime Timezone Crash Plan

## Problem Statement

`sase ace` can crash with `TypeError: can't compare offset-naive and offset-aware datetimes` when code compares a local
agent timestamp with a timestamp parsed from an external or persisted source that carries timezone information.

The recent chat transcript points to the Gemini thinking-panel path:

- `AgentThinkingPanel._fetch_thinking_in_background()` passes `agent.run_start_time or agent.start_time` as `since`.
- Agent start timestamps are intentionally local naive datetimes in the Agents-tab model.
- Gemini rotated log filenames are parsed as timezone-aware datetimes in the configured SASE timezone.
- Comparing those directly in `_find_gemini_log_files()` caused `ts >= since`.

This checkout already contains the one-line normalization fix for that exact stack frame, but it has no regression test,
so it is easy for an installed copy or future refactor to keep regressing. While tracing nearby datetime paths, I also
found another active risk: absolute `%wait` metadata is displayed in both the Agents list row and the prompt-panel
header by subtracting `datetime.now()` from `datetime.fromisoformat(agent.wait_until)`. That works for today's naive
`parse_absolute_time()` output, but crashes as soon as `waiting.json` or `agent_meta.json` contains an aware ISO string.

## Root Cause

The underlying design mismatch is not a single line. Different subsystems use different datetime conventions:

- Agent artifact and suffix timestamps are local naive datetimes.
- Gemini log file timestamps are local timezone-aware datetimes.
- Runtime metadata such as `run_started_at` and `stopped_at` starts as UTC-aware ISO text and is normalized back to
  local naive for the Agents model.
- User-facing persisted metadata such as `wait_until` remains an ISO string and can be either naive or aware.

Python intentionally rejects ordering or arithmetic between naive and aware datetimes. Any UI or worker path that parses
an aware ISO string and compares/subtracts it against local naive `datetime.now()` is fragile.

## Implementation Plan

1. Add focused timezone normalization where values cross subsystem boundaries.
   - Keep the Agents model's established local-naive convention intact.
   - In the Gemini thinking parser, replace the ad hoc `tzinfo is None` check with a small local helper that treats
     naive `since` values as configured-local time and converts aware `since` values into the same timezone used for
     Gemini log timestamps.
   - In Agents-tab wait display helpers, parse `wait_until` through a helper that returns a timezone-compatible target
     and reference time, so aware ISO strings and naive ISO strings both render safely.

2. Add regression tests for the confirmed crash.
   - Exercise `read_gemini_log(since=<naive datetime>)` against a timestamped Gemini log file.
   - Verify it returns the expected thoughts instead of raising the original comparison `TypeError`.

3. Add regression tests for the nearby current risk.
   - Verify `format_wait_until()` accepts an aware ISO string.
   - Verify the waiting-row rendering path can render a WAITING agent with an aware `wait_until` and include a countdown
     without crashing.

4. Run targeted tests first, then full project checks.
   - Run the relevant thinking/parser and agent model/render tests.
   - Because this repo's memory says file changes require it, run `just install` if needed and then `just check` before
     handing back results.

## Non-Goals

- Do not change stored timestamp formats globally.
- Do not convert the Agents model wholesale to aware datetimes.
- Do not broaden this into a Rust migration or unrelated TUI startup/status work.
