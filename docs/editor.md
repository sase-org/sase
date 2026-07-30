# Editor Integration

SASE exposes two editor-facing surfaces for prompt and xprompt editing:

- `sase lsp` is the interactive editor path. Configure your editor to launch it as a stdio language server when you want
  completions, snippets, hover, diagnostics, code actions, and jump-to-definition while editing a prompt.
- `sase editor helper-bridge ...` is the integration/debugging path. It reads one JSON request from stdin and writes one
  JSON response to stdout, so clients can fetch the same catalogs without implementing an LSP client.

## Language Server

`sase lsp` starts the SASE xprompt language server over stdio. Run `--version` or `--help` in a terminal to verify the
wrapper, then point your editor's LSP configuration at `sase lsp`:

```bash
sase lsp --version
sase lsp --help
```

In editor configuration terms, the command is `sase` and the argument list is `["lsp"]`.

The wrapper resolves the server command in this order:

1. `SASE_XPROMPT_LSP_CMD`, parsed as a shell-style command for development.
2. A `sase-xprompt-lsp` binary in the current Python environment's `bin/` directory.
3. `sase-xprompt-lsp` on `PATH`.
4. The newer debug or release `sase-xprompt-lsp` binary under a sibling `../sase-core` checkout.
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --` when `cargo` is available and the sibling
   checkout has a `Cargo.toml`.

Use `SASE_XPROMPT_LSP_CMD` when you need to point the editor wrapper at a different source checkout or command,
including a custom binary that should beat the managed venv copy. Full editable-install SASE updates reinstall the
server into the uv-tool venv when pulled `sase-core` commits change. The `Justfile` uses `SASE_CORE_DIR` and
`SASE_LINKED_REPO_SASE_CORE_DIR` (with the legacy `SASE_SIBLING_REPO_*` variables as fallbacks) for local `sase-core`
build/install targets, but `sase lsp` itself does not read those variables.

The xprompt LSP binary is built and installed from the local `sase-core` checkout (`just rust-lsp-install` for
development/editor validation). It is separate from the `sase-core-rs` Python wheel; installing or rebuilding that wheel
alone does not install the language server.

The wrapper also exports installed package xprompt locations, bundled default config, plugin xprompt directories, and
plugin config paths to the Rust server. It also materializes a local artifact-reference catalog under
`~/.sase/xprompt_lsp/` by default. The server refreshes its xprompt catalog when the LSP session starts, keeps a short
cache for completion requests, and exposes a `sase.xpromptLsp.refreshCatalog` command for clients that surface LSP
commands. Artifact-reference completion, diagnostics, and semantic highlighting re-read their catalog on each request,
so a launcher refresh or external rewrite is visible on the next editor pass.

## LSP Features

The xprompt language server is focused on prompt and xprompt editing:

| Feature                 | Behavior                                                                                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| XPrompt completion      | Completes `#name`, `#!workflow`, namespaced references, and slash-skill references from the structured catalog.                                                    |
| Project/ChangeSpec tags | Completes `+query` at prompt offset zero or immediately after an ASCII space from enabled projects and active ChangeSpecs, inserting canonical VCS workspace tags. |
| VCS ref roots           | Completes `#gh:`, `#git:`, and other registered VCS workflow ref roots from project, ChangeSpec, and namespace catalog rows.                                       |
| VCS repositories        | Completes repository names after namespace slashes such as `#gh:owner/` through the owning workspace provider.                                                     |
| Argument assistance     | Completes named arguments, path inputs, and bool values for typed xprompt inputs where the catalog exposes input metadata.                                         |
| Directive completion    | Completes SASE prompt directives and fixed directive values, including `%model:` values from the live model catalog.                                               |
| Artifact references     | Completes bare `@` and `@query` tokens as one grouped artifact-kind plus local-path response, then local document, chat, and indexed-file payloads after `@kind:`. |
| File completion         | Completes path-like tokens and recent file-history entries; `@`-prefixed local paths also appear in the grouped artifact-reference response.                       |
| Snippets                | Offers SASE snippets after bare trigger words when the client advertises LSP snippet support.                                                                      |
| Hover                   | Shows xprompt metadata, descriptions, previews, source display paths, tags, and active input hints.                                                                |
| Diagnostics             | Reports xprompt/directive issues plus malformed or unresolved known artifact references outside prompt literal zones.                                              |
| Semantic highlighting   | Highlights the kind, payload, and fragment of known artifact references outside prompt literal zones using standard LSP semantic tokens.                           |
| Definition              | Jumps from xprompt and slash-skill references to real source files when the catalog provides a resolvable path.                                                    |

Snippet completions come from the same registry ACE uses: xprompts with `snippet` front matter plus user-defined
`ace.snippets`, with `ace.snippets` winning on trigger collisions. The server asks the host helper bridge for that
authoritative registry and falls back to native Rust loading only for simple xprompt snippets and configured
`ace.snippets` when the helper is unavailable.

