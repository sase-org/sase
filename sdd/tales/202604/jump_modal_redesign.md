---
create_time: 2026-04-04 15:38:07
status: done
prompt: sdd/prompts/202604/jump_modal_redesign.md
---

# Redesign Jump-to-Entry Modal

## Problem

The "Jump to Entry" modal (`JumpAllModal`) is the cross-tab navigation hub of the TUI — it's triggered with backtick and
lets users jump to any entry across CLs, Agents, and AXE tabs with a single keypress. Currently it's cramped (fixed
60-char width, 30-line scroll cap) and visually plain, feeling like an afterthought compared to the polished help modal
and notification modal.

## Design Goals

- **Fill the screen**: The modal should command attention, using ~85% of the terminal like other major modals (help,
  notifications)
- **Visual hierarchy**: Clear section grouping with decorated headers so the eye can scan quickly
- **Tab identity**: Each section (CLs, Agents, AXE) should use its own accent color for names, reinforcing the tab color
  language already established in the app
- **Readable entries**: Wider name columns, tree-drawing chars for nested AXE items, pinned-agent indicators
- **Premium feel**: Double border, decorative title with horizontal rules, consistent spacing

## Visual Mockup

```
 ╔══════════════════════════════════════════════════════════════════════════════════════╗
 ║                                                                                    ║
 ║                           ─── ✦ Jump to Entry ✦ ───                                ║
 ║                                                                                    ║
 ║   ── CLs (2) ────────────────────────────────────────────────────────────────────   ║
 ║                                                                                    ║
 ║      [1]  fix_chezmoi_bashunit_ci                                         WIP      ║
 ║      [2]  add_jump_modal_redesign                                       Draft      ║
 ║                                                                                    ║
 ║   ── Agents (3) ─────────────────────────────────────────────────────────────────   ║
 ║                                                                                    ║
 ║      [3]  sase/20260404151342                                       PLAN DONE      ║
 ║      [4]  sase/20260404151009                                       PLAN DONE      ║
 ║      [5]  sase/20260402221629                                           DONE  pin  ║
 ║                                                                                    ║
 ║   ── AXE (6) ───────────────────────────────────────────────────────────────────   ║
 ║                                                                                    ║
 ║      [6]  sase axe                                                                 ║
 ║      [7]    checks                                                                 ║
 ║      [8]    comments                                                               ║
 ║      [9]    hooks                                                                  ║
 ║      [0]    housekeeping                                                           ║
 ║      [a]    run_every                                                              ║
 ║                                                                                    ║
 ║  ────────────────────────────────────────────────────────────────────────────────   ║
 ║                        press key to jump  ·  esc cancel                            ║
 ║                                                                                    ║
 ╚══════════════════════════════════════════════════════════════════════════════════════╝
```

Key visual details:

- Entry names use each tab's accent color: turquoise (#00D7AF) for CLs, cyan (#87D7FF) for Agents, gold (#FFD700) for
  AXE
- Hint keys are bold bright yellow
- Status text uses existing per-status colors (gold for WIP, cyan for Draft, etc.)
- Pinned agents get a dim "pin" suffix
- AXE children are indented with 2 extra spaces (clean indentation, no tree chars — keeps it simple)
- Section headers: leading `──`, tab-colored label with count, trailing `──` fill

## Changes

### 1. CSS: `src/sase/ace/tui/styles.tcss` (lines 1121-1160)

**Container sizing** — match help modal proportions:

- `width: 85%` (from fixed `60`)
- `max-width: 130` (cap for ultra-wide terminals)
- `height: 80%` (from `auto` + `max-height: 80%`)
- `border: double $primary` (from `thick`)

**Scroll area** — fill available space:

- `height: 1fr` (from `auto` + `max-height: 30`)
- Remove the `max-height` constraint

### 2. Python: `src/sase/ace/tui/modals/jump_all_modal.py`

**Visual constants** — widen columns for the larger modal:

- `_NAME_MAX`: 30 -> 50
- `_STATUS_MAX`: 14 -> 18
- New `_SECTION_RULE_WIDTH = 76` for section header horizontal rules

**`_build_title()`** — decorative centered title:

```
─── ✦ Jump to Entry ✦ ───
```

Horizontal rule segments in dim, stars in bold gold, text in bold white.

**`_build_display()`** — section headers and entry rows:

Section headers become:

```python
# Count entries in this section
count = sum(1 for e in self._entries if e.tab == current_tab)
text.append(f"  ── {label} ({count}) ", style=f"bold {color}")
text.append("─" * fill_width, style=f"dim {color}")
```

Entry rows gain:

- Tab-specific name color (pulled from `_TAB_STYLES` color)
- Wider name field (50 chars)
- Pinned agent indicator: dim " pin" suffix after status
- Cleaner indent for AXE children (2-space indent per level)

**`_build_entries()`** — add `name_style` field to `_Entry`:

- Store the tab's accent color so each entry knows its name color
- Add pinned indicator info

**Footer text** — keep simple: "press key to jump · esc cancel"

## Files to Change

1. `src/sase/ace/tui/styles.tcss` — Modal container size, scroll area, border style
2. `src/sase/ace/tui/modals/jump_all_modal.py` — Title, section headers, entry formatting, constants
