---
create_time: 2026-04-25 21:24:19
status: done
prompt: sdd/prompts/202604/agents_tab_per_group_fold.md
---
# Plan: Per-group expand/collapse on the Agents tab

## Background

The Agents tab renders agents grouped by **L0** (project / changespec) and **L1** (name-root) banners. Today, `l` and
`h` step a single global "group fold level" (`AgentGroupFoldState.level` ∈ {0, 1, 2}) that applies uniformly to every
group in the panel:

- L0 = only project banners visible
- L1 = project + name-root banners visible
- L2 = full tree (default)

This produces the surprising behaviour the user wants to fix: pressing `h` while focused inside one project collapses
**every** project at once, because the operation mutates a single shared integer rather than the focused group's own
state.

Relevant existing code:

- `src/sase/ace/tui/models/agent_group_fold.py` — defines `AgentGroupFoldState` (single global level,
  `expand`/`collapse`/ `expand_all`/`collapse_all`).
- `src/sase/ace/tui/actions/agents/_folding.py` — `_expand_fold`, `_collapse_fold`, `_expand_all_folds`,
  `_collapse_all_folds`, `_snap_focus_after_group_fold_change` plus `action_*` entry points bound to `l`/`L`/`h`/`H` via
  `bindings.py`.
- `src/sase/ace/tui/models/agent_groups.py` — `build_agent_tree`, `find_visible_ancestor_banner`; consumes the global
  level via the `group_fold_level: int` parameter.
- `src/sase/ace/tui/widgets/agent_list.py` — accepts `group_fold_level`, passes it to `build_agent_tree`, and decides
  banner selectability via `banners_selectable = effective_level < 2`.
- `src/sase/ace/tui/actions/event_handlers.py` — banner-click handler sets `_current_group_key`, which is the existing
  hook for banner-aware focus.

## Goals

