---
create_time: 2026-05-13 12:33:38
status: done
prompt: sdd/prompts/202605/jump_to_stopped_agents.md
---
# Add `,J` Jump To Most Recently Stopped Agent

## Goal

Add a leader-mode keymap on the Agents tab that uses `,J` to jump to stopped agent rows in most-recently-stopped order.
It should behave like the current `,j` unread completed-agent jump for selection, visible-row filtering, panel focus,
banner focus, attempt reset, and refresh behavior, but it must not mutate unread/read state or dismiss notifications.

## Existing Behavior

The current `,j` action is implemented as `jump_to_next_unread_done_agent`:

- leader-mode dispatch lives in `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`
- row discovery and focus movement live in `src/sase/ace/tui/actions/agents/_unread.py`
- default leader key configuration lives in both `src/sase/default_config.yml` and the `LeaderModeKeymaps` dataclass
  defaults
- command palette/help/footer metadata lives in `commands/catalog.py`, `commands/availability.py`,
  `widgets/keybinding_footer.py`, and `modals/help_modal/bindings.py`
- targeted tests already exist in `tests/ace/tui/test_agent_unread_navigation.py`, `tests/test_keymaps.py`, and
  `tests/test_command_availability.py`

`_jump_to_next_unread_done_agent()` already has the right navigation skeleton: it filters to visible rows, sorts by
`agent.stop_time or agent.start_time` descending, wraps from the current candidate to the next one, moves panel focus
when the target is in another panel, clears banner focus, resets `current_attempt_number`, and chooses between full
refresh and row patching. Its final step acknowledges unread state, which is exactly the piece the new stopped-row jump
must avoid.

## Design

Introduce a shared internal helper in `AgentUnreadMixin` for recency-ordered completed-row jumps:

- keep `is_unread_completed_status()` / `DISMISSABLE_STATUSES` as the definition of “stopped agent row” for this
  feature, because those are the terminal rows that can be dismissed and already power “completed/done” Agents-tab
  behavior
- collect candidates from the currently visible agent panel indices only, preserving folded/grouped-panel semantics
- sort candidates by `stop_time`, falling back to `start_time`, newest first
- wrap based on the current selected agent index when focus is on a row
- from a focused group banner, always start at the newest candidate, matching `,j`
- move `_panel_group.focused_idx` when needed and clear `_current_group_key`
- set `current_attempt_number = None` after selecting a real agent row

Then keep two public methods:

- `_jump_to_next_unread_done_agent()` calls the helper with an unread-only predicate and an acknowledge callback,
  preserving existing `,j` behavior
- `_jump_to_next_stopped_agent()` calls the helper with a stopped/dismissable predicate and no acknowledge callback, so
  consecutive `,J` presses cycle through the same stopped candidates without changing unread state or dismissing
  notifications

## Keymap Conflict

`,J` is currently the default leader binding for `mark_all_unread_done_agents_read`. To make `,J` the stopped-row jump
without creating an unreachable duplicate binding:

- add a new leader action id `jump_to_next_stopped_agent` with default subkey `J`
- move `mark_all_unread_done_agents_read` to default subkey `U`, keeping the old command available and giving it an
  unread-management mnemonic under leader mode
- update default config, dataclass defaults, command labels, footer text, help modal text, and tests to reflect this
  default change

## Tests

Add and update focused tests:

- keymap tests assert `jump_to_next_stopped_agent == "J"` and `mark_all_unread_done_agents_read == "U"`
- command availability tests require stopped/completed agent count for `leader.jump_to_next_stopped_agent`
- unread navigation tests cover:
  - newest-first stopped-row selection using `stop_time`/`start_time`
  - repeated calls cycle through stopped rows without removing unread ids
  - running/non-terminal rows are ignored
  - no notification dismissal happens
  - cross-panel and group-banner focus behavior remains consistent with `,j`

## Verification

Run the smallest relevant tests first:

- `pytest tests/ace/tui/test_agent_unread_navigation.py tests/test_keymaps.py tests/test_command_availability.py`

Because this repo’s memory requires it after code changes, run:

- `just install`
- `just check`
