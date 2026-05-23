---
create_time: 2026-05-23 15:44:02
status: done
prompt: sdd/prompts/202605/xprompt_space_encoding.md
---
# Plan: XPrompt Space Encoding for Path Values

## Problem

An agent launched from ACE on macOS failed before the runtime started:

`Python step 'setup' output validation failed: At workspace_dir: expected path (no spaces), got '/Users/bbugyi/Library/Application Support/sase/wor...'`

The `#gh:sase ... #plan` prompt expands an embedded VCS workflow. Its `setup` step emits real filesystem paths such as
`workspace_dir`, `project_file`, and `primary_workspace_dir`. Managed workspace roots on macOS can legitimately live
under `~/Library/Application Support/...`, so the current `path` semantic type is too strict when it rejects spaces.

At the same time, xprompt reference arguments should remain space-free at the prompt syntax layer. A user should not
need literal spaces in a `#name:arg` token. When a value needs a space, it should use an encoded/substitution form such
as `Application+Support`, and SASE should decode that to `Application Support` internally before rendering templates or
validating typed inputs.

## Root Cause

Two contracts are currently conflated:

1. XPrompt reference syntax is token-oriented and whitespace-delimited, so bare colon arguments cannot contain literal
   spaces.
2. The semantic `path` type is used for internal workflow data and real filesystem paths, where spaces are valid as long
   as the value remains a single line.

The failed launch hit the second contract: `git_setup.py` printed a valid path, `parse_bash_output()` parsed it, and
`validate_against_schema()` rejected it because `OutputType.PATH` currently means "no whitespace" rather than
"single-line path value".

## Implementation Approach

1. Add a single xprompt argument decoding helper.
   - Put it near the existing argument parser in `src/sase/xprompt/_parsing_args.py`.
   - Decode plus-style space substitution in parsed argument values, using a narrowly documented helper such as
     `decode_xprompt_arg_value()`.
   - Apply it recursively through a `decode_xprompt_args(positional, named)` helper so every caller gets the same
     behavior.
   - Keep `#name+` as the existing boolean shorthand; only decode values after the parser has already identified an
     argument payload.

2. Route all xprompt/workflow argument parsers through that helper.
   - `parse_args()` and `parse_workflow_reference()` should return decoded values.
   - Callers that manually split colon comma args should use the helper instead of raw `colon_arg.split(",")`.
   - Cover normal xprompt expansion, embedded workflow expansion, standalone workflow flattening, and multi-agent
     xprompt expansion.
   - Leave the lexical regex whitespace boundaries intact so literal whitespace still terminates bare colon tokens.

3. Correct the semantic `path` contract.
   - Change `InputArg.validate_and_convert(..., InputType.PATH)` to reject newlines, not spaces.
   - Change `_validate_semantic_type(..., "path", ...)` to reject newlines, not spaces.
   - Update path field constraint hints to say "single-line path" or equivalent.
   - Keep `word` unchanged: it still rejects all whitespace.
   - Keep `line` unchanged: it still rejects newlines.

4. Add focused regression coverage.
   - XPrompt argument parsing decodes `Application+Support` to `Application Support` for colon and parenthesized
     syntaxes.
   - `#name+` still parses as `true`.
   - `path` input validation accepts a path containing spaces after decoding and rejects a newline.
   - Output schema validation accepts a macOS `Application Support` workspace path and rejects a newline.
   - Existing tests that assert "path with space fails" should be updated to the new newline-only rule.

5. Verify.
   - Run targeted xprompt parser/model/output tests first.
   - Run `just install` if needed, then `just check` per repo instructions.
   - If `just check` fails due unrelated environment state, capture the exact failure and still report targeted test
     results.

## Expected Outcome

The macOS ACE launch path will no longer fail when setup emits a workspace under `Application Support`. User-facing
xprompt references remain whitespace-delimited, while encoded values such as `Application+Support` are decoded before
typed input validation and template rendering. This preserves the no-literal-space prompt syntax without rejecting valid
single-line filesystem paths internally.
