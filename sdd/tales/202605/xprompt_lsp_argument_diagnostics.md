---
create_time: 2026-05-08 11:06:00
status: done
prompt: sdd/prompts/202605/xprompt_lsp_argument_diagnostics.md
---
# Plan: XPrompt LSP Argument Diagnostics

## Context

The xprompt LSP server already lives in `../sase-core` and is launched from this Python repo through
`src/sase/integrations/xprompt_lsp.py`. The server publishes push diagnostics from
`crates/sase_xprompt_lsp/src/server.rs` on `didOpen` and `didChange`, and delegates the editor analysis to
`sase_core::editor::diagnostics::analyze_document`.

Current diagnostics cover:

- unknown xprompt references;
- canonical `#` vs `#!` marker mismatches;
- unknown slash skills;
- unknown directives;
- a narrow malformed-argument-form heuristic.

They do not validate xprompt argument contracts. In particular, they do not flag missing required inputs, unknown named
arguments, duplicate/conflicting arguments, invalid typed values, or too many positional arguments. The catalog already
contains enough input metadata for this first version: `XpromptAssistEntry.inputs` exposes input `name`, `type`,
`required`, default display, and position. The Rust catalog loader parses the same `input:` shapes as Python for
markdown frontmatter, workflow YAML, config xprompts, plugin xprompts, built-ins, and project-local xprompts.

This behavior belongs in `../sase-core` per the Rust core boundary: other editors should get the same diagnostics as
Neovim without duplicating parser logic.

## Goals

Add reliable LSP diagnostics for incorrect xprompt argument usage:

- missing required args;
- too many positional args;
- unknown named args;
- duplicated named args;
- the same input provided both positionally and by name;
- type mismatches for `word`, `line`, `text`, `path`, `int`, `float`, and `bool`;
- structurally malformed argument lists where we can confidently identify the xprompt reference.

Keep diagnostics conservative. Avoid red squiggles for incomplete text while the user is still typing unless the form is
already clearly invalid.

## Non-Goals

- Do not reimplement full xprompt expansion or Jinja rendering in the LSP.
- Do not validate whether a `path` exists; Python currently only rejects whitespace for `path`.
- Do not validate arbitrary Jinja variable usage or legacy `{1}` placeholders in this pass.
- Do not change `sase-nvim` unless verification shows the server already publishes diagnostics but the client suppresses
  them. The desired red squiggly UX should come from standard `textDocument/publishDiagnostics`.
- Do not change the Python wrapper except for tests if the launch contract is affected, which is not expected.

## Design

### 1. Add A Real Editor-Side XPrompt Reference Parser

Add a focused parser under `crates/sase_core/src/editor/`, likely as `xprompt_args.rs` or inside `diagnostics.rs` if it
stays small.

The parser should return spans in byte offsets so diagnostics can point at the exact argument/name/value:

- reference marker and name span;
- normalized name, including `ns__foo` to `ns/foo`;
- HITL suffix `!!` / `??` on the name;
- argument syntax kind: none, plus, colon, double-colon text, parenthesized, malformed;
- positional args with value spans;
- named args with name/value spans;
- duplicate named arg spans;
- closing paren presence for parenthesized syntax.

Reuse the existing lexical rules where possible:

- xprompt names and namespaced forms from current completion/diagnostic regexes;
- parenthesis matching behavior equivalent to Python's `find_matching_paren_for_args`;
- comma splitting that respects quotes and `[[...]]` text blocks;
- `name=value` detection that respects quotes and `[[...]]`.

The parser should intentionally skip fenced code blocks and `%xprompts_enabled:false` regions only if there is already a
Rust helper for that. If not, keep this as a follow-up and preserve current behavior. The current analyzer does not yet
protect those regions, so this plan should not expand scope unless tests expose severe false positives.

### 2. Validate Parsed Calls Against Catalog Inputs

Implement an argument validation layer that consumes `ParsedXpromptCall` plus `XpromptAssistEntry`.

Rules:

- `+` counts as one positional bool-like value `"true"`, matching Python's plus syntax.
- `#foo:bar` counts as one positional value.
- `#foo:a,b` maps to positional values split by comma for colon syntax, matching current processor behavior.
- `#foo:: text` should count as one positional text value when parsed confidently.
- Parenthesized args support positional and named args, mixed in source order.
- For each positional arg with index `i`, map to `entry.inputs[i]`; if no input exists, report `too_many_args` on that
  value.
- For each named arg, require a matching `entry.inputs.name`; otherwise report `unknown_arg`.
- If a named arg appears more than once, report `duplicate_arg` on the later occurrence.
- If an input is supplied positionally and by name, report `duplicate_arg` or `conflicting_arg` on the named occurrence.
- After processing, report `missing_required_arg` for every required input not supplied by position or name.
- Treat raw value `"null"` as intentional pass-through and do not type-check it, matching Python
  `validate_and_convert_args`.

Type validation should mirror Python `InputArg.validate_and_convert`:

- `word`: reject any whitespace.
- `line`: reject newline.
- `text`: always valid.
- `path`: reject any whitespace.
- `int`: require Rust `i64` parse.
- `float`: require Rust `f64` parse.
- `bool`: accept `true`, `1`, `yes`, `on`, `false`, `0`, `no`, `off`, case-insensitive.

