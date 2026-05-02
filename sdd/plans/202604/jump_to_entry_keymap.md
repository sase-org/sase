---
create_time: 2026-04-03 11:30:20
status: done
---

# Implement `V` Jump-To-Entry Keymap Across Ace TUI Tabs

## Objective

Add a new global `V` keymap that enables a one-keystroke jump to entries in the left side panel on all Ace tabs:

- CLs tab: ChangeSpecs list
- Agents tab: agents/workflows left panel (including pinned section)
- AXE tab: axe parent/lumberjacks/background commands list

The interaction is:

1. User presses `V`.
2. TUI overlays single-character hints next to left-panel entries.
3. User presses one hint key to jump directly to that entry.

Hint alphabet must be: `1-9`, then `0`, then `a-z`.

## Scope

- App-level keymap and binding metadata updates.
- New transient app state for “entry jump mode”.
- Key event interception while jump mode is active.
- Left-list rendering changes to display hint prefixes.
- Per-tab selection logic for resolving hint key -> selected index.
- Tests for keymap coverage and hint mapping behavior.

## Design

### 1) Keymap surface

Add a new app action `jump_to_entry` to the existing keymap pipeline:

- `src/sase/default_config.yml` default: `jump_to_entry: "V"`
- `AppKeymaps` dataclass field
- `_BINDING_META` entry
- fallback `DEFAULT_BINDINGS` entry
- help-modal bindings text for CLs/Agents/AXE

This keeps runtime key remapping support consistent with existing app actions.

### 2) Jump mode state model

Introduce app state fields to track transient jump mode:

- Whether mode is active.
- Mapping of hint char -> target index (tab-specific global index).
- Mapping of target index -> hint char (for rendering).

State is rebuilt when jump mode starts and consumed on the next keypress.

### 3) Hint generation

Define a canonical sequence for this mode:

- `"1234567890abcdefghijklmnopqrstuvwxyz"`

When entering mode, assign hints to visible entries in visual order, up to sequence length.

Tab-specific target ordering:

- CLs: `changespecs[0..]`
- Agents: main panel entries top-to-bottom, then pinned panel entries top-to-bottom
- AXE: `_axe_items[0..]`

### 4) Rendering hints in left panels

Extend list widget renderers with optional hint-prefix input keyed by local row index:

- `ChangeSpecList.update_list(..., jump_hints=...)`
- `AgentList.update_list(..., jump_hints=...)`
- `BgCmdList.update_list(..., jump_hints=...)`

Each entry prepends a styled marker like `[x] ` when hints are provided.

For Agents, convert global-index mapping to per-panel local mappings before calling each panel’s `update_list`.

### 5) Key handling

While jump mode is active:

- Intercept all keys in app `on_key` path before other mode handlers.
- `Esc`: cancel mode and remove hints.
- Valid hint key: jump to mapped index and exit mode.
- Invalid key: exit mode without jumping (single-key interaction preserved).

After exit, refresh only the current tab display to clear hint overlays.

### 6) Agent panel focus correctness

When jumping on Agents tab:

- If destination is in pinned panel, switch focus to pinned.
- If destination is in main panel, switch focus to main.

Then refresh agent display with list rebuild to ensure proper highlight/focus styling.

## Validation

- Unit tests:
  - keymap defaults/metadata count updates include `jump_to_entry`.
  - hint-sequence helper behavior and truncation semantics.
  - list-widget formatting includes hint marker when provided (targeted tests).
- Run repo checks:
  - `just install`
  - `just check`

## Risks and mitigations

- **Duplicate key handling with user overrides**: covered by existing keymap loader conflict logic.
- **Agent two-panel indexing bugs**: mitigate via explicit global->local mapping and focused tests.
- **Mode conflicts with existing transient modes**: intercept jump mode first and clear deterministically after next
  key.
