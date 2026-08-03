# XPrompt Template Reference

XPrompts are reusable prompt templates with optional typed inputs and Jinja2 support. They let you define a prompt
fragment once and reference it by name anywhere a prompt is composed, keeping prompts DRY and consistent across
projects. Inline prompt fragments use `#name`; standalone workflows use `#!name` when they are launched as workflows.

Use xprompts when you want to:

- Share common instructions across multiple prompts (e.g., output format rules, role definitions).
- Parameterize prompts with typed, validated arguments.
- Compose prompts from smaller building blocks using `#name(args)` syntax.

![SASE xprompt inputs flowing through workspace dispatch, first-wins discovery, iterative expansion, and directive
extraction into runtime outcomes](images/xprompt-resolution-infographic.png)

There are two related paths to keep separate:

```text
launch setup:
  xprompt swarm fan-out check
  -> default workspace ref insertion when needed (#git:home)
  -> project name/alias canonicalization (#gh:bob -> #gh_bbugyi200__bob)
  -> workspace ref resolution (#git/#gh, plugin-provided refs, and known-project fallbacks)
  -> prompt/workflow execution

xprompt expansion inside a prompt or prompt_part:
  alias substitution
  -> fenced-block and disabled-region protection
  -> iterative reference expansion (parse -> lookup -> args -> render -> substitute)
  -> directive extraction at the launch or workflow-step boundary
```

The checked-in infographic prompt in `docs/images/xprompt-resolution-infographic.prompt.md` tracks the intended visual
version of this model; the text model above is the authoritative current reference for resolver order.

## Table of Contents

