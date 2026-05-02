---
create_time: 2026-04-27 09:45:48
status: done
prompt: sdd/prompts/202604/jump_hints_for_folded_banners.md
---
# Jump hints for folded headings on the Agents tab

## Problem

Pressing `'` (apostrophe — bound to `jump_to_entry`) on the Agents tab of `sase ace` paints `[x]` jump hints next to
**visible agent rows** so the user can leap to one with a single keystroke. Folded group headings (e.g.
`▸ aw ──────── 2 agents · 2 running`, `▸ m ───── 2 agents` in the snapshot) get no hint, even though they are selectable
rows that `j`/`k` already cycles through. There is no fast way to "jump to a folded group" — the user has to hammer
`j`/`k` past every visible agent until the cursor lands on the right banner.

We want `'` to also paint a hint next to every folded heading so a single keystroke can select that heading. Selecting a
heading here means the same thing it means today in `_navigate_agents_panel()`: set `_current_group_key` to the banner's
group key (and, when needed, switch the focused tag panel) — the renderer will then highlight that banner row and the
user can press the existing fold/expand keymap from there.

## Background — what already exists

- **Keymap**: `'` → `apostrophe` → `action_jump_to_entry` (`src/sase/default_config.yml:35`).
- **Hint allocator**: `action_jump_to_entry` (`src/sase/ace/tui/actions/navigation/_advanced.py:133-148`) calls
  `_jump_candidate_indices()` to get an ordered `list[int]` of agent indices, then `build_jump_hint_maps()`
  (`src/sase/ace/tui/actions/navigation/jump_hints.py:6-13`) zips those with `JUMP_HINT_CHARS` to produce two parallel
  dicts: `_entry_jump_hint_to_index: dict[str, int]` and `_entry_jump_index_to_hint: dict[int, str]`.
- **Hint dispatch**: `_handle_entry_jump_key()` (`_advanced.py:179-211`) looks up the keystroke in
  `_entry_jump_hint_to_index` and assigns the resulting `int` to `self.current_idx`. The `'` key is also overloaded as
  "jump back to last position" via `_entry_jump_last_index[tab]` (`_advanced.py:187-194`).
- **Agent hint rendering**: `_refresh_panel_widgets` passes `jump_hints: dict[int, str]` (per-panel localized) into
  `AgentList.update_list` (`src/sase/ace/tui/widgets/agent_list.py:124-269`), which threads `hint_char` into
  `cached_format_agent_option`; the renderer prepends `[{hint_char}] ` in bold yellow to the row's left text
  (`src/sase/ace/tui/widgets/_agent_list_rendering.py:256-257`).
- **Banner data model**: `build_agent_tree()` (`src/sase/ace/tui/models/agent_groups.py:445-576`) emits `TreeEntry`s
  whose `kind="group"` carries a `GroupRow(level, group_key, agent_indices, is_collapsed)`. Only collapsed banners are
  selectable — `_panel_navigation_stops()` (`src/sase/ace/tui/actions/agents/_core.py:144-187`) records them as
  `("banner", group_key)` stops, expanded banners are emitted as disabled options (`agent_list.py:300-321`,
  `_agent_list_rendering.py:540` `disabled=not selectable`) and `j`/`k` flies past them.
- **Banner selection**: setting `self._current_group_key = <group_key>` and refreshing causes `update_list` to highlight
  the matching banner row (`agent_list.py:322-327`). Cross-panel selection happens by also writing to
  `self._panel_group.focused_idx` (see `event_handlers.py:360-361`).

## Design

Extend the jump-hint pipeline so that targets can be either an agent index or a banner identity, and so that collapsed
banner rows render the same `[x]` chip that agent rows already render.

### 1. Generalize the hint target type

Change the per-tab target from `int` to a tagged tuple so banners can ride alongside agents. Defining a tiny dataclass
inside `jump_hints.py` is cleaner but a tuple keeps the diff small:

```python
# agents-tab targets
AgentJumpTarget = tuple[Literal["agent"], int]                       # ("agent", global_agent_idx)
BannerJumpTarget = tuple[Literal["banner"], int, tuple[str, ...]]    # ("banner", panel_idx, group_key)
JumpTarget = AgentJumpTarget | BannerJumpTarget
```

`build_jump_hint_maps()` becomes generic over the target type — its body already only `zip`s opaque values with
`JUMP_HINT_CHARS`, so the change is just a signature update (`list[T]` → `tuple[dict[str, T], dict[T, str]]`). The CLs
and AXE tabs continue to pass plain `list[int]` and get back the same shape they do today.

### 2. Collect targets in render order across all panels

Today `_jump_candidate_indices()` (`_advanced.py:150-167`) builds **one** `build_agent_tree` over the full
`self._agents` list, which doesn't reflect how the renderer actually splits agents per tag panel. Replace the agents
branch with a per-panel walk that mirrors `_refresh_panel_widgets` (`_display.py:287-372`):

