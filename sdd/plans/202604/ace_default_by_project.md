---
create_time: 2026-04-29 11:44:59
status: done
prompt: sdd/prompts/202604/ace_default_by_project.md
---
# Plan: Default ACE Grouping to By Project on Startup

## Goal

Make `sase ace` always open with the "by project" grouping/sorting strategy on both the CLs tab and the Agents tab,
regardless of the grouping mode selected in a previous TUI session.

The cycle actions should still work during a session:

- CLs: `BY_PROJECT -> BY_DATE -> BY_STATUS -> BY_PROJECT`
- Agents: `STANDARD` ("by project") `-> BY_DATE -> BY_STATUS -> STANDARD`

## Current Behavior

The grouping model already has the correct by-project modes:

- CLs use `ChangeSpecGroupingMode.BY_PROJECT`.
- Agents use `GroupingMode.STANDARD`, whose UI label is "by project".

The startup issue comes from persistence:

- `src/sase/ace/tui/actions/_state_init.py` calls `load_changespec_grouping_mode()` for CLs.
- `src/sase/ace/tui/actions/_state_init.py` calls `load_grouping_mode()` for Agents.
- The cycle action writes the selected mode back to `~/.sase/changespec_grouping_mode.txt` and
  `~/.sase/grouping_mode.txt`.

That means if a user last cycled to date or status, the next `sase ace` opens in that old mode instead of by project.

## Implementation Plan

1. Change ACE startup initialization to use explicit by-project defaults.
   - In `_state_init.py`, initialize Agents with `GroupingMode.STANDARD`.
   - Initialize CLs with `ChangeSpecGroupingMode.BY_PROJECT`.
   - Keep each tab's per-mode fold registry setup exactly as it is, keyed by the active startup mode.

2. Remove grouping-mode persistence from the cycle path.
   - In `actions/agents/_grouping.py`, stop importing and calling `save_grouping_mode()` when cycling Agents.
   - Stop importing and calling `save_changespec_grouping_mode()` when cycling CLs.
   - Keep notifications, registry swaps, current-banner-key clearing, and refresh/refilter behavior unchanged.

3. Retire or update stale persistence surfaces.
   - Prefer deleting the now-unused persistence modules and their direct tests if no other runtime code imports them.
   - If keeping the modules for compatibility, mark them as legacy and adjust tests so product behavior is covered by
     startup and cycle tests rather than saved-file round trips.

4. Update tests around the new startup contract.
   - Add or adjust tests so a stale saved Agents mode does not affect `_init_app_state`.
   - Add or adjust tests so a stale saved CLs mode does not affect `_init_app_state`.
   - Update cycle tests to assert cycling no longer creates either grouping-mode persistence file.
   - Keep existing cycle-order, fold-registry isolation, banner-focus reset, and tab-dispatch coverage.

5. Update user-facing documentation and help text.
   - Update `docs/ace.md` sections that currently say grouping mode is persisted.
   - Update the `?` help popup wording for Agents from "Cycle: default -> date -> status" to "Cycle: project -> date ->
     status" so the visible docs match the actual default naming.
   - Keep CLs help wording aligned with "proj -> date -> status".

## Verification

Run targeted tests first:

- `pytest tests/ace/tui/test_agent_grouping_cycle.py tests/ace/tui/test_changespec_grouping_cycle.py`
- Any startup/state-init tests added for stale grouping files.

Then run the repository check required by local instructions:

- `just install`
- `just check`

## Risk and Mitigation

The main behavior change is intentional: users who preferred date/status across restarts will now start from by project
and can press `o`/`O` to switch for the current session. The implementation keeps mode-specific fold registries within a
session, so cycling remains predictable without carrying stale mode selection into the next launch.
