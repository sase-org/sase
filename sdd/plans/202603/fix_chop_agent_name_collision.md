---
create_time: 2026-03-30 17:14:29
status: done
---

# Fix: Chop-spawned agents steal user agent names

## Problem

When a chop like `sase_fix_just` runs via `launch_agent_from_cwd()`, it creates an `ace-run/` artifact entry with an
auto-assigned name (e.g., "c"). Later, when a user runs their own agent, `_get_active_agent_names()` skips the chop's
entry because its `workflow_state.json` has `appears_as_agent: false`, making the name "c" available for reuse. The
user's agent then gets the same name "c", causing two agents to appear with identical names in the Agents tab.

Verified with current data: THREE agents share `name=c`:

- User's running agent (`appears_as_agent=True`)
- `sase/fix_just` chop (`appears_as_agent=False`)
- `sase/refresh_docs` chop (`appears_as_agent=False`)

## Root cause

Two independent issues compound to create the collision:

1. **`_get_active_agent_names()` in `src/sase/agent/names.py`** skips entries with `appears_as_agent=False` BEFORE
   checking done.json, so completed chop workflows never reserve their names. The comment says they "never show on the
   Agents tab" but this is wrong -- they DO show as `[sase/fix_just]` entries.

2. **Chop agents are not marked `hidden`**, so they don't get auto-dismissed. The `_is_axe_spawned_agent()` check only
   recognizes `axe(mentor)`, `axe(fix_hook)`, `axe(crs)`, etc. -- NOT chop-spawned workflows like `sase/fix_just` or
   `sase/pylimit_split`. Without auto-dismiss, these entries accumulate forever, each holding a name that's invisible to
   the allocator but visible in the UI.

## Fix

### Part 1: Mark chop agents as hidden via `SASE_AGENT_AUTO_DISMISS`

The lumberjack already sets `SASE_AGENT_AUTO_DISMISS=1` for recurring chops. Propagate this into `agent_meta.json` so
the agent is marked `hidden: true` from birth.

**File: `src/sase/axe/run_agent_phases.py`** (`extract_directives_and_write_meta`):

- Check `os.environ.get("SASE_AGENT_AUTO_DISMISS")`. If set, write `"hidden": true` to `agent_meta.json`.

This has two effects:

- The TUI auto-dismisses these agents on completion (existing logic in `_core.py`)
- The agent is hidden by default (shown only with `.` toggle)

### Part 2: Skip name auto-assignment for auto-dismiss agents

Since auto-dismiss agents are background workflows that get dismissed on completion, they don't need user-facing names.
Skip auto-name assignment when `SASE_AGENT_AUTO_DISMISS=1`.

**File: `src/sase/agent/names.py`** (`get_next_auto_name` callers) or **File: `src/sase/axe/run_agent_phases.py`**
(`extract_directives_and_write_meta`):

- When `SASE_AGENT_AUTO_DISMISS=1` is set AND no explicit `%name` directive is present, skip calling
  `get_next_auto_name()` and leave the name as `None`.

### Part 3: Safety net in `_get_active_agent_names()`

Remove the `appears_as_agent=False` early exit. All entries with names should reserve them regardless of
`appears_as_agent`. The comment claiming these entries "never show on the Agents tab" is factually wrong.

**File: `src/sase/agent/names.py`** (`_get_active_agent_names`):

- Delete the `wf_path / appears_as_agent` check block (lines ~469-479).

### Part 4: Clean up `SASE_AGENT_AUTO_DISMISS` in lumberjack

Ensure the env var doesn't leak to non-recurring chops.

**File: `src/sase/axe/lumberjack.py`** (`_run_agent_chop`):

- Verify the env var is cleaned up in a `finally` block (or passed via the subprocess env dict instead of modifying
  `os.environ` in the parent process).

## Test plan

- Unit test: `_get_active_agent_names()` reserves names from entries with `appears_as_agent=False`
- Unit test: `extract_directives_and_write_meta()` skips name auto-assignment when `SASE_AGENT_AUTO_DISMISS=1`
- Unit test: `extract_directives_and_write_meta()` writes `hidden: true` when `SASE_AGENT_AUTO_DISMISS=1`
- Integration: run `just check` to verify lint/type/test pass
