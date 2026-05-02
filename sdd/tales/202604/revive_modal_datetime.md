---
create_time: 2026-04-12 16:40:10
status: done
prompt: sdd/prompts/202604/revive_modal_datetime.md
---

# Plan: Full Date+Time in Revive Modal Sidebar + Datetime Sorting

## Problem

The "Revive Agents" modal sidebar currently shows only `HH:MM` (e.g. `20:25`) for each agent's start time. When agents
span multiple days, this is ambiguous. Additionally, agents within the same scope have no datetime-based ordering — they
appear in whatever order the loader discovers them.

## Changes

### 1. New compact datetime format on Agent model

Add a `start_time_compact` property to `Agent` (`agent.py`) that returns a format like `"Apr 12 20:25"` — short enough
for sidebar use but includes the date. This sits alongside the existing `start_time_short` (HH:MM) and
`start_time_display` (full YYYY-MM-DD HH:MM:SS).

Format: `"%b %d %H:%M"` → `"Apr 12 20:25"` (12 chars, vs 5 for HH:MM).

### 2. Update Revive Modal sidebar to use the new format

In `revive_agent_modal.py:_format_agent_label()`, replace `agent.start_time_short` with `agent.start_time_compact`.

### 3. Update Agent Run Log Modal for consistency

In `agent_run_log_modal.py:_create_agent_label()`, replace `agent.start_time_short` with `agent.start_time_compact`.
This modal already groups agents by date (Today, Yesterday, etc.), so the date portion is somewhat redundant there — but
consistency across modals is valuable and the extra characters are affordable.

### 4. Add datetime-based secondary sort in `_show_dismissed_agents_for_scope()`

In `_revive.py`, after filtering agents for the selected scope, sort with a composite key:

- **Primary**: project-level agents first (existing `is_project_agent` check), then by ChangeSpec name
- **Secondary**: `start_time` descending (most recent first), with `None` times sorting last

This applies to all scope types (`all`, `home`, `project`, `cl`), not just the `project` case which is the only one that
currently sorts.