```python
def _jump_targets_agents(self) -> list[JumpTarget]:
    from ...models.agent_groups import GroupingMode, build_agent_tree
    from ...models.agent_panels import agents_for_panel, panel_key_per_agent

    registry = self._group_fold_registry
    mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
    panel_group = getattr(self, "_panel_group", None)
    panel_keys = panel_group.panel_keys if panel_group is not None else [None]
    keys_per_agent = panel_key_per_agent(self._agents)
    targets: list[JumpTarget] = []
    for panel_idx, key in enumerate(panel_keys):
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == key]
        panel_agents = agents_for_panel(self._agents, key)
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    targets.append(("banner", panel_idx, entry.group.group_key))
            elif entry.kind == "agent" and entry.agent_idx is not None:
                targets.append(("agent", global_indices[entry.agent_idx]))
    return targets
```

Notes:

- Walking panel-by-panel matches the visible top-to-bottom render order, so hint characters march down the screen the
  same way they do for agents today (preserving the property fixed in `sase_plan_agents_jump_hint_order.md`).
- `is_collapsed` already filters out expanded banners — they would not be selectable, so giving them hints would be
  confusing.
- `agent_indices` inside a collapsed banner are **not** emitted by `build_agent_tree`, so collapsed-out agents continue
  to be hint-less (existing behavior).
- The CLs/AXE branches of `_jump_candidate_indices()` are untouched; rename the internal helper to
  `_jump_candidate_targets()` and wrap their `range(len(...))` in `("agent", i)` shape (or, equivalently, keep two code
  paths and only widen the agents-tab path — same effect with a smaller diff).

### 3. Plumb banner hints through the renderer

`AgentList.update_list()` already accepts `jump_hints: dict[int, str]` for agents. Add a sibling parameter:

```python
banner_jump_hints: dict[tuple[str, ...], str] | None = None,
```

In the tree-walk loop (`agent_list.py:283-328`), pass `hint_char=banner_jump_hints.get(entry.group.group_key)` into
`cached_format_banner_option`, and only when the banner is selectable (`entry.group.is_collapsed`). Plumb `hint_char`
through `cached_format_banner_option` → `format_banner_option` (`_agent_list_rendering.py:439-541`) and the cache key
helper `_banner_render_key` (`:664-694`) so two cache entries don't collide on the same `(group_key, level, …)`.

Inside `format_banner_option`, prepend the hint chip immediately after the tier-guide gutter, mirroring the agent
renderer (`_agent_list_rendering.py:255-257`):

```python
text = _render_tier_gutter(tier_styles)
if hint_char is not None:
    text.append(f"[{hint_char}] ", style="bold #FFFF00")
text.append(prefix, style=prefix_style)
text.append(label, style=label_style)
```

The chip is part of the banner's left text, so the existing `used = gutter_cells + len(prefix) + len(label) + …` pad
math needs to add the chip's cell width when present (4 cells for `[x] `). Without this the rule glyphs overflow by 4
columns on hinted banners.

`_refresh_panel_widgets` (`_display.py:287-372`) needs to:

1. Build a `banner_jump_hints` dict per panel by inverting the (panel_idx → group_key) entries in the global hint map.
2. Pass it to each panel's `update_list` call (`:362-372`).

### 4. Dispatch a banner hint keystroke

In `_handle_entry_jump_key()` (`_advanced.py:179-211`), branch on the target's tag:

```python
target = self._entry_jump_hint_to_target.get(key)
if target is None:
    self._exit_entry_jump_mode()
    return True
self._save_entry_jump_anchor()  # see §5
kind = target[0]
if kind == "agent":
    self._current_group_key = None
    self.current_idx = target[1]
elif kind == "banner":
    _, panel_idx, group_key = target
    if panel_idx != self._panel_group.focused_idx:
        self._panel_group.focused_idx = panel_idx
    self._current_group_key = group_key
self._exit_entry_jump_mode_and_refresh()
```

Banner selection sets `_current_group_key`; the renderer then highlights the matching banner row in the focused panel
(existing logic at `agent_list.py:322-327`). Because the agent index didn't change, the existing safety net at
`_basic.py:62-63` (which forces a refresh when only `_current_group_key` changed) is reused — call
`_refresh_agents_display(list_changed=True)` from the exit path so hint overlays disappear on the same frame.

### 5. Back-jump (`'` again) needs a richer anchor

Today `_entry_jump_last_index[self.current_tab]` stores a single `int`. For the agents tab it must remember whether the
user was on an agent row or a banner row, and on which panel:

```python
AgentsAnchor = tuple[Literal["agent"], int] | tuple[Literal["banner"], int, tuple[str, ...]]
```

Two small changes:

