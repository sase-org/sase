---
title: Macro CLI and editor support
description: Macro command behavior and editor language-server features.
---

# Macro CLI and editor support

This page documents the macro CLI subcommands and editor language server.

## CLI Subcommands

The `sase macro` command provides seven subcommands for working with macros. With no
subcommand, it defaults to `sase macro list`. Flags belong to the explicit subcommand,
so use forms like `sase macro expand --trace '#plan'` rather than putting `--trace` on
bare `sase macro`.

### `sase macro expand`

Expands macro references in a prompt. Reads from a positional argument or stdin.

```bash
sase macro expand '#greet(Alice)'         # Expand from argument
echo '#greet(Alice)' | sase macro expand  # Expand from stdin
sase macro expand --trace '#plan'         # Show expansion trace on stderr
```

The `--trace` flag prints a detailed expansion trace to stderr showing each resolved
reference, its source file, arguments, and expanded content. This is useful for
debugging reference resolution order and understanding how a complex prompt is
assembled.

### `sase macro explain`

Shows a dry-run visualization of a workflow's execution plan without actually running
it. Displays workflow metadata, input requirements, resolved arguments, and the full
step-by-step execution plan with types, control flow annotations, rendered step bodies,
and output schemas.

```bash
sase macro explain my_workflow                    # Explain with no args
sase macro explain my_workflow arg1 arg2          # With positional args
sase macro explain my_workflow --arg key=value    # With named args
```

### `sase macro list`

Lists all available macros and workflows as a JSON array. Each entry includes the name,
type (`"macro"` or `"workflow"`), kind, reference prefix, insertion text, `is_skill`,
source file path, user-facing input definitions, tags, and a content preview. Clients
should treat `insertion` as the authoritative reference text. Most `macro` and
`embeddable_workflow` entries insert as `#name`, including markdown macro swarms;
standalone workflows insert as `#!name`. `is_skill` is `true` only for macro catalog
entries marked as skills; workflows report `false`. Step inputs are omitted from the
JSON `inputs` array because they are supplied by workflow execution rather than typed by
a user.

```bash
sase macro list                   # JSON array to stdout
sase macro list | jq '.[].name'  # Extract just names
```

### `sase macro show`

Shows one macro or workflow definition with its properties, typed inputs, local helper
macros, provenance, references, and highlighted body. The `NAME` argument accepts a bare
name or a copied reference such as `#name`, `#!name`, or `/name`; copied arguments like
`#name(a, b)`, `#name:arg`, and `#name+` are ignored with a warning.

```bash
sase macro show sase/reads                  # Render a readable definition view
sase macro show '#!sync'                    # Show a standalone workflow
sase macro show plan --format json | jq .inputs
sase macro show coder --format raw > coder.md
sase macro show t --color always | less -R
```

`--format full` is the default Rich detail view. `--format json` emits the stable
schema-versioned show record, while `--format raw` writes the exact source definition
bytes without adding a trailing newline. `--color auto|always|never` controls ANSI
output for the rendered view, and `--project PROJECT` resolves within a specific project
namespace.

### `sase macro graph`

Generates a directed acyclic graph (DAG) visualization of a workflow. Without a workflow
name, lists all available multi-step workflows with their step counts and source paths.

```bash
sase macro graph                        # List all workflows
sase macro graph my_workflow            # Mermaid DAG (default)
sase macro graph my_workflow --format text  # Plain-text summary
```

The Mermaid output can be pasted into any Mermaid-compatible renderer. Parallel
sub-steps are shown as subgraphs, and nodes include type indicators and control flow
annotations.

### `sase macro catalog`

Renders every visible macro to a formatted PDF catalog for browsing and sharing.

```bash
sase macro catalog                # Write the PDF to a tempdir and print its path
sase macro catalog --out /tmp/out # Write the PDF to the specified directory
```

The command collects all visible macro templates, renders each into an HTML section, and
produces a single PDF using the bundled `catalog_template.html.j2` and
`catalog_style.css`. The mobile helper's structured catalog uses the same collection and
classification, and returns JSON metadata instead of requiring a PDF renderer. That JSON
omits string input defaults: `default_display` is null for strings, including an empty
string, and also null when the default itself is null. Numbers and booleans are still
shown (`3`, `true`, `false`). `required` is true only when the input declares no
default. `sase macro show` still prints string defaults, and sase's TUI argument assist
may show them locally. The mobile catalog does not. The JSON `inputs` rows keep `type`
as the base kind and `choices` as canonical string values. They also include
`type_label`, `choice_details` (value, optional label, and optional description),
`named_type`, and `value_role`. The text view uses the same type label and shows each
choice's canonical value with its display label and description.

