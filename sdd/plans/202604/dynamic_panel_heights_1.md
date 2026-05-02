---
create_time: 2026-04-26 01:18:51
status: done
prompt: sdd/prompts/202604/dynamic_panel_heights_1.md
---
# Plan: Dynamic Heights for Agents-Tab Tag Panels

## Problem

On the Agents tab (TUI), the agent list slot (`#agent-list-container`) is a vertical stack of `AgentList` widgets — one
per tag bucket. The first panel is the "(untagged)" main pane; each additional panel is one tag. This stack was added in
`dc6a0c50 feat: stack Agents-tab tag panels vertically with per-panel titles` and
`5bf25bbe feat: phase 3 dynamic tag panels and J/K panel navigation`.

Today every panel is sized **equally** by:

```tcss
#agent-list-container AgentList {
    width: 100%;
    height: 1fr;            /* equal share regardless of content */
    border: solid $primary;
    padding: 0 1;
}
```

Consequences:

- A panel with 1 agent gets the same vertical space as a panel with 25 agents.
- The dense panel always shows a scrollbar (`AgentList { scrollbar-gutter: stable }` reserves a column even when not
  scrolling); the sparse panel wastes most of its allocation as empty space.
- Visually, the agent the user actually wants to look at is often hidden below the fold of its panel while another panel
  sits half-empty.

The user's stated goal: **size each panel based on the agents it holds, so all entries are visible whenever they can be,
and inner scrollbars disappear in the common case.**

## Goals & Non-Goals

**Goals**

1. When the _sum of natural heights_ of all panels fits the available container height, every panel is sized to exactly
   fit its content — no inner scrollbars, no wasted space.
2. When the sum exceeds the available height (many tags, many agents), space is distributed proportionally to content
   size so the largest panel gets the most room. Some scrolling is unavoidable here, but is minimized and concentrated
   where it makes sense.
3. The focused-panel border, J/K panel navigation, and the existing per-panel `border_title = "@tag · N"` continue to
   work unchanged.
4. Behavior degrades gracefully for the single-panel case (untagged-only) — that panel just fills the slot, same as
   today.

**Non-Goals**

- Re-architecting the Agents-tab layout slots (`slot-1`/`slot-2`/`slot-3`, CLASSIC/TRIPTYCH/STACK/FOCUS). This work is
  scoped to the _contents_ of `slot-1` (the agent list). The outer slot layout is unrelated and staying as-is.
- Changing the notification panel sectioning (priority/inbox/muted is one OptionList already, not multiple panels —
  different problem).
- Persisting per-panel sizes across restarts or letting users drag to resize. The sizes are derived from content only.

## Design

### Two regimes

The behavior splits cleanly on whether the natural content fits:

| Regime       | Trigger                               | Per-panel `height`                         |
| ------------ | ------------------------------------- | ------------------------------------------ |
| **Fits**     | `Σ natural_height ≤ container_height` | exact integer rows (`height: <N>`)         |
| **Overflow** | `Σ natural_height > container_height` | weighted fractional (`height: <weight>fr`) |

Where `natural_height = rendered_row_count + 2` (top + bottom border) plus 1 if a top/bottom margin is applied. The
rendered row count includes agent rows, attempt children, group banners, and the spacer rows the tree builder inserts
between L0 banners — i.e. exactly `option_count` on the underlying `OptionList`, plus the border.

In the **Fits** regime we use absolute integer heights so the layout is pixel-tight and predictable. In the **Overflow**
regime we fall back to `fr` weighting because the deficit must land somewhere, and putting it on the larger panels is
the least bad outcome (a 25-agent panel scrolling 5 rows is better than a 1-agent panel hiding its only entry).

### Where the sizing decision lives

Sizing is computed inside `AgentDisplayMixin._refresh_panel_widgets` (`src/sase/ace/tui/actions/agents/_display.py`), at
the end of the loop that calls `widget.update_list(...)`. This is the right hook because:

- It already runs whenever the panel set or the agent counts change (mount/unmount, agent loaded, tag added/removed,
  fold toggled).
- It already iterates the panel widgets in display order, so we can read the OptionList's row count cheaply right after
  populating it.
- The container's `size.height` is available via Textual at that point.

We add a small helper, `_apply_panel_heights(container, widgets)`, that runs after all `update_list` calls. It:

1. Reads each widget's `option_count` and adds the border allowance to get its natural height.
2. Reads `container.size.height`. If zero (pre-mount), defers via `call_later` and bails — the next refresh will get a
   real value.
3. Picks the regime and sets `widget.styles.height` accordingly using Textual's programmatic style API (`Scalar` from
   `textual.css.scalar`, units `cells` or `fr`).

### CSS change

The default rule becomes a sensible fallback for the very first paint (before Python has a chance to override) and for
the focused-panel border:

```tcss
#agent-list-container AgentList {
    width: 100%;
    height: 1fr;          /* fallback only; overridden per-refresh */
    border: solid $primary;
    padding: 0 1;
}
```

The `1fr` stays as a safe default so a brand-new panel that mounts between refreshes still has a reasonable height.
Python overwrites it on every refresh.

### Container height & re-layout on resize

Tag panels live inside `slot-1` of `#agents-panels`, whose height is determined by the active layout (CLASSIC: full
height; STACK: `8fr` of the vertical stack; etc.). When the user cycles layouts, the container height changes — we need
a recompute.

Two paths trigger the recompute:

