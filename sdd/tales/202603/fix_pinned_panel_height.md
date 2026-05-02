---
create_time: 2026-03-31 09:31:54
status: done
prompt: sdd/prompts/202603/fix_pinned_panel_height.md
---

# Plan: Fix Pinned Panel Height — Content Not Visible

## Problem

The dynamic pinned panel height feature (commit `97b16da3`) doesn't work. With 1 pinned agent, the agent entry is
invisible — only the inner OptionList border chrome is visible. The panel should show at least 5 pinned agents before
requiring a scrollbar.

## Root Cause

Two bugs in the height formula:

1. **Unaccounted inner border**: `AgentList` extends Textual's `OptionList`, which has a default `border: tall` style
   (renders as the tall block characters). This border consumes 2 rows inside the container. The formula only budgets 2
   rows of overhead for the _container_ border, missing the inner border entirely.

2. **Wrong per-item multiplier**: Each pinned item takes 1 row, not 2. The `* 2` multiplier was speculative and
   overestimates for large counts while underestimating for small counts due to the missing border overhead.

**Concrete failure for 1 pinned item**:

- Container max-height = `min(1*2 + 2, 20)` = **4**
- Inner list max-height = 4 - 2 = **2**
- Inner list needs: 2 (OptionList tall border) + 1 (item content) = **3** rows minimum
- Result: only 2 rows available -> border renders, content clipped to 0 rows

## Design

**Remove the inner OptionList border** from `#pinned-list-panel`. It's redundant — the container already provides a
border with the "Pinned (N)" title. The main agent list (`#agent-list-panel`) explicitly sets `border: solid $primary`
which overrides the default, so this is consistent with the existing pattern. Removing it reclaims 2 rows and simplifies
the formula.

**Fix the formula** to `pinned_count + 2` (1 row per item + 2 rows for container border). This ensures:

| Pinned count | Container max | Inner list max | Fits?                               |
| ------------ | ------------- | -------------- | ----------------------------------- |
| 1            | 3             | 1              | 1 item visible                      |
| 5            | 7             | 5              | 5 items visible (meets requirement) |
| 10           | 12            | 10             | 10 items visible                    |
| 18+          | 20 (cap)      | 18             | 18 items before scrollbar           |

**Update CSS fallbacks** to match the new formula's assumptions (no inner border, cap at 20/18).

## Changes

### 1. `src/sase/ace/tui/styles.tcss` — Remove inner border

Add `border: none;` to `#pinned-list-panel` to suppress the inherited OptionList tall border.

### 2. `src/sase/ace/tui/actions/agents/_display.py` — Fix formula

Change `pinned_count * 2 + 2` to `pinned_count + 2` in `_update_panel_focus_styling()`.

### 3. No other changes needed

The widget hierarchy, compose structure, and all other styling remain the same.
