---
create_time: 2026-04-25 19:23:11
status: done
prompt: sdd/prompts/202604/skip_bare_word_at_refs.md
---
# Plan: Skip validation of bare-word `@<word>` references

## Problem

An agent on another machine failed with a validation error because `@IgnoreForDiff` appeared in the prompt and no
`IgnoreForDiff` file existed in CWD. `@IgnoreForDiff` is not a file reference at all — it's an inline marker /
placeholder. The current `@`- reference parser treats any `@<token>` as a candidate file path, and aborts the workflow
(`sys.exit(1)`) when the path can't be resolved.

We want validation to be conservative: only treat a token as a file reference when its shape genuinely looks like a path
or filename. Bare identifiers (no `/`, no `.`) should be left alone — passed through to the prompt verbatim, like URLs
and domain names already are.

## Current behavior

- Parser/validator: `src/sase/gemini_wrapper/file_references.py`
  - `_FILE_REF_PATTERN` (line 25) captures `@<non-delimiter chars>`.
  - `_parse_file_refs()` (line 56) categorizes each match. The bare-word case falls through to line 114
    (`os.path.exists("IgnoreForDiff")` is `False`) and gets appended to `missing_files`.
  - `_print_validation_errors()` (line 120) prints; `validate_file_references()` (line 169) calls `sys.exit(1)`.
  - Existing skips: `http*` URLs (line 79); TLD-suffixed tokens with no `/` (lines 84–87).
- Caller: `preprocess_prompt_late()` in `src/sase/llm_provider/preprocessing.py` (lines ~132–138, 162–165).
- Tests: `tests/test_file_references_parsing.py`, `tests/test_file_references_substitution.py`.

## Proposed rule

In `_parse_file_refs()`, if the captured token has neither a `/` nor a `.`, skip it (do not track in `seen_paths`, do
not add to any error bucket). The token stays in the prompt verbatim, just like `@google.com` and `@http://example.com`
already do.

### Why this rule

A genuine file reference is one of:

- An extension-bearing name: `foo.md`, `notes.txt`
- A relative path with a separator: `docs/foo`, `src/sase/...`
- An absolute path: `/x/y`
- A tilde path: `~/x`
- A parent path: `../x`

All of these contain `/` or `.`. A bare CamelCase or snake_case identifier (no dot, no slash) is overwhelmingly
something the user wrote literally — a placeholder, a marker, a code identifier — not a file. The TLD skip already
established the same shape-based heuristic; we're generalizing it.

### Trade-offs considered

- **False negatives** (a real file gets silently skipped): Possible only for extensionless files in CWD with no path
  prefix (e.g. `@Makefile`, `@LICENSE`, `@README`). Workarounds: write `@./Makefile` or `@Makefile.` won't work — the
  user would need `@./Makefile`. This is an acceptable cost: such references are rare, and the current behavior of
  hard-aborting on bare words is worse than silently passing them through. If this turns out to bite us, we can revisit
  with a small allowlist (`Makefile`, `LICENSE`, `README`, `Dockerfile`, ...).
- **False positives** (a marker accidentally has a dot): A user writing `@v1.2` or `@feature.flag` would still trigger
  validation. That seems fine — dots are a strong file-shaped signal, and the user can quote/escape if needed.

## Plan steps

1. **Edit `src/sase/gemini_wrapper/file_references.py`**
   - In `_parse_file_refs()`, after the `http` skip (line 79), before the TLD skip (line 84), add:
     ```python
     # Skip bare-word tokens with no path separator and no extension —
     # these are almost always literal markers (e.g. @IgnoreForDiff), not files.
     if "/" not in file_path and "." not in file_path:
         continue
     ```
   - Update the comment block at lines 16–24 to mention the bare-identifier skip alongside the existing URL/domain
     notes.

2. **Add tests in `tests/test_file_references_parsing.py`**
   - `_parse_file_refs("See @IgnoreForDiff in the prompt")` → `seen_paths == {}`, `missing_files == []`.
   - `_parse_file_refs("Note @SomeMarker mid-sentence")` → same.
   - `validate_file_references("See @IgnoreForDiff")` does not raise.
   - Regression: `@foo.md` (no slash, has dot) still validates and errors when missing — confirms the skip is gated on
     _both_ characters being absent.
   - Regression: `@docs/foo` (has slash, no dot) still validates and errors when missing.
   - Regression: `@google.com` still skipped (existing behavior preserved).

3. **Run `just check`** from the workspace.

## Out of scope

- `process_file_references()` substitution: no direct change. The bare-word case simply never enters
  `absolute_paths`/`parent_dir_paths`, so it's left as literal `@IgnoreForDiff` text in the prompt — exactly the desired
  outcome.
- No config flag. The rule is simple and safe; YAGNI.
- No change to `preprocessing.py`. The parser-level fix is sufficient since validation flows through
  `_parse_file_refs()` for both `validate_file_references` and `process_file_references`.
- No allowlist for `Makefile` / `LICENSE` / etc. — defer until a real user hits it.

## Files touched

- `src/sase/gemini_wrapper/file_references.py` (parser + comment)
- `tests/test_file_references_parsing.py` (new tests)
