---
create_time: 2026-04-25 19:59:40
status: done
prompt: sdd/prompts/202604/restore_t_tmux_agents_tab.md
---
# Restore `t` tmux keymap on Agents tab; move tag/untag to `N`

## Problem

Commit `e6444e8f` ("feat: agents-tab `t` keymap to add/remove agent tags") repurposed `t` on the Agents tab to open the
agent-tag modal. This silently displaced the original `t` behavior — opening a tmux window in the focused agent's
**claimed** workspace (added in the older "Add 't' keymap to agents tab to open tmux window in agent workspace" commit).
The lowercase `t` (per-agent workspace) and uppercase `T` (primary workspace #1) used to be a paired UX: `t` jumps to
the agent's actual workspace, `T` jumps to the project's primary.

Currently on the Agents tab:

- `t` → opens the tag/untag modal (`action_start_tmux_mode` is overridden in `agents/_panels.py:233-238` to call
  `action_add_agent_tag()`).
- `T` → opens tmux in primary workspace (`action_open_tmux` overridden at `agents/_panels.py:226-231` to call
  `_open_agent_tmux_window(use_primary=True)`).

The helper `_open_agent_tmux_window()` (`agents/_panels.py:240-293`) is intact and already supports both modes via its
`use_primary` flag — so restoring the original `t` is a one-line behavior change, not a re-implementation.

## Goal

1. Restore `t` on the Agents tab so it opens tmux in the **focused agent's claimed workspace**
   (`_open_agent_tmux_window(use_primary=False)`).
2. Move the agent tag/untag modal from `t` to a new `N` keymap. `N` is currently unbound (lowercase `n` is `rename_cl`).
3. Keep all other tabs' `t` behavior (`start_tmux_mode` workspace-number picker) unchanged.

## Approach

This is a keymap rewiring, not a feature change. The tag-modal action method (`action_add_agent_tag` in
`agents/_tagging.py`) and the tmux helper (`_open_agent_tmux_window`) both already exist — we just need to:

- Register a new keymap action (`add_agent_tag` → `N`) so the textual `Binding` can address it directly instead of going
  through `action_start_tmux_mode`.
- Revert the agents-tab override of `action_start_tmux_mode` to invoke the per-agent tmux helper.
- Update the footer + help modal text so users can discover the new layout.

### Files to change

1. **`src/sase/default_config.yml`** — add `add_agent_tag: "N"` to the keymap block (alongside `add_tag`,
   `start_tmux_mode`, etc.). Per `gotchas.md`, keymap config values must be added here when introducing a new keymap.

2. **`src/sase/ace/tui/keymaps/types.py`**
   - Append `("add_agent_tag", "Add Agent Tag", False)` to `_BINDING_META` (around line 110, after
     `toggle_attempt_view`).
   - Add `add_agent_tag: str` to the `Keymaps` dataclass (in the "Agent / axe" section near line 243).

3. **`src/sase/ace/tui/bindings.py`** — add `Binding("N", "add_agent_tag", "Add Agent Tag", show=False)` to
   `DEFAULT_BINDINGS`.

4. **`src/sase/ace/tui/actions/agents/_panels.py`**
   - Change `action_start_tmux_mode` (lines 233-238) so the agents-tab branch calls
     `self._open_agent_tmux_window(use_primary=False)` instead of `self.action_add_agent_tag()`. Update its docstring to
     "`t` opens tmux in the focused agent's workspace; tmux mode otherwise."

5. **`src/sase/ace/tui/widgets/_keybinding_bindings.py`** (footer)
   - Line 151: replace `bindings.append((self._kd("start_tmux_mode"), "tag/untag"))` (always-shown) with a conditional
     `(self._kd("start_tmux_mode"), "tmux")` block guarded on
     `agent.workspace_num is not None and agent.workspace_num > 0` — same gate already used for `open_tmux` two lines
     below. The label `tmux` matches legacy snapshots (e.g. `specs/202604/jump_modal_redesign.md` shows
     `t tmux  T tmux (primary)`).
   - Add a new always-shown entry `(self._kd("add_agent_tag"), "tag/untag")` so the tag modal stays discoverable for any
     focused agent (including those without a workspace).

6. **`src/sase/ace/tui/modals/help_modal/bindings.py`** (Agent Actions section)
   - Line 320: change `(d(a.start_tmux_mode), "Tag/untag agent (or marked set)")` to
     `(d(a.start_tmux_mode), "Tmux in agent workspace")`.
   - Add new entry: `(d(a.add_agent_tag), "Tag/untag agent (or marked set)")` near the new tmux entries.
   - Per `src/sase/ace/AGENTS.md`: descriptions max 32 chars — both fit ("Tmux in agent workspace" = 22 chars,
     "Tag/untag agent (or marked set)" = 31 chars).

7. **`tests/ace/tui/test_agent_tagging.py`** — review the nine `app.action_add_agent_tag()` call sites. Direct action
   calls don't depend on the bound key, so most should pass unchanged. If any test asserts on the binding being `t`
   (e.g. through a textual key event), retarget it to `N`.

### Behavioral details to preserve

- `_open_agent_tmux_window(use_primary=False)` already notifies "No agent selected" / "No workspace directory for agent"
  when the agent lacks a workspace, so users still get a sensible message if they hit `t` on an agent without one. The
  footer guard (file 5 above) just keeps the binding from advertising itself in that case — matching the existing `T`
  behavior.
- The `action_add_agent_tag` guard `if self.current_tab != "agents": return` stays in place, so pressing `N` on the
  CLs/Axe tab is a silent no-op (consistent with how other agents-only actions behave). The footer entry added in file 5
  only renders on the Agents tab anyway.
- `t` on non-Agents tabs keeps invoking `action_start_tmux_mode` (the workspace-number picker on CLs tab) via the
  `super()` call; only the agents-tab early-return branch changes.

## Out of scope

- No changes to the tag-modal UI itself (`AgentTagModal`, `agent_tags.json` storage).
- No changes to the `T` (primary-workspace tmux) binding.
- No deprecation shim for the previous `t = tag` behavior — short-lived (~1 day in master) and the user is the sole
  consumer asking for the revert.

## Verification

1. `just check` (lint + mypy + tests) — required by `memory/short/build_and_run.md`.
2. Manual: run `sase ace`, focus a running agent on the Agents tab, press `t` → tmux window opens in the agent's
   workspace; press `N` → tag modal opens; press `T` → tmux opens in primary workspace.
3. Manual: focus an agent without a workspace; verify footer shows `N tag/untag` but not `t tmux`, and pressing `t`
   shows the "No workspace directory for agent" toast.
4. Help modal (`?`): verify the "Agent Actions" section shows both new entries with correct descriptions and keys, and
   the 57-char box width is preserved.