- `_entry_jump_last_index` becomes `dict[str, AgentsAnchor | int]` (agents tab uses the union; CLs / AXE keep `int`).
- The `key == "apostrophe"` branch of `_handle_entry_jump_key` (`_advanced.py:187-194`) restores the anchor: assign
  `current_idx` and/or `_current_group_key` and `_panel_group.focused_idx` from the stored tuple, save the current state
  as the new anchor before jumping, and refresh.

### 6. Footer / help / docs

- Footer: no new keymap appears (still just `'`); the existing jump-mode footer (`_advanced.py:213-222`) does not need
  to change, but verify the "back" indicator computation still works with the widened `_entry_jump_last_index` value
  type (treat any non-None entry as "has back").
- Help modal: `'` is already documented as "jump to entry"; per `src/sase/ace/AGENTS.md`'s help-popup rule, update the
  agents-tab section of `help_modal.py` to mention that hints now also appear on folded headings.

## Files to change

- `src/sase/ace/tui/actions/navigation/jump_hints.py` — generic `build_jump_hint_maps[T]`.
- `src/sase/ace/tui/actions/navigation/_advanced.py` — replace `_jump_candidate_indices` with `_jump_candidate_targets`;
  rewrite `_handle_entry_jump_key` for tagged targets; widen `_entry_jump_last_index` to anchors.
- `src/sase/ace/tui/actions/navigation/_types.py` — type annotations for the new state attributes
  (`_entry_jump_hint_to_target`, `_entry_jump_target_to_hint`, anchor type).
- `src/sase/ace/tui/widgets/agent_list.py` — accept `banner_jump_hints`; pass `hint_char` into
  `cached_format_banner_option`.
- `src/sase/ace/tui/widgets/_agent_list_rendering.py` — `format_banner_option` and its cache wrapper accept `hint_char`;
  update `_banner_render_key` to include it; pad math accounts for chip width.
- `src/sase/ace/tui/actions/agents/_display.py` — split the global hint map into per-panel
  `(jump_hints, banner_jump_hints)` and pass both into each `update_list` call.
- `src/sase/ace/tui/modals/help_modal.py` — one-line note that hints now cover folded headings.

## Edge cases

- **Expanded banners get no hint.** They are not selectable; rendering `[x]` next to them would mislead the user. The
  `is_collapsed` filter in the target collector handles this naturally.
- **Banner in a non-focused panel.** Jumping switches `focused_idx` first, then sets `_current_group_key`. Both writes
  fire a single refresh.
- **More targets than `JUMP_HINT_CHARS` (62).** `build_jump_hint_maps` already truncates via `zip(strict=False)`;
  late-render targets simply get no hint — consistent with current behavior.
- **Banner group_key collisions across panels.** Per-panel maps avoid this: each panel's `banner_jump_hints` only
  contains keys for that panel's tree, and the global `_entry_jump_hint_to_target` disambiguates with `panel_idx`.
- **`'` re-press for back-jump from a banner anchor.** Anchor restoration must happen before clearing
  `_entry_jump_mode_active` so the refresh paints the restored cursor.
- **Agent's hint chip already shifts the row text right** by 4 cells; banners need the same shift accounted for in the
  rule-padding calculation or hinted banner rules will overrun the chip column.

## Out of scope

- Hints for the right-pane AGENT DETAILS / files / chat (this work is left-pane only).
- Re-targeting `'` to also jump to **expanded** group banners.
- Renaming or rebinding `'` itself.
- Changing the banner cache invalidation strategy beyond extending `_banner_render_key`.

## Validation

- `just check` passes (mypy will catch any missed call-site updates from widening the hint target type).
- New unit tests under `tests/ace/tui/`:
  - `test_jump_targets_includes_collapsed_banners`: with one collapsed L0 banner + 3 visible agents, assert
    `_jump_candidate_targets()` returns `[("banner", 0, (...,)), ("agent", a), ("agent", b), ("agent", c)]` in render
    order.
  - `test_jump_targets_skips_expanded_banners`: same setup with the banner expanded, assert no banner target appears.
  - `test_jump_dispatch_banner_sets_group_key`: simulate the keystroke, assert `_current_group_key` is set and
    `current_idx` is unchanged.
  - `test_jump_dispatch_banner_switches_focused_panel`: with the banner in panel 1 while panel 0 is focused, assert
    `focused_idx` becomes 1 after the jump.
  - `test_back_jump_restores_banner_anchor`: agent → banner → `'` → agent restores the original `current_idx`.
- Manual smoke (per `memory/short/workspaces.md`, `just install` first inside the workspace clone): launch `sase ace`,
  collapse a project banner with the per-group fold key, press `'`, verify a `[x]` chip appears on the banner. Press the
  corresponding key and confirm the cursor highlights the banner. Re-press `'` to verify the back-jump returns to the
  prior agent.
