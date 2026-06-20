---
create_time: 2026-06-20 14:25:04
status: done
prompt: sdd/prompts/202606/alt_brace_syntax.md
bead_id: sase-52
tier: epic
---
# Plan: migrate alt shorthand from `%(...)` to `%{...}`

## Goal

Introduce `%{A | B | ...}` as the prompt fan-out shorthand for `%alt(A, B, ...)`, with:

- parser/launch support for `%{...}` across Python and Rust-backed launch planning;
- good syntax highlighting in the ACE prompt input widget and Neovim;
- prompt input and Neovim editing help:
  - typing `%{` inserts the matching `}`;
  - deleting the just-opened `{` also deletes its auto-inserted `}`;
  - typing `|` inside `%{}` normalizes to a padded separator, keeping the cursor before the closing `}`;
  - the concrete acceptance case `%{foo ,bar, and baz|` becomes `%{foo, bar, and baz | }` with the cursor before `}`.

The existing long form `%alt(...)` should remain supported. The old shorthand `%(...)` should stay parse-compatible
during this migration unless Bryan explicitly asks to make it a hard error; new completion, snippets, docs, and UI
examples should emit `%{...}` only.

## Current Shape

- Launch fan-out planning is Rust-owned in `../sase-core/crates/sase_core/src/agent_launch/mod.rs`, reached from Python
  through `sase_core_rs.plan_agent_launch_fanout`.
- Python wrapper logic in `src/sase/xprompt/_directive_alt.py` still has quick scans and model-rewrite guard logic that
  know about `%alt(...)` and `%(...)`.
- ACE prompt input uses `PromptTextArea` with pre-insert key interception in
  `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`, post-delete hooks in `_prompt_text_area_actions.py`, and
  overlay highlighting in `_jinja_highlight.py`.
- Neovim integration lives in `../sase-nvim`; there is no local tree-sitter grammar today. It already uses
  `InsertCharPre` for the `#@` picker trigger and uses the xprompt LSP from `../sase-core` for completion/diagnostics.
- The xprompt LSP currently emits an old alt snippet `%(${1:variant})$0` from `crates/sase_xprompt_lsp/src/server.rs`.

## Phase 1: Core Grammar Contract

Repo: `../sase-core` workspace 10.

Implement `%{...}` in the Rust launch fan-out planner before touching UI surfaces.

Work items:

- Extend alt directive detection from `%alt(...)` / `%(...)` to include `%{...}` at the same directive-valid positions.
- Parse `%{...}` branches using top-level `|` separators, not commas.
- Preserve existing parser behavior inside branches:
  - nested `()`, `[]`, `{}` and backtick-quoted text must not split;
  - `[[...]]` text blocks still become raw branch text;
  - named branches should work as `name=value`, e.g. `%{sec=[[security]] | perf=[[performance]]}`;
  - a single branch still produces with/without variants.
- Update model fan-out handling so `%model` directives inside `%{...}` are treated the same as those inside `%alt(...)`:
  they participate through the alt branch and are not double-collected.
- Keep `%alt(...)` and `%(...)` compatibility in `plan_agent_launch_fanout`; change emitted rewrites/snippets later.
- Add focused Rust tests for:
  - two/three branch `%{a | b | c}`;
  - comma-containing branch text, e.g. `%{foo, bar | baz}`;
  - named branches and numeric suffix allocation;
  - single branch with implicit empty variant;
  - Cartesian products mixing `%{}` with `%alt(...)` and `%m(...)`;
  - nested `%model` inside `%{}`;
  - unclosed `%{` error text.

Validation:

- `cargo fmt --all -- --check`
- `cargo test -p sase_core fanout_planner`
- `cargo test -p sase_core agent_launch`

## Phase 2: Python Fan-Out Integration

Repo: `sase` workspace 10. Depends on Phase 1 and a rebuilt editable Rust extension (`just rust-install` from the SASE
repo if needed).

Wire the new core grammar through Python wrappers and quick predicates.

Work items:

- Update `src/sase/xprompt/_directive_alt.py`:
  - docstrings mention `%{...}` as the shorthand;
  - `_ALT_DIRECTIVE_RE` and `has_alt_directive()` detect `%{`;
  - alt-inner-region logic handles brace spans as well as paren spans, so model rewrite does not double-collect nested
    models.
