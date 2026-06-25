---
create_time: 2026-06-25 08:03:44
status: done
prompt: sdd/prompts/202606/fix_agent_completion_text_muted_style.md
---
# Fix `MissingStyle` crash on `%w:` agent-name completion (`$text-muted` leak)

## Problem / Product context

Typing `%w:` in the `sase ace` prompt input — which should trigger **agent-name completion** for the `%wait` directive —
crashes the TUI with:

```
MissingStyle: Failed to get style 'bold $text-muted'; unable to parse
'$text-muted' as color; '$text-muted' is not a valid color
```

The completion panel renders fine for some agents but blows up as soon as it has to draw a row for a visible agent whose
status falls outside the handful of recognized values. This makes the brand-new agent-name completion feature (shipped
yesterday in `1c8acbd94 feat(ace): add agent name completions`) effectively unusable for anyone whose Agents panel
contains an agent in an "other" status.

## Root cause

`status_style()` in `src/sase/ace/tui/agent_completion.py` returns the Rich style string for the `●` status indicator.
Every recognized branch returns a concrete Rich color, but the fallback returns a **Textual CSS theme variable**:

```python
def status_style(status: str) -> str:
    """Return the Rich style used for a status indicator."""
    status_upper = status.upper()
    if status_upper in {"RUNNING", "STARTING"}:
        return "bold #00D7AF"
    if status_upper == "WAITING":
        return "bold #AF87FF"
    if "DONE" in status_upper:
        return "bold #5FD7FF"
    if "FAILED" in status_upper:
        return "bold #FF5F5F"
    return "bold $text-muted"      # <-- line 128: the bug
```

`$text-muted` is a Textual CSS variable. It is only resolved inside Textual CSS (`.tcss` / `_styles.py`), **not** inside
a Rich `Text` span style. The completion panel is a plain Rich render path:

- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py:325`
  `content.append("● ", style=status_style(metadata.status))`
- The assembled `Text` is pushed to a `Static` widget via `panel.update(content)`.
- When Textual renders that `Static`, Rich's `Console.get_style("bold $text-muted")` tries to parse `$text-muted` as a
  color and raises `MissingStyle` — exactly the traceback observed.

So the crash fires whenever **any** visible agent's status is not one of RUNNING / STARTING / WAITING / _DONE_ /
_FAILED_ (e.g. `PLAN`, `QUESTION`, `KILLED`, `ARCHIVED`, empty, etc.). The traceback's `text` locals confirm a
`Span(2, 4, 'bold $text-muted')` on the first row.

### Verified reproduction

```
Style.parse("bold $text-muted")          -> StyleSyntaxError
Console().get_style("bold $text-muted")  -> MissingStyle   (matches traceback)
Style.parse("dim") / "bold grey50" / "bold #00D7AF"  -> all OK
```

### Blast radius

`status_style()` is also consumed by the **wait modal** (`src/sase/ace/tui/modals/wait_modal.py` → `_status_style` →
`status_style`, used at `wait_modal.py:200`), which renders its own Rich `Text`. That modal had the same latent crash
for unrecognized statuses. Fixing `status_style()` once repairs both call sites. No other Python style helper leaks a
`$`-variable — a repo-wide search for `$text-muted` finds only this line plus the legitimate Textual CSS in
`src/sase/memory/review_tui/_styles.py`.

This is presentation-only Python glue (Rich style strings); per the `rust_core_backend_boundary` memory it correctly
stays in this repo — no `sase-core` change is involved.

## Fix

Replace the fallback at `src/sase/ace/tui/agent_completion.py:128` with a valid Rich style that conveys the same "muted
/ other" intent:

```python
    return "dim"
```

Rationale for `"dim"`:

- It is a valid Rich style and renders as a muted indicator, matching the original visual intent of `$text-muted`.
- It mirrors the established fallback convention already used by
  `src/sase/ace/tui/widgets/tools_panel.py::_status_style`, which returns `"dim"` for its unknown-status default.
- The dimmed (non-bold-colored) `●` reads as a deliberate "other/unknown status" distinction from the bold colored
  bullets of known statuses.

Alternative if we'd rather preserve a bold weight consistent with the other branches: `"bold grey50"` (a concrete muted
grey). Recommendation: `"dim"` for consistency with `tools_panel`. Final choice can be confirmed at implementation time,
but it MUST be a Rich-parseable style — never a Textual `$variable`.

## Regression test

The feature shipped without a test that renders an unrecognized-status row, so the leak went unnoticed. Add a focused,
fast unit test (no Textual app needed) that guards the exact failing API:

- New test in `tests/ace/tui/test_agent_completion.py` (the existing home for `agent_completion` unit tests) that
  asserts, for every recognized status plus representative "other" statuses (e.g. `"PLAN"`, `"QUESTION"`, `"KILLED"`,
  `""`), that `status_style(status)` is consumable by Rich without raising:

  ```python
  from rich.console import Console
  from rich.style import Style
  from sase.ace.tui.agent_completion import status_style

  def test_status_style_returns_rich_parseable_styles() -> None:
      console = Console()
      for status in [
          "RUNNING", "STARTING", "WAITING", "DONE", "PLAN DONE",
          "FAILED", "PLAN", "QUESTION", "KILLED", "ARCHIVED", "",
      ]:
          style = status_style(status)
          Style.parse(style)         # would raise StyleSyntaxError on a $var
          console.get_style(style)   # mirrors the TUI render path (MissingStyle)
  ```

  Both `Style.parse` and `Console.get_style` reproduce the original failure modes, so this test fails on the current
  code and passes after the fix.

Optionally (lower priority), extend the directive-arg completion render coverage in
`tests/ace/tui/widgets/test_directive_arg_completion.py` to build an `AgentCompletionCandidate` with an "other" status
and render the completion-row `Text` through a Rich `Console`, asserting no `MissingStyle`. The unit test above already
covers the root cause; this is defense-in-depth at the panel level.

## Files touched

1. `src/sase/ace/tui/agent_completion.py` — change line 128 fallback from `"bold $text-muted"` to `"dim"`.
2. `tests/ace/tui/test_agent_completion.py` — add the `status_style` Rich-parseability regression test.

## Validation

- `just install` (ephemeral workspace may have stale deps), then `just check` (lint + mypy + tests), since this changes
  Python source.
- Confirm the new test fails before the one-line fix and passes after.
- Manual smoke: `sase ace`, type `%w:` with an Agents panel containing an agent in an "other" status, and confirm the
  completion panel renders without crashing.

## Out of scope

- No change to which statuses get which color, beyond the fallback.
- No Textual-theme-aware color resolution for `status_style` (the module is intentionally theme-agnostic and returns
  plain Rich style strings shared across Rich-only call sites like the wait modal). Introducing live theme resolution
  would require threading app/theme context through every caller and is unjustified for this fix.
