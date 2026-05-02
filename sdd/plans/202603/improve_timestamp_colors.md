---
create_time: 2026-03-30 13:44:38
status: done
prompt: sdd/prompts/202603/improve_timestamp_colors.md
---

# Plan: Improve Timestamp Colors in TUI and Neovim

## Problem

The TIMESTAMPS section datetime values are hard to read:

- **TUI**: `dim #808080` — barely visible on dark backgrounds
- **Neovim**: `bold #87AFD7` — decent but inconsistent with TUI

The user wants better, more visible colors for timestamps in both rendering contexts.

## Color Analysis

### Current palette context

The TUI and Neovim already share a consistent design language:

| Role                     | Color          | Usage                                        |
| ------------------------ | -------------- | -------------------------------------------- |
| Headers/labels           | `#87D7FF` bold | Section headers like `TIMESTAMPS:`, `HOOKS:` |
| Entry numbers            | `#D7AF5F` bold | `(1)`, `(2)` markers                         |
| Detail text              | `#D7D7AF`      | Commit messages, status transitions          |
| Structural/dim           | `#808080`      | Pipes, durations, folded indicators          |
| HOOKS/MENTORS timestamps | `#AF87D7`      | Old `[YYmmdd_HHMMSS]` format                 |
| File paths               | `#87AFFF`      | Chat/diff paths                              |

The datetime sits between "structural metadata" (should be dim) and "important info" (should be bright). It's more
important than pipes/durations but less important than event types or detail text.

### Proposed color: `#AF87D7` (purple)

**Rationale**: Use the same purple (`#AF87D7`) that's already used for HOOKS/MENTORS timestamps in both TUI and Neovim.
This creates visual consistency — all timestamps across all sections share the same color. It's clearly more readable
than `#808080` while being distinct from event types and detail text.

This is also the natural choice because the HOOKS/MENTORS `[YYmmdd_HHMMSS]` timestamps and the TIMESTAMPS section
`[YYYY-MM-DD HH:MM:SS]` datetimes serve the same purpose — they're both timestamps. Having them look the same reinforces
their semantic role.

**Style**: Non-bold in both TUI and Neovim. Timestamps are metadata — readable but not attention-grabbing. Non-bold also
matches the HOOKS/MENTORS timestamp style (`#AF87D7` without bold).

### Arrow color adjustment

The `->` arrow in STATUS transitions is currently `bold #808080` — also too dim. Changing it to `#808080` (non-bold) or
a slightly brighter value would be an option, but since the arrow is pure structure (not content), keeping it as-is is
fine. The main readability win comes from the datetime.

## Changes

### Phase 1: TUI (timestamps_builder.py)

**File**: `src/sase/ace/tui/widgets/timestamps_builder.py`

1. Change `_COLOR_TIMESTAMP` from `"dim #808080"` to `"#AF87D7"`
2. Change folded count style from `"italic #808080"` to `"italic #AF87D7"` (so the folded state count is also more
   visible)

### Phase 2: Neovim (sase_gp.vim)

**File**: `../sase-nvim/syntax/sase_gp.vim`

1. Change `saseGpTsDatetime` highlight from `guifg=#87AFD7 gui=bold` to `guifg=#AF87D7` (non-bold, matching TUI)
2. Update `ctermfg` from `110` to `140` (the 256-color approximation of `#AF87D7`)

### What stays the same

- Event type colors (COMMIT, STATUS, SYNC, REWORD) — already good and distinctive
- Detail text color (`#D7D7AF`) — readable as-is
- Arrow color (`bold #808080`) — structural, fine as-is
- HOOKS/MENTORS timestamp color (`#AF87D7`) — already this exact target color

## Verification

- Run `just install && just check` in the sase repo
- Run `just check` in sase-nvim if it has one (it doesn't based on prior conversation)
- Visual verification by the user in both TUI and Neovim
