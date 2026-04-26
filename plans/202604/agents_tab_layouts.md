---
name: agents_tab_layouts
description: Make the Agents tab layout customizable via cyclable layouts and panel rotation
create_time: 2026-04-25 22:00:39
status: done
---

# Agents tab — cyclable panel layouts + panel rotation

## Goal

Make the Agents tab feel like a tiling window manager: a small set of curated **layouts** that the user cycles with `p`
/ `P`, plus a **panel rotation** axis (`{` / `}`) that rotates which logical content gets the "primary" slot. The
combination lets the user view any of the three core panels in full-screen.

## What "three panels" means here

The Agents tab today nests the detail view inside one container. To make full- screening any panel meaningful, we expose
the detail-view's two main children as peers of the agent list, giving us three top-level **panel slots** on the Agents
tab:

- **L — List**: the per-tag agent list panels (`#agent-list-container`).
- **C — Chat**: the agent's prompt + transcript (today: prompt panel inside `AgentDetail`).
- **F — File**: the agent's current file _or_ its thinking trace, whichever is active per the existing `]` / `[` mode
  cycle (so we don't disturb that established affordance).

The `AgentInfoPanel` header bar (one-line summary at the top) is **not** part of the rotation — it stays anchored above
all layouts. It's a status strip, not a panel a user would want to full-screen.

## Two orthogonal user controls

```
p / P         cycle layouts          (geometry — how the three slots are arranged)
{ / }         rotate panel order     (content — which logical panel sits in each slot)
```

A single `panel_order` state — a permutation of `[L, C, F]` — is consulted by every layout. Slot **#1 is "primary"** in
every layout (largest, focus border, the only one visible in FOCUS). Rotating reassigns which logical content becomes
primary, so `{` / `}` work uniformly across layouts.

## Layouts (the cycle that `p` walks)

Four layouts, ordered from familiar → minimalist. `P` walks the cycle in reverse. ASCII shows slots `#1`, `#2`, `#3`
(post-rotation, not L/C/F).

### 1. CLASSIC (default — matches today's layout when `panel_order = [L, C, F]`)

```
┌─ AgentInfoPanel ────────────────────────────────────┐
├─ #1 (60ch) ─┬─ #2 ────────────────────────────────┤
│             │                                       │
│   list /    │   chat / prompt                       │
│   primary   │                                       │
│             ├─ #3 ──────────────────────────────────┤
│             │                                       │
│             │   file / thinking                     │
└─────────────┴───────────────────────────────────────┘
```

### 2. TRIPTYCH — three equal columns, all visible

```
┌─ AgentInfoPanel ────────────────────────────────────┐
├─ #1 (1.4fr) ─┬─ #2 (1fr) ─────┬─ #3 (1fr) ─────────┤
│              │                 │                     │
│              │                 │                     │
└──────────────┴─────────────────┴─────────────────────┘
```

Primary slot gets a slightly larger fr so it reads as the focal point.

### 3. STACK — three full-width rows

```
┌─ AgentInfoPanel ────────────────────────────────────┐
├─ #1 (1.6fr) ────────────────────────────────────────┤
│                                                      │
├─ #2 (1fr) ──────────────────────────────────────────┤
│                                                      │
├─ #3 (1fr) ──────────────────────────────────────────┤
│                                                      │
└──────────────────────────────────────────────────────┘
```

Useful for narrow terminals or for skim-reading lots of one panel at a time.

### 4. FOCUS — primary fills the screen ("full screen")

```
┌─ AgentInfoPanel ────────────────────────────────────┐
├─ #1 ────────────────────────────────────────────────┤
│                                                      │
│                  primary panel only                  │
│                                                      │
└──────────────────────────────────────────────────────┘
```

This is the full-screen mode. With `{` / `}` you rotate which of L/C/F gets the screen. Three rotations × FOCUS =
full-screen any panel.

A subtle breadcrumb in `AgentInfoPanel` (e.g. `· focus[chat]`) tells the user what layout + primary they're in — see
"Looking beautiful" below.

## Keymaps

Add to `src/sase/default_config.yml` under `ace.keymaps.app`:

```yaml
cycle_agents_layout: "p" # repurpose existing 'p' (was toggle_layout)
cycle_agents_layout_reverse: "P"
rotate_agents_panels: "right_brace" # }
rotate_agents_panels_reverse: "left_brace" # {
```

`}` advances the rotation, `{` reverses it (mirrors how the `]`/`[` pair is already used for detail-panel cycling —
consistent with the user's mental model from that existing affordance).

The current `toggle_layout` keymap (file vs. prompt priority inside the detail panel) is **subsumed** by the new design:
in CLASSIC and TRIPTYCH layouts, the `{` / `}` rotation accomplishes the same thing more uniformly (rotate so C is
primary vs. F is primary). Drop the old action; remove its binding to keep the config clean.

## Persistence

- `layout` and `panel_order` are **not persisted** — they reset to (CLASSIC, `[L, C, F]`) on TUI start. Keeps things
  predictable; matches how `AgentDetail._panel_mode` already behaves. (If we want persistence later, tuck both into the
  same place that ends up holding fold state.)
- All keymaps are no-ops outside the Agents tab (early-return on `current_tab != "agents"`), matching the pattern used
  by every other Agents-tab action in `_panels.py`.

## Implementation outline

Files to touch (focused list — leaves a small surface area):

1. **`src/sase/ace/tui/models/agent_panels.py`** — add:
   - `class AgentsLayout(Enum)` with `CLASSIC | TRIPTYCH | STACK | FOCUS`.
   - `class PanelSlot(Enum)` with `LIST | CHAT | FILE`.
   - `AgentsLayoutState` dataclass: `layout: AgentsLayout`, `order: tuple[PanelSlot, PanelSlot, PanelSlot]`. Methods:
     `cycle_layout(reverse)`, `rotate(reverse)`, `slot_for_position(i) -> PanelSlot`.

2. **`src/sase/ace/tui/app.py`** — restructure `#agents-content`:
   - Replace the hard-coded `Horizontal(list-container, detail-container)` with a single `#agents-panels` container
     holding three peer wrappers (`#agents-slot-1`, `#agents-slot-2`, `#agents-slot-3`).
   - On `compose`, mount the existing list, prompt, and file widgets into the slot whose CSS class matches their
     `panel_order` position. (No widget destruction on layout changes — only re-`mount` to a new parent and a CSS class
     swap on `#agents-panels`.)

3. **`src/sase/ace/tui/widgets/_agent_detail_panels.py`** — extract the prompt and file/thinking sub-widgets so they can
   live as peers of the list. Keep `AgentDetail` as a thin coordinator that routes data to whichever widgets are
   currently visible. The `]` / `[` `DetailPanelMode` cycle stays — it still controls _what_ the FILE slot shows (file
   vs. thinking vs. metadata).

4. **`src/sase/ace/tui/styles.tcss`** — add four classes on `#agents-panels`: `.layout-classic`, `.layout-triptych`,
   `.layout-stack`, `.layout-focus`. Each class sets `layout: horizontal | vertical`, slot widths (`fr` units), and
   `display: none` on `#agents-slot-2` / `#agents-slot-3` for FOCUS. All transitions handled by Textual's CSS swap — no
   manual hide/show calls in Python.

5. **`src/sase/ace/tui/actions/agents/_panels.py`** —
   - Replace `action_toggle_layout` with `action_cycle_agents_layout` and `action_cycle_agents_layout_reverse`.
   - Add `action_rotate_agents_panels` and `action_rotate_agents_panels_reverse`.
   - Each action mutates `AgentsLayoutState`, calls a single `_apply_agents_layout()` that (a) sets the CSS class on
     `#agents-panels`, (b) re-parents widgets to the right slots, (c) updates the breadcrumb.

6. **`src/sase/ace/tui/bindings.py`** — swap the `p` binding, add `P`, `{`, `}`. Remove the old `toggle_layout` binding.

7. **`src/sase/default_config.yml`** — keymap changes from above.

8. **`src/sase/ace/tui/help_modal/bindings.py`** (or equivalent) — document the four new actions in the help modal under
   the Agents-tab section.

9. **Tests**:
   - Unit-test `AgentsLayoutState` — cycle wraps both directions, rotate is a true 3-cycle, `slot_for_position` returns
     correct slot after each.
   - Snapshot/integration test similar to the existing `test_agent_panel_titles.py` — exercise each layout × each
     rotation, assert the right widget ends up in slot #1 and that FOCUS hides slots #2 / #3.

## Looking beautiful

A few small touches that make this feel polished rather than utilitarian:

- **Primary indicator** — slot #1 always renders with the `$accent` border; slots #2 / #3 with `$primary`. Already how
  the focused tag panel renders, so it'll feel native.
- **Breadcrumb in `AgentInfoPanel`** — append a soft-dim suffix like `· classic[L]`, `· triptych[C]`, `· focus[F]`.
  Tells the user at a glance what's active without needing to memorize the cycle order.
- **Layout name `notify` on cycle** — bottom-right toast: `Layout: TRIPTYCH` (matches the notify pattern used elsewhere
  in `_panels.py`). Fades quickly, but covers the case where the user can't see the breadcrumb because they're in FOCUS
  on the file panel.
- **Consistent fr ratios** — primary always 1.4–1.6× the others. Avoids the visual jitter of one layout being "tight"
  and another "loose."
- **No layout flash on rotate** — the CSS class on `#agents-panels` only changes for `p` / `P`, not for `{` / `}`;
  rotation just re-parents widgets, so the geometry stays put while content swaps.

## Open questions

1. **Drop or keep the old "file vs. prompt priority" toggle?** I propose drop: `{` / `}` subsumes it more cleanly. If
   users disagree we can re-add it under a new key without affecting this design.
2. **Should the rotation order be `[L, C, F] → [C, F, L] → [F, L, C]` (cyclic shift) or a more clever heuristic?** I
   propose cyclic shift — predictable, easy to reason about, and three presses returns you home.
3. **STACK layout for very tall terminals** — should slot #1 stay 1.6fr, or adapt? Defer; 1.6fr is fine as a v1 default
   and easy to tune later.

## Out of scope

- Persisting layout/order across restarts.
- Per-tag layout preferences.
- Drag-to-resize of slot boundaries (Textual supports it but it's a separate affordance that would deserve its own
  design pass).
- Restructuring the `AgentInfoPanel` header.
