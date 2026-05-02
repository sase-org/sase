---
create_time: 2026-04-27 09:30:38
status: done
prompt: sdd/prompts/202604/panel_scoped_dismiss_kill.md
---
# Plan: Scope `X` and `,X` to the focused agent panel

## Problem

On the "Agents" tab of the `sase ace` TUI, two bulk-action keymaps currently operate on the entire global agent list,
ignoring panel boundaries:

- **`X`** — dismisses **all** done/failed agents (any panel).
- **`,X`** — kills **all** running agents and dismisses **all** done agents (any panel).

The Agents tab is organized into panels keyed by agent `tag` (with `None` = the always-present "untagged" main panel).
Workflow children inherit their parent's panel. The user expects bulk actions to respect the focused panel: pressing
`X`/`,X` should only affect agents in the panel the user is currently looking at, not blow away unrelated tagged work in
other panels.

## Goal

Both `X` and `,X` should act only on agents whose effective panel key matches `self._panel_group.focused_key`. Behavior,
modals, double-confirm flow, and per-agent semantics (status filters, suffix checks, kill vs. dismiss split) remain
unchanged — only the candidate set is narrowed.

## Investigation findings

Key files and current state:

- **`X` keymap dispatch**: `src/sase/ace/tui/actions/axe.py:59-67` (`action_toggle_axe`) routes to
  `_dismiss_all_done_agents()` when on the Agents tab.
- **`,X` keymap dispatch**: `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py:106-110` (`_handle_leader_key`,
  `kill_all` branch) routes to `_kill_and_dismiss_all_agents()` when on the Agents tab.
- **`X` handler**: `src/sase/ace/tui/actions/agents/_dismissing.py:181-211` (`_dismiss_all_done_agents`) iterates
  `self._agents` unfiltered.
- **`,X` handler**: `src/sase/ace/tui/actions/agents/_killing.py:345-395` (`_kill_and_dismiss_all_agents`) iterates
  `self._agents` unfiltered for both `killable` and `dismissable`.
- **Panel model**: `src/sase/ace/tui/models/agent_panels.py` defines `PanelKey = str | None`, `_panel_key_for_agent`
  (with workflow-child parent inheritance), `agents_for_panel(agents, key)`, `panel_key_per_agent(agents)`, and the
  `AgentPanelGroup` dataclass with `focused_key`.
- **Focused panel access**: `self._panel_group: AgentPanelGroup | None`. When non-`None`,
  `self._panel_group.focused_key` is the tag of the panel the user is currently viewing (already used in
  `_core.py:133-142`). When `None` (no panel grouping active — e.g. early lifecycle), every agent is in scope.
- **Default config**: `X` is bound globally in `src/sase/default_config.yml` under `app.bindings.toggle_axe`, and `,X`
  is `leader_mode.keys.kill_all`. No binding changes are required — the candidate-set scope is what's changing, not the
  keymap surface.
- **No existing tests** target `_dismiss_all_done_agents` or `_kill_and_dismiss_all_agents` directly. New tests will be
  needed.

## Design

### Single helper in `_core.py`

Add a small helper on `AgentsActionMixin` (the `_core.py` mixin) that returns the agents in the currently focused panel,
falling back to all agents when the panel group hasn't been built yet:

```python
def _agents_in_focused_panel(self) -> list[Agent]:
    panel_group = getattr(self, "_panel_group", None)
    if panel_group is None:
        return list(self._agents)
    return agents_for_panel(self._agents, panel_group.focused_key)
```

Two reasons to centralize:

1. The fallback behavior (no `_panel_group` → all agents) needs to be identical for both handlers, and we don't want it
   to drift.
2. Future panel-scoped bulk actions (revive-all, retry-all, etc.) get a single hook to reuse.

### `X` handler change (`_dismissing.py`)

Replace the `dismissable` comprehension's source list:

```python
dismissable = [
    a
    for a in self._agents_in_focused_panel()
    if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
]
```

Empty-state notification stays the same ("No agents to dismiss") — it now correctly describes "no dismissable agents in
this panel," which is the user's intent.

### `,X` handler change (`_killing.py`)

Same substitution for both lists. Compute the panel slice once for clarity:

```python
panel_agents = self._agents_in_focused_panel()
killable = [
    a for a in panel_agents
    if a.pid is not None and a.status not in DISMISSABLE_STATUSES
]
dismissable = [
    a for a in panel_agents
    if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
]
```

Modal flow (double-confirm `ConfirmKillAllModal`), kill mechanics, post-kill dismiss step — all unchanged.

