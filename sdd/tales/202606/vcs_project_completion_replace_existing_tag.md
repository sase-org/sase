---
create_time: 2026-06-21 10:19:57
status: done
prompt: sdd/prompts/202606/vcs_project_completion_replace_existing_tag.md
---
# Fix `#+` Project Completion After Existing VCS Tag

## Problem

Using VCS project completion immediately after an existing VCS xprompt workflow tag, for example:

```text
#gh:sase #+
```

and selecting another project produces two tags instead of replacing the existing one:

```text
#gh:sase #git:foobar
```

The same behavior is reported in both the ACE prompt input widget and Neovim.

## Diagnosis

The failure is in the shared VCS project completion expansion contract, not in catalog selection.

The Python path is:

- `src/sase/xprompt/vcs_project_completion.py`
  - `find_vcs_project_trigger()` correctly detects the trailing `#+`.
  - `apply_vcs_project_selection()` strips the trigger, then delegates existing-tag replacement to
    `_parsing.replace_vcs_workflow_tags()`.
- `src/sase/xprompt/_parsing_vcs_tags.py`
  - `_get_vcs_replace_pattern()` only matches line-start VCS workflow tags when the tag is followed by `\s`.

For `#gh:sase #+`, stripping `#+` also removes the orphan space before it, leaving:

```text
#gh:sase
```

That is a valid existing VCS workflow tag, but it is at EOF with no trailing whitespace. The replacement regex does not
match it, so `replace_vcs_workflow_tags()` takes its no-existing-tag branch and prepends the selected tag. That yields
the bad doubled-tag output.

The Rust/nvim path mirrors the same assumption in
`../../sase-core/sase-core_14/crates/sase_core/src/editor/completion.rs`:

- `vcs_replace_regex()` also requires trailing whitespace.
- `apply_vcs_project_selection()` and `vcs_project_byte_edits()` therefore make the same prepend-vs-replace decision for
  EOF tags.
- The LSP converts those byte edits into primary `textEdit` plus `additionalTextEdits`, so fixing the Rust regex and
  tests should fix Neovim without Lua-side changes.

## Implementation Plan

1. Add failing coverage for the exact edge case in the Python repo.
   - Extend the golden vectors in `tests/test_xprompt_vcs_project_completion.py` with `#gh:sase #+` and a query variant
     such as `#gh:sase #+foo`, expecting the selected tag to replace the old one.
   - Extend the ACE prompt widget representative accept tests in `tests/ace/tui/widgets/test_vcs_project_completion.py`
     with the same shape.
   - Add or adjust lower-level VCS replacement coverage in `tests/test_xprompt_vcs_tag_replacement.py` for a tag at EOF,
     so the root behavior is pinned outside the project-completion wrapper.

2. Fix the Python replacement pattern.
   - Update `_get_vcs_replace_pattern()` in `src/sase/xprompt/_parsing_vcs_tags.py` so a line-start VCS workflow tag is
     replaceable when it is followed by either whitespace or EOF.
   - Preserve the current replacement behavior of emitting exactly one trailing space after the selected display tag.
   - Keep group 1 as the directive prefix capture so existing `%directive #gh:...` replacement behavior remains
     unchanged.

3. Add matching Rust coverage in `sase-core`.
   - In `../../sase-core/sase-core_14/crates/sase_core/src/editor/completion.rs`, add the EOF-tag cases to the
     `vcs_project_golden_vectors()` table.
   - Include the same case in `vcs_project_edits_never_overlap()` because the LSP representation will use adjacent
     primary/additional edits: replace old tag, delete trailing ` #+`.
   - Add an LSP server-level test in `../../sase-core/sase-core_14/crates/sase_xprompt_lsp/src/server.rs` for completing
     `#git:foo #+`, asserting the primary edit deletes ` #+` and the additional edit replaces the existing `#git:foo`
     range with `#gh:sase `.

4. Fix the Rust replacement pattern.
   - Update `vcs_replace_regex()` in `../../sase-core/sase-core_14/crates/sase_core/src/editor/completion.rs` to match
     either whitespace or EOF after a VCS workflow tag.
   - Confirm the edit splitting still produces non-overlapping LSP edits for the EOF-tag case.

5. Verify parity and regressions.
   - Run the focused Python tests:
     - `pytest tests/test_xprompt_vcs_project_completion.py tests/test_xprompt_vcs_tag_replacement.py tests/ace/tui/widgets/test_vcs_project_completion.py`
   - Run focused Rust tests in `sase-core_14`:
     - `cargo test -p sase_core vcs_project`
     - `cargo test -p sase_xprompt_lsp vcs_project`
   - If focused tests pass, run formatting/lint checks that are cheap and locally relevant:
     - Python formatting/lint only if touched files require it by repo conventions.
     - `cargo fmt --all --check` for `sase-core_14` after Rust edits.

## Risks and Notes

- The regex currently consumes trailing whitespace as part of the match. The fix should add EOF as an alternate boundary
  without changing the newline/space behavior for existing cases.
- This changes generic `replace_vcs_workflow_tags()` behavior for a prompt that consists only of a VCS tag. That is
  intentional and aligns it with “replace any existing leading VCS tag.”
- Neovim is expected to need only `sase-core` changes because the Lua plugin consumes LSP completion edits; no Lua-side
  replacement logic appeared in the inspected paths.
