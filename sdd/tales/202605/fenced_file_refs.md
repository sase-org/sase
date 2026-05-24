---
create_time: 2026-05-24 11:49:41
status: done
prompt: sdd/prompts/202605/fenced_file_refs.md
---
# Plan: Ignore @ File References Inside Fenced Blocks

## Context

The failing workflow transcript at `/home/bryan/.sase/workflows/202605/sase_ace-run-260524_114348.txt` shows
`preprocess_prompt_late()` aborting in `sase.gemini_wrapper.file_references.process_file_references()`. The prompt
contains a `sase ace` snapshot inside an outer triple-backtick block. That snapshot itself displays another prompt
containing a line with literal triple backticks and agent labels like `@a9q.cdx`, `@a9y.f1`, and `@a9f.w1`.

The file-reference parser correctly skips fenced blocks when it receives protected text, but the shared fenced-block
protector currently uses a loose regex:

```python
r"(`{3,})[^\n]*\n[\s\S]*?\1"
```

That regex treats any later matching
```sequence as the closing fence, including the triple backticks shown inside the boxed TUI snapshot. As a result, only the first part of the snapshot is protected and the remaining agent labels are exposed to`@path`
validation. Since dotted agent names look file-shaped, the validator reports missing and duplicate file references.

## Approach

1. Replace the loose fenced-block regex in `src/sase/xprompt/_fenced_blocks.py` with a small Markdown-aware scanner.
   - Recognize opening fences only at the start of a line, allowing up to three leading spaces.
   - Support backtick fences and tilde fences.
   - Require closing fences to be line fences too: same fence character, length at least the opener length, up to three
     leading spaces, and only trailing whitespace.
   - Treat an unclosed fence as protecting through end-of-input.

2. Keep the public helper contract unchanged.
   - `protect_fenced_blocks(text, blocks)` still appends original block text and replaces each protected region with the
     existing null-byte placeholder.
   - `fenced_block_ranges(text)` still returns `(start, end)` byte-offset style string index ranges.
   - `unprotect_fenced_blocks()` remains unchanged unless tests expose a placeholder interaction.

3. Add focused regression coverage.
   - Unit coverage that `protect_fenced_blocks()` protects an entire outer fence when the block contains a
     displayed/boxed ` ``` ` sequence.
   - Range coverage that `fenced_block_ranges()` returns the full outer block range for the same shape.
   - Late-preprocessing coverage that `@a9q.cdx` style labels after a displayed inner fence do not reach file-reference
     validation when they are still inside the real outer fenced block.
   - Preserve existing behavior for ordinary fenced blocks and text outside fences.

4. Verify narrowly first, then with the repo check.
   - Run the relevant tests for fenced blocks, xprompt references, preprocessing, and file reference parsing.
   - Because implementation files will change, run `just check` before final response, after `just install` if the
     workspace needs it.

## Expected Outcome

Prompts may include screenshots, terminal captures, or TUI snapshots inside Markdown fenced blocks without accidental
`@path` validation. Real `@path` references outside fenced blocks continue to be validated and processed exactly as
before.
