---
create_time: 2026-05-07 01:23:39
status: done
prompt: sdd/prompts/202605/nvim_slash_skill_completion.md
---
# Add Slash Skill Completion to sase-nvim

## Context

The prompt input TUI now supports `<ctrl+t>` completion for slash-prefixed xprompt skills:

- `/sas` can complete to `/sase_plan`.
- Slash completion is limited to catalog entries marked as skills.
- Absolute paths such as `/tmp/foo` remain file completion candidates.
- Accepting `/skill` does not enter xprompt argument-hint mode because slash skills are runtime skill invocations, not
  `#xprompt(...)` references.

The Neovim plugin has its own lightweight `<C-t>` dispatcher in `../sase-nvim`. It intentionally mirrors the TUI by
using thin JSON helpers from the core `sase` CLI rather than reimplementing TUI internals. Today it recognizes `#token`
/ `#!token`, file paths, and file history. It treats any token starting with `/` as path-like, and its xprompt picker
consumes `sase xprompt list`, whose current JSON output includes insertion metadata but not the structured catalog's
`is_skill` field.

## Goal

Bring `sase-nvim` to parity with the TUI for slash skill completion:

- Typing `/sas` then `<C-t>` in Neovim should offer skill candidates like `/sase_plan`.
- Selecting a slash skill should replace the token with `/sase_plan`.
- Slash completion should show only xprompt catalog entries marked as skills.
- Existing `#` / `#!` xprompt completion, file completion, recent-file completion, and `#@` picker behavior should
  remain unchanged.

## Non-Goals

- Do not make slash skills expand through the xprompt processor.
- Do not parse skill source files from the Neovim plugin.
- Do not broaden slash completion into arbitrary command completion.
- Do not redesign the Neovim picker UI beyond the minimum label/copy updates needed for slash skill entries.

## Design

1. Extend the core `sase xprompt list` JSON contract.
   - Add a backward-compatible `is_skill: boolean` field to each item.
   - Preserve existing fields (`name`, `type`, `kind`, `prefix`, `insertion`, `source`, `inputs`, `tags`, `preview`) and
     their current semantics.
   - Use the xprompt catalog/loader as the source of truth for the skill flag. Simple xprompts that came from
     `XPrompt.skill` should emit `is_skill: true`; workflows should emit `false` unless the core data model later gains
     a workflow skill concept.
   - Add a focused core test so editor integrations can depend on this field.
   - Update the `sase xprompt list` docs to mention `is_skill`.

2. Mirror the TUI token classification in `sase-nvim`.
   - Add a conservative slash-skill predicate in `lua/sase/complete/_token.lua`, equivalent to the TUI's
     `^/[A-Za-z0-9_]*$` rule.
   - Classify bare slash skill tokens (`/`, `/sase_plan`) as `xprompt` before path classification.
   - Keep `/tmp/foo`, `/foo/bar`, `/sase-plan`, and other non-identifier slash tokens path-like or unrecognized under
     the existing rules.
   - Expose the helper for headless Neovim tests.

3. Teach the Neovim xprompt picker about slash skill mode.
   - Extend the `SaseXPromptItem` annotation with `is_skill? boolean`.
   - In `filter_items_for_token`, detect slash-skill tokens, filter to `item.is_skill == true`, and match the partial
     against `item.name`.
   - Render and insert `/name` for slash skill candidates while preserving existing `item.insertion` behavior for `#`
     and `#!` candidates.
   - Avoid leaking slash behavior into the `#@` picker: when no slash token is active, the picker should continue to
     show normal xprompt insertion text.
   - Adjust labels so slash entries read as skills in Telescope and `vim.ui.select` output without changing the
     underlying selection mechanics.

4. Keep integration boundaries clean.
   - `sase-nvim` should continue to fetch via `sase xprompt list`; it should not call private Python modules or read
     source directories.
   - The core CLI change should be additive so older plugins remain compatible and newer plugins can gracefully treat a
     missing `is_skill` as false.

5. Update documentation.
   - Update `../sase-nvim/README.md` so the `<C-t>` table includes `/skill` / `/partial` slash skill completion.
   - Mention that slash completion is filtered by `is_skill` from `sase xprompt list`.

## Tests and Verification

Core `sase` repo:

- Add or update tests around `sase xprompt list` to assert skill xprompts emit `is_skill: true` and non-skill prompts /
  workflows emit `false`.
- Run the focused test(s) for xprompt listing.
- Because this workspace may have stale dependencies, run `just install` before broader checks if needed.
- Run `just check` after core file changes.

`sase-nvim` repo:

- Add headless Neovim Lua tests or a small checked script for pure token and xprompt filtering helpers:
  - `/` and `/sase_plan` classify as `xprompt`.
  - `/tmp/foo` remains `file`.
  - Slash filtering returns only `is_skill = true` entries.
  - Slash insertion text is `/name`.
  - `#` / `#!` filtering still preserves existing behavior.
- Run `nvim --headless` against the test script.
- Run available Lua checks (`luacheck`, `stylua --check`) if the repo has compatible config; otherwise run targeted
  headless checks plus a syntax/load smoke test.
- Per external repo memory, run `just check` in `../sase-nvim` if a `justfile` is added or exists by implementation
  time; otherwise document that no `just check` target exists.

## Risks and Mitigations

- Risk: `/tmp` could open skill completion instead of file completion.
  - Mitigation: use the same conservative slash-token regex as the TUI and classify slash skill tokens before the
    broader path predicate only when they contain no second slash and no punctuation.

- Risk: `sase xprompt list` currently converts xprompts to workflows and loses `XPrompt.skill`.
  - Mitigation: add the `is_skill` field from the original xprompt data before or alongside conversion, and cover the
    behavior with a regression test.

- Risk: older `sase` versions used with newer `sase-nvim` will not emit `is_skill`.
  - Mitigation: treat missing `is_skill` as false. Slash completion may show no candidates until core is upgraded, but
    existing `#` completion remains intact.

- Risk: Telescope and `vim.ui.select` paths could diverge.
  - Mitigation: keep slash insertion logic in shared `lua/sase/xprompt.lua` helper functions and have the Telescope
    extension call those helpers as it does today.

## Implementation Steps

1. Update core `sase xprompt list` to emit `is_skill` and add focused tests/docs.
2. Update `sase-nvim` token classification to recognize conservative slash skill tokens.
3. Update `sase-nvim` xprompt filtering, display, and insertion helpers for slash skill mode.
4. Add headless Neovim coverage or equivalent checked Lua smoke tests for the helper behavior.
5. Refresh `sase-nvim` README completion documentation.
6. Run focused tests, `just check` in the core repo, and the available plugin checks.