- Update tests:
  - add `%{}` cases to `tests/test_directives_split_alternatives.py`;
  - add `%{}` quick-detection and fenced/disabled-region cases to `tests/test_directives_has_helpers.py`;
  - keep representative `%(...)` compatibility tests so the transition is intentional.
- Update any code comments in launch paths that currently say only `%alt/%(`.

Validation:

- `just install` if this workspace has not been installed yet.
- `just rust-install` after the core changes are present.
- `pytest tests/test_directives_split_alternatives.py tests/test_directives_has_helpers.py`

## Phase 3: ACE Prompt Editing Behavior

Repo: `sase` workspace 10.

Implement prompt input typing/deleting behavior with small pure helper functions and Textual tests.

Work items:

- Add a focused helper module, for example `src/sase/ace/tui/widgets/_alt_syntax_editing.py`, that can:
  - identify whether a cursor offset is inside an active `%{...}` span;
  - identify directive-valid `%{` openings;
  - plan the `%{}` auto-pair edit;
  - plan paired deletion of `{}` when the `{` directly left of `}` is removed;
  - plan `|` separator insertion inside `%{}`.
- `|` insertion behavior:
  - only inside a live `%{...}` span;
  - normalize to exactly one space before and after the inserted separator;
  - keep the cursor after the trailing space and before `}`;
  - normalize simple comma spacing in the current branch so the example `%{foo ,bar, and baz|` lands as
    `%{foo, bar, and baz | }`.
- Integrate the helper in `PromptTextAreaKeyHandlingMixin._on_key()` before the default TextArea insertion path.
- Integrate paired deletion in `PromptTextAreaActionsMixin.action_delete_left()` and `action_delete_right()`.
- Clear/refresh transient completion and xprompt hint state consistently with existing Jinja auto-pair behavior.
- Do not add synchronous I/O or subprocess work on the Textual event loop. All logic must be in-memory string scanning
  and bounded similarly to the existing Jinja overlay.
- Add tests, likely in a new `tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py`:
  - typing `%` then `{` yields `%{}` with cursor between braces;
  - backspace from `%{|}` leaves `%` and removes `}`;
  - delete-right on `%|{}` removes both braces;
  - typing `|` inside `%{foo}` yields `%{foo | }`;
  - acceptance example `%{foo ,bar, and baz|` yields `%{foo, bar, and baz | }`;
  - no behavior outside `%{}` or with selections.

Validation:

- `pytest tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py`
- `pytest tests/ace/tui/widgets/test_directive_completion.py`

## Phase 4: ACE Prompt Syntax Highlighting

Repo: `sase` workspace 10.

Add visual treatment for `%{...}` in the prompt input widget.

Work items:

- Extend the current overlay approach rather than adding a separate highlighter that fights TextArea themes.
- Add spans for:
  - `%{` opener and `}` closer;
  - top-level `|` separators;
  - optional branch names before top-level `=`;
  - unmatched opener/closer as warning/error spans.
- Keep the same size guard pattern as `_jinja_highlight.py` (`_MAX_OVERLAY_BYTES`, `_MAX_OVERLAY_LINES`) so prompt
  typing stays responsive.
- Register theme styles using the current app theme, similar to the existing Jinja styles.
- Add tests proving alt highlighting coexists with Jinja and search overlays.

Validation:

- `pytest tests/ace/tui/widgets/test_prompt_alt_syntax_highlight.py`
- `pytest tests/ace/tui/widgets/test_prompt_search_highlight.py`
- If visual snapshots are affected, run `just test-visual` and inspect diffs before accepting any updates.

## Phase 5: LSP And Neovim Highlighting

Repos: `../sase-core` and `../sase-nvim`.

Make Neovim understand and display `%{...}` well.

Work items in `sase-core`:

- Update editor directive metadata so new user-facing surfaces describe `%{...}` as the alt shorthand and stop
  advertising `%(...)`.
- Keep old `canonical_directive_name("(") -> alt` only for compatibility, not for display.
- Change the xprompt LSP directive snippet for `alt` from `%(${1:variant})$0` to a `%{...}` snippet.
- If practical in the existing LSP, add diagnostics for malformed `%{...}` spans; otherwise keep diagnostics out of this
  phase and rely on parser errors at launch.

Work items in `sase-nvim`:

