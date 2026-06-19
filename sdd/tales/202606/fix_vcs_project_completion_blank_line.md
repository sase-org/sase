---
create_time: 2026-06-19 14:31:53
status: done
prompt: sdd/prompts/202606/fix_vcs_project_completion_blank_line.md
---
# Plan: Fix blank line above expanded VCS tag in `+` project completion (LSP)

## Problem

The `+` project-completion feature (epic bead `sase-4z`) inserts a stray **blank line above** the expanded VCS xprompt
workflow tag when the `+` trigger is used at the **start of a line** in Neovim (via the Rust `sase-xprompt-lsp`).

Reproduction (empty prompt buffer in Neovim):

```
+s<enter>
```

Expected expansion:

```
#gh:sase␣
```

Actual expansion:

```

#gh:sase␣
```

(`␣` = trailing space.) The TUI (`sase ace`) does **not** show the bug for the simple `+s` case, because the TUI passes
the prompt text with no trailing newline.

## Root cause (diagnosed + empirically confirmed)

Two facts combine:

1. **Neovim sends the document with a trailing newline.** `vim.lsp.util.buf_get_full_text` appends a line ending when
   the buffer's `'eol'` option is set (the default for normal files). So a buffer whose only line is `+s` is sent to the
   LSP as the document text `"+s\n"`, not `"+s"`. (The sase-nvim plugin uses Neovim's native `vim.lsp.completion`; it
   adds no custom edit handling — `lua/sase/lsp.lua`.)

2. **The canonical prepend-offset helper skips leading whitespace _including newlines_.** The expansion algorithm
   (`apply_vcs_project_selection`, mirrored in Python and Rust) removes the `+query` trigger token, then — when there is
   no existing VCS tag — inserts the new tag at `find_vcs_workflow_tag_prepend_offset(base)`. That helper is:
   - Python: `src/sase/xprompt/_parsing_vcs_tags.py::find_vcs_workflow_tag_prepend_offset` uses `re.match(r"\s*", body)`
     to skip leading whitespace.
   - Rust: `../sase-core/crates/sase_core/src/editor/completion.rs::vcs_prepend_offset` uses
     `body.len() - body.trim_start().len()`.

   `\s` / `trim_start()` both include `\n`/`\r`. So when the trigger is at the start of a line and the trigger removal
   leaves `base` beginning with the line's terminating newline, the helper **skips past that newline** and inserts the
   tag on the line _below_, leaving a blank line above.

### Trace for `+s<enter>` (document `"+s\n"`, cursor after `s`)

- Trigger token `+s` = span `[0, 2)`. After trigger removal, `base = "\n"`.
- `find_vcs_workflow_tag_prepend_offset("\n")` → `1` (the leading `\n` is skipped).
- Result = `base[:1] + "#gh:sase " + base[1:]` = `"\n" + "#gh:sase " + ""` = `"\n#gh:sase "` ← blank line above.

Confirmed by running the real Python helpers:

```
prompt='+s'            -> '#gh:sase '           # OK (no trailing newline; TUI case)
prompt='+s\n'          -> '\n#gh:sase '         # BUG (Neovim case)
prompt='+s\nmore text' -> '\n#gh:sase more text'# BUG (start-of-line, multiline)
prompt='Line one\n+'   -> '#gh:sase Line one\n' # OK (base='Line one\n', offset 0)
off('\n')=1   off('\nmore')=1   off('  Body')=2   off('Line one\n')=0
```

### Why existing tests miss it

- The Python and Rust golden-vector tables (`tests/test_xprompt_vcs_project_completion.py::_GOLDEN_VECTORS`,
  `completion.rs::vcs_project_golden_vectors`) only have BOF cases with **no trailing newline** (`+‸`, `+sa‸`) and the
  one line-start case (`Line one\n+‸`) has non-whitespace content before the newline, so its `base` starts at offset 0.
- The Neovim smoke test (`sase-nvim/tests/lsp_vcs_project_smoke.lua`) only exercises **end-of-line** triggers and
  applies the edits via `vim.lsp.util.apply_text_edits` directly; none of its cases leave `base` starting with
  whitespace.

## Fix

Make the prepend-offset helper skip only **horizontal** whitespace (spaces/tabs), never line breaks. A VCS workflow tag
is a line-level prefix that belongs at the very start of the prompt (after a leading YAML frontmatter block and leading
`%directive` tokens, per the existing contract); it must never be pushed onto a lower line past a blank line.

Apply the identical change on **both** sides of the parity contract (the feature deliberately mirrors the transform in
Python and Rust; see the `sase-4z` plan and `memory/rust_core_backend_boundary.md`):

- **Python** — `src/sase/xprompt/_parsing_vcs_tags.py::find_vcs_workflow_tag_prepend_offset`: change
  `re.match(r"\s*", body)` to match horizontal whitespace only, e.g. `re.match(r"[^\S\r\n]*", body)`.

