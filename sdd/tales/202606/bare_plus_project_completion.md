---
create_time: 2026-06-19 16:32:32
status: done
prompt: sdd/prompts/202606/bare_plus_project_completion.md
---
# Plan: Bare Plus Project Completion

## Context

SASE currently supports VCS project completion with `#+query` in two surfaces:

- The ACE prompt input widget uses Python helpers in `src/sase/xprompt/vcs_project_completion.py`, with TUI wiring under
  `src/sase/ace/tui/widgets/`.
- The XPrompt LSP uses the Rust parity implementation in `/home/bryan/projects/github/sase-org/sase-core`, especially
  `crates/sase_core/src/editor/token.rs`, `crates/sase_core/src/editor/completion.rs`, and
  `crates/sase_xprompt_lsp/src/server.rs`.

The existing expansion algorithm is the right one: selecting a project removes the trigger token, prepends or replaces
the leading VCS workflow tag, and is covered by shared Python/Rust golden vectors. The requested change is narrower:
support the same completion using `+` only when that `+` starts at the absolute beginning of the prompt.

## Semantics

1. `+` at prompt offset 0 opens the project completion menu with an empty query.
2. `+query` at prompt offset 0 opens and filters by `query`.
3. `#+query` keeps its existing behavior everywhere it is valid today: beginning of prompt, after whitespace, and after
   a newline.
4. Bare `+` is not a project trigger anywhere except absolute prompt offset 0. In particular, `Fix +`, ` +`, `\n+`, and
   `word+` remain ordinary text and must not open the project menu.
5. Accepting a bare-plus project completion uses the same canonical expansion as `#+`; only the trigger span and query
   prefix length differ.

## Implementation

1. Extend the Python trigger helper.
   - Update `find_vcs_project_trigger()` in `src/sase/xprompt/vcs_project_completion.py` to recognize a token beginning
     with `+` only when the token start is exactly `0`.
   - Keep the returned `VcsProjectTrigger` shape stable (`start`, `end`, `query`) so TUI accept code can keep calling
     `apply_vcs_project_selection()` unchanged.
   - Compute the query after `+` for bare-plus tokens and after `#+` for hash-plus tokens.
   - Refresh docstrings/comments from "`#+query` only" to "`#+query` or BOF `+query`" where they describe trigger
     detection rather than the catalog itself.

2. Reuse the existing TUI wiring.
   - The prompt input already calls `_try_vcs_project_completion()` when `+` is typed and calls the same helper from
     `Ctrl+T`; after the trigger helper changes, both auto-open and explicit completion should work for beginning `+`
     with minimal TUI code churn.
   - Keep catalog warming as-is so the new path does not add synchronous project enumeration on the keypress path.
   - Add only targeted TUI glue if tests show a gap, such as panel query display or active-menu refresh when typing
     after `+`.

3. Extend the Rust LSP parity trigger.
   - Update `vcs_project_trigger_token()` in `crates/sase_core/src/editor/token.rs` to recognize `+query` only when the
     token starts at byte offset `0`, while preserving all existing `#+query` cases.
   - Update `is_vcs_project_trigger_token()` and nearby docs/tests to reflect that `+query` can be a trigger token only
     in the detector's BOF context.
   - In `build_vcs_project_completion_candidates()`, derive the query start from the token spelling (`+` => offset 1,
     `#+` => offset 2) instead of assuming `#+`.

4. Keep LSP client filtering correct.
   - `crates/sase_xprompt_lsp/src/lsp_convert.rs` currently sets `filter_text` to `#+<name>`. For bare-plus completion,
     pass the trigger prefix through the VCS-project response path and use `+<name>` when the user typed `+query`.
   - Keep the existing `+` trigger-character advertisement in the LSP server.
   - The project catalog JSON schema should not change; this is trigger syntax, not catalog data.

5. Avoid memory-file edits.
   - `memory/glossary.md` mentions `#+`, but project instructions require approval before modifying memory files.
   - I will not edit memory files unless separately approved. Non-memory code comments and docs can be updated if they
     are directly stale after the implementation.

## Tests

1. Python foundation tests in `tests/test_xprompt_vcs_project_completion.py`.
   - Add golden vectors for `+‸`, `+sa‸`, and `+sa‸ Fix`.
   - Add trigger positives for `+`, `+sa`, and mid-token cursor behavior like `+abc` with the cursor after `+a`.
   - Add trigger negatives for `Fix +`, ` +`, `\n+`, and embedded plus tokens.
   - Keep existing `#+` vectors unchanged to guard regression.

2. TUI widget tests in `tests/ace/tui/widgets/test_vcs_project_completion.py` and
   `tests/ace/tui/widgets/test_auto_xprompt_completion.py`.
   - Change the current empty-prompt bare-plus expectation from "does not open" to "opens project completion".
   - Add explicit negative coverage for bare `+` after existing text or whitespace.
   - Add accept coverage showing `+` expands to `#gh:sase ` and `+te` filters to the matching project.
   - Add `Ctrl+T` coverage on an existing `+query` token at prompt start.

3. Rust core tests in `crates/sase_core/src/editor/token.rs` and `crates/sase_core/src/editor/completion.rs`.
   - Mirror the Python trigger positives/negatives.
   - Extend the shared golden-vector table with bare-plus cases.
   - Assert candidate filtering uses the correct query for `+sa`.
   - Assert edits remain non-overlapping for the new bare-plus vectors.

4. Rust LSP tests in `crates/sase_xprompt_lsp/src/server.rs` and, if needed, `lsp_convert.rs`.
   - Replace the existing "bare plus does not complete" case with "bare plus at BOF completes".
   - Add a negative case for plus outside BOF.
   - Assert bare-plus completion uses `filter_text = "+sase"` while hash-plus completion still uses
     `filter_text = "#+sase"`.
   - Confirm primary/additional edits produce the same final prompt as the canonical expansion.

## Verification

1. In this Python repo:
   - `pytest tests/test_xprompt_vcs_project_completion.py`
   - `pytest tests/ace/tui/widgets/test_vcs_project_completion.py tests/ace/tui/widgets/test_auto_xprompt_completion.py`

2. In `/home/bryan/projects/github/sase-org/sase-core`:
   - `cargo test -p sase_core editor::token::tests::detects_vcs_project_trigger_tokens`
   - `cargo test -p sase_core editor::completion::tests::vcs_project_golden_vectors`
   - `cargo test -p sase_xprompt_lsp vcs_project`
   - `cargo fmt --all -- --check`

3. Manual smoke, if the automated tests pass:
   - In ACE prompt input, type `+`, select a project, and confirm the project tag is inserted exactly as with `#+`.
   - In Neovim/XPrompt LSP, request completion after `+` at column 1 and confirm project entries appear; request
     completion after `Fix +` and confirm they do not.

## Risks

- LSP client-side filtering can silently hide all project candidates if `filter_text` remains `#+name` while the user
  typed `+query`; that is why the Rust LSP response path needs explicit bare-plus coverage.
- The wording "very beginning" should be interpreted strictly as offset 0, not "start of any line" or "after leading
  whitespace"; the tests should lock that down.
- The prompt widget must not perform a cold project-catalog build on the keypress path. The existing warm-cache strategy
  should be preserved.
