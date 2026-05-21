---
create_time: 2026-05-21 19:06:19
status: wip
prompt: sdd/prompts/202605/xprompt_frontmatter_validation.md
---

# XPrompt Frontmatter Validation Plan

## Goal

Expand the xprompt LSP's markdown frontmatter diagnostics from a single invalid-`input.type` lint into a practical
authoring validator for the xprompt fields SASE understands today. The validator should catch mistakes while preserving
runtime tolerance: invalid or odd frontmatter can still load as it does now, but the editor should point authors at the
specific field or scalar that will be ignored, coerced, or fail later.

The implementation should live in `../sase-core/crates/sase_core`, with an LSP smoke test in
`../sase-core/crates/sase_xprompt_lsp`, because diagnostics are shared editor-core behavior.

## Current Shape

- `sase_xprompt_lsp` publishes diagnostics by calling `sase_core::editor_analyze_document()`.
- `editor::diagnostics` already extracts leading markdown YAML frontmatter and validates explicit `input` type values.
- Markdown xprompt loading in `xprompt_catalog.rs` currently recognizes these frontmatter fields:
  - `name`
  - `input`
  - `tags`
  - `description`
  - `skill`
  - `snippet`
  - `keywords` for dynamic-memory markdown files
- Runtime parsing remains intentionally forgiving:
  - unknown input types become `line`
  - malformed frontmatter is treated like absent frontmatter
  - unknown top-level fields are ignored
  - invalid snippet triggers simply do not create snippet entries
- `serde_yaml::Value` does not retain spans, so exact editor ranges need source-text indexing/scanning. Parse errors do
  expose line/column/index through `serde_yaml::Error::location()`.

## Validation Scope

Implement authoring diagnostics for the leading `---` frontmatter block only. Keep the scope tied to SASE xprompt
metadata and avoid linting arbitrary markdown frontmatter outside what the xprompt catalog already consumes.

### YAML and Shape

1. Report malformed YAML as `invalid_xprompt_frontmatter_yaml` with an `Error` diagnostic at the parser location when
   available, otherwise on the frontmatter block.
2. Report non-mapping frontmatter as `invalid_xprompt_frontmatter_shape`.
3. Report likely unsupported top-level xprompt metadata keys as `unknown_xprompt_frontmatter_field`, but only at
   `Information` severity so future/user metadata is not treated as a hard failure. Allow the documented keys `name`,
   `input`, `tags`, `description`, `skill`, `snippet`, and `keywords`.

### `name`

1. If present, `name` must be a non-empty scalar.
2. Warn when an explicit name is not referenceable by the current xprompt grammar: `segment(/segment)*`, where each
   segment starts with an ASCII letter or `_` and continues with ASCII letters, digits, or `_`.
3. Do not require `name`, because file-backed xprompts default to the filename stem and `editor_analyze_document()` does
   not currently receive the document URI/path.

### `input`

Support both SASE input syntaxes:

- Shortform mapping:
  ```yaml
  input:
    target: word
    count:
      type: int
      default: 1
  ```
- Longform sequence:
  ```yaml
  input:
    - name: target
      type: word
      default: docs
  ```

Diagnostics:

1. `input` must be either a mapping or a sequence.
2. Input names must be non-empty scalars.
3. Input names should be valid Jinja/named-argument identifiers (`[A-Za-z_][A-Za-z0-9_]*`); warn rather than error so
   existing unusual templates are not broken.
4. Detect duplicate parsed input names in longform and shortform where source scanning can identify them.
5. Explicit `type` values must be one of `word`, `line`, `text`, `path`, `int`/`integer`, `bool`/`boolean`, or `float`.
6. A missing longform `type` remains valid and means `line`, matching runtime behavior.
7. Validate `default` values against the declared type when possible:
   - `word` and `path`: scalar default must not contain whitespace
   - `line`: scalar default must not contain newlines
   - `int`: scalar default must parse as an integer
   - `float`: scalar default must parse as a float
   - `bool`: scalar default must be one of the accepted bool spellings
   - `text`: any scalar default is valid
   - `null` default is valid and optional
8. Unknown keys inside a longform input item or a nested shortform input mapping should be `Information` severity, not
   an error. Allow `type` and `default` for now.

### `tags`

1. Accept a comma-separated scalar string or a sequence of non-empty scalar tags.
2. Report non-scalar sequence items.
3. Do not reject unknown tag names in the first implementation; the Rust catalog treats tags as strings and users may
   reasonably use custom tags for filtering.

### `description`

1. If present, require a scalar string-compatible value.
2. Warn if it contains a newline, because the documented field is a one-line description.
3. Warn when `skill` is truthy but `description` is missing or empty, since generated skills need useful metadata.

### `skill`