- **Rust** — `../sase-core/crates/sase_core/src/editor/completion.rs::vcs_prepend_offset` (open the sibling with
  `sase workspace open -p sase-core 12`): replace `body.trim_start()`-based length with a count of the leading run of
  whitespace characters that are not `\n`/`\r` (mirroring `[^\S\r\n]*`).

This is the minimal change that targets exactly the defect. Verified against the full golden table + bug cases: skipping
horizontal-only whitespace fixes `'\n'`, `'\nmore text'` (→ `'#gh:sase \n'`, `'#gh:sase \nmore text'`) while leaving all
nine existing golden vectors and the two existing prepend-offset unit tests unchanged (their leading whitespace is
spaces, which are still skipped):

- `test_prepend_offset_preserves_frontmatter_directives` (`tests/test_xprompt_vcs_tag_parsing.py`)
- `test_prepend_inserts_after_frontmatter_whitespace_and_directives`
  (`tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py`)

### Bonus / consistency

`find_vcs_workflow_tag_prepend_offset` is also used by TUI VCS-tag MRU cycling
(`src/sase/ace/tui/widgets/_vcs_mru_cycling.py`), which has the same latent blank-line bug for a prompt that begins with
a newline. The shared fix corrects both surfaces consistently; no separate change needed there.

### Scope note (deliberately not changed)

The `%directive` prefix regex (`_DIRECTIVE_PREFIX_RE = ^(?:%\S+[\s]+)+`) also matches newlines in its inter-token
whitespace, but it is not implicated in the reported bug and is exercised by golden vector #9; it is left untouched to
keep the change surgical. Note for the record only.

## Tests

Add regression coverage that pins the start-of-line-with-trailing-content behavior on every layer so the parity contract
stays honest:

1. **Python golden vectors** (`tests/test_xprompt_vcs_project_completion.py::_GOLDEN_VECTORS`): add
   - `"+s‸\n"` → `"#gh:sase \n"` (the exact reported bug: BOF `+` with a trailing newline)
   - `"+s‸\nmore text"` → `"#gh:sase \nmore text"` (start-of-line, multiline)

2. **Rust golden vectors** (`completion.rs::vcs_project_golden_vectors`): add the byte-identical cases (asserts both the
   canonical transform and the applied byte-edits, including the trigger-at-prepend-site merge path).

3. **Direct prepend-offset unit tests** (Python `tests/test_xprompt_vcs_tag_parsing.py`, Rust `completion.rs`): assert
   `find_vcs_workflow_tag_prepend_offset` / `vcs_prepend_offset` return `0` for `"\n"`, `"\nmore"`, and continue to skip
   leading spaces/tabs (`"  Body"` → `2`).

4. **Neovim smoke test** (`sase-nvim/tests/lsp_vcs_project_smoke.lua`, via `sase workspace open -p sase-nvim 12`): add a
   start-of-line assertion driven through a **real attached buffer** (which carries the trailing newline) — e.g. a `+`
   on an otherwise-empty first line expands to `#gh:sase ` with no blank line above. This is the layer that actually
   reproduces the Neovim document shape, so it is the most important regression guard.

5. Keep the historical plan's golden table in sync (`~/.sase/plans/202606/vcs_project_plus_completion.md`) is optional
   (outside the repo); the repo-side tables are the live contract.

## Verification

- `just install` then `just check` in the primary repo (Python lint + mypy + tests, incl. the new golden vectors).
- In `../sase-core`: `cargo test -p sase_core` (and `-p sase_xprompt_lsp`) for the Rust golden vectors + offset tests.
- In `../sase-nvim`: run the LSP smoke test (`tests/lsp_vcs_project_smoke.lua`) headless.
- Manual end-to-end check in Neovim: empty prompt buffer, type `+s<enter>`, confirm the result is `#gh:sase ` with no
  leading blank line; repeat with the cursor on a non-empty first line and with an existing `#git:foo` tag to confirm
  the replace path is unaffected.

## Files to change

- `src/sase/xprompt/_parsing_vcs_tags.py` (helper fix)
- `../sase-core/crates/sase_core/src/editor/completion.rs` (helper fix + Rust golden vectors / offset tests)
- `tests/test_xprompt_vcs_project_completion.py` (Python golden vectors)
- `tests/test_xprompt_vcs_tag_parsing.py` (Python offset unit tests)
- `../sase-nvim/tests/lsp_vcs_project_smoke.lua` (Neovim start-of-line regression)

## Risks

- **Parity drift** between Python and Rust transforms — mitigated by making the identical change on both sides and
  extending the shared golden table on both.
- **Behavior change for prompts that begin with a blank line** (the helper now keeps the tag at the top instead of
  pushing it below the blank line) — this is the _desired_ correction and matches the stated "prepend to the very
  beginning" contract; no golden vector or existing test depends on the old behavior.
