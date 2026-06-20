---
create_time: 2026-06-20 00:00:28
status: done
prompt: sdd/prompts/202606/completion_directives_skills.md
---
# Auto Completion for Directives and XPrompt Skills

## Goal

Extend the prompt input bar's automatic completion menu so it behaves like the current `#...` project/xprompt completion
path for:

- SASE prompt directives typed as `%<name-prefix>`, such as `%m` or `%wai`.
- XPrompt-backed skills typed as `/<skill-prefix>`, such as `/sase_p`.

The change should preserve the existing explicit `Ctrl+T` completion behavior, the current `#+` project / ChangeSpec
completion behavior, and the prompt input bar's responsiveness.

## Current Behavior

The TUI prompt input already has most of the needed pieces:

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` runs automatic completion after printable insert-mode
  keypresses.
- `src/sase/ace/tui/widgets/_file_completion_open.py` has `_try_auto_xprompt_completion()`, but it currently only
  auto-opens for `#...` xprompt tokens. It explicitly does not auto-open slash-skill tokens.
- `src/sase/ace/tui/widgets/directive_completion.py` already provides pure directive candidate building and directive
  row metadata.
- `src/sase/ace/tui/widgets/xprompt_completion.py` already supports slash-skill completion by filtering structured
  xprompt catalog entries where `is_skill=True`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` already renders directive rows and xprompt skill rows.
- `Ctrl+T` already supports `%...`, `#...`, `#!...`, and `/...`; the missing behavior is automatic menu opening while
  typing.

Important constraint from `memory/tui_perf.md`: no disk reads, catalog builds, JSON parsing, or subprocess work may be
introduced on the per-keystroke path. XPrompt/skill catalog work must continue to use the existing warm-cache and
background-worker pattern.

## Proposed Design

Generalize the current automatic xprompt-menu path into an automatic prompt reference menu path.

The post-keypress flow should keep this precedence:

1. Refresh any active completion panel from the cursor.
2. If `+` creates a `#+` / start-of-token project trigger, open the existing project / ChangeSpec completion menu.
3. If no panel is active and the inserted character is printable, try automatic prompt-reference completion for
   directives and xprompt references.
4. Refresh xprompt argument hints and soft completion as today.

Directive auto completion:

- Detect tokens through the existing `_get_directive_token_context()` / `extract_directive_token_around_cursor()` logic.
- Open only after the user has typed `%` plus at least one directive identifier character. Bare `%` should stay quiet to
  avoid an overly noisy menu.
- Use `build_directive_completion_candidates(token)`.
- If candidates exist, open the existing completion panel with `_completion_kind = "directive"`.
- Never auto-accept, even for one candidate. Acceptance remains explicit via `Enter` or `Ctrl+L` while the menu is
  active.
- If no candidates match, do not show a placeholder.

Slash-skill auto completion:

- Treat slash-skill tokens as the skill-specific side of xprompt completion.
- Open only after `/` plus at least one skill identifier character. Bare `/` should stay quiet.
- Reuse `is_xprompt_like_token()` and `build_xprompt_completion_candidates()`, but only through the warm-cache path used
  by automatic `#...` completion: `_build_warm_xprompt_completion_candidates(token)`.
- This means a cold catalog schedules `_warm_current_xprompt_assist_entries()` and returns without building
  synchronously. Once warm, later keypresses can open the menu.
- Candidate construction already filters slash tokens to `entry.is_skill`.
- Keep `_completion_kind = "xprompt"` so the existing panel renderer shows rows as `skill` when metadata says
  `is_skill=True`.
- Never auto-accept, even for one candidate.

Hash xprompt behavior:

- Preserve existing `#...` and `#!...` behavior.
- Keep `#+` reserved for project / ChangeSpec completion.
- Keep not opening on bare `#`.
- Keep avoiding embedded tokens such as `foo#bar`.

Settings:

- Keep `auto_xprompt_menu` as the control for automatic `#...` xprompt and `/...` skill menus, because skills are
  sourced from the xprompt catalog.
- Add `auto_directive_menu: bool = True` to `PromptCompletionSettings` so users can disable directive auto popups
  without disabling xprompt/skill auto popups.
- Continue to leave explicit `Ctrl+T` unaffected by auto-menu settings.

Implementation shape:

- Replace or wrap `_try_auto_xprompt_completion()` with a more general helper, such as
  `_try_auto_prompt_reference_completion()`. Keep a small compatibility wrapper if existing tests or call sites benefit
  from it.
- Add an internal directive branch near the xprompt branch in `_file_completion_open.py`.
- Update `_prompt_text_area_key_handling.py` to call the generalized helper when either relevant auto-menu setting is
  enabled.
- Extend `PromptCompletionSettings` and `parse_prompt_completion_settings()` in `prompt_completion.py`.
- No generated `SKILL.md` files should be edited. This feature consumes skill metadata through the structured xprompt
  catalog.

## Test Plan

Add or update focused tests in the existing completion test modules:

- `tests/ace/tui/widgets/test_directive_completion.py`
  - `%m` auto-opens the directive panel without changing text to `%model`.
  - Single directive matches still require explicit acceptance.
  - `%p` / unknown directives do not open a stale or placeholder panel.
  - Invalid contexts such as `word%m` do not auto-open.
  - Typing narrows, backspace widens, and whitespace dismisses an active directive menu through the existing refresh
    path.

- `tests/ace/tui/widgets/test_auto_xprompt_completion.py`
  - Replace the current `slash skill token does not auto open` regression with positive coverage that `/s` opens a
    skill-only xprompt panel when warm.
  - Verify the slash-skill auto path never performs a cold synchronous catalog build and schedules warming instead.
  - Verify `auto_xprompt_menu=False` disables slash-skill auto opening while leaving explicit `Ctrl+T` intact.
  - Preserve existing `#+` project / ChangeSpec precedence coverage.

- `tests/ace/tui/widgets/test_prompt_live_completion.py`
  - Extend settings parsing coverage for `auto_directive_menu`.

- Existing xprompt/skill completion tests should continue to cover candidate filtering, rendering metadata, and explicit
  `Ctrl+T` acceptance semantics.

Run the affected test set:

```bash
pytest tests/ace/tui/widgets/test_auto_xprompt_completion.py \
  tests/ace/tui/widgets/test_directive_completion.py \
  tests/ace/tui/widgets/test_xprompt_completion.py \
  tests/ace/tui/widgets/test_prompt_live_completion.py
```

## Risks and Mitigations

- Slash-skill completion could look like absolute path completion. Mitigate by only auto-opening for slash tokens
  accepted by the existing skill-token regex and only when skill candidates match. Bare `/` and path-like `/tmp/foo`
  stay quiet.
- Auto directive completion could be noisy. Mitigate by requiring at least one directive character after `%`, not
  auto-accepting, and adding `auto_directive_menu`.
- XPrompt/skill catalog loading could regress prompt typing latency. Mitigate by using only the existing
  warm-cache/background-worker path for automatic slash-skill completion.
- Existing soft completion and `Ctrl+T` behavior could drift. Mitigate by keeping explicit completion code paths
  unchanged and running the focused completion tests above.
