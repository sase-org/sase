---
title: Macro arguments and typed inputs
description: Argument syntax, input types, defaults, and rendered output shapes.
---

# Macro arguments and typed inputs

This page documents the argument and input syntax used by macros.

## Arguments

### Positional Arguments

Positional arguments are comma-separated values inside parentheses:

```
#greet(Alice)
#format(json, 4)
```

Positional arguments are mapped to input definitions by position (0-indexed).

### Named Arguments

Named arguments use `key=value` syntax:

```
#greet(user_name=Alice)
#format(style=json, indent=4)
```

Positional and named arguments can be mixed; positional arguments must come first:

```
#template(Alice, style=formal)
```

### Quoted Strings

Values containing commas or special characters can be double- or single-quoted:

```
#note("Hello, world!", priority=high)
#tag('key=value')
```

### Text Blocks

For multi-line argument values, use `[[...]]` delimiters:

```
#review([[
  This is a multi-line
  text block argument.
  Blank lines are preserved.
]])
```

A `[[` opens a text block. It closes at the first `]]` whose next non-whitespace
character is an argument terminator — `,`, `)`, `}`, `|`, or the end of the scanned
region. A `]]` anywhere else is ordinary content, so prose such as
`` `[<web>:<keyword> [...]]` `` does not end the argument.

Text blocks automatically strip leading whitespace from the first line and dedent
continuation lines by their minimum common indentation.

Shorthand free-text payloads (`#name: text`, `#name:: text`, and `#name(args): text`)
are bound structurally during expansion. The captured text is not rewritten into
`#name([[...]])` and re-lexed, so commas, `]]`, `+`, and unbalanced parentheses in user
prose stay inside the bound value.

One residual ambiguity remains: a text block whose content holds a `]]` that is itself
followed by an argument terminator closes there, because first-match cannot distinguish
that content from the real terminator. `#name([[a]], b]])` binds two arguments (`a` and
`b]]`), not one. Content ending in `]]` is fine — `#name([[foo]]]])` binds `foo]]` —
because only the final `]]` sits in terminator position. Prefer an explicit quoted
argument when a `]]` must be followed by `,`, `)`, `}`, or `|`, for example
`#name("a]], b")`.

### Argument Completion and Highlighting