- [CLI Subcommands](#cli-subcommands)
  - [sase xprompt expand](#sase-xprompt-expand)
  - [sase xprompt explain](#sase-xprompt-explain)
  - [sase xprompt list](#sase-xprompt-list)
  - [sase xprompt show](#sase-xprompt-show)
  - [sase xprompt graph](#sase-xprompt-graph)
  - [sase xprompt catalog](#sase-xprompt-catalog)
- [Editor LSP](#editor-lsp)
- [Discovery Order](#discovery-order)
- [File Format](#file-format)
- [Reference Syntax](#reference-syntax)
- [Arguments](#arguments)
- [Shorthand Syntax](#shorthand-syntax)
- [Typed Inputs](#typed-inputs)
- [Output Specification](#output-specification)
- [Jinja2 Integration](#jinja2-integration)
- [Legacy Placeholders](#legacy-placeholders)
- [Raw Prompt Placeholders](#raw-prompt-placeholders)
- [Tags](#tags)
- [Snippet Field](#snippet-field)
- [Skill Field](#skill-field)
  - [Bundled Skills](#bundled-skills)
- [Built-in XPrompts](#built-in-xprompts)
- [Config-Based XPrompts](#config-based-xprompts)
- [Local Configuration Files](#local-configuration-files)
- [Directives](#directives)
  - [Launch-Scoped Model Alias Overrides](#launch-scoped-model-alias-overrides)
- [Command Substitution](#command-substitution)
- [Protected Content](#protected-content)
- [XPrompt Aliases](#xprompt-aliases)
- [Recursive Expansion](#recursive-expansion)
- [Stored Prompt Renderings](#stored-prompt-renderings)
- [Multi-Agent Prompts](#multi-agent-prompts)
  - [Xprompt Swarms (Library-Defined Fan-Out)](#xprompt-swarms-library-defined-fan-out)
- [Relationship to Workflows](#relationship-to-workflows)

## CLI Subcommands

The `sase xprompt` command provides six subcommands for working with xprompts. With no subcommand, it defaults to
`sase xprompt list`. Flags belong to the explicit subcommand, so use forms like `sase xprompt expand --trace '#plan'`
rather than putting `--trace` on bare `sase xprompt`.

### `sase xprompt expand`

Expands xprompt references in a prompt. Reads from a positional argument or stdin.

```bash
sase xprompt expand '#greet(Alice)'         # Expand from argument
echo '#greet(Alice)' | sase xprompt expand  # Expand from stdin
sase xprompt expand --trace '#plan'         # Show expansion trace on stderr
```

The `--trace` flag prints a detailed expansion trace to stderr showing each resolved reference, its source file,
arguments, and expanded content. This is useful for debugging reference resolution order and understanding how a complex
prompt is assembled.

### `sase xprompt explain`

Shows a dry-run visualization of a workflow's execution plan without actually running it. Displays workflow metadata,
input requirements, resolved arguments, and the full step-by-step execution plan with types, control flow annotations,
rendered step bodies, and output schemas.

```bash
sase xprompt explain my_workflow                    # Explain with no args
sase xprompt explain my_workflow arg1 arg2          # With positional args
sase xprompt explain my_workflow --arg key=value    # With named args
```

### `sase xprompt list`

Lists all available xprompts and workflows as a JSON array. Each entry includes the name, type (`"xprompt"` or
`"workflow"`), kind, reference prefix, insertion text, `is_skill`, source file path, user-facing input definitions,
tags, and a content preview. Clients should treat `insertion` as the authoritative reference text. Most `xprompt` and
`embeddable_workflow` entries insert as `#name`, including markdown xprompt swarms; standalone workflows insert as
`#!name`. `is_skill` is `true` only for xprompt catalog entries marked as skills; workflows report `false`. Step inputs
are omitted from the JSON `inputs` array because they are supplied by workflow execution rather than typed by a user.

```bash
sase xprompt list                   # JSON array to stdout
sase xprompt list | jq '.[].name'  # Extract just names
```

### `sase xprompt show`

Shows one xprompt or workflow definition with its properties, typed inputs, local helper xprompts, provenance,
references, and highlighted body. The `NAME` argument accepts a bare name or a copied reference such as `#name`,
`#!name`, or `/name`; copied arguments like `#name(a, b)`, `#name:arg`, and `#name+` are ignored with a warning.

```bash
sase xprompt show sase/reads                  # Render a readable definition view
sase xprompt show '#!sync'                    # Show a standalone workflow
sase xprompt show plan --format json | jq .inputs
sase xprompt show coder --format raw > coder.md
sase xprompt show t --color always | less -R
```

`--format full` is the default Rich detail view. `--format json` emits the stable schema-versioned show record, while
`--format raw` writes the exact source definition bytes without adding a trailing newline. `--color auto|always|never`
controls ANSI output for the rendered view, and `--project PROJECT` resolves within a specific project namespace.

### `sase xprompt graph`

Generates a directed acyclic graph (DAG) visualization of a workflow. Without a workflow name, lists all available
multi-step workflows with their step counts and source paths.

```bash
sase xprompt graph                        # List all workflows
sase xprompt graph my_workflow            # Mermaid DAG (default)
sase xprompt graph my_workflow --format text  # Plain-text summary
```

The Mermaid output can be pasted into any Mermaid-compatible renderer. Parallel sub-steps are shown as subgraphs, and
nodes include type indicators and control flow annotations.

### `sase xprompt catalog`

Renders every visible xprompt to a formatted PDF catalog for browsing and sharing.

```bash
sase xprompt catalog                # Write the PDF to a tempdir and print its path
sase xprompt catalog --out /tmp/out # Write the PDF to the specified directory
```

The command collects all visible xprompt templates, renders each into an HTML section, and produces a single PDF using
the bundled `catalog_template.html.j2` and `catalog_style.css`. The mobile/helper structured catalog uses the same
collection and classification code, but returns JSON metadata instead of requiring a PDF renderer.

## Editor LSP

`sase lsp` starts the SASE xprompt language server over stdio for editor integrations. It resolves the server command in
this order:

1. `SASE_XPROMPT_LSP_CMD`, parsed as a shell-style command for development.
2. A `sase-xprompt-lsp` binary in the current Python environment's `bin/` directory.
3. `sase-xprompt-lsp` on `PATH`.
4. The newer debug or release `sase-xprompt-lsp` binary under a sibling `../sase-core` checkout.
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --` when `cargo` is available and the sibling
   checkout has a `Cargo.toml`.

Examples:

```bash
sase lsp
sase lsp --version
SASE_XPROMPT_LSP_CMD='cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --' sase lsp
```

Use `SASE_XPROMPT_LSP_CMD` for any non-default LSP command, including a custom binary that should beat the managed venv
copy. Full editable-install SASE updates reinstall the server into the uv-tool venv when pulled `sase-core` commits
change. `SASE_CORE_DIR` is a `Justfile` build/install override, not part of `sase lsp` command resolution.

The LSP loads the supported xprompt catalog sources directly in Rust for completion, hover, diagnostics, and definition
requests. `sase lsp` exports the installed package xprompt paths to the server so built-in Markdown prompts, YAML
workflows, default config prompts, project-local prompts, user config prompts, and memory prompts do not require a
Python helper subprocess on the completion path. The Python helper bridge remains stable for mobile clients and as a
compatibility fallback for sources the Rust loader cannot discover.

When the editor advertises LSP `completionItem.snippetSupport`, the server also returns SASE snippets as ordinary
`CompletionItemKind.Snippet` entries after bare trigger words such as `fix` or `review`. Snippet entries are loaded from
the same registry as ACE: xprompts with `snippet` front matter plus user-defined `ace.snippets`, with `ace.snippets`
winning on trigger collisions. The registry also includes the generated initial-capital aliases (`foo` → `Foo`), so a
completion for `Foo` appears wherever `foo` does. The editor does not need to shell out or parse SASE config to discover
snippets.

The Python helper operation `sase editor helper-bridge snippet-catalog` is the authoritative snippet registry because it
matches ACE's xprompt composition behavior. The Rust server also has a native fallback for simple xprompt snippets and
`ace.snippets` so completion can degrade gracefully if the helper is unavailable. That fallback intentionally skips
xprompts that require complex Jinja or composition it cannot mirror exactly; when the helper is available, its response
is preferred.

See the [editor integration guide](editor.md) for setup, feature coverage, helper bridge usage, and troubleshooting.

## Discovery Order

Markdown xprompts are loaded from multiple locations. When two locations define an xprompt with the same name, the
higher-priority source wins (first-wins).

| Priority | Location                               | Role                                                        |
| -------- | -------------------------------------- | ----------------------------------------------------------- |
| 1        | `<project>/sase/xprompts/`             | Canonical project files; writable                           |
| 2        | `<project>/.xprompts/`                 | Legacy hidden project files; read-only compatibility        |
| 3        | `<project>/xprompts/`                  | Legacy visible project files; read-only compatibility       |
| 4        | `~/sase/xprompts/`                     | Canonical user-wide files; writable                         |
| 5        | `~/.xprompts/`                         | Legacy hidden home files; read-only compatibility           |
| 6        | `~/xprompts/`                          | Legacy visible home files; read-only compatibility          |
| 7        | `~/sase/xprompts/{project}/`           | Canonical project-specific home files; writable             |
| 8        | `~/.config/sase/xprompts/{project}/`   | Legacy project-specific home files; read-only compatibility |
| 9        | `<project>/sase/sase.yml`              | Canonical project config definitions; writable              |
| 10       | `<project>/sase.yml`                   | Exclusive legacy project-config fallback                    |
| 11       | `~/.config/sase/sase_*.yml`            | User overlays; reverse lexical winner order                 |
| 12       | `~/.config/sase/sase.yml`              | User base config                                            |
| 13       | Plugin `default_config.yml` resources  | Installed plugin config definitions                         |
| 14       | Package `default_config.yml`           | Built-in config definitions                                 |
| 15       | Plugin packages (`sase_xprompts` EPs)  | Installed plugin files                                      |
| 16       | `<sase_package>/default_xprompts/*.md` | Built-in default Markdown files                             |
| 17       | `<sase_package>/xprompts/`             | Built-in Markdown, YAML, and shared steps                   |

Each directory-based source can contain individual `.md` files and, where supported, `.yml` or `.yaml` workflows plus a
`steps/` directory. Project config is exclusive: if priorities 9 and 10 both exist, SASE reports a collision instead of
merging them. File directories are first-wins, so a canonical definition shadows a same-named legacy definition. All
save, create, copy-on-edit, export, and workflow-editor destinations use writable canonical sources; legacy sources are
displayed only for migration. See [Canonical SASE Content Layout](content_layout.md) for before/after paths and the
compatibility timeline.

For file-based xprompts, the xprompt name defaults to the filename stem (e.g., `summarize.md` defines the xprompt
`summarize`). The name can be overridden via the `name` field in the YAML front matter.

Project-specific xprompts (priorities 7-8) are namespaced: a file `bar.md` in the `foo` project directory becomes
`foo/bar`. Inline-capable project xprompts are referenced as `#foo/bar`; standalone project workflows are referenced as
`#!foo/bar`.

When a project is detected (via the workspace provider), project xprompts (priorities 1-3) and local config xprompts are
also auto-namespaced with the `{project}/` prefix. For example, if the project is `myapp` and `sase/xprompts/deploy.md`
exists, it becomes `myapp/deploy` and is referenced as `#myapp/deploy`. A project workflow with no `prompt_part` would
instead be launched as `#!myapp/deploy`. This prevents name collisions between project-local xprompts and global or
built-in ones.

An explicit namespaced reference also works when the caller is outside that project's checkout. For an enabled
registered project, `#myapp/deploy` resolves checkout-backed files and local config from the project's primary
workspace. Write the literal reference with the configured project name shown by the xprompt catalog or completion.
Loader-facing project selection accepts the directory key or an alias too, but catalog entries are still exposed under
the configured name; those alternate identifiers are not literal xprompt namespaces. If the caller is already inside
another checkout of that same project, the current checkout wins over the registry copy so local edits are visible.
Disabled projects are not loaded through this registry fallback. When one inline prompt mentions registered project
namespaces, the first such namespace selects the checkout-backed project catalog for that prompt.

## File Format

An xprompt file is a Markdown file with optional YAML front matter delimited by `---` lines. Everything after the
closing `---` is the template body.

```markdown
---
name: greet
description: Greet a named user.
input:
  user_name:
    type: word
    description: User name to include in the greeting.
---

Hello, {{ user_name }}! Welcome aboard.
```

### Front Matter Fields

| Field         | Required | Description                                                                   |
| ------------- | -------- | ----------------------------------------------------------------------------- |
| `name`        | No       | XPrompt name (defaults to filename stem)                                      |
| `input`       | No       | Input parameter definitions (see [Typed Inputs](#typed-inputs))               |
| `snippet`     | No       | Opt-in to ACE snippet expansion (see [Snippet Field](#snippet-field) below)   |
| `description` | No       | Human-readable one-line description of what the xprompt does                  |
| `skill`       | No       | Marks this xprompt as an agent skill source for `sase skill init` (see below) |
| `xprompts`    | No       | File-local helper xprompts whose names must start with `_`                    |

If no front matter is present, the entire file content is the template body and the filename stem is the name.

Markdown xprompt files can carry file-local helper xprompts under `xprompts:`. These helpers use the same structured
format as config-based xprompts, including typed inputs and descriptions, and they can reference each other
transitively. During expansion they inherit the containing xprompt's arguments and template scope, so a helper can use
values such as `{{ topic }}` from the outer xprompt. They are visible only while expanding the containing xprompt and
must use `_`-prefixed names such as `_review_rules`; they do not leak into the global catalog, completion catalog, or
other xprompt files. This underscore rule also applies to local xprompts in ad hoc prompt front matter, while YAML
workflow-local xprompts follow the workflow rules described in [workflow_spec.md](workflow_spec.md).

## Reference Syntax

Reference inline-capable xprompts inside any prompt with the `#` prefix, including markdown-defined xprompt swarms whose
body contains top-level `---` segment separators. Use `#!` only for standalone YAML workflows that do not have a
`prompt_part` step. The marker must appear at the start of the string, after whitespace, or after one of `([{"'`. For
compatibility, `#!name` is still accepted for xprompt swarms, but new prompts should use `#name`.

| Syntax                        | Description                                                    |
| ----------------------------- | -------------------------------------------------------------- |
| `#name`                       | Inline/template reference, no arguments                        |
| `#name(args)`                 | Inline parenthesis syntax with comma-separated arguments       |
| `#name:arg`                   | Inline colon syntax, passes `arg` as a single positional arg   |
| `#name:a,b,c`                 | Inline colon syntax with comma-separated multiple args         |
| `` #name:`arg with spaces` `` | Colon+backtick syntax for args containing spaces (single only) |
| `#name+`                      | Plus syntax, equivalent to `#name:true`                        |
| `#ns/name`                    | Namespaced reference (e.g., project-specific)                  |
| `#!name`                      | Standalone workflow reference, no args                         |
| `#!name(args)`                | Standalone workflow reference with parenthesized arguments     |
| `#!name:arg`                  | Standalone workflow reference with one colon-style arg         |
| `#!name!!` / `#!name??`       | Standalone workflow with an explicit HITL approval override    |

Examples:

```bash
sase run '#!sync'
sase run '#gh:sase #!sync'
```

During the compatibility window, top-level legacy invocations such as `sase run '#sync'` still run but emit a warning
that points to `#!sync`. Inline expansion contexts reject standalone workflows instead of passing literal `#sync` text
to the model. Shell examples should use single quotes around `#!...` so `!` is not interpreted by interactive shells.

For workspace references, underscores can be used as an alternative to colons: `#gh_sase` is equivalent to `#gh:sase`.
The underscore is normalized to a colon before pattern matching, so both forms work identically. This is useful in
contexts where colons are inconvenient.

Provider-backed references also support `@name` agent references in the ref portion. The `@name` is resolved at runtime
to the named agent's ChangeSpec (branch name), allowing one agent's prompt to target another agent's workspace:

```
#gh:@planner     resolves to e.g. #gh:planner_add_config_parser
#gh_@reviewer    same, underscore form
```

This is useful when chaining agents — for example, a review agent can target the branch created by a prior agent using
`@name` instead of hardcoding the branch name.

### VCS Workspace References

Workspace-managing workflows use the same `#name:ref` reference syntax as xprompts, but they control where the agent
runs before the rest of the prompt is executed. Built-in `#git` references are VCS-backed; provider plugins can add
other workspace refs such as `#gh`.

| Reference           | Behavior                                                       |
| ------------------- | -------------------------------------------------------------- |
| `#git:<ref>`        | Run in a bare-git workspace                                    |
| `#gh:<ref>`         | Run in a GitHub workspace, when the GitHub plugin is installed |
| `#<provider>:<ref>` | Run through any other installed workspace provider             |

Prompts that do not contain a workspace reference are normalized to `#git:home`, so a bare prompt runs from the managed
bare-git `home` project by default and gets normal numbered workspace, checkout, diff, and release behavior.

By default, a missing or uninitialized `home` ProjectSpec is bootstrapped as a managed empty bare-git project at the
default `home` paths. To make bare prompts use an existing home/dotfiles bare repository, register a bare repository
whose basename resolves to `home`, for example `#git:/path/to/home.git`.

Provider-prefixed refs that point at a known project name are preserved as workspace launches even if the matching
workspace plugin is not loaded in the current process. Known projects come from `~/.sase/projects/*/*.sase` (with legacy
`~/.sase/projects/*/*.gp` accepted as a fallback). A launch such as `#gh:sase #!sync` therefore targets the registered
`sase` project, allocates a numbered workspace for non-wait runs, and lets dispatch surfaces strip the wrapper ref when
identifying an embedded workflow body.

Known projects may also declare `PROJECT_NAME` and `PROJECT_ALIASES` in their ProjectSpec. Friendly refs in VCS
workspace tags are canonicalized before workspace resolution and xprompt expansion, so `#gh:bob #p` is processed as a
ref to the directory-key project when that project declares `PROJECT_NAME: bob` or alias `bob`. The rewrite is exact and
applies to colon, underscore, and parenthesized workspace-ref forms; it does not rewrite owner/repo paths such as
`#gh:bbugyi200/bob`, partial project names, prose, or fenced code examples. See
[Project Names and Aliases](project_spec.md#project-names-and-aliases) for validation and management commands.

GitHub `owner/repo` refs use `PROJECT_NAME` after first use. Resolving `#gh:foo-org/foo` creates or reuses the canonical
project whose `WORKSPACE_DIR` is `~/projects/github/foo-org/foo/`; for a new repo that canonical directory key is
typically `gh_foo-org__foo`, with `PROJECT_NAME: foo`. A second repo with the same basename, such as `#gh:bar-org/foo`,
gets a different canonical project such as `gh_bar-org__foo` and the next available display name, for example `foo_1`.
Future launches can use `#gh:foo` and `#gh:foo_1`, and those refs canonicalize before prompt history, metadata, and
artifacts are written.

For compatibility, existing basename ProjectSpecs are reused when their `WORKSPACE_DIR` already matches the GitHub repo.
Owner/repo fallback avoids basename routing when duplicate GitHub basenames would make that ambiguous; direct
`owner/repo` refs match the GitHub workspace path first, then only use a basename fallback when it is unambiguous.

ACE and the xprompt LSP provide the same project/ChangeSpec completion helper for these references. Type `+query` at
absolute prompt offset zero or immediately after a literal ASCII space to open a picker of enabled launchable projects
and active PR-sized ChangeSpecs in `WIP`, `Draft`, `Ready`, or `Mailed` status. The token extends to the next whitespace
boundary, and `#+query`, line-start `+query` without a preceding space, tab-delimited forms, and plus signs glued to
other text are not project triggers. Accepting a project row inserts a tag such as `#gh:sase`; accepting a ChangeSpec
row inserts a tag such as `#gh:my_change`. The helper filters by `PROJECT_NAME`, directory-key project name, project
alias, or ChangeSpec name prefix, and it ignores system-managed `home`, disabled projects, sibling records, and
non-launchable projects.

ACE and the xprompt LSP also provide token-local completion at the root of registered VCS workflow refs. Typing `:` or
`(` after a workflow tag, such as `#gh:` or `#git(`, opens project and active PR-sized ChangeSpec rows scoped to that
provider. Providers can add fast local namespace rows; the GitHub plugin derives organization rows from enabled GitHub
project records and `github_orgs`. Accepting a project or ChangeSpec completes the current token, for example
`#gh:sase ` or `#gh(sase)`. Accepting a namespace inserts a trailing slash such as `#gh:sase-org/` without closing the
token, so repository completion can immediately take over.

ACE and the xprompt LSP also complete repositories inside provider refs after the namespace slash. Typing
`#gh:bbugyi200/` asks the registered GitHub workspace plugin for repositories owned by `bbugyi200`; typing
`#gh:bbugyi200/sa` narrows the menu toward matching repository names. Accepting a row rewrites only the current ref
value, so colon form becomes `#gh:bbugyi200/sase ` and parenthesized form becomes `#gh(bbugyi200/sase)`. The hook is
provider-agnostic: another workspace plugin can support the same UX for nested namespaces such as `#gl:group/subgroup/`
by implementing repository candidate listing.

Known-project discovery defaults to enabled ProjectSpecs. Disabled and sibling records are omitted from broad
project-local xprompt catalogs and completion menus. An explicitly typed known-project VCS ref is a launch-time
exception: launch preparation writes `PROJECT_STATE: enabled` before claiming the workspace. This is a persistent state
change, so use `sase project enable <project>` first when you prefer to make the transition separately. A checkout cwd
or mobile `project` value is context rather than a workspace ref; a prompt without an explicit ref defaults to
`#git:home`. Direct claims that bypass launch preparation remain blocked while the ProjectSpec is disabled. Management
and history code paths that need hidden projects opt into an all-state scan explicitly.

Double underscores (`__`) in xprompt names are treated as forward slashes (`/`), enabling flat references to namespaced
xprompts. For example, `#foo__bar` resolves to the xprompt registered as `foo/bar`, and `#a__b__c` resolves to `a/b/c`.
Single underscores are not affected. This is useful when `/` is inconvenient in certain input contexts (e.g., shell
completion or certain prompt editors).

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

Both forms accept optional one-line `description` fields. Input descriptions do not change argument parsing or compact
input signatures; rich surfaces such as catalogs, explain output, argument help, and editor documentation can use them
as human-facing help text.

ACE can synthesize required `text` inputs from raw `<placeholder>` tags when saving a prompt-bar draft as a new global
or frontmatter-local xprompt. See [Raw Prompt Placeholders](#raw-prompt-placeholders) for the launch-time collection,
save-time conversion, and literal-zone rules.

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

| Variable                            | Description                                                                                                |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `{{ name }}`                        | Named argument or input mapped by name                                                                     |
| `{{ _1 }}`                          | First positional argument (1-indexed)                                                                      |
| `{{ _2 }}`                          | Second positional argument, etc.                                                                           |
| `{{ _args }}`                       | List of all positional arguments                                                                           |
| `{{ root }}`                        | Absolute path to the primary workspace directory (omitted if unresolvable)                                 |
| `{{ wait_chats }}`                  | List of chat-transcript paths for agents named in `%wait:<name>` directives, in the order they appear      |
| `{{ agents["build"].path }}`        | Output variables loaded from `%wait:build` when that agent used `sase var set path=...`                    |
| `{{ agents["p--plan"].plan_file }}` | Proposed plan path of a submitted planner row, synthesized from `%wait:p--plan` (no `sase var set` needed) |

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

## Raw Prompt Placeholders

ACE recognizes valid single-line `<label>` tags as raw placeholders. A label must be nonempty, contain no leading or
trailing whitespace, and be at most 100 characters. Raw placeholders are highlighted in prompt panes, participate in
placeholder completion, and feed the saved common-placeholder history described in [ACE completion](ace.md#completion).
Repeated tags with the same exact, case-sensitive inner text are one logical placeholder. Tags inside inline code,
fenced code blocks, or `%xprompts_enabled:false` regions stay literal and are excluded from highlighting, completion
history, launch-time collection, and conversion.

Classification is syntactic rather than HTML-aware: `<div>`, `</div>`, and an angle-bracket link destination outside a
code zone are placeholders too, and a preceding backslash does not escape them. Keep literal angle-bracket markup in an
inline or fenced code zone, place it in a disabled xprompt region, or use the launch panel's keep-literal control.

By default, submitting a prompt from ACE opens **Fill in this prompt** whenever the prompt body contains a live raw
placeholder. The panel shows raw placeholders first and then any frontmatter-declared inputs, so both kinds are resolved
before the agents launch. Enter one value per distinct label to replace every matching occurrence across all segments,
or press `Ctrl+L` on a placeholder field to keep that tag literal. YAML frontmatter itself is not scanned. Set
`ace.prompt_inputs.collect_raw_placeholders: false` to skip only raw-placeholder collection and launch the tags
unchanged; declared [`input:`](#frontmatter-declared-inputs) values are still collected. Non-interactive `sase run` does
not collect raw placeholders.

When an ACE draft is saved as an xprompt (`gx`, `Ctrl+G x`, or `Ctrl+G Ctrl+X` in xprompt mode), live raw placeholders
are converted before the save preview into required `text` inputs:

```text
Deploy <service> to <target file>
```

becomes:

```markdown
---
input:
  service: text
  target_file: text
---

Deploy {{ service }} to {{ target_file }}
```

The `gX` active-pane conversion applies the same rewrite when it creates a frontmatter-local xprompt. Generated names
are Jinja-safe slugs allocated in document order; collisions receive `_2`, `_3`, and so on. During `gx`, a generated
name that matches an authored input is reused instead of redeclared, preserving its type, default, and description. Both
conversions reuse a matching undeclared Jinja variable. Repeated occurrences are substituted together, tags in literal
zones remain untouched, and inserted values are not scanned again for more placeholders. Saving the same draft as a
snippet keeps the original active-pane body rather than applying this xprompt-only conversion. Writing an already bound
xprompt with `gw` saves the body as edited and does not perform a new conversion pass.

Set `ace.prompt_inputs.xprompt_placeholder_args: false` to keep live raw placeholders literal during `gx` and `gX` and
mint no placeholder-derived `text` inputs. Undeclared Jinja variables still become required `gX` inputs.

## Tags

XPrompts and workflows can be annotated with semantic role tags. Tags enable lookup-by-role instead of lookup-by-name,
making the system extensible — a plugin or user can override the CRS workflow simply by defining a new xprompt with
`tags: crs`.

### Available Tags

| Tag                            | Description                                                                                                                               |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `vcs`                          | Workspace workflow xprompt (`#git`, `#gh`, or a plugin-provided ref) — wraps other embedded workflows, running setup/teardown around them |
| `crs`                          | Code Review Summary workflow (singleton — `get_by_tag(crs)` returns the first match)                                                      |
| `fix_hook`                     | Fix hook workflow (singleton — used by axe to find the hook-fix agent)                                                                    |
| `rollover`                     | Marks workflows whose embedded references carry forward to follow-up agent steps                                                          |
| `mentor`                       | Mentor review prompt workflow                                                                                                             |
| `commit`                       | Commit workflow (appended by mentor review `A` key for direct commit)                                                                     |
| `propose`                      | Propose workflow (appended by mentor review `a` key for propose-style amend)                                                              |
| `make_mentor_changes`          | Apply accepted mentor comments workflow (launched by mentor review `Enter`)                                                               |
| `diff_file`                    | Injects the PR diff into the mentor prompt                                                                                                |
| `append_to_pr`                 | VCS-specific post-commit prompt appended when the active commit method creates a pull request                                             |
| `append_to_commit_and_propose` | VCS-specific post-commit prompt appended when the active commit method creates a commit or proposal                                       |
| `create_epic_bead`             | Plan-approval Epic flow — creates the plan file, beads, and the epic agent prompt                                                         |
| `work_phase_bead`              | Per-phase agent prompt used by `sase bead work` (input: `bead_id`)                                                                        |
| `work_task_bead`               | Task-agent prompt used by `sase bead work` (input: `bead_id`)                                                                             |
| `land_epic`                    | Final land agent prompt used by `sase bead work`: verifies, integrates, and closes the epic                                               |

### Defining Tags

Tags can be defined in three places:

**YAML workflow files** (`.yml`):

```yaml
tags: vcs, rollover       # comma-separated string
# or
tags: [vcs, rollover]     # list format
```

**Markdown front matter** (`.md`):

```markdown
---
name: fix_hook
tags: fix_hook
---

Fix the failing hook...
```

**Config-based xprompts** (`sase.yml`):

```yaml
xprompts:
  my_crs:
    content: "Review the code..."
    tags: [crs]
```

### Tag-Based Lookup

The `get_by_tag()` function returns the first xprompt/workflow matching a tag, respecting the standard
[discovery order](#discovery-order). This means higher-priority sources (e.g., project-local) can override built-in
tagged xprompts.

```python
from sase.xprompt.tags import XPromptTag, get_by_tag

crs_wf = get_by_tag(XPromptTag.crs)
fh_wf = get_by_tag(XPromptTag.fix_hook)
```

### Backward Compatibility

The legacy `wraps_all: true` field on workflows is still supported — it automatically adds the `vcs` tag. New workflows
should use `tags: vcs` instead.

Source: `src/sase/xprompt/tags.py`, `src/sase/xprompt/models.py`

## Snippet Field

XPrompts can opt-in to ACE TUI snippet expansion by setting the `snippet` field in their front matter. When set, the
xprompt's content is converted into a snippet template and merged into the ACE snippet registry at startup, so users can
expand it by typing the trigger word and pressing `Tab`.

```markdown
---
name: review
snippet: true
input:
  language: word
---

Review this {{ language }} code for correctness and style.
```

**Values:**

| Value           | Behavior                                                     |
| --------------- | ------------------------------------------------------------ |
| `true`          | Use the xprompt's base name (part after last `/`) as trigger |
| `"custom_name"` | Use the custom string as the trigger word                    |

**Conversion rules:**

- Normal xprompt references in the content are expanded before conversion, so snippets can compose reusable xprompts
- `{{ input_name }}` placeholders for required inputs become snippet tabstops (`$1`, `$2`, etc.)
- `{{ input_name }}` placeholders for inputs with defaults are pre-filled with the default value
- Legacy `{N}` placeholders are also converted
- XPrompts with complex Jinja2 control flow (`{% %}` or `{# #}`) are skipped
- User-defined snippets in `ace.snippets` take precedence over xprompt-derived snippets on name collision

Snippet templates can reuse other snippets with `#[trigger]` after the xprompt snippets and `ace.snippets` entries are
merged. The referenced snippet's `$1`, `$2`, ... tabstops are spliced into the caller and renumbered in document order:

```yaml
ace:
  snippets:
    greet: "Hello $1!$0"
    welcome: "#[greet] Welcome to $1.$0"
```

`welcome` expands as `Hello $1! Welcome to $2.$0`. Positional arguments fill the referenced tabstops before the splice:
`#[greet(World)]` or `#[greet:World]` expands as `Hello World!`.

After the merge, each effective snippet also gains a generated initial-capital alias — only the first character of the
trigger and of the resolved template is uppercased. An xprompt-derived `foo` therefore expands as both `foo` and `Foo`,
already-capitalized triggers produce no extra entry, an explicitly authored `Foo` is never replaced, and both spellings
can be referenced with `#[foo]` / `#[Foo]`. The aliases are runtime-only. See
[docs/ace.md — Capitalized aliases](ace.md#capitalized-aliases) for the complete rule.

Snippets saved from the ACE prompt panel become available immediately to all prompt inputs in that running TUI. With
`use_chezmoi` enabled, this includes a snippet written only to the chezmoi source tree: ACE keeps a session overlay
until the applied config catches up. The optional confirmed commit/push flow applies chezmoi; saving by itself does not
apply unconfirmed source changes.

Editor clients receive the same templates through `sase lsp` when they support LSP snippets. To troubleshoot the raw
registry, run:

```bash
printf '{"schema_version":1}\n' | sase editor helper-bridge snippet-catalog
```

See [docs/ace.md — Snippets](ace.md#snippets) for snippet usage in the prompt input widget and editor completion.

Source: `src/sase/xprompt/snippet_bridge.py`, `src/sase/xprompt/models.py`

## Skill Field

XPrompts can be marked as agent skill sources by setting the `skill` field in their front matter. `sase skill list`
shows the loaded skill catalog without writing files. `sase skill init` reads that catalog, including bundled skill
sources and runtime config overlays, to determine which xprompts should be rendered into per-provider `SKILL.md` files
and deployed to agent skill directories. By default, generated skill files begin with a
`sase skill use <name> --reason ...` directive so SASE can audit which skills an agent used; set `log_skill_use: false`
in a skill source to omit that directive (see below). Recorded skill uses can be summarized and inspected with
`sase skill log`. The compatibility alias `sase init skills` runs the same initializer.

```markdown
---
name: sase_git_commit
skill: true
description: Commit changes using sase commit for git-based VCS
---

Commit instructions here...
```

**Values:**

| Value               | Behavior                            |
| ------------------- | ----------------------------------- |
| `true`              | Deploy to all registered providers  |
| `["claude", "agy"]` | Deploy only to the listed providers |

The `description` field provides a human-readable summary shown in `sase xprompt list` and `sase skill list` output. The
structured catalog also marks these entries with `is_skill: true`; ACE and editor clients use that flag to offer
slash-skill completions such as `/sase_plan` while keeping ordinary xprompts out of slash completion results.

The optional `log_skill_use` boolean field controls the generated audit directive. It defaults to `true`, so generated
skills instruct the agent to run `sase skill use <name> --reason ...` as their first step. Set `log_skill_use: false` to
suppress that directive for skills that should not record their own use (the bundled `/sase_plan` and
`/sase_memory_read` skills set this). The field only affects sources that are also marked as skills.

**Workflow:** Edit packaged skill sources in `src/sase/xprompts/skills/`, or define user/runtime skill xprompts through
the normal xprompt catalog sources. Do not include the `sase skill use` directive yourself; the generator injects it
unless `log_skill_use: false` is set. Then run `sase skill list` and `sase skill init --dry-run` (or `--diff`) to
preview. Commit the source change and land it on the canonical branch before deploying, then run
`sase skill init --force`: a chezmoi deploy is refused when `src/sase/xprompts/` is dirty, when `HEAD` is not an
ancestor of the canonical branch, or when it would move the destination off the source commit recorded in the provenance
manifest — see [Commit Before Deploying](init.md#commit-before-deploying). When `use_chezmoi` is enabled,
`sase skill init` commits, pushes, and applies the generated files unless passed `--no-commit`, `--no-push`, or
`--no-apply`. Do not edit deployed `SKILL.md` files directly. `sase init skills` is a compatibility alias for
`sase skill init`.

Provider plugins declare where generated skills should be written. A source can target multiple providers, and a
provider can have multiple filesystem targets. Built-in targets are:

| Provider          | Skill target(s)                                     |
| ----------------- | --------------------------------------------------- |
| Claude            | `~/.claude/skills/<skill>/SKILL.md`                 |
| Codex             | `~/.codex/skills/<skill>/SKILL.md`                  |
| Antigravity (agy) | `~/.gemini/antigravity-cli/skills/<skill>/SKILL.md` |
| Qwen              | `~/.qwen/skills/<skill>/SKILL.md`                   |
| OpenCode          | `~/.config/opencode/skills/<skill>/SKILL.md`        |

### Bundled Skills

The following skills ship in `src/sase/xprompts/skills/` and are deployed by `sase skill init`. They are packaged with
sase, included in `sase xprompt list`, and available to prompt completion clients even when a checkout does not have
local skill files. Coding agents invoke them by their registered names, such as `/sase_plan` or `/sase_repo`. Runtime
config overlays can add more skill sources, so `sase skill list` may show entries that are not bundled here:

| Skill                | Purpose                                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `sase_agents_status` | Report on currently running SASE agents                                                       |
| `sase_artifact_file` | Create, list, show, resolve, and open SASE artifacts through `sase artifact`                  |
| `sase_changespecs`   | Inspect and reason about ChangeSpecs, commits, hooks, comments, and mentors                   |
| `sase_chats`         | Inspect prior SASE agent prompts and responses                                                |
| `sase_gate`          | Create a durable custom confirmation gate for a proposed command or decision                  |
| `sase_git_commit`    | Commit through `sase commit` for git and GitHub workflows                                     |
| `sase_hg_commit`     | Commit through `sase commit` for the fig VCS workflow where deployed                          |
| `sase_memory_read`   | Perform audited long-term memory reads through `sase memory read`                             |
| `sase_notify`        | Inspect SASE notifications and notification inbox entries                                     |
| `sase_plan`          | Create and submit an implementation plan when provider-native plan mode is disabled           |
| `sase_project`       | Inspect or manage project lifecycle state and aliases                                         |
| `sase_questions`     | Ask the user structured questions when the provider-native question tool is disabled          |
| `sase_repo`          | Open and audit linked, sidecar, other-project, or external repositories before accessing them |
| `sase_run`           | Request an agent-initiated launch through `LaunchApproval`                                    |
| `sase_var`           | Attach named output variables to the current SASE agent run                                   |

## Built-in XPrompts

Core xprompts ship in `src/sase/default_config.yml`, `src/sase/default_xprompts/*.md`, and `src/sase/xprompts/`. They
are always available without needing a project- or user-level definition. They're at the built-in end of the
[discovery order](#discovery-order), so any project, user, or config xprompt with the same name overrides the packaged
defaults. Common entries include:

| Reference             | Body summary                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| `#git`                | Check out a git ref in an isolated workspace and show resulting changes                           |
| `#commit`             | Create a normal commit from completed agent changes                                               |
| `#propose`            | Create a proposal from completed agent changes                                                    |
| `#file`               | Require the agent to write its response to a named markdown artifact                              |
| `#fork`               | Resume context from an agent, a complete clan, or the next completed entity in a tribe            |
| `#fork_by_chat`       | Resume context from a specific chat transcript path                                               |
| `#mentor`             | Run a structured mentor review against a PR                                                       |
| `#split_file`         | Ask an agent to split one large Python file into import-safe smaller files                        |
| `#summarize`          | Summarize a file in a short phrase for a specified use                                            |
| `#tribe`              | Assign an auto-named agent to a user-managed tribe                                                |
| `#json`               | Require the agent response to satisfy a JSON schema                                               |
| `#!sync`              | Sync the current workspace and launch conflict-resolution help if needed                          |
| `#plan`               | Asks the agent to think the work through and use its `/sase_plan` skill before any file changes   |
| `#epic`               | Marks the request as a multi-phase epic and chains `#plan`                                        |
| `#review`             | Asks the agent to fix bugs and apply only clear-win improvements                                  |
| `#prompt/approve`     | Boilerplate "I've edited the previous reply with my decisions; implement this" preamble + `#plan` |
| `#prompt/review`      | Wraps a `prompt` input and asks for a gap/ambiguity review before implementation                  |
| `#x:name,cmd`         | Saves a freeform `sase_xcmd` command to the prompt (`@$(sase_xcmd <name> <cmd>)`)                 |
| `#bd/work_phase_bead` | Per-phase agent prompt used by `sase bead work`; uses the default queue priority                  |
| `#bd/work_task`       | Task-agent prompt used by `sase bead work`; routes distinct follow-ups through `/sase_new_task`   |
| `#bd/land_epic`       | Final lander; reviews all bead notes and routes distinct follow-ups through `/sase_new_task`      |
| `#bd/review/plan`     | Plan-review helper for an epic plan                                                               |
| `#bd/review/prompt`   | Prompt-review helper for an epic plan                                                             |

When `#fork` / `#fork_by_chat` injects a `# Previous Conversation` block, the prior **user prompts** in that block are
sanitized first: sase directives (`%id`, `%wait`, `%model`, ...), `#`/`#!` xprompt and workspace references, and any
unrendered Jinja2 markers (`{{ }}`, `{% %}`, `{# #}`) are stripped so the forked agent sees clean natural-language text.
Fenced code blocks and real markdown headings are preserved, and assistant responses are left untouched. Raw transcripts
on disk are unchanged — the cleanup happens only when building resume history (so `sase chat show` still shows the
original prompts).

`#fork:<clan>` waits for a complete clan generation and injects a launch-ordered clan summary. The summary includes each
member's sanitized prompts, outcome/model metadata, reply size, and transcript path, but deliberately omits full member
replies so the child can open only the transcripts it needs. `#fork:@<tribe>` waits for the earliest completed
standalone agent or complete clan in that tribe launched after the new agent, then injects the matching agent
conversation or clan summary. Multiple `#fork(...)` parents can mix agent, clan, and tribe references; SASE preserves
the declared parent order while removing duplicates.

To see the exact body of any built-in inline xprompt, run `sase xprompt expand --trace '#<name>'` or browse the catalog
with `sase xprompt catalog`. Use `sase xprompt explain <name>` for workflows; the explain command takes the workflow
name without a `#` or `#!` marker.

Bundled task, phase, and lander workers do not author a priority wait, so they use the runner's default priority (`10`)
when otherwise eligible. Higher-precedence project, user, config, and plugin overrides supply their own bodies and may
choose a different priority.

The bundled task worker invokes `/sase_new_task` before recording a genuinely distinct follow-up. The epic lander
reviews the epic's own notes and every child note, keeps unresolved issues caused by the epic inside that epic, and uses
the same skill only for distinct follow-ups. Phase workers remain prohibited from creating tasks and instead append
`PROPOSED FOLLOW-UP:` notes for the lander.

### Bundled Follow-Up XPrompts

SASE ships two embeddable follow-up prompt workflows for manual family rounds:

| Reference        | Inputs                        | Purpose                                                                  |
| ---------------- | ----------------------------- | ------------------------------------------------------------------------ |
| `#with_feedback` | `feedback`, optional `parent` | Append plan feedback using the same replan prompt renderer as the runner |
| `#with_q_and_a`  | `prompt`, `qa_file`           | Append answered SASE questions using the same Q&A renderer as the runner |

Both xprompts only assemble prompt text; `%i(suffix, family=parent)` is the launch directive that attaches the new agent
to the family. See [Agent Clans, Families, and Tribes](agent_families.md) for the full attachment and launch-approval
model.

For feedback, pass `parent=` explicitly or combine it with `%i(suffix, family=parent)` and let SASE infer the parent:

```text
%i(@, family=planner) #with_feedback:: Add failure handling before coding.
%i(reviewer, family=planner) #with_feedback(parent=planner):: Re-check the API shape.
```

For Q&A, provide a JSON file containing one or more answered question rounds:

```text
%i(@, family=planner) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The Q&A file should use the same structured request/response shape SASE writes for user questions: `questions` plus a
`response`, or a top-level `rounds` list of those objects. Literal `#xprompt` text inside answers is protected so it
does not expand accidentally.

Glossary note: this feature uses the runner's double-dash plan-chain family model — agents such as `foo--0`,
`foo--plan`, and `foo--code` share the pure family container `foo`. Dot-separated names such as `foo.bar` are agent
hoods/neighbors in the ACE TUI, a distinct grouping concept. See [Agent Clans, Families, and Tribes](agent_families.md)
for the full family model.

### Scheduled Work Uses Chops

Scheduled automation is no longer implemented by chop-owned xprompt workflows. The former `refresh_docs`,
`audit_recent_bugs`, `audit_recent_improvements`, and `fix_just` workflows were retired. Axe now runs scripts that may
emit structured launch proposals; shared triggers, guards, checkpoints, dedupe, and target fan-out stay in the runner.
Proposal prompts may use inline `#xprompt` templates, but standalone `#!workflow` references are rejected. See
[Axe](axe.md#structured-results-and-launch-proposals) for the script/result contract and the builtin documentation
refresh chop.

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
    description: Greet a user a configurable number of times.
    input:
      name:
        type: word
        description: Name to greet.
      count:
        type: int
        default: 1
        description: Number of greetings to render.
    content: "Hello {{ name }}, count is {{ count }}"
```

Config-based xprompts follow project and home file sources and precede plugin/package file resources. Within config,
project `sase/sase.yml` wins over user overlays and base config.

Standalone workflows must be defined as YAML files in an `sase/xprompts/` directory (project or home), a compatibility
`xprompts/` directory, a project plugin, or a built-in package. Top-level `workflows:` blocks in project
`sase/sase.yml`, global `sase.yml`, or `sase_*.yml` overlays are no longer supported and will be ignored by the runtime;
move any such definitions into `sase/xprompts/<name>.yml` files.

## Local Configuration Files

You can define project-specific xprompts in `sase/sase.yml` at the detected project root. This is a full SASE config
file that can override any configuration, including xprompts. It is the highest-priority config source in the
[deep-merge system](configuration.md#deep-merge-system), overriding global `sase.yml`, overlay files, plugin configs,
and built-in defaults. Individual `.md` files in xprompts directories still take precedence over config-defined
xprompts. A root-level `sase.yml` remains an exclusive legacy fallback during the compatibility window.

```yaml
xprompts:
  # Simple format — value is the template body
  propose: "Please propose your changes before applying them."

  # Structured format — with typed inputs and/or output
  greet:
    description: Greet a user a configurable number of times.
    input:
      name:
        type: word
        description: Name to greet.
      count:
        type: int
        default: 1
        description: Number of greetings to render.
    content: "Hello {{ name }}, count is {{ count }}"
```

## Directives

Directives are in-prompt tags with a `%` prefix that modify agent runner behavior. They are extracted and stripped from
the prompt before further processing.

### Supported Directives

| Directive | Alias | Description                                                            |
| --------- | ----- | ---------------------------------------------------------------------- |
| `%model`  | `%m`  | Override the LLM model for this prompt                                 |
| `%effort` | `%e`  | Set the reasoning-effort level (e.g. `%effort:xhigh`)                  |
| `%id`     | `%i`  | Assign an id, clan, family, or user-managed tribe                      |
| `%clan`   | `%c`  | Declare a new named, rootless parallel agent clan                      |
| `%wait`   | `%w`  | Wait for agents, closed beads, a time floor, and/or a runner threshold |
| `%hide`   | `%h`  | Hide the agent from the default Agents tab display                     |
| `%auto`   | `%a`  | Request automatic gate resolution; an optional argument is gate-owned  |
| `%repeat` | `%r`  | Run the prompt multiple times (e.g., `%repeat:3`)                      |
| `%alt`    | `%{}` | Split prompt into variants with different text (brace shorthand)       |

Agent identity uses `%id` or its `%i` alias. The retired `%name` and `%n` prompt directives are not launch aliases.
Using either as a top-level directive now raises a migration error that points to `%id` / `%i` and, for clan membership,
the `%id(<id>, clan=<clan>)` form.

The retired `%tribe` and `%t` directives also raise a migration error. Use `%id(<id>, tribe=<tribe>)`,
`%id(tribe=<tribe>)` / `#tribe:<tribe>`, or `%clan(<clan>, tribe=<tribe>)` according to the identity being tagged.

### Syntax

Directives use the same argument syntax as xprompt references:

```
%model:claude-sonnet         # Colon syntax
%model(claude-sonnet)        # Parenthesis syntax (single value only)
%model:`claude-sonnet-4`     # Backtick syntax (for values with special chars)
%model:codex/o3              # Provider/model syntax — switches both provider and model
%m:agy/gemini-3.6-flash-high # Provider/model value with a stable Antigravity slug
%model:opencode/anthropic/claude-sonnet-4-5 # Nested provider/model syntax
%model(opus, coder=codex/gpt-5.6-sol) # This agent uses opus; its coder follow-up uses Codex
%model(coder=@medium_phase_worker) # Leave this agent on the default; route @coder through another alias
%effort:xhigh                # Set the reasoning-effort level for this prompt
%e:xhigh                     # Same, using alias
%effort:%{medium | high | xhigh} # Fan out directive values
%model:opus@xhigh            # Model + reasoning-effort suffix (alias: %m:opus@xhigh)
%{%m:opus@xhigh | %m:sonnet@low} # Per-branch effort via fan-out
%id:reviewer               # Short-form
%i:reviewer                  # Same, using alias
%i(reviewer, family=parent)  # Attach parent--reviewer to parent's family
%i(@, family=parent)         # Attach the next free feedback/Q&A suffix
%id(worker, clan=research)   # Derive research.worker and join clan research
%id(!worker, clan=research)  # Same derived name, with forced reuse
%id(reviewer, tribe=review)  # Name reviewer and assign it to tribe @review
%id(tribe=review)            # Auto-name the agent and assign tribe @review
#tribe:review                # Built-in shorthand for %id(tribe=review)
%id                        # Bare — auto-generates a unique name
%id:!reviewer              # Force reuse by wiping the previous owner
%clan:research.{@1}          # Declare a keyed template clan; this member uses a full hood-qualified id
%c:research.{@1}             # Same, using alias
%id:research.{@1}.cdx        # Keyed template; same key resolves together across the dispatch
%id(image, clan=research.{@1}) # Join the same keyed clan and derive research.{@1}.image
%id:outer.{@shared!}.lead    # Already-qualified key; share deliberately across nested swarms
%clan(research, tribe=review) # Declare a new clan in tribe @review
%clan(research, summary="Audit the authentication boundary") # Store a launch-time clan description
%clan(research, summary_script=./describe-clan) # Generate that description with an executable
%clan(research, summary_script=[[sase_clan_summary_plan "plans/research plan.md"]]) # Pass quoted script argv
%clan:research:: Audit the authentication boundary. # Text block; ends at the next top-level % or # line
%wait:agent1                 # Wait for agent1
%w:agent2                    # Wait for agent2 (alias)
%wait                        # Bare — waits for the most recently named agent
%wait:agent1,agent2          # Multi-value: equivalent to two separate %wait: lines
%wait(agent1, agent2)        # Same, paren form
%wait:@review                # Wait for the next completed @review agent or clan
%wait(bead=sase-87.2)        # Wait for a bead in this project to close
%wait(agent1, bead=sase-87.2) # Require both the agent and bead conditions
%wait(time=5m)               # Wait for 5 minutes before starting
%wait(time=1h30m)            # Wait for 1 hour 30 minutes
%wait(time=90s)              # Wait for 90 seconds
%wait(time=1430)             # Wait until 14:30 today (wraps to tomorrow if past)
%wait(time=260415/0900)      # Wait until 2026-04-15 at 09:00
%wait(agent1, time=5m)       # Wait for agent1, then a 5-minute floor
%wait(runners=3)             # Start when at most 3 agents are already running
%wait(runners=0)             # Drain barrier: start after all running agents stop
%wait(priority=1)            # Join the runner queue ahead of larger priorities
%wait(agent1, time=5m, runners=1) # Dependencies, then time floor, then runner gate
#t:5m                        # Shorthand for %wait(time=5m)
%repeat:3                    # Run the prompt 3 times
%r:5                         # Same, using alias
%{#review | #test}           # Brace shorthand: branches split on top-level `|`
%alt(#review,#test)          # Long form: same two variants, comma-separated
%(#review,#test)             # Legacy shorthand, still accepted (prefer `%{...}`)
%{sec=#review | perf=#test}  # Named branches become child name suffixes
%{extra instructions}        # Single branch: split into with/without variants
%auto                        # Request automatic gate resolution using its default
%a                           # Same, using alias
%auto:plan                   # Compatibility alias for normal-plan auto-approval
%auto:tale                   # Plan first, then auto-approve & commit as a tale
%auto:epic                   # Plan first, then auto-approve & commit as an epic
```

Model names containing spaces or parentheses must use the quoted parenthesis form (for example,
`%m("provider/Model Name (Variant)")`); colon syntax cannot express those values.

The `%clan` directive and the `clan=` keyword on `%id` request execution-neutral membership in a rootless parallel agent
clan. Adding membership does not change the model, waits, fan-out, spawn order, VCS/project context, or workspace
behavior; it only adds clan metadata and strips the directive before model execution. The clan name is a reserved
container, never an agent. `%clan` is a create-only declaration, requires an explicitly hood-qualified member name, and
may appear for a resolved clan in only one prompt per launch. It errors if that clan already exists. Use
`%clan(<name>, tribe=<tribe>)` to assign one authoritative tribe to the generation. Every other member uses
`%id(<id>, clan=<clan>)`, which derives `<clan>.<id>` and joins the newest generation or creates the clan implicitly
without a tribe. The join form cannot be combined with `%clan`; joining a clan also joins its tribe. A member segment
may fan out, and identical raw clan templates in one batch resolve to the same generation. See
[Agent Clans, Families, and Tribes](agent_families.md) for the full launch, wait, display, and cleanup contract.

The declaring `%clan` can also attach one launch-time description with `summary=`, `summary_script=`, or the
`%clan...::` text-block shorthand. These forms are mutually exclusive, and clan joiners cannot replace the description.
The `::` form requires a following space and captures up to the next top-level line beginning with a `%` directive or
`#` reference. The captured text becomes metadata rather than member instructions; use the explicit `summary=` form when
the work prompt follows immediately. Script-backed summaries may run synchronously during directive extraction and again
after the primary workspace, sidecars, and linked repositories are prepared. Both attempts share the same 20-second,
non-fatal contract and clan/epic environment; the last successful non-empty output wins. Scripts must be read-only and
idempotent because runner re-exec can repeat them. `summary_script=` may contain shell-style quoted argv (without
invoking a shell), and `sase_clan_summary_plan PLAN_REF` renders a valid tale or epic with the shared PLAN-lane layout;
without `PLAN_REF`, it uses `SASE_EPIC_PLAN_REF`. Scripts inherit the environment available to each attempt, including
epic `SASE_EPIC_PLAN_REF`, `SASE_EPIC_PLAN_SNAPSHOT`, `SASE_EPIC_BEAD_ID`, `SASE_PHASE_BEAD_ID`, and
`SASE_EPIC_CLAN_TRIBE`, while SASE overrides the clan identity variables. The snapshot is an absolute project-scoped
best-effort copy that the built-in epic summary script uses as a guaranteed-local fallback after the normal checkout
candidates; the original reference remains authoritative for display and metadata. See
[Launch-time clan summaries](agent_families.md#launch-time-clan-summaries) for the complete ordering, execution, and
persistence details.

The `%model` directive also supports automatic provider resolution: known model names (e.g., `opus`, `o3`,
`qwen3.6-plus`) are automatically mapped to their provider. See
[Per-Prompt Provider Switching](llms.md#per-prompt-provider-switching) for the full model-to-provider mapping. ACE and
the xprompt LSP complete `%model:` / `%m:` values from the same model catalog used for provider resolution. The inserted
value is a canonical model name or configured alias; provider short aliases are only filter/display hints.

Model aliases are listed beneath the concrete model names. Each alias row shows its kind (`default`, `role`, `coder`, or
`custom`), the `PROVIDER(model)` target it currently resolves to — with an ` @ <effort>` suffix when the alias carries
one — and its provenance (`configured`, `implicit → @fallback`, `override`, plus a `· pool 2/3` chip for round-robin
selectors). Typing `@` right after the colon (`%m:@`) narrows the menu to aliases only; a bare partial such as `de`
still matches `@default` through its bare name, but always after the model rows. The ACE menu reflects active temporary
alias overrides, while the LSP's catalog is a launch-time snapshot that does not — restart the LSP to pick up config
changes, and use the ACE [Models panel](ace.md#models-panel) (`,m`) to inspect live override state.

### Launch-Scoped Model Alias Overrides

The parenthesized `%model` form accepts keyword arguments that temporarily replace model aliases for one launch lineage:

```text
%model(opus, coder=codex/gpt-5.6-sol, small_phase_worker=@cheap)
%model(xsmall_phase_worker=@cheaper, medium_phase_worker=@default@high)
%model(large_phase_worker=@smart, xlarge_phase_worker=@smartest)
%model(coder=@medium_phase_worker)
```

The optional positional value selects the current agent's model. Each `alias=value` entry changes how that bare alias
resolves. Without a positional value, the current agent still starts from the normal default, but that resolution uses
the map: `default=...` changes it directly, while a size-specific phase-worker keyword affects only that phase or task
route. The size-specific worker aliases and implicit defaults are:

| Route           | Alias                 | Implicit default      |
| --------------- | --------------------- | --------------------- |
| `xsmall` worker | `xsmall_phase_worker` | `@cheaper`            |
| `small` worker  | `small_phase_worker`  | `@cheap`              |
| `medium` worker | `medium_phase_worker` | `codex/gpt-5.5@xhigh` |
| `large` worker  | `large_phase_worker`  | `@smart`              |
| `xlarge` worker | `xlarge_phase_worker` | `@smartest`           |

Legacy tasks without stored size metadata normalize to the `small_phase_worker` route at launch.

Keys must be known builtin or custom alias names without `@`; values may be concrete models, `provider/model` targets,
quoted targets, xprompt references, or another alias with `@`. A trailing reasoning-effort suffix is supported on a
single-target value, including an alias reference such as `@default@high`.

"Launch-scoped" describes persistence, not every subprocess the agent starts. SASE records the map in agent metadata and
carries it through its plan/coder follow-up path. An explicit `%id(suffix, family=parent)` attachment inherits the
parent's map when its prompt supplies no alias keywords; a prompt with its own keywords uses that new map. Ordinary
nested launches do not inherit the map. This lineage often overlaps an [Agent Family](agent_families.md), but the terms
are not interchangeable.

At each alias hop a launch-scoped value wins over a machine-wide temporary override and the configured or implicit alias
value. A generic `coder` entry also controls a provider-specific alias such as `claude_coder` unless the map contains
that provider-specific key. The `default` key wins over the machine-wide default override for this lineage.

The launch preview shows the resulting map before approval. Invalid alias names, missing values, duplicate keys,
self-references, and ambiguous bare alias values fail with a directive error. Use `@medium_phase_worker`, not
`medium_phase_worker`, when the value should reference another alias.

A `%model` value may carry a trailing `@<effort>` reasoning-effort suffix (e.g. `%model:opus@xhigh`); the effort is
split off the clean model and behaves exactly like a standalone `%effort` directive. See the
[Effort Directive](#effort-directive) below.

The `%id` and `%wait` directives can be used without arguments. Bare `%id` auto-generates a permanent unique name for
the agent. `%id(<id>, clan=<clan>)` derives the full `<clan>.<id>` name and requests membership in that clan. Dotted ids
are allowed, and a leading `!` forces reuse of the derived name. `%id(<id>, tribe=<tribe>)` tags an explicit id, while
`%id(tribe=<tribe>)` and `#tribe:<tribe>` tag an auto-named agent. The `clan=`, `family=`, and `tribe=` keywords are
mutually exclusive, and none can be combined with a `%clan` declaration in the same prompt. Bare `%wait` resolves to the
most recently named agent (raises an error if no previous agent exists).

Agent-name templates contain exactly one marker: either the bare `@` marker or a keyed marker written `{@<id>}` or
`{@<id>!}`. The marker is not a wildcard; SASE replaces it with the next token from the shared auto-name sequence (`0`,
`1`, ..., `9`, `a`, ..., `z`, `00`, ...). The `<id>` in a keyed marker is one or more alphanumeric segments joined by
dots, such as `{@1}`, `{@research}`, or `{@lead.a}`. A single agent-name value cannot contain multiple markers or mix a
braced marker with a stray bare `@`.

For bare templates, with no reserved names, `%id:@.cld` renders as `0.cld`, `%id:build-@` renders as `build-0`, and
`%id:research.@.final` renders as `research.0.final`; `%id(cld, clan=research.@)` derives that same `research.@.cld`
template before allocation. The older terminal `-@` form still works, but new allocations now start at token `0` and use
the alphanumeric sequence instead of positive integers. Later `%wait`, `#fork`, and `#resume` references can use the
same template text; in one multi-agent launch, SASE rewrites those references to the concrete name already planned for
that template before spawning dependent agents.

Keyed markers resolve once per dispatch before directives are extracted or agent processes spawn. Every occurrence of
the same key in the prompt text gets the same concrete token, including `%id`, `%clan`, `clan=`, `%wait`, `#fork`,
`#resume`, and ordinary prose references such as `research.{@1}.cdx`. The same separator rule as bare templates applies:
with token `o`, `research.{@1!}` becomes `research.o`, `foo{@1!}` becomes `foo-o`, and a marker at the start of a line
becomes `o`.

Inside an xprompt swarm, unqualified keyed markers are implicitly qualified to `{@<xprompt>.<stamp>.<id>!}` while the
swarm expands. That qualification gives each swarm invocation its own key space, even when the same swarm is invoked
more than once in one dispatch. Keys are dispatch-scoped: a later `sase run` or TUI launch allocates fresh tokens rather
than reusing a previous dispatch's table. A trailing `!` means "already qualified" and suppresses the implicit
`<xprompt>.<stamp>.` prefix; use it only when a caller and a nested swarm must deliberately share one hood, for example
`{@shared!}` in both bodies. Outside xprompt swarm expansion, an unqualified keyed marker in a literal prompt or plain
inline xprompt resolves with its literal id, as if it had been written with `!`.

The bare `@` marker remains supported and is not deprecated, but references to a bare template keep the historical
latest-wins behavior. That is unsafe for xprompt swarms whose members can start late, because a later swarm launch can
become the latest matching hood before a deferred member boots. Use keyed markers in xprompt swarms whenever several
segments, waits, clan references, or prose references need the same generated name.

Agent names are permanent IDs. A name that belongs to any existing agent state cannot be reused by a normal `%id:<name>`
launch; SASE cancels the launch before spawning an agent, records the prompt as cancelled, and suggests the lowest free
numeric suffix such as `<name>1`. To deliberately reuse a name, use `%id:!<name>` from the TUI; the `!` form is the
explicit confirmation to wipe the previous owner and its persisted system state before launching the new agent with that
name. Non-TUI launch surfaces reject `%id:!<name>` unless they provide an explicit confirmation path.

The `%i(<suffix>, family=<parent>)` form attaches a new agent to a sequential family. On the first attachment, SASE
renames the original agent with its own `--<role>` suffix and reserves the bare base name as a pure family container;
generic originals become `--0`, while plan proposers become `--plan`. SASE then names the new member
`<family-base>--<suffix>`, writes the normal family metadata, and strips the directive before the model sees the prompt.
The positional suffix is a bare token: write `%i(reviewer, family=foo)`, not `%i(--reviewer, family=foo)`.

Reserved suffixes (`plan`, `q`, `code`, `epic`, `commit`) select their built-in family roles and status labels. Numeric
suffixes and `@` are feedback/Q&A rounds; `@` allocates the next free suffix. Other alphanumeric suffixes such as
`reviewer` or `tester` are allowed, preserve that open-set role in `agent_family_role` metadata, and use ordinary
RUNNING/DONE status labels. See [Agent Clans, Families, and Tribes](agent_families.md) for attachment and
agent-initiated launch behavior.

If the parent is still running, the new family member appears immediately as a WAITING row and starts when that exact
parent artifact completes successfully. If the parent fails, is stopped, or is killed, the queued member is cancelled to
`STOPPED` and SASE sends a completion notification explaining the failed dependency. If the parent is absent, ambiguous,
dismissed, or the composed child name already exists, launch preparation fails before spawning the child; collision
errors suggest `%i(@, family=parent)`.

The family-attach form works from every normal user launch surface because the constraint check runs in shared launch
preparation. In a multi-agent prompt, `%i(suffix, family=parent)` may reference a parent explicitly named in an earlier
`---` segment of the same prompt, such as `%i:foo` followed by `%i(reviewer, family=foo)`. The in-batch parent is
treated as a running parent: the member queues as a WAITING child and starts when that exact parent artifact completes
successfully. This same-prompt lookup is limited to earlier static names; template-named and auto-named parents still
require the parent artifact to exist before they can be used as `%i(suffix, family=parent)` targets.

Named `%wait` dependencies unblock only after the newest matching agent run has a `done.json` outcome of `"completed"`.
For a clan name, every member of its newest generation must complete successfully; for a family or multi-agent workflow
name, every member or child must complete successfully. An exact agent name still targets only that agent. Failed,
killed, crashed, still-running, malformed, or missing `done.json` artifacts do not satisfy the wait; the dependent agent
stays parked until a later successful run of the same dependency name appears.

The repeatable `bead=<bead-id>` keyword adds a closure condition from the waiting agent's own project bead store. Every
named agent/artifact condition and every bead condition must resolve before the wait releases; a missing bead, missing
store, or read error keeps the agent parked. For example, `%wait(build, bead=sase-87.2)` requires both the successful
`build` agent and closed bead `sase-87.2`. Multiple `bead=` values preserve their authored order and are deduplicated.
Bead-only waits do not name an agent, so they do not participate in bare-wait rewriting, agent-name templates, or
cross-project lookup. Once a wait releases, reopening the bead does not re-park the agent.

An `@<tribe>` dependency has next-entity semantics. `%wait:@review` ignores older tribe members and selects the earliest
successfully completed eligible entity launched after the waiting agent: one standalone agent or one whole clan
generation. A tribe-assigned clan member enrolls its generation, which becomes eligible only when the normal aggregate
clan wait succeeds. `#fork:@review` implies this same wait and then resumes from the selected agent conversation or
every member's launch-ordered prompt and reply summary in the selected clan; full clan-member replies remain available
through the included transcript paths rather than being injected automatically. Tribe names use letters, digits,
underscores, dots, and dashes after the leading `@`.

A submitted plan awaiting review is the one exception. A planner that ran `sase plan propose` blocks in the approval
flow without writing a `done.json`, so its planner row shows the `PLAN` status. A `%wait` on that planner row — its
canonical `<base>--plan` name (or a legacy `<base>.plan` spelling) — treats the submitted plan as done and unblocks
while the plan is still in review. This targets the planner row only: a `%wait:<base>` on the bare family container
stays parked until the whole plan chain actually completes, so a submitted plan alone never makes the chain look
finished.

When a launch has exactly one explicit `%wait:<name>` dependency and no explicit `%id`, SASE can allocate a derived name
before spawning the waiting agent: `<name>.w0`, `<name>.w1`, and so on, using the first free template token. After
`<name>.w9`, letter-leading IDs gain a separator (`<name>.w-a`, `<name>.w-b`, and so on) to keep the name readable.
Multi-value waits, tribe targets, bare `%wait`, and prompts whose name depends on unresolved xprompt expansion do not
get a parent-side derived name. Repeat launches reuse this rule, then chain later repeat slots with
`%wait:<previous-slot-name>`.

Fork/resume names follow the same sequence: `<name>.f0` through `<name>.f9`, then `<name>.f-a`, `<name>.f-b`, and so on.
Retries use `<name>.r0` through `<name>.r9`, then `<name>.r-a`, `<name>.r-b`, and so on. If a prompt includes both
`#fork`/`#resume` and `%wait`, the fork-derived `.f@` template takes precedence over the wait-derived `.w@` template.
The wait still controls launch ordering, but the planned agent name follows the resume/fork lineage. A tribe fork uses a
neutral auto-name because the concrete parent entity is deliberately unknown until its wait resolves.

The `%wait` directive also accepts a `time=` keyword to defer launch by a duration or until an absolute wall-clock time.
For a pure time wait, `#t:<time>` is shorthand for `%wait(time=<time>)`.

- **Durations** in `XhYmZs` format (e.g., `%wait(time=5m)`, `%wait(time=1h30m)`, `%wait(time=90s)`, or `#t:5m`). When
  multiple `time=` durations are specified, the maximum is used.
- **`HHMM`** — wait until that time today (e.g., `%wait(time=1430)` for 14:30). If the time has already passed, it wraps
  to tomorrow.
- **`yymmdd/HHMM`** — wait until a specific date and time (e.g., `%wait(time=260415/0900)` for 2026-04-15 at 09:00).
  Raises an error if the target is in the past.

Agent and bead dependencies, `time=`, and `runners=` combine across `%wait(...)` directives. All dependencies wait
first, then the time floor applies, and the runner-slot gate is the final admission stage. Primary and linked-workspace
preparation starts only after admission, so admitted runner counts include that preparation work.

The `runners=N` keyword is a per-prompt threshold, not a reservation of future capacity: the agent starts only when at
most `N` other slot-participating user agents are holding slots. It overrides the effective `max_running_agents - 1`
threshold for that launch, so it can either lower or raise the effective limit. Among waiters eligible at the current
running count, the lowest numeric `priority=N` starts first, with FIFO ordering among equal priorities. That sort only
compares waiters already parked when a slot frees, so a waiter whose priority is numerically worse than the `10` default
additionally holds back for a bounded deference window rather than claiming the instant it becomes eligible. Default-
and better-priority waiters (`priority=10` or lower) never defer and start on the first eligible poll. A deprioritized
waiter defers only while a live, unstarted agent with a better priority has not yet joined the queue and could still
plausibly arrive; when no such agent remains it claims immediately, and the window resets whenever the waiter stops
being eligible, so time parked behind a full cap does not count toward it. The window is `min((priority - 10) * 3, 60)`
seconds by default and is configurable through [`runner_slots`](configuration.md#runner_slots). There is no priority
aging—deference delays a volunteer, it never improves a waiter's own priority and never preempts a running agent—so a
steady stream of higher-priority arrivals can still starve default- or lower-priority waiters. An older waiter with a
lower, currently ineligible threshold does not block eligible launches. `runners=0` is therefore a drain barrier that
waits for true quiescence. Newer eligible launches can start while it is parked and keep it waiting until they also
finish. Both values must be non-negative integers and may each appear only once across a prompt's `%wait` directives;
priority defaults to `10`.

Without an explicit `runners=`, the effective global `max_running_agents` value limits concurrent slot-participating
user agents (configured default `10`; an active `~/.sase/max_running_agents_override.json` value wins). Participants are
top-level user agents—including every clan member launched independently—plus parallel family members, even when ACE
renders them as nested rows. Immediate participating launches claim a slot before workspace preparation; dependency,
time, and fork waiters remain uncounted until those prerequisites resolve. Serial family follow-ups, workflow
Python/bash steps, and axe ChangeSpec runners do not consume these slots.

A slot participant that pauses at `QUESTION` temporarily yields its slot while waiting for the user's answer. Answering
does not bypass the cap: before follow-up work resumes, the agent reacquires capacity through the same locked
priority/FIFO gate using the current effective global `max_running_agents` limit. If the cap is full, the answered agent
appears as a normal runner-slot `QUEUED` row until admitted. Its original `%wait(runners=N)` threshold governed initial
admission and is not reapplied to this resume, while its authored `priority=N` is retained for admission under the
current global cap.

This temporary question yield does not make `%wait(runners=0)` exclusive. A drain-barrier launch may enter during the
pause, and other work may still enter after that barrier is admitted whenever its own threshold permits; the answered
agent then waits for capacity like any other eligible launch.

Absolute time waits cannot be combined with duration waits or with each other.

The old `%time:<value>` spelling is no longer accepted; use `#t:<value>` or `%wait(time=<value>)`. Every positional
`%wait` value is an agent or workflow name, including time-shaped values such as `%wait:4h` and `%wait:1430`. Timed
waits must use `%wait(time=<value>)` or `#t:<value>`.

Multi-value directives (`%wait`, `%model`, `%alt`) accept comma-separated arguments to collapse what would otherwise be
several lines: `%wait:agent_a,agent_b` is equivalent to two separate `%wait:` directives. Backtick-quoted values (e.g.
`` %wait:`a,b` ``) are treated as a single literal and not split on commas.

The `%hide` directive is a boolean flag — it takes no arguments and is simply present or absent. The `%auto` directive
defaults to plan mode when bare and accepts `:plan`, `:tale`, or `:epic`.

### Example

```
%model:`claude-sonnet-4-20250514`
%id:code-reviewer
%wait:planner
Review the code changes and provide feedback.
```

The directives are stripped from the prompt text. The agent will use the specified model, be named "code-reviewer", and
will wait for the "planner" agent to complete successfully before running.

### Effort Directive

The `%effort` directive (alias `%e`) sets the reasoning-effort level the agent's LLM provider should run at.
`%e:<level>` and `%e(<level>)` behave exactly like the `%effort` forms, and both resolve to the canonical `effort`
directive for duplicate/conflict validation and prompt cleanup. Bare `%e` (no level) raises the same "requires a level
argument" error as bare `%effort`.

```
%effort:xhigh
%e:xhigh         # same, using alias
%id:reviewer
Audit this module for subtle concurrency bugs.
```

The canonical effort vocabulary is `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (ordered least → most).
Spelling is validated globally — an unknown level raises a `DirectiveError`. _Which_ levels a given provider actually
honors is decided per provider; see the [provider support matrix](llms.md#reasoning-effort) in the LLM docs.

You can also attach an effort to a `%model` value with a trailing `@<effort>` suffix instead of a separate directive:

```
%model:opus@xhigh            # opus, run at xhigh effort
%m:codex/gpt-5.6-sol@high        # alias form, with an explicit provider/model
```

The suffix is split off the clean model before alias/provider resolution, so the resolved model stays `opus` /
`codex/gpt-5.6-sol`. To preserve an `@` that is genuinely part of a model id, wrap the value in a backtick literal
(`` %model:`literal@id` ``) — backtick literals are never split.

The `@effort` suffix works per branch in a fan-out, so different variants can run at different efforts (and the effort
token is stripped from the generated agent-name suffixes):

```
%{%m:opus@xhigh | %m:sonnet@low}
Try this two ways and compare.
```

To keep the model fixed and fan out only effort values, put the alt group after `%effort:`:

```
%m:opus %effort:%{medium | high | xhigh}
Run the same prompt at three effort levels.
```

If both a `%model:...@x` suffix and a separate `%effort:y` survive into the same final prompt branch with `x != y`, SASE
raises a `DirectiveError`; equal values are allowed.

When no `%effort` (or `@effort`) is given, the agent falls back to the `llm_provider.default_effort` config value, and
then to the runtime's own default. An _explicitly_ requested effort that the chosen provider cannot honor is an error,
while a config-default effort is best-effort (silently skipped with a warning on providers that don't support it). See
[Reasoning Effort](llms.md#reasoning-effort) for the resolution precedence and per-provider support.

### Hide Directive

The `%hide` directive marks an agent as hidden. Hidden agents are not shown in the Agents tab by default — press `.` to
toggle their visibility. This is useful for background agents spawned by axe or workflows that don't need active
monitoring:

```
%hide
%id:background-checker
Run periodic health checks.
```

### Auto Directive

The `%auto` directive (alias `%a`) requests automatic resolution when the agent reaches a notification gate. The
directive parser retains its optional raw argument without applying a global enum; the adapter for the gate kind
interprets and validates that argument. Consequently, an opaque spelling such as `%auto:foo` is valid directive syntax
and reaches the adapter, which may reject it as unsupported.

Bare `%auto` asks each adapter for its default automatic choice. A tale plan gate uses normal approval, an epic plan
gate uses epic approval, and a question gate selects the first listed option for each question. Launch approval gates
reject automatic resolution and must be answered explicitly.

```
%auto
%id:auto-fixer
Fix the lint errors in the codebase.
```

ACE and the xprompt LSP suggest `plan`, `tale`, and `epic` as compatibility arguments for plan workflows; those
suggestions are not a parser allowlist. `%auto:plan` explicitly selects normal approval for an authored tale plan,
`%auto:tale` auto-approves and commits an authored tale, and `%auto:epic` follows the authored epic path. The plan
adapter rejects unknown arguments and tier-changing combinations such as `%auto:epic` on a tale or `%auto:tale` on an
epic. Other adapters own different vocabularies: for example, the question adapter also accepts `first`, while the
launch adapter accepts no automatic argument or default.

When an agent launched with `%auto:tale` later submits a plan with `/sase_plan` or `sase plan propose`, sase
auto-approves and commits it as an SDD tale in the resolved plans root's `<YYYYMM>/` directory and launches the coder
follow-up — the same path as the TUI Tale action. Use `sase repo path plans` instead of assuming whether the root is
in-tree, a legacy `.sase/sdd/` clone, or the split `--plans` sidecar:

```
%auto:tale
%id:cleanup-tale
Tidy up the logging module.
```

### Editor Review Marker (` @`)

The old `%edit` directive has been removed. To compose a prompt in `$EDITOR` (via `Ctrl+G`) and then review or tweak it
in the ACE prompt bar instead of launching immediately, end any line of the editor buffer with the exact suffix ` @` (a
space followed by `@`):

```
Refactor the parser module to use dataclasses. @
```

This is an editor-return syntax, not a runtime directive — it is only recognized in text handed back from the external
editor. Typing ` @` directly in the prompt bar and submitting has no special behavior, and the marker carries no meaning
in CLI, mobile, or workflow execution. Submitting a leftover `%edit` from an old buffer raises a `DirectiveError`
pointing here rather than silently launching. (`%e` is no longer an `%edit` alias — it is now the `%effort` alias.)

When at least one line ends with ` @`, the marker is stripped from every matching line and the cleaned text is loaded
back into the prompt input bar; the agent is not launched until you press Enter there. The returned text loads with
editor-file semantics: real multi-agent `---` segment separators (outside fenced blocks and leading YAML frontmatter)
split the ACE prompt stack into one editable pane per agent segment, and any leading xprompt frontmatter is lifted into
the prompt properties panel above the top pane. Because the strip runs before this parsing, a marked separator line such
as `--- @` becomes a real `---` separator. See [Prompt Stacks](ace.md#prompt-stacks) in the ACE docs for the full review
flow.

### Plan Approval and Coder Follow-up {#plan-directive}

SASE's planning workflow is driven by the `/sase_plan` skill together with the `sase plan` approval pipeline. An agent
drafts a plan and submits it with `/sase_plan` (or `sase plan propose`); the plan then pauses for user approval before
any execution. In the TUI, the agent shows a PLAN status after submitting the plan for review, then PLAN APPROVED once
the user approves it. The `%auto:tale` and `%auto:epic` modes opt a planning agent into this same pipeline with
automatic tale or epic approval.

Once the plan is approved, sase launches a follow-up **coder** agent using the same handoff body as the `#coder`
built-in xprompt (see [sase/xprompts/coder.md](https://github.com/sase-org/sase/blob/main/src/sase/xprompts/coder.md)).
`#coder` takes the approved plan file as its `plan_file` input, injects it with `@`, and instructs the agent to
implement the plan. By default the coder does _not_ inherit the planner's chat transcript — the plan file is the
hand-off artifact. Set `SASE_CODER_INHERIT_PLANNER_CHAT=1` to restore the old behavior, in which case a
`#fork:<planner_name>` reference is prepended to the coder prompt so it resumes the planner's session. The coder prompt
also carries a `%model:` directive. A model chosen at approval time (or a `%model:`/`%m` directive inside a custom coder
prompt) wins. When no model is chosen, the follow-up routes through the planner provider's **coder alias**: a
Claude-authored plan emits `%model:@claude_coder`, a Codex plan `%model:@codex_coder`, and so on for every registered
provider. When the planner is missing provider metadata the follow-up falls back to the generic `%model:@coder`.
`@claude_coder` and `@codex_coder` remain distinct planner-provider aliases, but like every registered
`@<provider>_coder` alias they inherit `@coder`, whose shipped value is `codex/gpt-5.5`. Explicit launch-scoped coder
values and provider-specific temporary/configured values take precedence before the generic temporary/configured or
implicit `@coder` value. Configure `llm_provider.model_aliases.builtin.<provider>_coder` to route one provider's coder
follow-ups elsewhere (see [Configured Model Aliases](llms.md#configured-model-aliases)). The recorded follow-up metadata
resolves the alias to the concrete model the coder actually launches with.

Outside the TUI, `sase plan` shows the same pending PlanApproval notifications plus recent approved and inferred
rejected archived plans. Use the `id_prefix` from a Proposed row with `sase plan approve <id-prefix>` to use the
authored plan tier, add `--kind approve|commit|epic|tale` for an explicit override, or `sase plan reject <id-prefix>` to
reject. The `approve` kind runs the coder without committing an SDD plan; `tale` commits an SDD tale and runs the coder;
`epic` commits the matching SDD tier and launches the bead follow-up; `commit` records the approved plan in SDD without
launching a coder. `-m/--model` picks the follow-up agent's model, while `-p/--prompt` adds extra coder instructions for
the `approve` and `tale` paths. Tale and epic approvals validate the target schema first and leave an invalid proposal
pending. CLI rejection writes the same no-feedback rejection response as ACE, then attempts to dismiss and user-kill the
matching planner when it can be found.

When an agent launched with `%auto:epic` later submits a plan with `/sase_plan` or `sase plan propose`, sase follows the
same epic path as the TUI Epic action: it writes the SDD epic files, commits them as needed, initializes beads, and
launches the epic follow-up agent. Unlike bare `%auto`, `%auto:epic` is plan-specific and does not automatically answer
unrelated questions.

```
%auto:epic
%id:billing-epic
Plan the billing dashboard epic.
```

### Repeat Directive

The `%repeat` directive runs the same prompt multiple times. The argument is a positive integer specifying the repeat
count:

```
%repeat:3
%id:linter
Run lint checks on the codebase.
```

This launches 3 independent agents — each spawned with its own process, workspace, and `agent_meta.json`, appearing as
its own top-level entry in the Agents tab. Fan-out happens at launch time: the directive is consumed when the agents are
spawned, so there is no outer loop or TUI affordance ticking through iterations. The slot numbers are appended to the
`%id` base (`linter.1`, `linter.2`, `linter.3`); when `%id` is omitted the auto-assigned base is used (e.g. `a.1`,
`a.2`, `a.3`).

Iterations run **sequentially**: all N agents are spawned up front and register immediately in the TUI, but iteration
`k+1` is automatically wait-chained behind iteration `k` via an injected `%wait:<prev_name>` directive. This turns
`%repeat` into a serial iteration primitive — each iteration can observe its predecessor's work — without blocking the
launcher on any single agent.

Each iteration exposes two iteration-scoped named arguments in the agent's workflow:

| Variable | Meaning                                   | Example with `%repeat:5` |
| -------- | ----------------------------------------- | ------------------------ |
| `n`      | Current iteration (1-based)               | 1, 2, 3, 4, 5            |
| `N`      | Total iterations (the `%repeat` argument) | 5                        |

These are threaded through via the `SASE_REPEAT_ITERATION` and `SASE_REPEAT_TOTAL` environment variables — the agent
runner reads them, converts to ints, and passes them as named args into the workflow so they appear as Jinja2 variables
in the prompt body:

```
%repeat:5
Run test suite batch {{ n }} of {{ N }}.
```

#### Stopping a repeat chain early with `STOP`

A repeat iteration can stop every later slot by setting the reserved `STOP` output variable before it completes:

```
%repeat:5
Process the next batch; if there is no more work, run: sase var set STOP=1
```

Because the slots are already spawned and wait-chained, "stopping" works on wake: when a later slot's `%wait` on its
repeat predecessor resolves, the slot checks that predecessor's `STOP` output variable. If it is truthy, the slot
propagates `STOP`, finalizes as a successful **completed** (skipped) slot — recording `repeat_stopped: true` and
`stopped_by` in its `done.json` — and exits without claiming a workspace or running its prompt. Keeping the outcome
`completed` lets the stop cascade down the chain through the ordinary `%wait` resolution, so each remaining slot winds
down one wait-check cycle after the previous one. `STOP` is conservative: `""`, `0`, `false`, `no`, and `off`
(case-insensitive) are not-stop; any other value stops the chain. See
[Cross-Agent Output Variables](#cross-agent-output-variables) for how `STOP` behaves outside repeat chains.

### Alt Directive

The `%alt` directive splits a single prompt into multiple variant prompts, each launched as a separate agent. Each
branch replaces the directive span in the output prompt.

The preferred shorthand is `%{A | B | ...}`, which uses braces and splits branches on top-level `|` separators:

```
%{#review | #test | #docs}
Analyze the codebase.
```

This produces three agents, each with "Analyze the codebase." but with `#review`, `#test`, or `#docs` substituted in
place of the directive. Branches can be arbitrary text — xprompt references, directives, plain instructions, or
`[[text blocks]]`. Because branches split only on a top-level `|`, a comma is ordinary branch text: `%{foo, bar | baz}`
is two branches (`foo, bar` and `baz`), not three. Nested `()`, `[]`, `{}`, and backtick-quoted spans are not split, and
any `|` inside them is treated literally.

You can also fan out just a directive value by putting the alt group after the directive's colon. For example,
`%effort:%{medium | high | xhigh}` expands into three launched prompts with `%effort:medium`, `%effort:high`, and
`%effort:xhigh`; `%m:%{opus | sonnet}` is equivalent to `%{%m:opus | %m:sonnet}`.

The long form `%alt(...)` and the legacy `%(...)` shorthand remain accepted; both use parentheses with comma-separated
branches:

```
%alt(#review, #test, #docs)
%(#review, #test, #docs)
```

New prompts, completions, snippets, and docs should prefer `%{...}`. `%(...)` stays parse-compatible during the
migration; it may be removed in a future release.

#### Named Branches

Branches can be named with `id=value`. The `value` is inserted into the spawned prompt and the `id` becomes the child
agent suffix. For example, `%id:review %{sec=[[security]] | perf=[[performance]]}` launches `review.sec` and
`review.perf`. Unnamed branches use numeric suffixes while skipping any numeric ids already provided by named branches,
so `%{2=[[named]] | [[first]] | [[second]]}` launches suffixes `2`, `1`, and `3`.

When the same named branch id appears in more than one alt directive, those directives are correlated: values with the
same id render into the same child prompt, and a missing id in one correlated directive renders as empty text. Empty
renders also collapse adjacent horizontal whitespace, so they do not leave doubled spaces or spaces before punctuation;
only spaces and tabs are collapsed, newlines and indentation are preserved, and non-empty branches are untouched. For
example:

```
%id:repo %{a=Describe | b=Explain} how this repo works %{a=in detail}.
```

This launches `repo.a` with "Describe how this repo works in detail." and `repo.b` with "Explain how this repo works.".

#### Single Branch (With/Without Split)

A single-branch alt is treated as a with/without split — it produces two prompts: one with the branch text and one with
the directive removed entirely:

```
%{Also check for security issues.}
Review this module.
```

This launches two agents: one with "Also check for security issues. Review this module." and one with just "Review this
module."

#### Cartesian Product

Multiple alt directives can appear in the same prompt. Branch lists with no repeated named ids form a **Cartesian
product**: one agent is launched per combination. Brace and paren forms mix freely:

```
%{Focus on security | Focus on perf} %{%m:opus | %m:sonnet}
Review this code.
```

This produces 2 × 2 = 4 agents (every focus area paired with every model). Model directives used as branches inside
`%{...}` participate in the Cartesian product naturally: `%{#review | %model:opus}` fans out a default-model review
branch and an opus branch.

Repeated named ids are the exception to the Cartesian rule. Disjoint named ids and unnamed branches remain Cartesian;
only the same explicit id repeated across directives is zipped together.

### Multi-Model Fan-Out

The `%model` directive is single-value. To launch multiple agents in parallel — one per model — put one model directive
in each `%{...}` branch:

```
%{%m:opus | %m:sonnet}
Review this code for edge cases.
```

This launches two agents with identical prompts, each using a different model. Each agent appears as a separate entry in
the Agents tab. Comma/paren multi-argument syntax (`%m(opus,sonnet)`) and repeated top-level `%model` directives are no
longer supported; use `%{%m:opus | %m:sonnet}` instead. Colon syntax (`%m:opus`) and single-model parentheses
(`%m(opus)`) launch a single agent.

When a prompt fans out to multiple models, the spawned agents share a single base name and carry a runtime suffix so
they can be told apart at a glance. Given `%{%m:opus | %m:gpt-5.6-sol} %i:foo`, the two agents are named `foo.cld` and
`foo.cdx`. The runtime suffix is a short alias declared by the provider plugin (via the `llm_provider_short_name` hook)
— `cld`, `cdx`, `agy`, `qwn`, `opc` for the built-in providers — falling back to the full provider name for plugins that
don't declare one. If `%id` is omitted, a single auto-generated base is allocated and shared (e.g. `a.cld` / `a.cdx`)
rather than each agent picking its own letter independently. Single-model prompts retain their plain `%id` value
unchanged. When two models share a runtime (e.g. `%{%m:opus | %m:sonnet}` — both `claude`), the model name disambiguates
the suffix: `foo.cld-opus` and `foo.cld-sonnet`. Long model slugs are replaced with a short alias declared by the
provider plugin, so a same-runtime agy fan-out can read as `foo.agy-flash36h` / `foo.agy-flash35h` rather than echoing
the full model string. Model arguments used for naming are first resolved through xprompt shorthand expansion, while the
launched prompt keeps the original `%model` value. For example, `%i:ag %{%m:#flash | %m:#pro}` can launch agents named
`ag.agy-flash35h` and `ag.agy-flash36h`.

### Multi-Value Directives

The `%wait` directive supports multiple occurrences — each adds to the wait list:

```
%wait:agent1
%wait:agent2
%wait:agent3
Do work after all three agents finish.
```

Agent dependencies, time floors, and runner thresholds can be mixed freely:

```
%wait(agent1, time=5m, runners=1)
Wait for agent1 to finish, wait at least 5 minutes from launch, then wait until at most one other slot participant is
running.
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

The closing `%xprompts_enabled:true` marker may appear either on its own line or **inline** at the end of a content
line. In both forms the marker (and any whitespace immediately preceding an inline marker) is stripped from the final
output, so prompts authored as natural prose can re-enable expansion mid-line:

```
%xprompts_enabled:false
... raw content where #foo and @bar are passed through verbatim. %xprompts_enabled:true
And expansion resumes here.
```

## XPrompt Aliases

XPrompt aliases provide raw text-level substitution that runs _before_ any other xprompt processing. They are defined in
the `xprompt_aliases` config field in `sase.yml`.

These are global shorthand aliases for xprompt names and raw refs. They are separate from ProjectSpec `PROJECT_NAME` and
`PROJECT_ALIASES`, which map friendly project refs such as `bob` to canonical directory-key projects such as
`gh_bbugyi200__bob` at the launch boundary. Project names and aliases are canonicalized before xprompt expansion so
launch artifacts and history store the canonical directory-key project name.

The built-in defaults provide two shorthand aliases:

| Alias | Target    | Usage             |
| ----- | --------- | ----------------- |
| `c`   | `commit`  | `#c` → `#commit`  |
| `p`   | `propose` | `#p` → `#propose` |

Additional aliases can be added in user config files:

```yaml
xprompt_aliases:
  gh_sase: "gh:sase" # #gh_sase → #gh:sase
  gh_foo: "gh:foo/bar" # #gh_foo  → #gh:foo/bar
```

When the processor encounters `#alias_name` in a prompt, it replaces the alias name portion with the target string
before any xprompt resolution occurs. This is particularly useful when the target contains characters (like `:`) that
must be present in the raw text for other processing logic — such as VCS directory-switching — to work correctly.

See [Configuration Reference: xprompt_aliases](configuration.md#xprompt_aliases) for the full field specification.

## Recursive Expansion

XPrompt bodies can reference other xprompts. Expansion is iterative: after each round of substitution, the result is
scanned again for new `#name` references. This continues until no known references remain, up to a maximum of 100
iterations (to guard against circular references).

## Stored Prompt Renderings

Saved chats and canonical prompt archives expose related, but not identical, prompt representations:

- The **XPrompt prompt** in a saved chat comes from `raw_xprompt.md` after project and configured xprompt aliases have
  been resolved, but before xprompt expansion. It keeps reusable `#...` references visible.
- A prompt archive's **primary body** normally uses that same pre-expansion artifact for an agent-backed commit.
  Approved planner entries are the exception: their primary body is the dry-expanded, directive-stripped plan snapshot.
- The **rendered prompt** is the final preprocessed prompt SASE passed to the provider invocation. It is stored
  separately and is not linkified. It is not the provider's complete model context, which may also include provider
  instructions and repository context.

During launch, SASE records best-effort provenance for each used xprompt in `xprompt_sources.json`. During chat storage
and commit-backed prompt archive publication, resolvable references in a pre-expansion XPrompt are rewritten as hosted
Markdown links to their definition file, with `#L...` anchors for config-file definitions when the line is known.
Unresolvable references are left exactly as typed; SASE does not invent placeholder links. The primary body is not
size-truncated. A rendered prompt retains at most
[`chat_history.rendered_prompt_max_bytes`](configuration.md#chat_history) UTF-8 bytes and carries an explicit marker if
the rest was omitted.

Use `sase chat show -x` / `sase chat show -r` for the two representations in a saved transcript. For an archive,
`sase agent prompts show PROMPT` prints the primary body and `sase agent prompts show -r PROMPT` prints the stored
provider-prompt representation.

## Multi-Agent Prompts

A single prompt can launch multiple agents by using YAML frontmatter and `---` segment separators. SASE plans the
segments in document order, but agents do not wait for earlier segments unless you add a dependency such as
`%wait:<name>` or bare `%wait`. The same `---`-separator convention also applies inside an xprompt body -- see
[Xprompt Swarms (Library-Defined Fan-Out)](#xprompt-swarms-library-defined-fan-out) below.

### Frontmatter Panel (ACE TUI)

In the `sase ace` prompt input, ad hoc prompt frontmatter has a structured **Frontmatter Panel** above the prompt stack,
with the same field set an xprompt `.md` file supports (`name`, `description`, `tags`, `input`, `xprompts`, `skill`,
`snippet`). Open or focus it with the prompt NORMAL-mode `g=` keymap; in the panel's rows mode, `g=` runs the
deactivate/apply path. `q` or `Esc` in rows mode—or from NORMAL mode inside any panel sub-editor—returns focus to the
prompt pane you entered from; an invalid raw-YAML buffer remains open so it cannot be discarded accidentally. In rows
mode, `gj` jumps directly to the top prompt pane and `gk` to the bottom pane. The panel also auto-shows when ACE has
lifted leading frontmatter into the stack, such as a multi-agent prompt load or an editor-file return from a ` @` review
marker / whole-stack `Ctrl+G`. A single prompt recalled from history with leading frontmatter but no segment separator
stays one verbatim pane instead of auto-opening the panel. Typing `---` in the prompt body is passive during live
editing: at the very start it stays literal text, and after content it does not split the active pane. Add a top-level
property with `a` (an inline picker sourced from the same core schema that backs the editor LSP), edit scalar/list
fields inline, delete a field with `d`, undo the latest mutation with `u`, and use `R` for a live-validated raw-YAML
escape hatch. In raw mode, `Ctrl+C` explicitly discards an unparseable buffer. Unknown frontmatter keys remain visible
as raw-only rows and survive structured round trips.

The structured `input` and `xprompts` fields render as foldable sub-trees (`h`/`l`): navigate into them with `j`/`k`,
use `o`/`A` to insert a ghost row, `e`/`enter` to edit an item in place, `d` to delete, and `J`/`K` to reorder. Cell
editing uses `Tab`/`Shift+Tab`; `Enter` commits while remaining in the panel. Input types cycle through the core type
catalog and defaults are live-coerced. Local-helper content uses a bounded multiline editor in the panel. A `#_helper`
declared here lights up `<ctrl+t>`/`<ctrl+l>` completion and argument hints in every prompt pane exactly like a global
xprompt — define a helper in the panel and it is instantly usable below.

ACE can also author existing definitions without `$EDITOR`. In the XPrompt Browser, `Enter` loads a simple Markdown or
config-backed definition as raw body plus structured frontmatter; `E` keeps the external-editor path, and YAML workflow
graphs remain editor-only. A loaded definition is bound to its source: the prompt title shows the source and a dirty
dot, `gw` writes it atomically, and an external-change conflict offers overwrite, reload, or save-as. `gd` on a `#name`
reference loads that definition after stashing the current draft. `gx` is a one-screen save-as view with name, location,
resolved path, and a live collision/overwrite preview.

### Frontmatter-Defined Local XPrompts

YAML frontmatter at the start of a prompt can define local xprompts under the `xprompts:` key. These are defined once in
the frontmatter and each segment receives only the local xprompts it actually references (including transitive
dependencies). Local xprompt names **must** start with `_` to distinguish them from global xprompts.

```
---
xprompts:
  _review_rules: "Always check for error handling and edge cases."
---
#_review_rules
Review the authentication module.
```

Local xprompts support the same structured format as config-based xprompts (typed inputs, Jinja2 content):

```
---
xprompts:
  _template:
    input: { target: word }
    content: "Review the {{ target }} module."
---
#_template(auth)
```

### Frontmatter-Declared Inputs

Prompt frontmatter can also declare `input:` arguments using the same typed shorthand as xprompt files (see
[Typed Inputs](#typed-inputs)). The declared values are substituted into every segment's `{{ name }}` placeholders
before the agents fan out:

```
---
input:
  service: word
  retries: { type: int, description: how many times to retry }
  dry_run: { type: bool, default: false }
---
Refactor the {{ service }} module ({{ retries }} retries, dry_run={{ dry_run }}).
```

When a prompt with required (default-less) inputs or live raw placeholders is submitted in `sase ace`, the **Fill in
this prompt** panel opens after the whole-stack submit. Raw-placeholder fields appear first, followed by typed,
live-validated required inputs; optional inputs stay collapsed behind a reveal toggle and show their defaults when
opened. `Enter` advances through visible fields and launches from the last one once every required value is valid.
`Ctrl+L` keeps the focused raw placeholder literal. `Escape` cancels and returns to the draft; from field INSERT mode,
the first press returns to NORMAL and the second cancels. `path` fields reuse `Ctrl+T` path completion. See
[Raw Prompt Placeholders](#raw-prompt-placeholders) for matching, substitution, and the collection toggle.

Non-interactive CLI launches (`sase run`) cannot prompt, so a required input without a default fails fast with a clear
message instead of a cryptic template error — give such inputs a default or launch from the TUI.

### Segment Separators

After the frontmatter block is consumed, subsequent `---` lines on their own act as segment separators. Each segment
launches as a separate agent:

```
---
xprompts:
  _common: "Follow the project coding conventions."
---
%id:step1
#_common
Implement the new feature.
---
%id:step2
%wait:step1
#_common
Write tests for the new feature.
```

This launches two agents. `step2` starts after `step1` succeeds because the second segment includes `%wait:step1`; if
that line were omitted, both agents would be eligible to run independently. Both agents share the `_common` local
xprompt.

### Cross-Agent Output Variables

Agents can publish small JSON-shaped values for later waited agents or segments with `sase var set`. Values may be
strings, numbers, booleans, null, lists, or maps nested within the documented reliability limits. Give the producer a
stable name and make the consumer wait before referencing the producer's variables. Every producer's variables live
under a single reserved `agents` dictionary keyed by agent name:

```
%id:build-@
Build the report, then run:
sase var set report_path=dist/report.md status=ok
---
%id:review
%wait:build-@
Review {{ agents["build"].report_path }} after the build status is {{ agents["build"].status }}.
```

Use a heredoc through `--value-file -` for a multi-line value:

```bash
sase var set summary --value-file - <<'EOF'
Tests passed.

The release artifact is ready for review.
EOF
```

Add `-j` / `--json` to any input form to decode a structured value. Structured values remain real containers in Jinja,
so consumers can access and iterate them directly:

```
%id:build-@
Run the build, then publish:
sase var set report --json --value '{"passed":true,"suites":["unit","integration"]}'
---
%id:review
%wait:build-@
Build passed: {{ agents["build"].report.passed }}
{% for suite in agents["build"].report.suites %}
- Review the {{ suite }} results.
{% endfor %}
```

Rendering a whole container with `{{ agents["build"].report }}` produces compact JSON instead of a Python
representation. Jinja's `| tojson` filter remains available for explicit formatting. Map keys are sorted for stable
storage and display, while list order is preserved. Run `sase var list` to inspect the current agent's canonical block
display or `sase var list --json` for compact JSON.

The review prompt is rendered after the `build-@` dependency completes, so `{{ agents["build"].report_path }}` and
`{{ agents["build"].status }}` come from the producer's stored `agent_meta.json` values. A consumer that has already
started will not see later writes.

The `agents` key is a stable Jinja namespace for the producer, not always the producer's concrete runtime name.
Agent-name templates use the template base, so a producer that launches as `build-0` from `%id:build-@` is read as
`{{ agents["build"].report_path }}`, not `agents["build-0"]`. The key is otherwise the raw agent name with no identifier
munging, so dotted, hyphenated, and digit-leading names all work via bracket access: `%id:research.@.final` →
`{{ agents["research.final"].report_path }}`, and `%id:0n.cld` → `{{ agents["0n.cld"].report_path }}`. Identifier-safe
keys also support attribute access such as `{{ agents.build.report_path }}`. `agents` is a reserved agent-run Jinja
name; a workflow input named `agents` collides and fails clearly. Output variables are persisted in the producer's
`agent_meta.json` and also appear in ACE's Agents-tab `OUTPUT VARIABLES` metadata section and Telegram agent-completion
messages. They are visible metadata, not secret storage.

`STOP` is a reserved output-variable name, but only for `%repeat` / `%r` chain continuation: setting it stops later
repeat slots (see [Stopping a repeat chain early with `STOP`](#stopping-a-repeat-chain-early-with-stop)). It has no
special meaning for ordinary `%wait` consumers, `---` segments, or `%alt` fan-outs — those read it like any other
variable, e.g. `{{ agents["name"].STOP }}`.

A planner that submits a plan for review (`sase plan propose`) exposes the proposed plan path as a synthesized
`plan_file` variable in the same `agents` namespace, without any `sase var set` call. A later segment in the same
multi-agent prompt reads it under the producer's stable key, and an explicit `%wait` on the planner row reads it under
the canonical `<base>--plan` key:

```
%id:planner
Propose a plan for the feature.
---
%id:coder
%wait:planner--plan
Implement the plan at {{ agents["planner--plan"].plan_file }}.
```

`plan_file` is only ever namespaced under `agents[...]`; there is no top-level `plan_file` variable. An explicit
`sase var set plan_file=...` in the planner wins over the synthesized value, and any other output variables the planner
sets are preserved alongside it.

ACE renders loaded literal `---` multi-agent prompts as a prompt stack: each top-level segment becomes an editable pane,
while prompt-level frontmatter and fenced-code separators keep the same parsing rules described below. A `#name` xprompt
swarm invocation remains a single pane until launch. During live editing, typed `---` lines are ordinary prompt text;
add panes explicitly from the prompt-stack controls. Stash restore and marked-agent kill-and-edit can also seed multiple
panes, but those paths preserve each selected draft or agent prompt as one pane. Use `Enter` to choose how to submit
stacked panes, `g<enter>` to launch the selected pane directly, or `Ctrl+S` to stash the active pane. Inside the `Enter`
submit chooser, `a` or `Ctrl+S` submits all panes top-to-bottom. See the [ACE prompt-stack guide](ace.md#prompt-stacks)
for the editing keybindings and the default active-pane behavior.

### Rules

- The first `---` pair at the start of the document is treated as YAML frontmatter.
- After frontmatter is consumed, all subsequent `---` lines are segment separators.
- If there is no frontmatter, ALL `---` lines are segment separators.
- A prompt with frontmatter but only one segment is a single-agent prompt with local xprompts (not multi-agent).
- `---` inside fenced code blocks is not treated as a separator.
- When a multi-agent prompt is saved to prompt history, each individual segment is also saved as a separate entry. This
  allows segments to appear independently in the prompt history picker for reuse.

### Xprompt Swarms (Library-Defined Fan-Out)

An xprompt itself can be an xprompt swarm: its body contains `---` separators (outside fenced blocks), and referencing
it as the sole content of a user-prompt segment fans the call out into one agent per body segment. The spawned agents
share the same input arguments -- each segment is rendered with the same `(args)` substituted in. The catalog, TUI
picker, and completion UI display markdown-defined xprompt swarms with the inline marker (`#name`). The older `#!name`
form is still recognized for xprompt swarms for compatibility, but new prompts should use `#name`.

```
# sase/xprompts/three_phase.md
---
input:
  target: word
---
%id:plan
Draft a plan for {{ target }}.
---
%id:code
%wait:plan
Implement {{ target }} following the plan.
---
%id:review
%wait:code
Review the {{ target }} implementation and propose follow-ups.
```

Invoking it:

```bash
sase run '#three_phase(login)'
```

...dispatches three agents (`plan`, `code`, `review`), each receiving `target=login`. The `%wait` directives chain them
sequentially; without `%wait` they would run in parallel.

For swarm-owned generated hoods, use keyed agent-name markers so every segment and prose reference resolves in the
parent launch before any agent starts:

```text
%id:research.{@1}.cdx
Audit with Codex. Write your report path for `research.{@1}.cdx`.
---
%id:research.{@1}.cld
Audit with Claude. Write your report path for `research.{@1}.cld`.
---
%id(final, clan=research.{@1})
%wait:research.{@1}.cdx,research.{@1}.cld
Summarize both reports.
```

During swarm expansion, each unqualified `{@1}` is rewritten to an invocation-specific qualified key before dispatch, so
overlapping launches of the same xprompt cannot steal each other's clan or hood. Use `{@shared!}` only when a nested
swarm should intentionally share a key with its caller. See [Directives](#directives) for the complete keyed-marker
grammar and dispatch-scoping rules.

Detection happens at dispatch time (after standard `parse_multi_prompt`), in `src/sase/agent/xprompt_swarm.py`, and
applies at every dispatch site (`sase run`, the TUI agent launcher, the query handler).

Xprompt swarms can also be embedded inside a larger prompt. In that case, the first rendered body segment is embedded at
the reference location and the remaining rendered body segments become follow-up agent prompts:

```bash
sase run '#gh:sase Review this first: #three_phase(login)'
```

When the call site starts with a VCS workspace reference such as `#gh:sase`, `#git:feature`, a plugin-provided ref, or a
known-project underscore form such as `#gh_sase`, that workspace reference is inherited by every generated follow-up
segment unless the generated segment already declares its own VCS reference. Leading launch directives stay before the
inherited workspace reference, so a prompt like `%id:abq #gh:sase #three_phase(login)` keeps `%id:abq` attached to the
first generated segment and prefixes `#gh:sase` onto follow-ups.

#### Rules and Limitations

- A sole xprompt swarm reference replaces the whole segment with its generated segments. An embedded xprompt swarm
  reference replaces only that reference with the first generated segment, then appends the remaining generated segments
  as follow-ups.
- A user-prompt segment can contain multiple xprompt swarm references. They expand fully in document order. Text before
  the first reference attaches to the first generated segment only; text between references and after the last reference
  is discarded.
- Ordinary inline xprompt references inside an xprompt swarm body remain inline xprompt references; the agent runner
  expands them later as normal prompt text.
- `---` inside fenced code blocks in the xprompt body is not treated as a separator.
- Recursive fan-out (an xprompt swarm body whose own segments reference more xprompt swarms) is bounded by a depth cap
  and will raise if exceeded.

## Relationship to Workflows

XPrompts and [workflows](workflow_spec.md) share the same argument grammar, but the marker communicates how the
reference is allowed to participate in a prompt:

- `#name(args)` expands inline-capable xprompts and workflows with a `prompt_part` step, including markdown-defined
  xprompt swarms that fan out into multiple prompt segments.
- `#!name(args)` launches standalone YAML workflows that have no `prompt_part` step.

Simple markdown xprompts are converted internally to single-step workflows with a `prompt_part` step, so they remain
inline-capable and continue to use `#name`, even when their body contains top-level `---` segment separators.

YAML workflow files can set a top-level `description` and use the same input-description forms as markdown or
config-defined xprompts:

```yaml
description: Refresh generated docs and report drift.
input:
  docs_dir:
    type: path
    description: Documentation root to refresh.
steps:
  - name: refresh
    bash: just docs
```

Workflow agent steps can embed xprompt references inline:

```yaml
steps:
  - name: review
    agent: |
      #mentor(prompt=[[Review error handling]])
```

See the [Workflow Specification](workflow_spec.md) for full details on multi-step workflows, control flow, parallel
execution, and human-in-the-loop approval.

## Troubleshooting

If a launch prompt contains an unknown `#name` reference, SASE warns before launch and passes the text through
literally. This is non-blocking so prose hashtags can still be used, but typos such as `#reviewww` are visible at
`sase run`, `sase xprompt expand`, and from the `sase ace` prompt bar.

If a definition file is malformed, run:

```bash
sase xprompt list
sase doctor -C config.xprompt_definitions
```

Both commands report `skipped: <file>: <error>` lines for xprompt or workflow definitions that could not be loaded.
