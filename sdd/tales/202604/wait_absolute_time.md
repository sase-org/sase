---
create_time: 2026-04-11 00:31:41
status: done
prompt: sdd/prompts/202604/wait_absolute_time.md
---

# Plan: Absolute Time Formats for `%wait` Directive

## Overview

Add support for absolute time-based waits alongside the existing duration-based waits. Two new formats:

- **HHMM** — wait until a specific time today (e.g., `%wait:1430` = wait until 2:30 PM)
- **yymmdd/HHMM** — wait until a specific date and time (e.g., `%wait:260411/1430` = April 11, 2026 at 2:30 PM)

These complement the existing relative duration format (`%wait:5m`) by letting users schedule agents to run at specific
wall-clock times — useful for coordinating with deployments, meetings, or rate-limited APIs.

## Design Decisions

### Parsing Strategy

The formats are unambiguous with existing syntax:

- Duration: requires h/m/s suffix (`5m`, `1h30m`)
- Agent names: must start with a letter (`[a-zA-Z_]`)
- **HHMM**: exactly 4 digits, no suffix
- **yymmdd/HHMM**: 6 digits + `/` + 4 digits

Parse order: try duration first → try absolute time → treat as agent name.

### Internal Representation

Store as a **target datetime** (not converted to duration at parse time). This is critical for the TUI:

- Duration waits show countdowns: `WAITING (4m32s)`
- Absolute time waits show the target: `WAITING (until 14:30)`

New field: `wait_until: str | None` — ISO 8601 timestamp string on `PromptDirectives`, `Agent` model, and
`waiting.json`.

Using ISO string rather than a `datetime` object keeps serialization trivial and avoids timezone object complexity
across process boundaries.

### waiting.json Extension

```json
{
  "waiting_for": [],
  "cl_name": "...",
  "timestamp": "...",
  "wait_until": "2026-04-11T14:30:00"
}
```

The `wait_until` field is mutually exclusive with `wait_duration`. Both can coexist with `waiting_for` (agent names).

### Edge Cases

- **HHMM in the past**: If the specified time has already passed today, treat it as **tomorrow**. This is the intuitive
  behavior for "wait until 0900" typed at 10 PM.
- **yymmdd/HHMM in the past**: Error at parse time — the user specified a date explicitly, so a past date is likely a
  typo.
- **Invalid times** (e.g., `2500`, `1261`): Error at parse time with a clear message.
- **Combined with agent waits**: Both conditions must be met — agents must finish AND the target time must pass. Same
  semantics as duration floor.

### TUI Display

**Agent list (Agents tab)**:

```
[agent] my_agent (WAITING (until 14:30, 2h15m))
```

Shows target time + countdown in compact form. The target time gives meaning; the countdown gives urgency.

**Agent details panel**:

```
Waiting until: 14:30 (2h15m left)
```

Or with date:

```
Waiting until: Apr 11 14:30 (2h15m left)
```

The date portion only shows when the target is not today (avoids clutter for same-day waits).

## Implementation Phases

### Phase 1: Parsing

**File**: `src/sase/xprompt/directives.py`

1. Add `_parse_absolute_time(s: str) -> str | None` function that:
   - Matches `^\d{4}$` for HHMM → validates HH (00-23) and MM (00-59) → computes target datetime (today or tomorrow if
     past) → returns ISO string
   - Matches `^\d{6}/\d{4}$` for yymmdd/HHMM → validates date and time → errors if in the past → returns ISO string
   - Returns `None` if no match

2. Add `wait_until: str | None = None` field to `PromptDirectives` dataclass

3. Update directive extraction logic (line ~274) to try `_parse_absolute_time` between `_parse_duration` and the
   agent-name fallback

### Phase 2: Execution

**File**: `src/sase/axe/run_agent_phases.py`

1. Add `wait_until: str | None = None` parameter to `wait_for_dependencies()`

2. Implement absolute-time waiting logic:
   - Write `wait_until` to `waiting.json` (instead of `wait_duration`)
   - Compute remaining seconds from `wait_until - now()`
   - Poll with same `_WAIT_POLL_INTERVAL` pattern, recalculating remaining each iteration (resilient to clock drift or
     sleep imprecision)

3. Support combining with agent waits: agent must finish AND target time must pass (same as duration floor)

### Phase 3: Agent Model & Loaders

**File**: `src/sase/ace/tui/models/agent.py`

- Add `wait_until: str | None = None` field to `Agent` dataclass

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

- Read `wait_until` from `waiting.json` and populate agent model field

### Phase 4: TUI Display

**File**: `src/sase/ace/tui/models/agent.py`

- Add `format_wait_until(iso_str: str) -> str` helper that formats for display:
  - Same day: `"14:30"` (just the time)
  - Different day: `"Apr 11 14:30"` (short month + day + time)

**File**: `src/sase/ace/tui/widgets/agent_list.py`

- In the WAITING branch: if `agent.wait_until` is set, show `"until HH:MM"` + countdown
- Format: `WAITING (until 14:30, 2h15m)`

**File**: `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`

- In the waiting info section: display `"Waiting until: <time> (<countdown> left)"`

### Phase 5: Tests

- **Parsing tests** (`tests/test_directives_helpers.py`): valid HHMM, valid yymmdd/HHMM, invalid hours/minutes, past
  yymmdd/HHMM error, HHMM-past-wraps-to-tomorrow
- **Directive integration tests** (`tests/test_directives_types.py`): `%wait:1430` produces correct `wait_until`, mixed
  with agent names, mixed with duration (error? or allow both?)
- **Model tests** (`tests/test_agent_model.py`): `format_wait_until` formatting
- **Enrichment tests** (`tests/test_enrich_agent_wait_duration.py`): loading `wait_until` from waiting.json

### Phase 6: Caller/Launcher Integration

**File**: `src/sase/axe/run_agent_phases.py` (caller site)

- Pass `wait_until` from directives through to `wait_for_dependencies()`

**File**: `src/sase/agent/launcher.py`

- Ensure `has_wait_directive()` triggers workspace deferral for absolute time waits too (it should already since it
  checks for presence of `%wait` regardless of arg)