Severity should be:

- `Error` for missing required args, type mismatch, unknown arg, duplicate/conflicting arg, too many args, and malformed
  closed argument lists.
- `Information` or no diagnostic for incomplete in-progress forms such as `#foo(`, `#foo(arg=`, or `#foo:` where the
  cursor may still be typing. Since diagnostics are document-wide and do not know intent/cursor history, prefer no
  missing-required diagnostic for a reference whose argument list is syntactically open.

### 3. Wire Into Existing Analyzer

Replace or extend `argument_diagnostics()` in `crates/sase_core/src/editor/diagnostics.rs` so it uses the parser and
validator.

Preserve current diagnostics for:

- unknown xprompt;
- canonical marker mismatch;
- unknown slash skill;
- unknown directive.

Avoid duplicate reports. If a reference name is unknown, do not also emit argument contract diagnostics for it.

Diagnostic ranges:

- missing required arg: range the xprompt reference name or the whole call if no better target exists;
- unknown/duplicate/conflicting named arg: range the argument name;
- invalid type: range the argument value;
- too many positional args: range the extra value;
- malformed arg list: range the malformed suffix or opening paren.

Diagnostic codes should be stable strings, for example:

- `missing_required_arg`;
- `too_many_args`;
- `unknown_xprompt_arg`;
- `duplicate_xprompt_arg`;
- `conflicting_xprompt_arg`;
- `invalid_xprompt_arg_type`;
- `malformed_xprompt_argument`.

### 4. Improve Code Actions Where Low-Risk

Keep this optional and scoped after diagnostics are working.

The existing LSP code action `"Insert required named args"` already uses input metadata. It can remain unchanged, but
new diagnostics should make it more discoverable in Neovim. If easy, mark the code action as a quickfix for
`missing_required_arg` ranges and ensure it still inserts `#foo(required=)` over the existing token.

Do not add complex automatic fixes for type mismatches or unknown args in this pass.

## Tests

Add tests primarily in `../sase-core`.

Core analyzer tests in `crates/sase_core/src/editor/diagnostics.rs` or a new parser module:

- no diagnostics for `#foo(path=src/main.rs, count=3, enabled=true)` with matching inputs;
- missing required positional and named args;
- optional args do not trigger missing diagnostics;
- too many positional args for colon and paren syntax;
- unknown named arg;
- duplicate named arg;
- positional plus named conflict for the same input;
- `word`, `line`, `path`, `int`, `float`, and `bool` mismatch cases;
- bool accepts all Python-compatible truthy/falsy spellings;
- text block and quoted comma/equal parsing, e.g. `#foo(text=[[a,b=c]])`;
- namespaced `#ns/foo(...)` and `#ns__foo(...)`;
- HITL suffix `#foo!!(...)`;
- incomplete forms avoid noisy missing-required diagnostics.

LSP/server tests in `crates/sase_xprompt_lsp/src/server.rs` or `tests/jsonrpc_stdio.rs`:

- `diagnostics_for_text("#foo")` returns `missing_required_arg` when fixture catalog says `foo.path` is required.
- `diagnostics_for_text("#foo(path=bad value)")` returns an LSP diagnostic with source `sase-xprompt` and severity
  error.
- JSON-RPC `didOpen` publishes diagnostics for an invalid xprompt call, proving Neovim-compatible push diagnostics are
  on the wire.

Python repo tests are probably unnecessary unless the wrapper contract changes. The Python-side
`tests/main/test_lsp_handler.py` should remain valid.

## Verification

In `../sase-core`:

```bash
cargo test -p sase_core editor::diagnostics
cargo test -p sase_xprompt_lsp
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

In `sase_100`, if any Python files are changed:

```bash
just install
just check
```

Manual Neovim smoke check after implementation:

1. Start the LSP through the existing `sase lsp` wrapper.
2. Open a markdown prompt buffer.
3. Type an xprompt with a known required arg omitted, such as a fixture or local test xprompt.
4. Confirm Neovim shows a diagnostic on the line and `:lua vim.diagnostic.get(0)` includes the expected
   `missing_required_arg` message.
5. Fix the call and confirm diagnostics clear on change.

## Implementation Order

1. Add parser and parser unit tests.
2. Add type validation and contract diagnostics over parsed calls.
3. Replace the current malformed-args heuristic with parser-backed diagnostics.
4. Add LSP-level tests for diagnostic conversion and publish behavior.
5. Run focused tests, then full Rust checks.
6. Only if Python launch behavior was touched, run the Python repo checks.

## Risks And Mitigations

- **False positives while typing:** avoid required-arg diagnostics for syntactically open calls and keep malformed
  checks conservative.
- **Parser drift from Python:** port only the argument grammar needed for diagnostics and add tests for quotes,
  `[[...]]`, colon, plus, HITL, and namespaced forms.
- **Catalog metadata gaps:** diagnostics can only validate xprompts with declared `input:` metadata. For xprompts with
  no inputs, keep current behavior and do not report argument count errors unless the call is structurally malformed.
- **Duplicate diagnostics with unknown refs:** perform argument validation only after resolving the call name to a
  catalog entry.
