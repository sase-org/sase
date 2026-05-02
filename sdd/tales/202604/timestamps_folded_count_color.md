---
create_time: 2026-04-25 15:29:04
status: done
---
# Plan: Highlight folded-count digit in TIMESTAMPS section

## Context

In the `sase ace` TUI, ChangeSpec entries have two distinct "fold indicator" displays:

1. **COMMITS section** — shows `[folded: CHAT + DIFF + PLAN]` (or any subset). The bracketed labels (`CHAT`, `DIFF`,
   `PLAN`, `N proposals`) are rendered in **bold cyan `#87D7FF`**, while the surrounding `[folded: `, `+`, and `]` are
   rendered in dim italic gray (`italic #808080`). See `src/sase/ace/tui/widgets/commits_builder.py:256-274`.

2. **TIMESTAMPS section** — shows `[folded: 4]` (where `4` is the count of hidden timestamp entries). Today the
   **entire** string `  [folded: 4]\n` is rendered as flat `italic #808080` (gray). See
   `src/sase/ace/tui/widgets/timestamps_builder.py:79-86`.

The user wants the digit (`4` in the example) in the TIMESTAMPS fold indicator to pop with the same cyan color as the
COMMITS labels, so the eye can quickly tell that something is hidden and how many entries.

## Goal

Render the hidden-count number inside `[folded: N]` for the TIMESTAMPS section using `bold #87D7FF` (matching the
COMMITS section), while keeping the surrounding ` [folded:` and `]` punctuation in the existing dim italic gray.

Visually:

```
TIMESTAMPS:  [folded: 4]
              └── gray ──┘└── gray
                       ↑
              bold cyan #87D7FF
```

## Design

### Where the change lives

`src/sase/ace/tui/widgets/timestamps_builder.py`, in the `COLLAPSED` branch (lines 79–86). Today:

```python
if timestamps_fold == FoldLevel.COLLAPSED:
    hidden = len(changespec.timestamps) - 1
    if hidden > 0:
        text.append("TIMESTAMPS:", style=_COLOR_HEADER)
        text.append(
            f"  [folded: {hidden}]\n",
            style="italic #808080",
        )
```

After the change, the single `text.append(...)` call is split into three calls so the count gets a distinct style:

```python
text.append("TIMESTAMPS:", style=_COLOR_HEADER)
text.append("  [folded: ", style="italic #808080")
text.append(str(hidden), style="bold #87D7FF")
text.append("]\n", style="italic #808080")
```

### Color constant

Both files currently use the literal string `"bold #87D7FF"` inline (it is also assigned to `_COLOR_HEADER` in
`timestamps_builder.py`). To keep the cyan-label semantic distinct from the section-header semantic, I will introduce a
new module-level constant in `timestamps_builder.py`:

```python
_COLOR_FOLD_COUNT = "bold #87D7FF"
```

This mirrors the inline style used in `commits_builder.py` for `CHAT`/`DIFF`/`PLAN`. I am intentionally not centralizing
the cyan into a shared module: the two sites are small, the existing code already inlines the color literal in
`commits_builder.py`, and a shared palette refactor is out of scope for this UI tweak.

### Style strings reused (not changed)

- `"italic #808080"` for ` [folded:` and `]` — keeps punctuation visually subordinate.
- `_COLOR_HEADER` (`"bold #87D7FF"`) for the `TIMESTAMPS:` label — unchanged.

## Test plan

There is one existing assertion at `tests/ace/tui/test_timestamps_builder.py:62`:

```python
assert "[folded: 3]" in plain
```

This asserts on the _plain text_ output of `Text`, which is unaffected by style spans, so it should keep passing without
modification.

I will add one additional assertion in the same test verifying that the count digit is styled with the cyan color and
the surrounding brackets are still gray. Concretely, walk the `Text` spans (or use `text.get_style_at_offset`) and
assert:

- The offset corresponding to `"3"` in `"[folded: 3]"` carries `bold #87D7FF`.
- The offset corresponding to `"["` carries `italic #808080`.

If the existing test file already uses a particular pattern for span/style assertions, I'll match that pattern;
otherwise `text.get_style_at_offset(console, offset)` against a small `rich.console.Console()` works.

## Out of scope / non-goals

- **No changes to `commits_builder.py`** — its rendering is already correct.
- **No changes to non-TUI surfaces** (the AGENTS.md note in `src/sase/ace/AGENTS.md` about updating four files for
  "ChangeSpec suffix syntax highlighting" does not apply: the `[folded: N]` marker is purely a TUI-rendered fold-state
  indicator, not part of the persisted ChangeSpec text in `.gp` files, so vim syntax, CLI display, and query
  highlighting do not surface it).
- **No palette refactor** — leaving the cyan literal `#87D7FF` inline / per-module is consistent with what
  `commits_builder.py` already does.
- **No behavior change** when `hidden == 0` (no fold marker is rendered in that case; unchanged).

## Verification

After the edit:

1. `just check` (per repo convention from `memory/short/build_and_run.md`).
2. Eyeball `sase ace` on a ChangeSpec with multiple timestamps — confirm the `4` (or whatever count) is bold cyan and
   the brackets remain dim gray, matching the COMMITS section's `[folded: CHAT + DIFF + PLAN]` aesthetic.
