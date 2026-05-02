---
create_time: 2026-04-25 18:24:47
status: wip
prompt: sdd/prompts/202604/jk_banner_highlight.md
---
# `sase ace` Agents tab: `j`/`k` doesn't visually move the highlight off an L2 banner at fold < 3

## Problem

On the Agents tab, when the group fold level is < 3 the list shows banner-only rows (L0 tag rule, L1 project /
changespec rule, L2 name-root) with no agent rows interspersed. Pressing `j` (or `k`) on a banner is supposed to walk
the user through the full banner sequence.

In practice, after the user lands on an L1 (project / changespec) banner, pressing `j` does not visually move the
highlight to the L2 name-root banner directly below. The agent-detail panel on the right _does_ update — it shows the
first agent of the next group — which is why the user perceives "we navigated to the next ChangeSpec" instead of "we
landed on the L3 banner".

Reproduction (matches the user-attached `sase ace` snapshot):

- Layout in the agent list:
  ```
  ══ (untagged) 21 agents · 1 running ═══════════════
  ── sase / sase 21 agents · 1 running ──────────────
  · sase-r ·5 agents
  · sase-q ·6 agents
  ```
- Cursor on the L1 banner (`── sase / sase ──`).
- Press `j`. Expected: highlight moves to `· sase-r ·`. Actual: highlight stays on the L1 banner visually, but the
  right-hand detail panel jumps to a sase-r agent.

## Root cause

The j/k debounced refresh path drops `_current_group_key`, and `AgentList.update_highlight` has no way to highlight a
banner row even if it received the key:

- `src/sase/ace/tui/actions/agents/_display.py:186-209` — `_refresh_agents_display_debounced` calls
  `agent_list.update_highlight(local_idx, self.current_attempt_number)` at line 207. It does _not_ pass
  `_current_group_key`. The full-refresh sibling at line 124-135 _does_ pass it via
  `update_list(..., current_group_key=self._current_group_key)`.
- `src/sase/ace/tui/widgets/agent_list.py:299-320` — `update_highlight(current_idx, current_attempt_number=None)` only
  searches `self._row_entries` for the agent-row tuple `(current_idx, current_attempt_number)`. At fold level < 3 the
  collapsed tree built by `models/agent_groups.py::_build_collapsed_tree` emits banner rows only; every entry of
  `_row_entries` is `(_BANNER_ROW, None)`. The search never matches and `OptionList.highlighted` is left pointing at
  whatever banner the previous `update_list` set up.

The j/k navigation logic itself is correct: `actions/navigation/_basic.py:_navigate_agents_panel` walks the banner list
returned by `build_agent_tree`, updates `_current_group_key` to the next banner's `group_key`, and sets `current_idx` to
the first agent in the targeted group. The state is right; only the visual sync is broken.

## Fix

Two narrow, symmetric changes that make the debounced highlight path mirror the full-refresh path's banner handling.

### 1. Extend `AgentList.update_highlight` to accept `group_key`

`src/sase/ace/tui/widgets/agent_list.py`

Add an optional `group_key: tuple[str, ...] | None = None` parameter. When non-None, scan `self._banner_at_row` (already
maintained for selectable banners — see lines 243-244) for a row whose `GroupRow.group_key` matches and set
`self.highlighted` to that row. When None, keep the existing agent-row search.

Keep the `_programmatic_update` guard around the highlight assignment so the resulting `OptionHighlighted` event is
filtered out in `on_option_list_option_highlighted` — otherwise it would round-trip through
`actions/event_handlers.py:298` and clobber `_current_group_key`.

### 2. Pass `_current_group_key` from the debounced refresh

`src/sase/ace/tui/actions/agents/_display.py`

Update `_refresh_agents_display_debounced` (the main-panel branch only — pinned stays flat, no banners ever) to call:

```python
agent_list.update_highlight(
    local_idx,
    self.current_attempt_number,
    group_key=self._current_group_key,  # type: ignore[attr-defined]
)
```

This converges the two refresh paths on identical banner-highlight semantics.

## Why this shape

- Mirrors the full-refresh path; no new state, no new wiring beyond a single parameter.
- Does not touch banner navigation (`_navigate_agents_panel`), the tree builders (`_build_full_tree` /
  `_build_collapsed_tree`), or the SelectionChanged contract.
- At fold level == 3 the call site passes `_current_group_key`, which is forcibly `None` in that mode (see
  `_basic.py:32-34`), so behavior is unchanged for the unfolded view.
- Avoids alternative designs that would have been heavier:
  - "Just always full-refresh on j/k" — defeats the entire reason `_refresh_agents_display_debounced` exists (avoid
    expensive Rich rebuilds during scrolling).
  - "Track banner row index in app state" — duplicates `_banner_at_row` and adds another field that would have to be
    kept in sync with every `update_list`.

## Tests

Existing relevant test files:

- `tests/ace/tui/widgets/test_agent_list_grouping.py` — banner rendering / `_banner_at_row`.
- `tests/ace/tui/widgets/test_agent_list_attempts.py` / `_bindings.py` — `update_highlight` / attempt rows.
- `tests/ace/tui/test_agent_jk_navigation.py` — j/k flow at the action level.

Add cases:

1. `update_highlight(idx, group_key=K)` — banner row whose group matches K becomes the highlighted row regardless of
   `idx`.
2. `update_highlight(idx, group_key=K)` with no matching banner — falls back to the agent-row search (defensive: covers
   a refresh-vs-fold race).
3. Regression at the j/k action level: at fold level 2, with cursor on the L1 banner, dispatching
   `action_next_changespec()` advances `_current_group_key` to the L2 banner _and_ the `AgentList`'s `highlighted` row
   points at that banner's row.

## Files

Changed:

- `src/sase/ace/tui/widgets/agent_list.py` — extend `update_highlight` signature and add the banner-search branch.
- `src/sase/ace/tui/actions/agents/_display.py` — pass `_current_group_key` from `_refresh_agents_display_debounced`
  (line 207).
- `tests/ace/tui/widgets/test_agent_list_*.py` and/or `tests/ace/tui/test_agent_jk_navigation.py` — add the three cases
  above.

Out of scope:

- `_navigate_agents_panel` and the banner cycle logic — already correct.
- Tree builders in `models/agent_groups.py` — already correct.
- Pinned panel — stays flat at fold 3, no banner highlight needed.
- Highlight-event round-tripping (already gated by `_programmatic_update`).