### `sase macro types`

List the installed input-type catalog, or show one type's detail card. The catalog is
the same vocabulary the binder, TUI, and LSP use: scalar keywords, builtin
`agent`/`model`/`effort`, and plugin-shared enums.

```bash
sase macro types                                          # Grouped tables
sase macro types effort                                   # One builtin type
sase macro types sase-research-artifacts@audio_edition    # One plugin type
sase macro types --json                                   # Rust catalog projection
sase macro types model -j                                 # One type as JSON
```

`NAME` accepts a bare builtin (`effort`, `model`), a deprecated alias (`string`),
`builtin@<name>`, or a qualified plugin type (`sase-research-artifacts@audio_edition`).
`--json` prints the Rust catalog projection. Unknown names exit 1. See
[Typed Inputs](arguments.md#typed-inputs) for the rule authors learn and
[Shipping input types](../../plugins.md#shipping-input-types) for plugin manifests.

## Editor LSP

`sase lsp` starts the SASE macro language server over stdio for editor integrations. It
resolves the server command in this order:

1. `SASE_MACRO_LSP_CMD`, parsed as a shell-style command for development.
2. A `sase-macro-lsp` binary in the current Python environment's `bin/` directory.
3. `sase-macro-lsp` on `PATH`.
4. The newer debug or release `sase-macro-lsp` binary under a sibling `../sase-core`
   checkout.
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_macro_lsp --` when `cargo`
   is available and the sibling checkout has a `Cargo.toml`.

Examples:

```bash
sase lsp
sase lsp --version
SASE_MACRO_LSP_CMD='cargo run --manifest-path ../sase-core/Cargo.toml -p sase_macro_lsp --' sase lsp
```

Use `SASE_MACRO_LSP_CMD` for any non-default LSP command, including a custom binary that
should beat the managed venv copy. Full editable-install SASE updates reinstall the
server into the uv-tool venv when pulled `sase-core` commits change. `SASE_CORE_DIR` is
a `Justfile` build/install override, not part of `sase lsp` command resolution.

The LSP loads the supported macro catalog sources directly in Rust for completion,
hover, diagnostics, and definition requests. `sase lsp` exports the installed package
macro paths to the server so built-in Markdown prompts, YAML workflows, default config
prompts, project-local prompts, user config prompts, and memory prompts do not require a
Python helper subprocess on the completion path. The Python helper bridge remains stable
for mobile clients and as a compatibility fallback for sources the Rust loader cannot
discover.

When the editor advertises LSP `completionItem.snippetSupport`, the server also returns
SASE snippets as ordinary `CompletionItemKind.Snippet` entries after bare trigger words
such as `fix` or `review`. Snippet entries are loaded from the same registry as sase's
TUI: macros with `snippet` front matter plus user-defined `ace.snippets`, with
`ace.snippets` winning on trigger collisions. The registry also includes the generated
initial-capital aliases (`foo` → `Foo`), so a completion for `Foo` appears wherever
`foo` does. The editor does not need to shell out or parse SASE config to discover
snippets.

The Python helper operation `sase editor helper-bridge snippet-catalog` is the
authoritative snippet registry because it matches sase's TUI macro composition behavior.
The Rust server also has a native fallback for simple macro snippets and `ace.snippets`
so completion can degrade gracefully if the helper is unavailable. That fallback
intentionally skips macros that require complex Jinja or composition it cannot mirror
exactly; when the helper is available, its response is preferred.

The LSP also consumes the project's `glossary` memory web, authored as strand files
under `sase/memory/glossary/`; see [Memory Webs](../memory/memory.md#memory-webs). A leading VCS
workflow reference selects the glossary project for the document, otherwise the active
workspace project is used. Glossary phrases are emitted as standard `type` semantic
tokens, with the same case-insensitive, code-literal-skipping, longest-match scanner
sase's TUI uses. A phrase wrapped across one line break is emitted as one semantic token
per line. Derived plurals of terms and aliases are matched like configured aliases.
`sase-nvim` underlines those tokens by default through an overridable `SaseGlossaryTerm`
highlight group. Hover returns Markdown for the canonical term, aliases, project, and
source context, and go-to-definition targets the glossary strand file's definition
range. Explicit macro and artifact references keep precedence over glossary matches.
When the selected project is disabled, unknown, home, unreadable, or has an invalid
glossary, the server suppresses glossary semantics for that context instead of falling
back to another project's terms.

See the [editor integration guide](../../editor.md) for setup, feature coverage, helper bridge
usage, and troubleshooting.

## Related

- [Macro reference](index.md)
- [Directive catalog](directives.md)
