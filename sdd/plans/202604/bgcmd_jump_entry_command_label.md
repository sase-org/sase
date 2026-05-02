---
create_time: 2026-04-24 15:23:58
status: done
prompt: sdd/prompts/202604/bgcmd_jump_entry_command_label.md
---
# Plan: Show command in bgcmd entries in the "Jump to Entry" panel

## Goal

In the `sase ace` "Jump to Entry" modal (opened with the jump-to-entry hotkey), background command entries currently
render as `bgcmd #<N>` (e.g. `bgcmd #1`, `bgcmd #2`). This is uninformative — the user cannot tell which slot is which
without memorizing the slot order. We want entries to render as:

```
bgcmd #<N>: <command>
```

…where `<command>` is the actual shell command that was launched for that slot (e.g. `bgcmd #1: rabbit test -c opt`).

The sidebar AXE widget already displays the command (truncated to 25 chars in
`src/sase/ace/tui/widgets/bgcmd_list.py::_format_bgcmd_option`), so the Jump panel is the odd one out.

## Background / Context

- **bgcmd data model** — `BackgroundCommandInfo` in `src/sase/ace/tui/bgcmd.py:25-36` has a `command: str` field. It is
  persisted to `~/.sase/axe/bgcmd/<slot>/info.json` at launch (`start_background_command`, line 299).
- **Slot → info accessor** — `get_slot_info(slot)` at `src/sase/ace/tui/bgcmd.py:151` returns the
  `BackgroundCommandInfo` for a slot (or `None` if absent). This already does the JSON read.
- **Current label site** — `src/sase/ace/tui/modals/jump_all_modal.py:176-187`, inside `_build_entries`:
  ```python
  elif isinstance(item, BgCmdItem):
      entries.append(
          _Entry(
              "axe",
              i,
              f"bgcmd #{item.slot}",   # ← change here
              ...
          )
      )
  ```
  `BgCmdItem` (frozen dataclass in `src/sase/ace/tui/widgets/bgcmd_list.py:39-43`) only carries `slot: int`, so the
  modal must resolve the command itself.
- **Width** — the modal truncates names to `_NAME_MAX = 50` chars (line 33) and already truncates gracefully via
  `entry.name[:avail]` (line 257). Section rule width is 76. The prefix `bgcmd #N: ` is ~11 chars, leaving ~39 chars for
  the command before the 50-char cap kicks in — plenty for typical commands, and long commands are still safely
  truncated.

## Design

### Label format

```
bgcmd #<slot>: <command>
```

- If `get_slot_info(slot)` returns `None` (slot exists in the AXE list but info.json is missing/corrupt — an edge case
  during teardown or I/O error), fall back to the current label `bgcmd #<slot>` with no colon.
- Let the existing `_NAME_MAX = 50` truncation in `_build_display` handle over-long commands. We do **not** want a
  second, tighter truncation (like the 25-char one in the sidebar) here because the Jump panel has more horizontal room
  and the user is specifically looking at this modal to disambiguate entries.

### Where to resolve the command

Option A (chosen): resolve inside `_build_entries` of `JumpAllModal` by calling `get_slot_info(item.slot)`. The modal is
short-lived (opened on demand) and only a handful of bgcmd slots exist (max 9), so the extra disk reads are negligible.

Option B (rejected): plumb the command onto `BgCmdItem` itself. Rejected because `BgCmdItem` is used by the sidebar
widget which already fetches info its own way, so adding a field just for the modal would bloat the shared model and
duplicate state.

### Module coupling

`jump_all_modal.py` currently imports from `..widgets.bgcmd_list` only. We'll add an import of `get_slot_info` from
`..bgcmd`. No new dependencies or cyclic concerns — `bgcmd.py` already sits below the widgets layer.

## Files to change

1. **`src/sase/ace/tui/modals/jump_all_modal.py`**
   - Import `get_slot_info` from `..bgcmd`.
   - In the `BgCmdItem` branch of `_build_entries` (lines 176-187), look up the info and build a label of the form
     `bgcmd #{slot}: {command}`. Fall back to `bgcmd #{slot}` when info is `None`.

2. **`tests/ace/tui/test_jump_to_entry_hints.py`** (or a new test file nearby)
   - Add a test that instantiates `JumpAllModal` with a `BgCmdItem` whose slot has a seeded `info.json`
     (`BackgroundCommandInfo(command="rabbit test -c opt", ...)`) and asserts the constructed entry's `name` starts with
     `bgcmd #<N>: rabbit test`. Use `tmp_path` with `monkeypatch` of `BGCMD_STATE_DIR` to avoid touching the real
     `~/.sase` directory.
   - Add a test that when no info is present the label falls back to plain `bgcmd #<N>`.

## Things _not_ in scope

- No change to the sidebar `BgCmdList` widget — it already shows the command.
- No change to `BgCmdItem`'s data model.
- No change to the hint assignment logic or panel layout.
- No change to truncation policy beyond relying on the existing 50-char `_NAME_MAX`.

## Verification

- `just check` (lint + type-check + tests).
- Manual: launch a couple of bgcmds via `sase ace`, open the Jump modal, confirm the entries read `bgcmd #1: <cmd>` etc.
  and that a very long command truncates cleanly without breaking the layout.
