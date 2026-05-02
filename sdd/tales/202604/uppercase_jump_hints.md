---
create_time: 2026-04-24 13:09:34
status: done
prompt: sdd/prompts/202604/uppercase_jump_hints.md
---
# Plan: Extend Jump-to-Entry Hint Alphabet with A–Z

## Problem

In the `sase ace` TUI, the backtick (`` ` ``) keymap opens the "Jump to Entry" modal (`JumpAllModal`) which assigns
one-key hints to left-panel entries across all tabs (ChangeSpecs, Agents, AXE). The current hint alphabet is 36
characters:

```
1234567890abcdefghijklmnopqrstuvwxyz
```

When the total number of visible entries exceeds 36 (e.g. 15 ChangeSpecs + 22 Agents + AXE items in the user's
snapshot), entries beyond the 36th are rendered with an empty `[ ]` placeholder and are unreachable via the jump modal.
The user needs to extend the alphabet so overflow entries get hints `A–Z` after `a–z`, yielding 62 total hints.

## Goal

- Entries 37–62 in the `` ` `` "Jump to Entry" modal get uppercase-letter hints.
- The same alphabet is used by the apostrophe (`'`) per-tab jump action (they share one constant — consistent by
  design).
- Pressing `Shift+<letter>` inside the modal jumps to the corresponding entry.
- No visual regressions; lowercase entries still map identically.

## Why shared constant (not a separate one for backtick)

The apostrophe and backtick jump actions are two views of the same "jump by hint" UX — both build hint maps via
`build_jump_hint_maps()` from `src/sase/ace/tui/actions/navigation/jump_hints.py`. A per-tab jump can also exceed 36
entries (e.g. the 22-agent list in the snapshot). Splitting the constant would create an inconsistency with no
user-visible benefit. Use a single shared alphabet.

## Design

### Alphabet

Change the module-level constant in `jump_hints.py` from 36 chars to 62:

```python
JUMP_HINT_CHARS = (
    "1234567890"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
```

Digits first preserves the current muscle-memory mapping (entry 1 → `1`, …, entry 10 → `0`, entry 11 → `a`, …, entry 36
→ `z`). Uppercase is appended so existing users see no change for the first 36 entries.

### Key dispatch

No changes required. Both dispatchers already look up `event.key` in a case-sensitive dict built from `JUMP_HINT_CHARS`:

- `src/sase/ace/tui/modals/jump_all_modal.py:289`
- `src/sase/ace/tui/actions/navigation/_advanced.py:198`

Textual delivers `Shift+a` as `event.key == "A"` (distinct from `"a"`), so uppercase letters fall through to the same
lookup path.

### Rendering

No changes required. The three list widgets (`changespec_list.py`, `agent_list.py`, `bgcmd_list.py`) render hints as
`[{hint_char}]` with no character-class assumptions. `JumpAllModal._build_display` (`jump_all_modal.py:218`) iterates
`JUMP_HINT_CHARS` directly.

## Out-of-scope decisions to confirm with the user before implementing

1. **`runners_modal.py:46`** has its own private hint alphabet `_HINT_CHARS = "123456789abcdefghijklmnopqrstuvwxyz"` (no
   `0`, no uppercase). Recommendation: leave it alone in this change. It is a separate modal with its own UX, and the
   user's request explicitly named the backtick keymap. If the user wants symmetry we can open a follow-up.

2. **Key-capture side effect**: today, pressing any non-hint key (including uppercase letters like `W`, `Y`) inside
   `JumpAllModal` dismisses it without action. After this change, uppercase letters that are assigned as hints will
   trigger a jump instead of dismissing. This is the intended new behavior. Uppercase letters that are _not_ assigned
   (because entry count ≤ 36 or ≤ some value < 62) will continue to dismiss.

## Files to change

1. **`src/sase/ace/tui/actions/navigation/jump_hints.py`** — extend `JUMP_HINT_CHARS` to 62 chars.

2. **`tests/ace/tui/test_jump_to_entry_hints.py`** — update `test_build_jump_hint_maps_truncates_to_hint_alphabet`:
   - Keep existing assertions for `"1" → 0`, `"0" → 9`, `"a" → 10`.
   - Replace `hint_to_index["z"] == len(JUMP_HINT_CHARS) - 1` with `hint_to_index["z"] == 35`.
   - Add `hint_to_index["A"] == 36`, `hint_to_index["Z"] == 61`.
   - Add `len(JUMP_HINT_CHARS) == 62` as a sanity assertion in a new targeted test so an accidental future truncation
     fails loudly.

## Files NOT changed (verified)

- `jump_all_modal.py` / `_advanced.py` — dispatch is already case-sensitive.
- `changespec_list.py`, `agent_list.py`, `bgcmd_list.py` — hint rendering is character-agnostic.
- `bindings.py`, `help_modal/bindings.py` — the Jump action labels don't mention alphabet size; no doc drift.
- `runners_modal.py` — intentionally out of scope (see above).

## Verification

- `just check` passes (lint + mypy + tests).
- Smoke test in a live `sase ace`:
  1. Populate enough state that a single tab and the cross-tab modal both exceed 36 entries (e.g. the 15 CLs + 22 Agents
     scenario from the snapshot).
  2. Press `` ` ``; confirm hints advance `1…0`, `a…z`, `A…Z` with no `[ ]` placeholders until entry 63.
  3. Press `Shift+A`; confirm it jumps to the 37th entry.
  4. Press `'` inside the Agents tab; confirm per-tab jump shows uppercase hints for entries past `z`.
  5. Press an unassigned uppercase letter (e.g. `Z` when there are only 40 entries); confirm the modal dismisses as
     before.

## Risk assessment

- **Low blast radius.** Single-line constant change + test update; all downstream code paths already tolerate arbitrary
  hint characters.
- **Only behavioral surprise** is that uppercase letters inside the jump modal are no longer a no-op dismiss — which is
  the explicit goal.
- **No muscle-memory breakage** for existing 1–36 entry workflows.
