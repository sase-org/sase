---
create_time: 2026-03-30 10:32:08
status: done
---

# Consolidated Follow-up Agent Replies in AGENT REPLY Section

## Goal

Include planner and coder agent replies in the AGENT REPLY section of the agent metadata panel on the Agents tab, but
only for the **main agent entry** (not nested workflow steps or follow-up agents).

## Context

Currently, when a plan+code workflow runs:

1. The main agent (planner, `role_suffix=".plan"`) shows its own reply
2. Feedback round agents (`.2`, `.3`, etc.) show their own replies when selected
3. The coder agent (`.code`) shows its own reply when selected

The user has to navigate to each follow-up agent to see their replies. We want the main agent's AGENT REPLY section to
consolidate all follow-up replies into a single scrollable view.

## Design

### Visual Design

When a main agent has follow-up agents, the AGENT REPLY section will show labeled subsections for each phase:

```
AGENT REPLY

─── PLANNER ─── 14:23:45 ─────────────
─── 14:23:45 ──────────────────────────
[planner's timestamped reply chunks]

─── PLANNER (round 2) ─── 15:10:30 ───
─── 15:10:30 ──────────────────────────
[feedback round 2's reply chunks]

─── CODER ─── 15:45:00 ───────────────
─── 15:45:00 ──────────────────────────
[coder's timestamped reply chunks]
```

Phase label color: `bold #AF87FF` (medium purple) for the label, `dim #AF87FF` for the dashes. This creates a clear
visual hierarchy:

1. Section headers (AGENT REPLY) → gold `#D7AF5F`
2. Phase dividers (PLANNER, CODER) → purple `#AF87FF`
3. Timestamp dividers → lavender `#D7D7FF`

When there are no follow-up agents, the reply renders exactly as before (no phase labels).

### Phase Label Mapping

- Main agent with `.plan` suffix → `PLANNER`
- Feedback rounds (`.2`, `.3`, etc.) → `PLANNER (round N)`
- `.code` → `CODER`
- `.q` → `QUESTIONS`
- `.epic` → `EPIC`
- No suffix → `AGENT`

### Data Flow

1. **Agent model** (`agent.py`): Add `followup_agents: list[Agent]` field (not serialized in bundles)
2. **Agent loader** (`agent_loader.py`): Attach follow-up agents to their parent in `_apply_status_overrides()`
3. **Display** (`_agent_display.py`): Render consolidated reply when `agent.followup_agents` is non-empty

## Changes

### Phase 1: Agent Model -- Add `followup_agents` field

**File**: `src/sase/ace/tui/models/agent.py`

1. Add `followup_agents: list["Agent"] = field(default_factory=list)` as a new field on the Agent dataclass
2. In `to_bundle_dict()`: skip `followup_agents` (not serialized -- always reloaded from filesystem)

### Phase 2: Agent Loader -- Populate follow-up agents on parent

**File**: `src/sase/ace/tui/models/agent_loader.py`

In `_apply_status_overrides()`:

1. Collect ALL follow-up agents (both feedback rounds and non-feedback) and attach them to their parent's
   `followup_agents` list
2. Sort follow-ups chronologically (oldest first) so the display reads naturally: planner -> feedback -> coder

### Phase 3: Display -- Render consolidated reply

**File**: `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`

1. Add a `_render_phase_divider(label, start_time)` static method that creates a styled phase divider line
2. Add a `_get_phase_label(agent)` static method that maps role_suffix to human-readable label
3. Add a `_render_agent_reply_content(agent)` helper that renders one agent's reply (chunks/live/response)
4. In `update_display()`: when the main agent has `followup_agents`, render the AGENT REPLY section with:
   - The main agent's reply with a phase label
   - Each follow-up agent's reply with its phase label
5. In `update_display_with_hints()`: same logic but using text with file hints instead of Syntax

### Phase 4: Tests

**File**: `tests/ace/tui/widgets/prompt_panel/test_agent_display.py` (or similar)

1. Test `_get_phase_label()` for all suffix types
2. Test `_render_phase_divider()` produces correct styled output
3. Test that consolidated reply is rendered when `followup_agents` is non-empty
4. Test that follow-up agents are skipped (regular display) for workflow children
