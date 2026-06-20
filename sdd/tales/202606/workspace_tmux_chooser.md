---
create_time: 2026-06-20 17:03:12
status: done
prompt: sdd/prompts/202606/workspace_tmux_chooser.md
---
# Tmux Workspace Chooser for Agents with Opened Workspaces

## Goal

When the selected Agents-tab row has a visible `WORKSPACES` lane in `SASE CONTEXT`, pressing `t` should open a polished,
keyboard-first chooser instead of immediately opening the selected agent workspace.

The chooser should offer:

- one `CURRENT` option for the selected agent's own project / ChangeSpec workspace, preserving today's `t` behavior once
  selected;
- one `LINKED` option for each unique repository that the agent context opened through `sase workspace open`;
- immediate single-key selection for every option, with `enter` still selecting the highlighted row and `q` / `esc`
  cancelling.

When no opened-workspace context is visible for the selected agent, `t` should keep doing exactly what it does today.
`T` should continue to open the primary workspace directly.

## Product Design

This is a fast tmux disambiguation panel, not a search workflow. It should feel like a natural extension of the current
Agents-tab `t` keymap:

- Press `t`.
- See the current workspace and the opened linked repos as a compact, centered modal.
- Press one displayed key (`a`, `b`, `c`, etc.) to open or switch to that tmux window.

The panel should visually echo the new `WORKSPACES` lane:

- Use the same workspace magenta accent and fallback workspace glyph (`▣`) already verified against the local visual
  font.
- Use a gold selector column, matching the sibling-agent chooser and artifact chooser.
- Keep rows dense and scan-friendly: selector, type chip, primary name, dim path, optional truncated reason.
- Title example: `Tmux Workspace · 4 targets`.
- Hint footer: `a-z/0-9 select  enter open  j/k move  q/esc close`.

Example row grammar:

```text
a  CURRENT  sase_context_workspaces_lane  · sase  -> ~/.../sase_12
b  LINKED   sase-core                     -> ~/.../sase-core_12  · Need Rust backend context
c  LINKED   bob                           -> ~/.../bob_12        · Compare Obsidian workflow
```

I will use Rich `Text` styling rather than visible explanatory prose in the app. The modal should be self-explanatory
from labels and row structure.

## Current Behavior

On the Agents tab:

- `t` is handled by `AgentPanelTmuxMixin.action_start_tmux_mode`.
- It currently calls `_open_agent_tmux_window(use_primary=False)` directly.
- `T` calls `_open_agent_tmux_window(use_primary=True)`.
- `_open_agent_tmux_window` resolves the selected agent workspace, then either selects an existing tmux window or
  creates a new one.

For non-Agents tabs, `t` still routes to the existing ChangeSpec workspace-number modal.

The `WORKSPACES` lane data already exists from the prior change:

- `src/sase/ace/tui/opened_workspaces.py` loads `OpenedWorkspaceDisplayEvent` values from marker files.
- `build_detail_header_summary(agent)` loads those events on the debounced detail-panel path.
- The prompt panel renders `SASE CONTEXT` only when the expensive summary is present, so the visible lane is already a
  reliable signal that opened-workspace context has been loaded.

## Performance Design

Per `memory/tui_perf.md`, the `t` action must not synchronously parse marker JSON or `stat()` marker files just to
decide whether to show the chooser.

The implementation should therefore add a small no-I/O cache handoff:

1. When the debounced prompt-panel detail render builds `_DetailHeaderSummary`, it already has
   `summary.opened_workspaces`.
2. The prompt/detail layer stores those events on the app keyed by the selected agent identity. Empty tuples are stored
   too, so old non-empty data cannot leak across refreshes.
3. `action_start_tmux_mode` checks only that in-memory cache.
4. If cached opened-workspace events are present, `t` opens the chooser.
5. If there are no cached events, `t` falls back to the current direct-open path.

This exactly matches the product rule: the chooser appears when the `WORKSPACES` subsection is visible. It also avoids
introducing a second loader path on keypress.

## Interaction Details

### Target List

Build a pure target model, likely in a new `agent_workspace_tmux_modal.py` or a small adjacent helper:

- `AgentWorkspaceTmuxChoice`
  - `kind`: `"current"` or `"linked"`
  - `label`: display name
  - `project_name`: optional project context
  - `workspace_dir`: optional for current, required for linked
  - `window_name`: tmux window name
  - `reason`: optional linked-workspace reason
  - `agent_label`: optional family role label from the WORKSPACES event

The first choice is always `CURRENT`.

For `CURRENT`, do not reimplement workspace resolution in the modal. Selecting it should route through the existing
`_open_agent_tmux_window(use_primary=False)` path so numbered-workspace, directory-mode, and workflow-step behavior stay
unchanged.

For linked repos, use the recorded `workspace_dir`. The tmux window name should be the workspace directory basename when
available (`sase-core_12`), falling back to the linked repo name. This matches what users see on disk and keeps sibling
workspaces distinguishable.

For agent-family contexts, dedupe linked choices by `(repo name, workspace_dir)` so the chooser has one option per repo
destination, not one option per audit event. Keep the newest event's reason/role label for display.