1. **Content changes** — already handled, `_refresh_panel_widgets` runs.
2. **Geometry changes** — handle via Textual's `on_resize` event on the container. Subscribe in `event_handlers.py` (it
   already handles `AgentList.WidthChanged`); add a small handler that re-applies panel heights without rebuilding
   options.

For path 2, factor the height-computation logic so it can be called without a full content rebuild. A thin
`_reapply_panel_heights()` method on the mixin, callable from both the refresh path and the resize path.

### Minimum height & degenerate cases

- **Empty panel** (e.g., a tag whose only agent was just dismissed and the panel hasn't been pruned yet) — natural
  height is 2 (border only). In Fits regime, give it 2 cells; in Overflow regime, give it weight 1 (so it gets a sliver,
  not nothing). The panel will be unmounted on the next sync anyway.
- **Single panel** — natural height >= container, weight = 1. Either regime collapses to "panel fills container" — same
  as today.
- **Container too small** to show any panels at full height — Overflow regime weights by `option_count + 1` (the border
  allowance keeps tiny panels from being reduced to zero).

### Border-title visibility

The per-panel title `@tag · N` is rendered via `border_title`, which sits _on_ the border of the widget. With smaller
panel heights the title remains visible because it's part of the border, not the content area. No change needed.

### Scrollbar gutter

`AgentList` sets `scrollbar-gutter: stable`, which reserves one column for a scrollbar even when none is needed. In the
Fits regime this is purely cosmetic (one wasted column). We leave it alone — flipping it off would cause a visible
width-shift the moment a scrollbar _does_ appear in the Overflow regime. Width stability matters more than one extra
column.

## Tradeoffs Considered

1. **CSS `height: auto` only** — letting Textual auto-size each panel to its content. Rejected: when content sums exceed
   the container, panels overflow and Textual either clips or pushes the container into its own scroll mode, which the
   existing layout doesn't expect (the slot is a `Vertical`, not a `VerticalScroll`). Adopting it would require wrapping
   the container, which silently changes navigation behavior.
2. **Always-fractional weighting (`<rows>fr`)** — simpler, no regime split. Rejected: doesn't solve the problem when
   content fits — a 1-agent panel with weight 1 next to a 25-agent panel with weight 25 gets `1/26` of the height (~one
   row), exactly the same scrollbar problem as today, just inverted. The Fits regime is the whole point.
3. **Min-height per panel** — guarantee every panel shows ≥3 rows. Rejected as a default: in the Overflow regime with
   many tags, even 3 rows × 10 panels = 30 rows of mandatory chrome; better to let the weighting do its job. Could be
   added as polish later if real usage shows tiny panels disappearing.
4. **Resize debounce** — call `_reapply_panel_heights` directly on every `Resize` event. Rejected as a debounced
   approach: the recompute is cheap (counts and arithmetic, no I/O), and resize events stop firing the moment the user
   releases the terminal-resize drag. Keep it simple.

## Implementation Steps

1. **Add `_apply_panel_heights()` helper** in `src/sase/ace/tui/actions/agents/_display.py`.
   - Inputs: container widget + ordered list of `(AgentList, key)`.
   - Reads `option_count` per widget; computes natural heights.
   - Decides regime; sets `widget.styles.height` accordingly.
2. **Call from `_refresh_panel_widgets`** at the end of the per-panel loop, after focus class is set.
3. **Add an `on_resize` handler** for `#agent-list-container` in `src/sase/ace/tui/actions/event_handlers.py` that calls
   a thin `_reapply_panel_heights()` mixin method (no content rebuild).
4. **Update the CSS comment** at `styles.tcss:661` to note that `height: 1fr` is a fallback overridden by Python at
   refresh time.
5. **Tests** in `tests/test_agent_panels_display.py` (new or adjacent to existing panel tests):
   - Fits regime: 3 panels with 2/4/6 agents in a 30-row container → each gets natural height, no fr.
   - Overflow regime: 3 panels with 1/5/25 agents in a 12-row container → fr weights proportional, summing within
     container.
   - Single panel: gets full container height (no degenerate fr=0).
   - Resize re-applies heights without rebuilding content.
6. **Manual smoke test**: run the TUI in a few terminal sizes with a mix of tagged and untagged agents; verify no
   unnecessary scrollbars in the Fits regime, and proportional sizing in Overflow.
7. **`just check`** before reply.

## Files Touched (estimated)

- `src/sase/ace/tui/actions/agents/_display.py` — new helper + call site.
- `src/sase/ace/tui/actions/event_handlers.py` — resize handler.
- `src/sase/ace/tui/styles.tcss` — comment update only (default rule unchanged).
- `tests/test_agent_panels_display.py` — new tests (or extend existing panel-display test file).

No public API changes; no model changes; no layout-state changes.

## Risks

- **Textual scalar API quirks** — setting `widget.styles.height` to a cell-unit `Scalar` and later switching it to an
  `fr` unit on the same widget should work, but is worth verifying with a quick smoke test before committing to the
  regime-switch approach.
- **Pre-mount resize** — the container's `size.height` is 0 until first layout. Guarded by the
  `if not container_height: return` early-out; the next mounted refresh fixes it.
- **Focus border thickness** — the `-focused-panel` class swaps `solid $primary` for `solid $accent`; both are 1-cell
  borders, so the natural-height math (rows + 2) holds for both states. Confirm by reading the focused-panel style.