1. `l` and `h` on the Agents tab should expand/collapse **only the group under the focused row** (and its containing
   groups, when stepping beyond a single group's range), never sibling groups.
2. Each group remembers its own collapsed/expanded state across refreshes for the lifetime of the TUI session.
3. The lowercase `l`/`h` per-workflow fold behaviour for an agent inside a fully-expanded group is preserved.
4. The capital `L`/`H` "expand all / collapse all" endpoints still work and should affect every group in the focused
   panel — they are the single-keystroke escape hatch out of any per-group state.

## Non-goals

- No change to keymap names or to the bindings file. We are only changing what the existing `expand_or_layout` /
  `hooks_or_collapse` actions do on the Agents tab.
- No persistence to disk — fold state is in-memory only, like today.
- Tag panels (`dynamic_tag_panels`) and the Axe / ChangeSpecs tabs are unaffected.
- We will not introduce a fourth level (e.g. "show L1 headers but hide agents within an L0"). The mental model stays two
  levels deep — each group is just collapsed or expanded.

## Target UX

Every group has a binary collapsed/expanded state. New groups default to expanded (matches today's `level=2` default).
The "focused group" is whichever group contains the currently selected row, or the group whose banner is selected. State
is stored separately for L0 keys (length 2: `(project, cl)`) and L1 keys (length 3: `(project, cl, name_root)`).

### `h` (collapse one level) — focused group

| Focused row                                         | Effect                                                                 |
| --------------------------------------------------- | ---------------------------------------------------------------------- |
| Agent inside a per-workflow fold that can step down | Per-workflow `_fold_manager.collapse(...)` first (existing behaviour). |
| Agent inside an L1 group                            | Collapse that L1 group; snap focus to the L1 banner.                   |
| Agent in an L0 group with no L1 (dotless name)      | Collapse the L0 group; snap focus to the L0 banner.                    |
| L1 banner (already collapsed)                       | Collapse the parent L0; snap focus to the L0 banner.                   |
| L0 banner (expanded)                                | Collapse this L0.                                                      |
| L0 banner (already collapsed)                       | No-op.                                                                 |

### `l` (expand one level) — focused group

| Focused row                                   | Effect                                                                            |
| --------------------------------------------- | --------------------------------------------------------------------------------- |
| Collapsed L0 banner                           | Expand this L0 (children may themselves be collapsed).                            |
| Collapsed L1 banner                           | Expand this L1.                                                                   |
| Expanded L0 banner with collapsed L1 children | No-op (use `j` to descend onto the L1 and `l` it, or use `L` for full expansion). |
| Agent in fully-expanded chain                 | Per-workflow `_fold_manager.expand(...)` (existing behaviour).                    |

### `L` / `H` (capital — apply to all groups)

`H` collapses every L0 and L1 group in the focused panel and runs the existing per-workflow `collapse_all`. `L` expands
every group and runs per-workflow `expand_all`. Capital variants stay session-wide so users have a one-keystroke way to
undo a thicket of per-group collapses.

## Data model changes

### Replace `AgentGroupFoldState` with a per-key registry

```python
# src/sase/ace/tui/models/agent_group_fold.py

GroupKey = tuple[str, ...]

@dataclass
class AgentGroupFoldRegistry:
    collapsed: set[GroupKey] = field(default_factory=set)

    def is_collapsed(self, key: GroupKey) -> bool: ...
    def collapse(self, key: GroupKey) -> bool:        # True if changed
    def expand(self, key: GroupKey) -> bool:          # True if changed
    def collapse_keys(self, keys: Iterable[GroupKey]) -> bool:
    def expand_keys(self, keys: Iterable[GroupKey]) -> bool:
    def clear_unknown(self, known: Iterable[GroupKey]) -> None:
        # garbage-collect keys for groups that no longer exist after a refresh
```

Storing only the _collapsed_ set keeps "expanded by default" trivial and avoids stale entries from looking different
from never-seen groups. `clear_unknown` runs once per refresh in `_refilter_agents` so removed groups don't accumulate.

`AceApp` currently owns `_group_fold_state: AgentGroupFoldState`; rename to
`_group_fold_registry: AgentGroupFoldRegistry` and update the `AgentFoldingMixin` type hint plus the app's `__init__`.

### Tree builder takes the registry instead of an int

```python
# src/sase/ace/tui/models/agent_groups.py

def build_agent_tree(
    agents: list[Agent],
    fold_registry: AgentGroupFoldRegistry | None = None,
) -> list[TreeEntry]: ...
```

Walk semantics:

- Always emit each L0 banner. Set `GroupRow.is_collapsed = registry.is_collapsed(l0_key)`.
- If the L0 is collapsed: emit no children — skip to the next L0.
- If the L0 is expanded:
  - For each L1 sub-group in deterministic order (singletons still flattened as today): emit its banner with
    `is_collapsed = registry.is_collapsed(l1_key)`.
    - If the L1 is collapsed: emit no agents.
    - If the L1 is expanded: emit its agents (and their attempt children).
  - Dotless agents (no `name_root`) emit directly under the L0 banner, as today.

`_build_collapsed_tree` is dropped — `_build_full_tree` is generalised to handle both cases via the registry. The
`group_fold_level: int` parameter is removed.

### Banner selectability

Replace `banners_selectable = effective_level < 2` in `AgentList.update_list` with: a banner is selectable iff its
`GroupRow.is_collapsed` is True. The user always reaches a banner by collapsing into it (`h`) or by clicking it;
expanded banners stay disabled so `j`/`k` continues to fly through agents — this preserves today's navigation feel.

The widget's signature changes from `group_fold_level: int = 2, current_group_key: tuple[str, ...] | None = None` to a
single source of truth: the tree it receives already encodes collapse state per group, so the widget only needs
`current_group_key`. Builder calls in `_display.py` (and any test helpers) move from passing an int level to passing the
registry.

## Action behaviour

### `_expand_fold` (`l`) — rewrite

```
if current_tab != "agents":
    fall through to existing per-workflow behaviour

focused_l1, focused_l0 = _focused_group_keys()  # see helper below

# 1. Banner is the focus → expand exactly that group.
if _current_group_key is not None:
    if registry.expand(_current_group_key):
        _refilter_agents()
    return

# 2. Agent is the focus → per-workflow fold first (existing behaviour).
agent = _get_selected_agent()
if agent is not None:
    key = _get_workflow_key_for_agent(agent)
    if key is not None and _fold_manager.expand(key):
        _refilter_agents()
        return
```

`l` on an agent never changes group state — that only happens when the focused row _is_ a banner, which only occurs for
collapsed groups (per the selectability rule). This matches the user's mental model: "l on a banner opens that group".

### `_collapse_fold` (`h`) — rewrite

```
if current_tab != "agents":
    fall through to existing per-workflow behaviour

# 1. Try per-workflow fold first if focused on an expanded workflow agent
#    (preserves today's "h collapses my workflow" behaviour).
agent = _get_selected_agent()
if agent is not None:
    key = _get_workflow_key_for_agent(agent)
    if key is not None and _fold_manager.get(key) != COLLAPSED:
        ... existing per-workflow snap + collapse ...
        return

# 2. Banner focus → collapse it; if already collapsed, walk one level up.
if _current_group_key is not None:
    if len(_current_group_key) == 3 and registry.is_collapsed(_current_group_key):
        # L1 banner already collapsed → collapse the parent L0 instead.
        l0_key = _current_group_key[:2]
        if registry.collapse(l0_key):
            _current_group_key = l0_key
            _refilter_agents()
        return
    if registry.collapse(_current_group_key):
        _refilter_agents()
    return

# 3. Agent focus, no per-workflow fold to step → collapse its enclosing group.
focused_l1_key, focused_l0_key = _focused_group_keys()
target = focused_l1_key or focused_l0_key
if target is not None and registry.collapse(target):
    _current_group_key = target
    _snap_focus_after_group_fold_change()  # snap to the now-visible banner
    _refilter_agents()
```

### `_focused_group_keys()` helper

New mixin method that, given `current_idx`, returns `(l1_key | None, l0_key)` for the focused agent (delegating to the
existing `_grouping_keys_for` machinery in `agent_groups.py`, exposed as a small public helper). When the focus is a
banner, prefer `_current_group_key` and skip this lookup.

### `_snap_focus_after_group_fold_change`

Replace the `level >= 2 → clear group key` branch with: if the focused row's enclosing group(s) are now expanded **and**
the focused agent remains visible, clear `_current_group_key`. Otherwise snap to the deepest collapsed ancestor banner
using `find_visible_ancestor_banner`, which already does the right thing once the tree is rebuilt against the registry.

### `_expand_all_folds` / `_collapse_all_folds` (`L` / `H`)

- Collect every group key currently produced by the tree (both L0 and L1 — `agent_groups` already enumerates them).
- `L`: `registry.expand_keys(all_keys)` + existing per-workflow `expand_all`.
- `H`: per-workflow `collapse_all` + `registry.collapse_keys(all_keys)`, then `_snap_focus_after_group_fold_change`.

Behaviour matches today's "everything visible" / "everything collapsed to project banners" endpoints, just expressed in
the per-key model.

## Tests

Update / extend (paths under `tests/ace/tui/`):

- `models/test_agent_group_fold.py` — replace global-level tests with registry-based tests: per-key collapse/expand
  returning change flag, bulk operations, `clear_unknown`.
- `models/test_agent_groups.py` (existing tree builder coverage) — add cases that mix collapsed and expanded sibling
  groups, asserting only the targeted group hides its descendants and the others remain fully expanded.
- `test_agent_fold_transitions.py` — rewrite the L0/L1/L2 state machine tests to per-group scenarios:
  - Two projects A (focused) + B; press `h` → only A collapses.
  - Focus inside an L1, `h` collapses just the L1; second `h` collapses the parent L0.
  - `l` on a collapsed L1 banner expands only that L1.
  - `L` and `H` still snap the whole panel to fully-expanded / fully-collapsed.
  - Per-workflow `h` on a workflow parent still collapses the workflow before any group state moves.
- `widgets/test_agent_list_grouping.py` — update banner-selectability cases to assert: banner is selectable iff the
  group is collapsed; an expanded sibling banner remains disabled when its sibling is collapsed.
- `test_agent_group_kill.py` — sanity-check that `_current_group_key` semantics still drive group-aware kill.

Snapshot/integration runs (`just test`) should continue to pass after banner styling stays unchanged (no edits to
`_agent_list_rendering.py` or `_agent_list_styling.py` are required — the renderer keys off `GroupRow.is_collapsed`,
which already exists).

## Risks & mitigations

- **Stale registry keys**: a group that disappears (last agent killed) could leave a dangling collapsed entry that
  re-applies if the same group key reappears. `clear_unknown` after every refresh keeps the set bounded; tested via a
  refresh-cycle test.
- **Banner-only navigation feels different**: today's `l` after `H` walks a single ladder up to "everything visible".
  With per-group state, each L0 needs its own `l` press. This is intentional but worth calling out in the help modal if
  it currently advertises "step up one level". Search `help_modal.py` and update the hint string; required by the
  project's "Help Popup Maintenance" rule in `src/sase/ace/AGENTS.md`.
- **Cursor on a banner whose group just expanded**: with banners disabled when expanded, the highlighted row would jump
  after `l`. We resolve by: after `l` from a banner, re-anchor focus on the first agent of the now-expanded group (or,
  when the group's children are themselves L1 banners, on the first child banner that remains collapsed). Add a focused
  test for this case.
- **Migration of `_group_fold_state` references**: rename touches the app, the mixin, and any test that constructs the
  app/mixin directly. A repo-wide grep will surface them; the public surface beyond that is small.

## Out of scope / follow-ups

- Persisting collapse state across `sase ace` restarts.
- A "remember last fold per project" CLI flag.
- Tag-panel (`dynamic_tag_panels`) collapse — still treated as separate panels rather than groups.
- Visual changes to banners (colours, glyphs) — the existing `is_collapsed` styling already differentiates collapsed
  from expanded banners, and that is enough.
