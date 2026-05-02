---
create_time: 2026-04-27 20:19:19
status: done
prompt: sdd/prompts/202604/widen_agent_list_panel.md
---
# Plan: Widen the `sase ace` Agents-tab Agent List Panel

## Problem

In the `sase ace` TUI's "Agents" tab, the left-hand agent list panel truncates agent names / runtime suffixes like
`@bs.codex.plan`, `@sase-w.land`, `@read.gemini`. The user can see _some_ of the runtime info but not all of it, and
we'd rather grow the panel than wrap or truncate.

The panel already auto-sizes to its content — it computes `optimal_width = max(longest_row, banner_width) + 8` per
render and posts a `WidthChanged` message. The handler then clamps that value to the bounds
`[_MIN_AGENT_LIST_WIDTH, _MAX_AGENT_LIST_WIDTH] = [60, 80]`. The truncation we see is exactly the **upper clamp**
kicking in: rows that need >80 cells get cut off at 80.

## Goal

Raise the upper bound enough that typical agent rows (including the runtime suffix appended after the agent name) fit
without truncation, while keeping the right-hand `AGENT DETAILS` / `AGENT XPROMPT` panel usable.

## Relevant Code

- `src/sase/ace/tui/app.py:71-72` — the constants `_MIN_AGENT_LIST_WIDTH = 60` / `_MAX_AGENT_LIST_WIDTH = 80`.
- `src/sase/ace/tui/styles.tcss:662-666` — `#agent-list-container { width: 60 }` (initial width before the first
  auto-size message; not a cap).
- `src/sase/ace/tui/widgets/_agent_list_build.py:311-314` — computes `optimal_width = max(...) + 8` and posts
  `WidthChanged`.
- `src/sase/ace/tui/actions/event_handlers.py:492-503` — `on_agent_list_width_changed` clamps to
  `[_MIN_AGENT_LIST_WIDTH, _MAX_AGENT_LIST_WIDTH]` and applies it to `#agent-list-container.styles.width`.
- `src/sase/ace/tui/widgets/agent_list.py:83-88` — the `WidthChanged` message.
- For comparison: `_MIN_LIST_WIDTH = 43`, `_MAX_LIST_WIDTH = 80` for the ChangeSpec list (left panel of CLs tab) at
  `src/sase/ace/tui/app.py:67-68`.

## Approach

**Bump `_MAX_AGENT_LIST_WIDTH` from 80 to a higher value.** That is the single source of truth for the upper clamp;
nothing else needs to change because:

- The widget already auto-fits to content. If the content needs only 70 cells, the panel stays at 70 — we are only
  raising the **ceiling**.
- The right-hand panel uses `1fr` and absorbs whatever is left, so the layout naturally accommodates a wider left panel
  without wrapping.
- The initial CSS width of 60 is fine to leave as-is; the first render immediately resizes via `WidthChanged`.

### Choosing the new max

Looking at the snapshot, the longest visible truncated rows look like `│  ⚡ sase (PLAN APPROVED) ×6 @bt.plan` plus a
trailing runtime label that gets cut. With the existing left-side decorations (group indent, status icon, attempt-count
`×N`, agent name, runtime suffix) plus the +8 padding, content lengths in the high 80s–low 100s are realistic. Going
modest avoids starving the detail panel on narrow terminals.

Proposed: **`_MAX_AGENT_LIST_WIDTH = 110`** (≈ +30 over current).

Rationale:

- Comfortably accommodates `@<group>.<runtime>.<phase>`-style names plus the status prefix and attempt-count badge.
- On a typical 200+ column terminal (the snapshot is ~210 wide), the right panel still gets ~95+ cells — plenty for
  AGENT DETAILS / XPROMPT.
- On a narrow 120-column terminal, the right panel gets ~10 cells, which is cramped — but the auto-fit only goes to 110
  when content _needs_ it; on short rows it'll stay smaller. Users on narrow terminals with long agent names always face
  a tradeoff; this matches the existing behavior, just at a higher ceiling.

If 110 still truncates in real use, a follow-up can raise it further (or we move to a terminal-relative cap; see "Out of
scope" below).

### Why not also raise `_MIN_AGENT_LIST_WIDTH`?

The min (60) is fine — short rows shouldn't force a wide panel. Only the ceiling needs to move.

### Why not change the auto-size formula?

The formula already includes `+8` padding and uses the longest actual row. The truncation isn't a bug in measurement —
it's the clamp.

## Out of Scope

- **Terminal-relative cap** (e.g. `min(_MAX_AGENT_LIST_WIDTH, term_cols // 2)`). Worth considering if the static cap
  turns out to feel wrong, but it adds on-resize bookkeeping and isn't needed to solve the reported issue. Skip for now.
- **User-configurable max width**. Possible future addition but not asked for.
- **Touching the ChangeSpec panel cap (`_MAX_LIST_WIDTH = 80`)** — out of scope; user only reported the Agents tab.
- **Changing the initial CSS `width: 60`** in `styles.tcss` — auto-fit resizes on the first render so this is cosmetic.

## Files to Change

1. `src/sase/ace/tui/app.py` — bump `_MAX_AGENT_LIST_WIDTH` from `80` to `110`.

That's it. One constant.

## Verification

- Run `just install && just check` in the workspace.
- Manually launch `sase ace`, switch to Agents tab, confirm long agent rows (e.g. `@<long_group>.<runtime>.<phase>`)
  render without truncation and that the AGENT DETAILS / XPROMPT panel remains readable.
- Confirm short-row case still renders narrow (panel doesn't always go to 110).

## Risk

Very low. Single-constant change to an existing clamp; auto-fit logic is unchanged; right pane is `1fr` so layout
self-adjusts.