### Selector Keys

Every rendered option must have a single-key selector.

Use a selector pool large enough for the loader's current cap:

- lowercase letters excluding navigation/cancel keys: `a-z` minus `j`, `k`, `q`;
- digits `0-9`;
- uppercase letters excluding `J`, `K`, `Q`.

That gives enough single-key selectors for the current `MAX_KEPT_OPENED_WORKSPACES` plus `CURRENT`.

Rows should still support:

- `enter`: open highlighted target;
- `j` / `k`, arrows, `ctrl+n` / `ctrl+p`: move highlight;
- `q` / `esc`: close without opening;
- mouse/OptionList selection as a secondary affordance.

### Tmux Opening

Factor the duplicated tmux window select/create logic in `_panel_tmux.py` into a helper such as:

```python
_open_tmux_window_for_directory(workspace_dir: str, window_name: str) -> None
```

Then:

- `_open_agent_tmux_window(...)` keeps resolving the current/primary workspace as it does today and calls the helper.
- linked modal choices call the helper directly with the recorded linked workspace path.

If a linked workspace path no longer exists, notify with a warning and do not launch tmux.

## Footer And Help

The Agents-tab footer currently shows `t tmux` whenever the focused agent has a workspace. Update that label without
changing keymaps:

- no opened-workspace context cached: `t tmux`;
- opened-workspace context cached: `t tmux choices (N)`, where `N` includes `CURRENT`;
- `T tmux (primary)` stays unchanged.

The help modal / command catalog wording can be lightly updated from "Tmux in agent workspace" to "Tmux workspace
chooser" for Agents-tab context, while preserving the same `start_tmux_mode` action id and user-config key.

## Files To Change

Source:

- `src/sase/ace/tui/actions/agents/_panel_tmux.py`
  - route `t` to the chooser only when cached opened-workspace events exist;
  - factor shared tmux window select/create helper;
  - add linked-target open path.
- `src/sase/ace/tui/modals/agent_workspace_tmux_modal.py` (new)
  - target dataclass, selector-key generation, row rendering, modal behavior.
- `src/sase/ace/tui/modals/__init__.py`
  - export the new modal/types.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` or nearby prompt-panel plumbing
  - publish `summary.opened_workspaces` to the app after the debounced detail summary is built.
- `src/sase/ace/tui/actions/agents/_display_detail.py`
  - pass cached opened-workspace target counts into footer computation, or expose an app helper used by footer refresh.
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`
  - update the Agents-tab `t` footer label when choices are available.
- `src/sase/ace/tui/widgets/_keybinding_modes.py`
  - thread the new count parameter through `update_agent_bindings`.
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
  - refresh the Agents-tab wording for `t`.
- `src/sase/ace/tui/styles.tcss`
  - add compact modal styling, borrowing the sibling modal dimensions but using the workspace accent.

Tests:

- `tests/ace/tui/modals/test_agent_workspace_tmux_modal.py` (new)
  - selector keys skip navigation/cancel keys and cover at least 51 choices;
  - letter/digit/uppercase quick selection dismisses the correct choice;
  - `enter`, `j/k`, and `q/esc` behave like the sibling chooser;
  - row text includes current/link type, repo/project label, path, and truncated reason.
- `tests/ace/tui/actions/test_agent_panel_tmux.py`
  - no cached workspaces: `t` directly opens the current agent workspace as today;
  - cached workspaces: `t` pushes the chooser instead of launching tmux immediately;
  - selecting `CURRENT` calls the existing current-workspace path;
  - selecting a linked repo opens tmux in the recorded linked workspace with the expected window name;
  - missing linked workspace path emits a warning.
- Footer/help tests
  - footer label remains `tmux` without cached choices;
  - footer label becomes `tmux choices (N)` with cached choices;
  - help text reflects the chooser wording.
- Visual tests
  - add a narrow or medium PNG snapshot for the new modal with one current target and two linked repos;
  - assert SVG contains the title, selectors, `CURRENT`, `LINKED`, a repo name, and a reason fragment.

## Validation

Targeted:

```bash
uv run pytest \
  tests/ace/tui/modals/test_agent_workspace_tmux_modal.py \
  tests/ace/tui/actions/test_agent_panel_tmux.py \
  tests/ace/tui/test_footer_visibility.py \
  tests/test_keymaps_defaults.py \
  tests/test_command_catalog_guards.py
```

Visual:

```bash
just test-visual --sase-update-visual-snapshots
just test-visual
```

Full gate:

```bash
just check
```

If the existing `uv run` lockfile issue in this workspace recurs, use the installed virtualenv Python for targeted
pytest, as in the prior change, then still run the repo-level `just check`.

## Review Decisions

- The chooser appears only from cached visible `WORKSPACES` context, not by doing fresh marker reads from the `t`
  keypress.
- `CURRENT` is always first and preserves today's `t` behavior.
- Linked repo targets open the recorded workspace directory directly and do not checkout a branch.
- Agent-family opened workspace events are deduped to one option per repo destination.
- `T` remains the direct primary-workspace shortcut.