1. Accept `true`, `false`, or a sequence of non-empty provider strings.
2. Warn on scalar strings/maps/numbers, because Rust currently treats them as false while Python-side skill handling
   expects bool-or-list semantics.
3. Warn on an empty provider list.

### `snippet`

1. Accept `true`, `false`, or a string trigger.
2. For string triggers, require the same trigger grammar used by snippet conversion: ASCII alphanumeric or `_`,
   non-empty.
3. Report invalid triggers as `invalid_xprompt_frontmatter_snippet_trigger`; the runtime silently skips these, so this
   is high-value feedback.

### `keywords`

1. Accept a sequence of non-empty scalar keywords.
2. Warn if `keywords` is present but `tags` does not include `memory`, because dynamic memory matching filters by the
   memory tag in the Python runtime while Rust auto-discovery gives `memory/long` entries the tag automatically.
3. Report non-scalar items.
4. Let malformed unquoted `!negative` keywords fall out through the YAML parse diagnostic; valid negative keywords
   should be quoted strings like `"!vendor"`.

## Design

Refactor the current frontmatter lint into a small validation subsystem inside
`crates/sase_core/src/editor/diagnostics.rs` first. If it grows too large during implementation, split it into a private
`editor/frontmatter.rs` module and keep `diagnostics.rs` as the orchestrator.

Use a two-track model:

1. Parse the frontmatter with `serde_yaml::Value` for semantic validation.
2. Build a lightweight source index for frontmatter ranges:
   - top-level key ranges
   - top-level value ranges
   - `input` item name/type/default ranges for the block and flow styles SASE documents
   - fallback ranges for a containing field/item when exact scalar localization is not available

Do not replace runtime catalog parsing in this change. The validator may share constants/predicates with the catalog
where practical, but the runtime's tolerant parsing behavior should stay unchanged.

Use stable diagnostic codes and severities:

- `Error` when the field cannot be parsed as intended or will be coerced to a materially different meaning.
- `Warning` when the field is valid YAML but likely unusable or surprising.
- `Information` for ignored/unknown metadata.

## Implementation Steps

1. Add frontmatter validation types:
   - `FrontmatterDiagnosticBuilder`
   - reusable `FrontmatterSourceIndex`
   - helpers for scalar conversion, type aliases, identifier/name validation, and diagnostic construction.
2. Replace `invalid_frontmatter_input_type_values()` with a structured `validate_frontmatter_value()` pass that returns
   full diagnostics rather than only bad type strings.
3. Add parse-error diagnostics using `serde_yaml::Error::location()` and convert the error's frontmatter-relative byte
   location into a document range.
4. Add top-level field validation for `name`, `tags`, `description`, `skill`, `snippet`, and `keywords`.
5. Expand input validation:
   - mapping and sequence shapes
   - name presence/type/identifier warnings
   - explicit type validation
   - duplicate parsed names
   - default-vs-type validation
   - information diagnostics for ignored input item keys
6. Rework the current input source scanner into the source index so all new diagnostics can prefer exact ranges and fall
   back gracefully.
7. Add focused `sase_core` unit tests covering:
   - YAML parse errors
   - non-mapping frontmatter
   - bad top-level keys
   - invalid explicit name
   - invalid input shape, missing longform name, duplicate names, bad identifier, bad type
   - invalid default for `word`, `int`, `float`, and `bool`
   - valid aliases and valid defaults
   - invalid snippet trigger
   - invalid tags/keywords shapes
   - skill-without-description warning
   - flow-style inputs where the diagnostic range lands on the offending scalar
8. Add or update a `sase_xprompt_lsp` JSON-RPC test that opens a markdown document with multiple frontmatter problems
   and asserts the published `sase-xprompt` diagnostics include representative new codes.

## Verification

Run focused checks first:

```bash
cd ../sase-core
cargo fmt --all
cargo test -p sase_core editor::diagnostics
cargo test -p sase_xprompt_lsp stdio_jsonrpc
```

Then run the broader Rust checks:

```bash
cd ../sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
git diff --check
```

If clippy still fails on pre-existing unrelated warnings, report those separately and keep the implementation diff
scoped to frontmatter diagnostics and tests.

No Python changes are expected unless implementation reveals a direct mismatch with documented frontmatter semantics. If
this repo is touched only for this plan artifact, do not run `just check`; if Python/docs/config files are modified, run
`just install` first and then `just check` per workspace memory.

## Risks and Tradeoffs

- Exact source ranges for arbitrary YAML are hard without span-aware YAML nodes. The implementation should cover the
  documented block/flow forms and degrade to field-level ranges for uncommon YAML.
- Unknown-field diagnostics could be noisy for markdown files that are not xprompts. Keeping them at `Information`
  severity is the conservative first step.
- Some validations, especially unknown tags and provider names, are intentionally left permissive because current
  runtime behavior and plugin extensibility make strict rejection risky.