Artifact assistance is local-only. Before a `:` appears, `@` completion returns artifact-kind rows first and local file
rows second; completion labels and filter text include the sigil, such as `@plans:` and `@src/`, so editors filtering
the typed word keep both groups visible. Document-role kinds (including dynamic sidecar roles), chats, and indexed
artifact files are enumerated or resolved from the selected project's catalog roots. `commit` and `bug` references
receive shape validation but no completion enumeration or resolution request, and the LSP never contacts git hosts,
issue trackers, or other network providers. Unknown `@kind:` text remains ordinary prose.

Artifact-reference semantic tokens use the standard LSP legend: `namespace` for the kind, `string` for the payload, and
`number` for the fragment. Dynamic document-role references carry the standard `documentation` modifier; builtin
references do not. Editors therefore use their normal semantic-token theme without SASE-specific client configuration.
The provider currently emits artifact-reference tokens only. Neovim's native LSP semantic-token support consumes this
capability directly, so the `sase-nvim` plugin needs no matching syntax or capability changes.

## Helper Bridge

Editor integrations that do not need live LSP behavior can call fixed helper operations directly:

```bash
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge xprompt-catalog
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge snippet-catalog
printf '{"schema_version":1}\n' | sase editor helper-bridge agent-catalog
printf '{"schema_version":1,"workflow":"gh","namespace":"sase-org"}\n' \
  | sase editor helper-bridge vcs-repo-catalog
```

`xprompt-catalog` returns the structured xprompt catalog used by mobile/editor clients, including insertion text,
reference prefix, kind, tags, typed inputs, display/source fields, and `definition_path` when SASE can resolve a real
file.

`snippet-catalog` returns the composed snippet registry:

- XPrompt-derived snippets from markdown files with `snippet` front matter.
- User snippets from `ace.snippets` in merged SASE config.
- Valid trigger words only; user snippets override xprompt snippets on collision.
- `#[trigger]` snippet references resolved after the xprompt/user merge.
- Generated initial-capital aliases (`foo` → `Foo`, uppercasing only the first character of the trigger and template)
  composed after that merge, so the registry matches ACE. Explicit `Foo` definitions are never overwritten.

`agent-catalog` requires only `{"schema_version":1}` and reads across projects. It returns active and recent ordinary
agent rows, de-duplicated by name, with `status` and `project`. When the same artifact snapshot contains usable group
metadata, the response adds the latest identifiable generation of each family and clan plus `@tribe` references derived
from stored tribe assignments and clan declarations. Every row has `name`, `kind`, `member_count`, and display-ready
`detail`; clan rows also have aggregate `status`. Group entries are additive, so malformed legacy group metadata does
not hide the ordinary agent rows.

`vcs-repo-catalog` requires a `workflow` and `namespace`, then asks that workflow's registered workspace provider for
repositories. The response reports `status`, `error_kind`, `message`, `provider_display`, and whether returned cache
data is `stale`. Each entry has a short `name` and a full `ref` such as `sase-org/sase`; replace the current VCS ref
with `ref` rather than appending it after the namespace.

All four helper operations read one JSON object from stdin and write one compact JSON object to stdout. They are fixed
catalog operations, not a general shell or filesystem bridge.

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

Snippet templates can reuse other snippets by trigger with `#[trigger]`. Positional forms such as `#[trigger(value)]`
and `#[trigger:value]` fill the referenced snippet's tabstops before the composed template is renumbered.

## Troubleshooting

| Symptom                        | Check                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `sase lsp` cannot start        | Run `sase lsp --version`; run a full editable SASE update, build `../sase-core`, or set `SASE_XPROMPT_LSP_CMD`.                      |
| Snippets do not appear         | Confirm the editor advertises LSP `completionItem.snippetSupport`; inspect `sase editor helper-bridge snippet-catalog`.              |
| Completion catalog looks stale | Restart the LSP session after changing installed plugin resources; for rewritten artifact catalogs, retry completion or diagnostics. |
| Jump-to-definition is missing  | Check whether the catalog entry has a real `definition_path`; plugin or built-in virtual entries may only have display paths.        |
| A user snippet is ignored      | Trigger names must contain only ASCII letters, digits, or `_`.                                                                       |

## Related Pages

- [XPrompt reference](xprompt.md) for xprompt syntax, discovery order, typed inputs, snippets, and workflows.
- [Integration APIs](integrations.md#editor-helper-bridge) for the Python helper facade.
- [Configuration](configuration.md#sase-editor) for CLI flag and environment-variable reference.
- [ACE snippets](ace.md#snippets) for the in-TUI prompt widget behavior.