### Edge cases

- **Untagged panel focused (`focused_key is None`)**: only untagged agents (and workflow children of untagged parents)
  are affected. Tagged agents in other panels are untouched. This is the desired behavior.
- **Empty focused panel**: both `killable` and `dismissable` are empty → existing "No agents to ..." notification fires;
  no modal pops up. No special handling needed.
- **Workflow children**: `agents_for_panel` already routes children to their parent's panel, so a child's effective
  panel matches its parent. Killing the parent's panel kills its children — this matches what the user sees on screen.
- **Panel disappears mid-action**: not a real concern — the focused key is read once at handler entry, and the modal's
  `on_dismiss` callback uses the captured `killable`/`dismissable` lists, which are snapshots.
- **`_panel_group is None`**: defensive fallback to old "all agents" behavior. Should be unreachable on the Agents tab
  post-load, but the handler must not crash if a user manages to fire the keymap during a rare window before the panel
  group is built.

### Footer / help-modal text

Current strings:

- Footer (`keybinding_footer.py:378`): `"kill & dismiss all"`.
- Help modal (`help_modal/bindings.py:347`): `"Kill & dismiss all agents"`.

These should be updated to reflect panel scope so users aren't surprised:

- Footer → `"kill & dismiss panel"`.
- Help modal → `"Kill & dismiss agents in focused panel"`.

The repo's `AGENTS.md` flags help-popup sync as critical — keep them aligned.

The plain-`X` keymap doesn't appear in the footer or the help modal as a distinct line on the Agents tab (it's a global
"toggle_axe" binding whose Agents-tab behavior is described only in the `action_toggle_axe` docstring). Docstring
update:

- `axe.py:60` → `"Clear AXE output (X on AXE tab); dismiss done agents in focused panel on Agents tab."`

### Configuration

`src/sase/default_config.yml` does **not** need changes. The keymap identity (`X`, `,X`) is unchanged; only the
in-handler candidate set narrows.

## Files to modify

1. `src/sase/ace/tui/actions/agents/_core.py` — add `_agents_in_focused_panel()` helper to the mixin; ensure
   `agents_for_panel` is imported.
2. `src/sase/ace/tui/actions/agents/_dismissing.py` — switch `_dismiss_all_done_agents` source list.
3. `src/sase/ace/tui/actions/agents/_killing.py` — switch `_kill_and_dismiss_all_agents` source lists.
4. `src/sase/ace/tui/actions/axe.py` — update `action_toggle_axe` docstring.
5. `src/sase/ace/tui/widgets/keybinding_footer.py` — update label at line 378.
6. `src/sase/ace/tui/modals/help_modal/bindings.py` — update label at line 347.

## Tests

Add a new test module `tests/ace/tui/actions/test_panel_scoped_bulk.py` (or extend an existing actions test file if the
import wiring is already set up there) covering:

- **Dismiss is panel-scoped**: with three agents — one done in panel `None`, one done in panel `"fix"`, one done in
  panel `"review"` — and `_panel_group.focused_key == "fix"`, only the `"fix"` agent is passed to the dismiss modal's
  `on_dismiss` callback.
- **Kill+dismiss is panel-scoped**: mixed running and done agents across two tags; only those in the focused panel
  appear in the `killable`/`dismissable` lists handed to `ConfirmKillAllModal`.
- **Workflow child inheritance**: child agent inherits parent's panel. Focusing the parent's panel → child is included;
  focusing a different panel → child is excluded.
- **Empty focused panel**: handler short-circuits with the "No agents to ..." notification and never pushes a modal.
- **`_panel_group is None` fallback**: handler treats every agent as in-scope (preserves legacy behavior in the
  lifecycle gap).

The tests should mock `push_screen` / `notify` to capture the modal constructor args (or callback invocation) without
rendering a Textual app — pattern already used elsewhere in `tests/ace/tui/`.

## Risks

- Low. The change is a candidate-set narrowing inside two well-bounded handlers. No data persistence paths change. The
  double-confirm modal for `,X` still gates destructive action.
- Slight UX change: a user who relied on "`,X` nukes everything from any panel" loses that one-shot. Mitigation: focus
  the untagged panel and press `,X` per panel, or — if a global "kill everything" is still wanted — file a follow-up for
  a separate keymap. Not in scope here.

## Out of scope

- Adding a new global "kill across all panels" keymap.
- Changing how panel focus is tracked or rendered.
- Touching per-agent dismiss/kill paths (`,x`, single-agent `x`).
- `default_config.yml` changes.