sase's TUI helps fill arguments in. Inside `#name(`, it offers the macro's missing
`name=` inputs in declaration order, each with its type, default, and description, and
accepting a `bool`, `path`, or `agent` input opens that input's value menu next. sase's
TUI and `sase macro show` color argument keys and values by type and underline unknown,
repeated, or mistyped keywords; the macro LSP reports the same argument spans as
[semantic tokens](../../editor.md#semantic-token-legend). See
[sase's TUI completion](../../ace.md#completion) and the
[Prompt Input Widget](../../ace.md#prompt-input-widget).

Compact input signatures use the shared type label: closed sets of up to four values
show their canonical values, larger sets show the named type and count, and domain
inputs show their named type. For example, an enum may appear as
`environment: staging | prod`.

## Shorthand Syntax

Shorthand syntax captures line-oriented prompt text as a single argument without
requiring explicit `[[...]]` delimiters. Expansion binds that payload structurally; it
does not round-trip the prose through source syntax.

### Single-Colon Shorthand

`#name: text` captures text until a blank line (`\n\n`) or end of string. Like any
reference, it must start the prompt or follow whitespace or one of `([{"'`; the space
after the colon is what distinguishes it from the `#name:arg` form:

```
#review: Please check this code for correctness
and performance issues.
```

The captured payload is the same value `#review([[...]])` would bind, but expansion does
not rewrite the source into that form.

### Double-Colon Shorthand

`#name:: text` captures text until the next line that starts with a macro reference
followed by `(`, `: `, `:: `, or `::` at end of line, or until the end of the string.
`::` may end its line, in which case the payload starts on the next line. Blank lines do
not terminate it, and neither do lines that start with a `%` directive, a bare `#name`,
or a `#name:arg` reference:

```
#instructions:: Follow these rules:

1. Be concise
2. Be accurate

#review: Now review the code.
```

```
#template(style=formal)::
Please review the following code.
```

### Paren + Shorthand

Combine parenthesized args with shorthand text:

```
#template(style=formal): Please review the following code.
#template(style=formal):: Please review the following code.

Even across blank lines (double-colon only).
```

The text is bound as one more positional argument after any positional arguments inside
the parentheses.

## Typed Inputs

`type` names what the value is: a scalar keyword (`word`, `line`, `text`, `path`, `int`,
`float`, `bool`, `code`), `enum` with inline `choices`, a builtin type (`agent`,
`model`, `effort`), or a plugin's shared enum (`<dist>@<id>`). Bare names belong to
sase; qualified names belong to plugins.

The same catalog drives every surface: the runtime binder,
[`sase macro types`](../cli/macro.md#sase-macro-types) and `sase macro show`, the
[TUI prompt bar](../../ace.md#completion), and the [macro LSP](../../editor.md#lsp-features).
Completing, validating, and explaining a value follows one rule.

```yaml
---
name: deploy
input:
  env: # inline enum
    type: enum
    choices:
      - { value: staging, description: Pre-prod cluster }
      - { value: prod, label: Production, description: Customer traffic }
    default: staging
  model: { type: model, default: "@large" } # builtin domain, same values as %model
  effort: effort # builtin closed enum, same values as %effort
  edition: sase-research-artifacts@audio_edition # plugin-shared enum
---
```

The shortform `name: <type string>` already works for every named type.

### Longform Syntax

```yaml
input:
  - name: diff_path
    type: path
    description: Diff file to review.
  - name: max_retries
    type: int
    default: 3
    description: Maximum retry attempts.
```

### Shortform Syntax

```yaml
input:
  diff_path: path
  max_retries:
    type: int
    default: 3
    description: Maximum retry attempts.
```

Both forms accept optional one-line `description` fields. Input descriptions do not
change argument parsing or compact input signatures; rich surfaces such as catalogs,
explain output, argument help, and editor documentation can use them as human-facing
help text.

sase's TUI can synthesize required `text` inputs from raw `<placeholder>` tags when
saving a prompt-bar draft as a new global or frontmatter-local macro. See
[Raw Prompt Placeholders](templating.md#raw-prompt-placeholders) for the launch-time collection,
save-time conversion, and literal-zone rules.

### Supported Types

Resolution is scalar → inline `enum` → builtin (`agent`, `model`, `effort`) → plugin
`<dist>@<id>`. `sase macro types` prints the installed catalog in that grouping.

| Type     | Kind    | Aliases   | Validation                                                                |
| -------- | ------- | --------- | ------------------------------------------------------------------------- |
| `word`   | scalar  | --        | No whitespace allowed                                                     |
| `line`   | scalar  | --        | No newlines allowed (default type)                                        |
| `text`   | scalar  | --        | Any content, no restrictions                                              |
| `path`   | scalar  | --        | A single line; spaces are allowed, newlines are not                       |
| `int`    | scalar  | `integer` | Must parse as an integer                                                  |
| `bool`   | scalar  | `boolean` | Accepts `true`/`false`, `yes`/`no`, `1`/`0`, `on`/`off`                   |
| `float`  | scalar  | --        | Must parse as a float                                                     |
| `code`   | scalar  | --        | Structured source plus language (default language bash)                   |
| `enum`   | inline  | --        | One of the input's declared `choices`                                     |
| `agent`  | builtin | --        | Non-empty, no whitespace; completes agent names                           |
| `effort` | builtin | --        | One of the seven `%effort` levels, matched exactly                        |
| `model`  | builtin | --        | A model token `%model` would accept without the default-provider fallback |

Plugin types use `<distribution>@<id>` (for example
`sase-research-artifacts@audio_edition`) and resolve to closed enums. See
[Named plugin input types](#named-plugin-input-types).

Use `line` for string values; `string` remains an accepted alias and loaders emit an
`input_type_warning` when it appears. See [Macro migration notes](../upgrading/macros.md#template-and-input-aliases).
`builtin@<name>` is an
accepted alias of any bare builtin; hover, labels, and formatters always show the bare
form. An unknown type name is a per-macro load error with suggestions (`enmu` suggests
`enum`); only that macro is skipped.

A `code` input is not a plain string with a convention. Binding yields a structured
`CodeValue` (source, language, digest, preview). Unlabelled values default to Bash;
sase's TUI and the macro LSP treat the field as code rather than a scalar.

An `effort` input accepts exactly one of the seven `%effort` levels (`none`, `minimal`,
`low`, `medium`, `high`, `xhigh`, `max`); anything else is rejected the same way a
non-member `enum` value is. A `model` input accepts exactly the tokens the `%model`
directive would accept _and_ route to a provider without the silent default-provider
fallback: aliases need `@` (`@large` routes; bare `large` does not), `provider/model` is
open for unknown model ids and closed for unknown providers, and a trailing `@<level>`
peels only when `<level>` is one of the seven effort levels. See
[Macro model inputs](../providers/models.md#macro-model-inputs). `%model:opsu` still parses and still
falls back at launch; `type: model` rejects that token at bind time with a suggestion.

### Enum Choices

An `enum` input must declare a non-empty `choices` list; every other type must leave
`choices` unset. Choices are either plain scalars or `{value, label, description}`
mappings. `label` and `description` are optional free text a rich surface (sase's TUI,
Gate Debug, editor completion) can show; they are never accepted as the value. The
`value` itself is always what gets passed to the template. Matching is exact and
case-sensitive.

Choice values must be quoted strings. An unquoted YAML scalar that PyYAML reads as a
boolean, number, or null is a load error: `yes` must be written `"yes"` because YAML
reads the bare token as a boolean. Values cannot contain Unicode whitespace, cannot be
the literal `null`, and cannot be repeated. Characters that need quoting in shorthand
(`,` `+` `(` `)` `[` `]` `"` `'` and backtick) produce a warning and still load.

```yaml
input:
  - name: log_level
    type: enum
    choices: [debug, info, warn, error]
    default: info
  - name: environment
    type: enum
    choices:
      - { value: staging, label: "Staging", description: "Pre-production" }
      - { value: prod, label: "Production" }
```

A value outside the declared `choices` fails validation, lists the allowed values, and
includes a did-you-mean suggestion when a close match exists. A closed-set default that
is not a string member of `choices` is a load error.

### Named plugin input types

Plugins share closed enums as named types referenced as `<distribution>@<id>`, for
example `sase-research-artifacts@audio_edition`:

```yaml
input:
  edition: sase-research-artifacts@audio_edition
```

Bare names belong to sase; qualified names belong to plugins. Distributions use PEP 503
canonicalization, matching is exact and case-sensitive, and installing an unrelated
plugin never changes what an existing macro means. A named type already defines its
values, so an authored `choices` override is an error. Defaults must be string members
of the resolved choices. See [Shipping input types](../../plugins.md#shipping-input-types) for
the manifest and `sase macro types` for the installed catalog.

### Repeatable Inputs

Set `repeatable: true` on the last user-facing positional input to let it collect every
remaining positional value as a list. Only one input may be repeatable, and it must be
the final positional input; any other placement is a validation error. The bundled
`#fork` workflow uses this so `#fork(a, b)` resumes from several parents:

```yaml
input:
  name:
    type: agent
    default: null
    repeatable: true
```

An explicitly supplied repeatable value is always a list, even when only one value is
given. A `null` value cannot be combined with other values for the same input.

### Defaults

- An input with no `default` is required. Omitting it causes a template error if the
  caller does not supply a value.
- `default: null` means the YAML value was explicitly null. When `null` is passed as a
  positional or named argument value, it acts as a pass-through (the callee's own
  default applies).
- `default: ""` or any other value makes the input optional with that default.

## Output Specification

Macros used as agent steps in workflows can declare an output schema for structured
output validation. See the [Output Specification](../workflows.md#output-specification)
section in the workflow spec for full details on the format.

### Shortform Object

```yaml
output: { name: word, description: text }
```

### Shortform Array

```yaml
output: [{ name: word, description: text, parent: { type: word, default: "" } }]
```

### Longform

```yaml
output:
  type: json_schema
  schema:
    properties:
      name: { type: word }
      description: { type: text }
```

When an output spec is present, the agent's response is validated against the schema.
Semantic types (`word`, `line`, `text`, `path`, `bool`, `int`, `float`) are converted to
JSON Schema types for validation and then checked for additional constraints (e.g.,
`word` rejects whitespace).

## Related

- [Macro reference](index.md)
- [Template rendering](templating.md)
