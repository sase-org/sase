# XPrompt Template Reference

XPrompts are reusable prompt templates with optional typed inputs and Jinja2 support. They let you define a prompt
fragment once and reference it by name anywhere a prompt is composed, keeping prompts DRY and consistent across
projects.

Use xprompts when you want to:

- Share common instructions across multiple prompts (e.g., output format rules, role definitions).
- Parameterize prompts with typed, validated arguments.
- Compose prompts from smaller building blocks using `#name(args)` syntax.

## Table of Contents

- [Discovery Order](#discovery-order)
- [File Format](#file-format)
- [Reference Syntax](#reference-syntax)
- [Arguments](#arguments)
- [Shorthand Syntax](#shorthand-syntax)
- [Typed Inputs](#typed-inputs)
- [Output Specification](#output-specification)
- [Jinja2 Integration](#jinja2-integration)
- [Legacy Placeholders](#legacy-placeholders)
- [Config-Based XPrompts](#config-based-xprompts)
- [Directory Configuration Files](#directory-configuration-files)
- [Directives](#directives)
- [Command Substitution](#command-substitution)
- [Protected Content](#protected-content)
- [Recursive Expansion](#recursive-expansion)
- [Relationship to Workflows](#relationship-to-workflows)

## Discovery Order

XPrompts are loaded from multiple locations. When two locations define an xprompt with the same name, the
higher-priority source wins (first-wins).

| Priority | Location                              | Notes                                     |
| -------- | ------------------------------------- | ----------------------------------------- |
| 1        | `.xprompts/` (CWD, hidden dir)        | Highest priority; project-local overrides |
| 2        | `xprompts/` (CWD)                     | Non-hidden variant                        |
| 3        | `~/.xprompts/` (home, hidden dir)     | User-wide overrides                       |
| 4        | `~/xprompts/` (home)                  | Non-hidden variant                        |
| 5        | `~/.config/sase/xprompts/{project}/`  | Project-specific (when project is set)    |
| 6        | `sase.yml` `xprompts:` section        | Config-based definitions                  |
| 7        | Plugin packages (`sase_xprompts` EPs) | Installed plugin xprompts                 |
| 8        | `<sase_package>/xprompts/`            | Built-in xprompts shipped with sase       |

Each directory (priorities 1-5, 7-8) can contain individual `.md` files and/or an `xprompts.yml` config file. See
[Directory Configuration Files](#directory-configuration-files) for the config file format.

For file-based xprompts (priorities 1-5, 7), the xprompt name defaults to the filename stem (e.g., `summarize.md`
defines the xprompt `summarize`). The name can be overridden via the `name` field in the YAML front matter.

Project-specific xprompts (priority 5) are namespaced: a file `bar.md` in the `foo` project directory becomes `foo/bar`
and is referenced as `#foo/bar`.

## File Format

An xprompt file is a Markdown file with optional YAML front matter delimited by `---` lines. Everything after the
closing `---` is the template body.

```markdown
---
name: greet
input:
  user_name: word
---

Hello, {{ user_name }}! Welcome aboard.
```

### Front Matter Fields

| Field   | Required | Description                                                     |
| ------- | -------- | --------------------------------------------------------------- |
| `name`  | No       | XPrompt name (defaults to filename stem)                        |
| `input` | No       | Input parameter definitions (see [Typed Inputs](#typed-inputs)) |

If no front matter is present, the entire file content is the template body and the filename stem is the name.

## Reference Syntax

Reference an xprompt inside any prompt with the `#` prefix. The `#` must appear at the start of the string, after
whitespace, or after one of `([{"'`.

| Syntax                        | Description                                           |
| ----------------------------- | ----------------------------------------------------- |
| `#name`                       | Simple reference, no arguments                        |
| `#name(args)`                 | Parenthesis syntax with comma-separated arguments     |
| `#name:arg`                   | Colon syntax, passes `arg` as a single positional arg |
| `` #name:`arg with spaces` `` | Colon+backtick syntax for args containing spaces      |
| `#name+`                      | Plus syntax, equivalent to `#name:true`               |
| `#ns/name`                    | Namespaced reference (e.g., project-specific)         |

Markdown headings like `# Heading` are not matched because a space after `#` prevents the pattern from firing.

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

Text blocks automatically strip leading whitespace from the first line and dedent continuation lines by their minimum
common indentation.

## Shorthand Syntax

Shorthand syntax converts line-oriented prompt text into `#name([[text]])` calls, avoiding the need for explicit text
block delimiters.

### Single-Colon Shorthand

`#name: text` at the start of a line captures text until a blank line (`\n\n`) or end of string:

```
#review: Please check this code for correctness
and performance issues.
```

This is equivalent to `#review([[Please check this code for correctness\nand performance issues.]])`.

### Double-Colon Shorthand

`#name:: text` captures text until the next xprompt directive at a line boundary or end of string (blank lines do not
terminate it):

```
#instructions:: Follow these rules:

1. Be concise
2. Be accurate

#review: Now review the code.
```

### Paren + Shorthand

Combine parenthesized args with shorthand text:

```
#template(style=formal): Please review the following code.
#template(style=formal):: Please review the following code.

Even across blank lines (double-colon only).
```

The text is appended as a final positional text-block argument.

## Typed Inputs

XPrompts can declare typed input parameters in the YAML front matter.

### Longform Syntax

```yaml
input:
  - name: diff_path
    type: path
  - name: max_retries
    type: int
    default: 3
```

### Shortform Syntax

```yaml
input:
  diff_path: path
  max_retries: { type: int, default: 3 }
```

### Supported Types

| Type    | Aliases   | Validation                                              |
| ------- | --------- | ------------------------------------------------------- |
| `word`  | --        | No whitespace allowed                                   |
| `line`  | --        | No newlines allowed (default type)                      |
| `text`  | --        | Any content, no restrictions                            |
| `path`  | --        | No whitespace                                           |
| `int`   | `integer` | Must parse as an integer                                |
| `bool`  | `boolean` | Accepts `true`/`false`, `yes`/`no`, `1`/`0`, `on`/`off` |
| `float` | --        | Must parse as a float                                   |

### Defaults

- An input with no `default` is required. Omitting it causes a template error if the caller does not supply a value.
- `default: null` means the YAML value was explicitly null. When `null` is passed as a positional or named argument
  value, it acts as a pass-through (the callee's own default applies).
- `default: ""` or any other value makes the input optional with that default.

## Output Specification

XPrompts used as agent steps in workflows can declare an output schema for structured output validation. See the
[Output Specification](workflow_spec.md#output-specification) section in the workflow spec for full details on the
format.

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

When an output spec is present, the agent's response is validated against the schema. Semantic types (`word`, `line`,
`text`, `path`, `bool`, `int`, `float`) are converted to JSON Schema types for validation and then checked for
additional constraints (e.g., `word` rejects whitespace).

## Jinja2 Integration

When the template body contains Jinja2 markers (`{{ }}`, `{% %}`, or `{# #}`), it is rendered as a Jinja2 template.
Arguments (both positional and named) are available in the template context.

```markdown
---
input: { user: word, verbose: { type: bool, default: false } }
---

Hello, {{ user }}.

{% if verbose %} Here is the detailed explanation... {% endif %}
```

### Template Context

| Variable      | Description                            |
| ------------- | -------------------------------------- |
| `{{ name }}`  | Named argument or input mapped by name |
| `{{ _1 }}`    | First positional argument (1-indexed)  |
| `{{ _2 }}`    | Second positional argument, etc.       |
| `{{ _args }}` | List of all positional arguments       |

Named arguments and positional-to-name mappings take priority; if an xprompt is called within a workflow step, the
workflow's execution scope is also available (xprompt args override scope values on conflict).

## Legacy Placeholders

For templates that do not use Jinja2 syntax, a legacy placeholder mode is available. Placeholders use `{N}` syntax
(1-indexed):

```
Review the {1} module and check for {2:correctness}.
```

- `{1}` -- required first positional argument.
- `{2:correctness}` -- second positional argument with default `correctness`.

Legacy mode is auto-detected: if the body contains no Jinja2 markers, legacy substitution is used.

## Config-Based XPrompts

XPrompts can be defined inline in `sase.yml` under the `xprompts:` key.

### Simple Format

```yaml
xprompts:
  propose: "Please propose your changes before applying them."
```

### Structured Format

```yaml
xprompts:
  greet:
    input: { name: word, count: { type: int, default: 1 } }
    content: "Hello {{ name }}, count is {{ count }}"
```

Config-based xprompts have priority 6 (below file-based, above plugin and built-in).

## Directory Configuration Files

In addition to defining xprompts as individual `.md` files, you can define multiple xprompts in a single `xprompts.yml`
(or `xprompts.yaml`) file placed inside any `xprompts/` directory in the search path.

### Format

The file uses the same format as the `xprompts:` section in `sase.yml`:

```yaml
# Simple format — value is the template body
propose: "Please propose your changes before applying them."

# Structured format — with typed inputs and/or output
greet:
  input: { name: word, count: { type: int, default: 1 } }
  content: "Hello {{ name }}, count is {{ count }}"
  output: { result: text }
```

### Precedence Rules

- Only one config file per directory — `xprompts.yml` takes precedence over `xprompts.yaml` if both exist.
- Within a directory, config entries are loaded first, then individual `.md` files override them (so a `foo.md` file in
  the same directory will take priority over a `foo:` entry in `xprompts.yml`).
- Across directories, the normal [discovery order](#discovery-order) applies.

## Directives

Directives are in-prompt tags with a `%` prefix that modify agent runner behavior. They are extracted and stripped from
the prompt before further processing.

### Supported Directives

| Directive | Alias | Description                                   |
| --------- | ----- | --------------------------------------------- |
| `%model`  | `%m`  | Override the LLM model for this prompt        |
| `%name`   | `%n`  | Assign a name to the agent                    |
| `%wait`   | `%w`  | Wait for another agent to finish (can repeat) |

### Syntax

Directives use the same argument syntax as xprompt references:

```
%model:claude-sonnet         # Colon syntax
%model(claude-sonnet)        # Parenthesis syntax
%model:`claude-sonnet-4`     # Backtick syntax (for values with special chars)
%name:reviewer               # Short-form
%n:reviewer                  # Same, using alias
%wait:agent1                 # Wait for agent1
%w:agent2                    # Wait for agent2 (alias)
```

### Example

```
%model:`claude-sonnet-4-20250514`
%name:code-reviewer
%wait:planner
Review the code changes and provide feedback.
```

The directives are stripped from the prompt text. The agent will use the specified model, be named "code-reviewer", and
will wait for the "planner" agent to complete before running.

### Multi-Value Directives

The `%wait` directive supports multiple occurrences — each adds to the wait list:

```
%wait:agent1
%wait:agent2
%wait:agent3
Do work after all three agents finish.
```

## Command Substitution

XPrompt arguments support shell command substitution using `$(cmd)` syntax. The command is executed via the shell and
its output replaces the `$(cmd)` expression.

```
#bug:$(branch_bug)           # Use output of branch_bug command as the argument
#review:$(git diff HEAD~1)   # Pass git diff output as argument
```

Nested parentheses are supported: `$(echo $(date))`. To include a literal `$(`, escape it as `\$(`.

Failed commands or commands producing empty output result in an empty string replacement. Command outputs are cached
within a single expansion pass to avoid redundant execution.

## Protected Content

### Fenced Code Blocks

Content inside triple-backtick fenced code blocks is automatically protected from xprompt expansion:

````
Here's an example:

```
#foo will NOT be expanded inside this code block
```

But #foo HERE will be expanded normally.
````

This prevents accidental expansion of `#name` patterns in code examples, documentation, and similar content.

### Disabled Regions

You can explicitly disable xprompt expansion for a region of text using the `%xprompts_enabled` directive:

```
%xprompts_enabled:false
This content is passed through verbatim.
#foo will NOT be expanded here.
%xprompts_enabled:true
Normal expansion resumes here.
#foo WILL be expanded.
```

The markers are stripped from the final output. This is useful for embedding raw xprompt syntax in documentation or for
passing literal `#name` patterns to downstream consumers.

## Recursive Expansion

XPrompt bodies can reference other xprompts. Expansion is iterative: after each round of substitution, the result is
scanned again for new `#name` references. This continues until no known references remain, up to a maximum of 100
iterations (to guard against circular references).

## Relationship to Workflows

XPrompts and [workflows](workflow_spec.md) share the same `#name(args)` calling convention. Internally, a standalone
xprompt is converted to a single-step workflow with a `prompt_part` step, so both can be invoked uniformly via
`sase run '#name(args)'`.

Workflow agent steps can embed xprompt references inline:

```yaml
steps:
  - name: review
    agent: |
      #mentor(prompt=[[Review error handling]])
```

See the [Workflow Specification](workflow_spec.md) for full details on multi-step workflows, control flow, parallel
execution, and human-in-the-loop approval.