- Add a Lua highlighting module, e.g. `lua/sase/alt_highlight.lua`, rather than introducing tree-sitter from scratch.
- Attach it to the same prompt-oriented buffers that `sase.lsp` supports: `markdown` prompt files, `gitcommit`, `sase`,
  and `sase_prompt`, respecting `allow_all_markdown`.
- Use namespace extmarks or match groups to highlight `%{`, `}`, top-level `|`, and named branch prefixes.
- Debounce buffer rescans and cap scanned content for large buffers.
- Define stable highlight groups with default links, e.g. `SaseAltDelimiter`, `SaseAltSeparator`, `SaseAltBranchName`,
  `SaseAltError`.
- Add headless Neovim tests for attach eligibility and highlight span placement.

Validation:

- In `../sase-core`: `cargo test -p sase_xprompt_lsp directive_snippet` or the relevant server test subset.
- In `../sase-nvim`: headless Lua tests matching the repo’s existing style, e.g.
  `nvim --headless -u NONE -c "set rtp+=." -l tests/alt_highlight.lua`.
- Re-run `tests/lsp_snippet_smoke.lua` after the LSP snippet change.

## Phase 6: Neovim Editing Behavior

Repo: `../sase-nvim` workspace 10. Depends on Phase 5 only for buffer eligibility helpers, not for parser support.

Implement `%{}` pairing, paired deletion, and `|` normalization in Neovim.

Work items:

- Add a Lua editing module, e.g. `lua/sase/alt_edit.lua`.
- Register buffer-local behavior from `require("sase").setup()` with a default-on option such as
  `alt_editing.enabled = true`.
- Use `InsertCharPre` for:
  - `{` after `%`: insert `{}` and move cursor between braces;
  - `|` inside `%{}`: normalize to padded separator and keep cursor before `}`.
- Add buffer-local insert-mode handling for backspace/delete where needed so deleting the `{` in `%{}` also removes the
  paired `}`.
- Reuse the same prompt-buffer eligibility rules as the LSP/highlighter so ordinary Markdown is not changed unless
  `allow_all_markdown` is enabled.
- Ensure the existing `#@` picker trigger still works.
- Add headless tests for:
  - `%{}` auto-pair;
  - paired delete;
  - `|` spacing and the explicit `%{foo ,bar, and baz|` acceptance case;
  - no edits outside supported buffers.

Validation:

- `nvim --headless -u NONE -c "set rtp+=." -l tests/alt_edit.lua`
- `nvim --headless -u NONE -c "set rtp+=." -l tests/lsp_config.lua`
- A short manual smoke in an eligible prompt buffer.

## Phase 7: Documentation, Cleanup, And Cross-Repo Verification

Repos: `sase`, `../sase-core`, `../sase-nvim`.

Finish the migration and verify the full stack.

Work items:

- Update docs:
  - `docs/xprompt.md`: directive table, examples, alt directive section, Cartesian product examples, named branch
    examples.
  - `docs/ace.md`: prompt input editing/highlighting behavior.
  - `../sase-nvim/README.md`: `%{}` highlighting and editing behavior.
  - Update README/blog references only if they are current user-facing docs, not historical posts unless Bryan wants
    historical edits.
- Update completion descriptions/hints in both Python and Rust so they name `%{...}`.
- Consider a small migration note: `%(...)` remains accepted for now but `%{...}` is the preferred shorthand.
- Run targeted tests from prior phases, then the broad gates:
  - in `../sase-core`: `cargo fmt --all -- --check`, `cargo test --workspace`;
  - in `sase`: `just install`, `just rust-install`, then `just check`;
  - in `../sase-nvim`: all available headless Lua smoke tests.

Acceptance criteria:

- `%{A | B}` launches the same two variants as `%alt(A,B)`.
- `%{name=A | other=B}` preserves named alt ids and generated child suffix behavior.
- `%{A}` still produces with/without variants.
- `%{A | %model:opus}` composes correctly with model fan-out and naming.
- `%{foo, bar | baz}` treats the comma as branch text, not a separator.
- ACE prompt input and Neovim both auto-pair `%{}`, paired-delete `{}`, and normalize `|` inside `%{}`.
- ACE prompt input and Neovim both visibly distinguish alt delimiters and separators.
- New snippets/completion/docs emit `%{...}`, not `%(...)`.
- Existing `%(...)` prompts still parse during this migration unless a later phase explicitly removes compatibility.
