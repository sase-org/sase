# Editor Integration

SASE exposes editor-facing APIs for xprompt authoring, prompt completion, snippet expansion, and jump-to-definition. Use
the language server when your editor has LSP support; use the helper bridge when an integration wants a simple
JSON-over-stdin catalog without running an LSP client.

## Language Server

`sase lsp` starts the SASE xprompt language server over stdio:

```bash
sase lsp
sase lsp --version
```

The wrapper resolves the server command in this order:

1. `SASE_XPROMPT_LSP_CMD`, parsed as a shell-style command for development.
2. `sase-xprompt-lsp` on `PATH`.
3. A sibling `../sase-core` debug or release binary.
4. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --` when Cargo and the sibling checkout are
   available.

The wrapper also exports installed package xprompt locations, bundled default config, plugin xprompt directories, and
plugin config paths to the Rust server so completions match the SASE runtime catalog as closely as possible.

## LSP Features

The xprompt language server is focused on prompt and xprompt editing:

| Feature              | Behavior                                                                                                                         |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| XPrompt completion   | Completes `#name`, `#!workflow`, namespaced references, and slash skills from the structured catalog.                            |
| Argument assistance  | Completes named arguments and values for typed xprompt inputs where the catalog exposes input metadata.                          |
| Directive completion | Completes SASE prompt directives such as `%model`, `%wait`, and other known directive names.                                     |
| File completion      | Completes path-like tokens and recent file-history entries for prompt references.                                                |
| Snippets             | Offers SASE snippets after bare trigger words when the client advertises LSP snippet support.                                    |
| Hover                | Shows xprompt metadata, descriptions, previews, source display paths, tags, and active input hints.                              |
| Diagnostics          | Reports unknown xprompts, unknown slash skills, unknown directives, malformed xprompt arguments, and argument type/arity issues. |
| Definition           | Jumps from xprompt and slash-skill references to real source files when the catalog provides a resolvable path.                  |

Snippet completions come from the same registry ACE uses: xprompts with `snippet` front matter plus user-defined
`ace.snippets`, with `ace.snippets` winning on trigger collisions. The server asks the host helper bridge for that
authoritative registry and falls back to native Rust loading only for simple xprompt snippets and configured
`ace.snippets` when the helper is unavailable.

## Helper Bridge

Editor integrations that do not need a full LSP session can call fixed helper operations:

```bash
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge xprompt-catalog
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge snippet-catalog
```

`xprompt-catalog` returns the structured xprompt catalog used by mobile/editor clients, including insertion text,
reference prefix, kind, tags, typed inputs, display/source fields, and `definition_path` when SASE can resolve a real
file.

`snippet-catalog` returns the composed snippet registry:

- XPrompt-derived snippets from markdown files with `snippet` front matter.
- User snippets from `ace.snippets` in merged SASE config.
- Valid trigger words only; user snippets override xprompt snippets on collision.

Both helper operations read one JSON object from stdin and write one compact JSON object to stdout. They are fixed
operations, not a general shell or filesystem bridge.

## Authoring Snippets

Use `ace.snippets` for local trigger-word templates:

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style.\n$0"
```

Use xprompt front matter when a reusable prompt should also appear as a snippet:

```markdown
---
name: review
snippet: true
input:
  path: path
---

Review {{ path }} for correctness, tests, and maintainability.
```

Required xprompt inputs become snippet tabstops. Optional inputs are pre-filled from defaults. XPrompts with complex
Jinja control flow are skipped by snippet conversion so the generated editor template stays predictable.

## Troubleshooting

| Symptom                        | Check                                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `sase lsp` cannot start        | Run `sase lsp --version`; install `sase-xprompt-lsp`, build `../sase-core`, or set `SASE_XPROMPT_LSP_CMD`.                    |
| Snippets do not appear         | Confirm the editor advertises LSP `completionItem.snippetSupport`; inspect `sase editor helper-bridge snippet-catalog`.       |
| Completion catalog looks stale | Restart the LSP session after changing installed plugin resources or package xprompts.                                        |
| Jump-to-definition is missing  | Check whether the catalog entry has a real `definition_path`; plugin or built-in virtual entries may only have display paths. |
| A user snippet is ignored      | Trigger names must contain only ASCII letters, digits, or `_`.                                                                |

## Related Pages

- [XPrompt reference](xprompt.md) for xprompt syntax, discovery order, typed inputs, snippets, and workflows.
- [Integration APIs](integrations.md#editor-helper-bridge) for the Python helper facade.
- [Configuration](configuration.md#sase-editor) for CLI flag and environment-variable reference.
- [ACE snippets](ace.md#snippets) for the in-TUI prompt widget behavior.
