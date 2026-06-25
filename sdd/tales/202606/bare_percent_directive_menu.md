---
create_time: 2026-06-25 13:56:33
status: done
prompt: sdd/prompts/202606/bare_percent_directive_menu.md
---
# Plan: Open the directive completion menu on a bare `%`

## Goal

In the ACE TUI prompt input widget, make the **`%` symbol alone** trigger the directive completion menu (showing all
directives), instead of requiring a second identifier character (e.g. `%m`) before the menu appears.

This is scoped to the `%` directive trigger only. The `#` (xprompt) and `/` (skill) triggers intentionally keep their
current "need one identifier character first" behavior — this change is the first step toward the bare-marker experience
and the user asked specifically for `%`.

## Current behavior (what we're changing)

Auto-completion for `%` / `#` / `/` opens only after the first character is typed _after_ the marker. For directives
this is enforced by a single guard in `_try_auto_directive_completion`:

`src/sase/ace/tui/widgets/_file_completion_open.py` (≈ lines 128-149):

```python
def _try_auto_directive_completion(self) -> bool:
    """Open the directive completion menu while typing a ``%`` token."""
    ctx = self._get_directive_token_context()
    if ctx is None:
        return False
    _row, _start, _end, token = ctx
    # Bare ``%`` stays quiet; open only once a directive character follows.
    if len(token) < 2:
        return False
    if not is_directive_like_token(token):
        return False
    ...
```

With `token == "%"`, the `len(token) < 2` guard returns early, so the menu does not open.

## Why the rest of the pipeline already supports a bare `%`

Verified by reading the surrounding code — only the one guard blocks it:

- **Keystroke gate** — `_open_auto_reference_completion_after_change` (`_prompt_text_area_key_handling.py`) only runs
  the auto-open path for printable, non-whitespace inserted characters via `_is_auto_xprompt_menu_character`. `%`
  qualifies, so typing `%` already reaches `_try_auto_directive_completion`.
- **Context validation** — `extract_directive_token_around_cursor` (`directive_completion.py`) only returns a `%` token
  when `_has_valid_directive_context` holds: `%` at start-of-line, after whitespace, or after an opening `([{"'`. So
  mid-word `%` (e.g. `100%`) still does **not** trigger — that protection is preserved automatically.
- **Candidate building** — `build_directive_completion_candidates("%")` yields `partial == ""`, which matches **all**
  user-facing directives (sorted). So a bare `%` naturally produces the full directive list with panel title
  "directives".
- **Narrowing after open** — `_refresh_file_completion_from_cursor` (`_file_completion_refresh.py`) recomputes directive
  candidates with `_get_token_context()` and has **no** `len < 2` guard. So once open, typing `%m` narrows to `%model`,
  and backspacing back to `%` keeps the menu showing all directives. Opening at `%` is therefore symmetric with the
  existing refresh behavior.
- **Manual Ctrl+T** — `_try_file_completion_tab` already opens directive completion for a bare `%` (it checks only
  `is_directive_like_token`, no min-length). This change makes the _auto_-open path consistent with the manual path.
- **Jinja guard** — typing `%` right after `{` is intercepted by `_try_jinja_auto_pair` (builds `{%  %}`) and returns
  before the auto-open path runs, so `{%` Jinja context is unaffected.
- **Settings gate** — `auto_directive_menu` (default `true`) still gates the whole path; setting it `false` continues to
  suppress the menu entirely.

## Implementation

### 1. Production change (one line of logic)

`src/sase/ace/tui/widgets/_file_completion_open.py`, in `_try_auto_directive_completion`: remove the `len(token) < 2`
early return so a bare `%` opens the menu. Keep the `is_directive_like_token(token)` guard (which still rejects
malformed tokens; `extract_directive_token_around_cursor` already guarantees the token starts with `%` and is at least
one character).

Update the adjacent comment to reflect the new intent (bare `%` opens the full directive menu; the marker must still sit
in a valid directive context).

Do **not** touch `_try_auto_xprompt_completion` — the `#` / `/` `len(token) < 2` guard stays as-is.

### 2. Tests

File: `tests/ace/tui/widgets/test_directive_completion_interactions.py`

- **Replace** `test_bare_percent_does_not_auto_open` (currently asserts the menu stays closed) with a test asserting the
  new behavior: after pressing `%`, `_file_completion_active is True`, `_completion_kind == "directive"`, the panel
  border title is `"directives"`, the candidate insertions equal the full sorted user-facing directive set, the text
  stays `"%"`, and nothing is auto-accepted.
- **Update** `test_percent_partial_auto_opens_directive_panel`: its current intermediate assertion that the menu is
  inactive after the first `%` keystroke is now wrong. Adjust it so that after `%` the menu is already open with the
  full directive list, and after `m` it narrows to `["%model"]` (the rest of the test — no auto-accept, text stays `%m`,
  panel title — is unchanged).
- **Keep (regression coverage, expected to still pass — confirm by running):**
  - `test_directive_invalid_context_does_not_auto_open` — `%` after `word` still fails `_has_valid_directive_context`,
    so no menu.
  - `test_unknown_directive_does_not_show_placeholder` — `%z` narrows to zero candidates; refresh clears the menu, so
    the final assertions (`active is False`, `candidates == []`) still hold.
  - The `auto_directive_menu=False` test — the menu stays closed when the setting disables it.
- Add (optional but recommended) a small regression test that a bare `%` typed **after existing text + a space** (valid
  context) opens the menu, to lock in that the trigger is not limited to offset zero.

### 3. Docs

- `docs/ace.md` (≈ lines 1803-1806): the sentence "Both auto-menus open only once at least one identifier character
  follows the marker (bare `#`, `/`, and `%` stay quiet)..." is now inaccurate. Reword so the **directive** menu opens
  on a bare `%` (in a valid directive context), while the xprompt/skill menus still require one identifier character
  after `#` / `/`.
- `docs/configuration.md` (the `auto_directive_menu` row, ≈ line 253): minor wording touch-up to note the directive menu
  opens on a bare `%`.

### 4. Help popup / keybinding docs (verify, likely no-op)

Per `src/sase/ace/AGENTS.md`, changes to `sase ace` option behavior must keep the `?` help popup in sync. A grep shows
the `?` help modal does not document the directive auto-menu trigger semantics (it covers keybindings/saved queries), so
no help-modal change is expected. Confirm during implementation and update only if a relevant mention exists.

## Out of scope / follow-ups

- **`#` and `/` parity** — extending bare-marker triggering to xprompts and skills is a deliberate follow-up, not part
  of this change.
- **Neovim xprompt LSP / Rust core parity** — the trigger _timing_ changed here lives in TUI presentation code
  (`src/sase/ace/tui/widgets/...`), which the `rust_core_backend_boundary` guidance treats as presentation-only Textual
  state. Directive candidate _content_ is unchanged. If the bare-`%` experience should also be mirrored in the Neovim
  LSP, that is a separate parity task.
- **Soft/live completion** (the `[^L] accept ...` subtitle hint) is a separate code path and is unchanged.

## Validation

- `just install` (ephemeral workspace may have stale deps), then `just check`.
- Run the directive completion interaction suite specifically, e.g.
  `tests/ace/tui/widgets/test_directive_completion_interactions.py`, plus the auto-xprompt completion suite to confirm
  `#` / `/` behavior is untouched.
- Manual smoke (optional): in `sase ace`, type `%` at the start of the prompt and confirm the directive menu opens with
  all directives; confirm `100%` mid-word does not open it.
