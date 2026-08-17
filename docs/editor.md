# Editor Integration

SASE exposes two editor-facing surfaces for prompt and xprompt editing:

- `sase lsp` is the interactive editor path. Configure your editor to launch it as a
  stdio language server when you want completions, snippets, hover, diagnostics, code
  actions, and jump-to-definition while editing a prompt.
- `sase editor helper-bridge ...` is the integration/debugging path. It reads one JSON
  request from stdin and writes one JSON response to stdout, so clients can fetch the
  same catalogs without implementing an LSP client.

## Language Server

`sase lsp` starts the SASE xprompt language server over stdio. Run `--version` or
`--help` in a terminal to verify the wrapper, then point your editor's LSP configuration
at `sase lsp`:

```bash
sase lsp --version
sase lsp --help
```

In editor configuration terms, the command is `sase` and the argument list is `["lsp"]`.

The wrapper resolves the server command in this order:

1. `SASE_XPROMPT_LSP_CMD`, parsed as a shell-style command for development.
2. A `sase-xprompt-lsp` binary in the current Python environment's `bin/` directory.
3. `sase-xprompt-lsp` on `PATH`.
4. The newer debug or release `sase-xprompt-lsp` binary under a sibling `../sase-core`
   checkout.
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --` when
   `cargo` is available and the sibling checkout has a `Cargo.toml`.

Use `SASE_XPROMPT_LSP_CMD` when you need to point the editor wrapper at a different
source checkout or command, including a custom binary that should beat the managed venv
copy. Full editable-install SASE updates reinstall the server into the uv-tool venv when
pulled `sase-core` commits change. The `Justfile` uses `SASE_CORE_DIR` and
`SASE_LINKED_REPO_SASE_CORE_DIR` (with the legacy `SASE_SIBLING_REPO_*` variables as
fallbacks) for local `sase-core` build/install targets, but `sase lsp` itself does not
read those variables.

The xprompt LSP binary is built and installed from the local `sase-core` checkout
(`just rust-lsp-install` for development/editor validation). It is separate from the
`sase-core-rs` Python wheel; installing or rebuilding that wheel alone does not install
the language server.

The wrapper also exports installed package xprompt locations, bundled default config,
plugin xprompt directories, and plugin config paths to the Rust server. It also
materializes a local artifact-reference catalog under `~/.sase/xprompt_lsp/` by default.
The server refreshes its xprompt catalog when the LSP session starts, keeps a short
cache for completion requests, and exposes a `sase.xpromptLsp.refreshCatalog` command
for clients that surface LSP commands. Artifact-reference diagnostics and semantic
highlighting re-read their catalog on each request, so a launcher refresh or external
rewrite is visible on the next editor pass; artifact-reference completion reads the same
catalog through a short-lived cache keyed by the catalog file's signature (see
[LSP Features](#lsp-features)).

## LSP Features

The xprompt language server is focused on prompt and xprompt editing:

| Feature               | Behavior                                                                                                                                                                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| XPrompt completion    | Completes `#name`, `#!workflow`, namespaced references, and slash-skill references from the structured catalog. Skills complete as `#skill/<name>` after `#` and as `/<name>` after a slash. [Memory notes](xprompt.md#memory-field) complete as `#memory/<stem>` and never appear in slash completion. |
| Project/Patch tags    | Completes `+query` at prompt offset zero or immediately after an ASCII space from enabled projects and active Patches, inserting canonical VCS workspace tags.                                                                                                                                          |
| VCS ref roots         | Completes `#gh:`, `#git:`, and other registered VCS workflow ref roots from project, Patch, and namespace catalog rows.                                                                                                                                                                                 |
| VCS repositories      | Completes repository names after namespace slashes such as `#gh:owner/` through the owning workspace provider.                                                                                                                                                                                          |
| Argument assistance   | Completes named arguments, path inputs, and bool values for typed xprompt inputs where the catalog exposes input metadata.                                                                                                                                                                              |
| Directive completion  | Completes SASE prompt directives and fixed directive values, including `%model:` values and provider-scoped `provider/model` drill-down from the live model catalog.                                                                                                                                    |
| Artifact references   | Fuzzy-completes bare `@` and `@query` tokens as canonical artifact kinds, adding local paths on a kind-prefix miss or manual completion request, then completes local payloads after `@kind:`, including local stitch references.                                                                       |
| File completion       | Completes path-like tokens and recent file-history entries; `@`-prefixed local paths appear automatically when no artifact kind prefix-matches, or on manual invocation.                                                                                                                                |
| Snippets              | Offers SASE snippets after bare trigger words when the client advertises LSP snippet support.                                                                                                                                                                                                           |
| Hover                 | Shows xprompt metadata, descriptions, previews, source display paths, tags, and active input hints. Memory entries also show their kind and tier (`short`/`long`).                                                                                                                                      |
| Diagnostics           | Reports xprompt/directive issues plus malformed or unresolved filesystem-backed artifact references outside prompt literal zones.                                                                                                                                                                       |
| Semantic highlighting | Highlights the kind, payload, and supported fragment of known artifact references, plus glossary phrases, outside prompt literal zones using standard LSP semantic tokens.                                                                                                                              |
| Definition            | Jumps from xprompt and slash-skill references to real source files when the catalog provides a resolvable path, including the backing note for `#memory/<stem>`.                                                                                                                                        |

Snippet completions come from the same registry ACE uses: xprompts with `snippet` front
matter plus user-defined `ace.snippets`, with `ace.snippets` winning on trigger
collisions. The server asks the host helper bridge for that authoritative registry and
falls back to native Rust loading only for simple xprompt snippets and configured
`ace.snippets` when the helper is unavailable. In ACE, that shared registry expands into
nested snippet sessions: expanding a trigger while another snippet's tabstops are live
visits the inner tabstops first, then returns to the remaining outer tabstops. LSP
clients receive ordinary editor snippets from the same catalog, so placeholder
navigation in external editors is handled by the editor.

Artifact assistance is local-only. Before a `:` appears, `@` completion withholds local
file rows whenever the query prefix-matches an artifact kind (including bare `@`), and
returns them automatically when no kind prefix-matches. A manually invoked completion
request includes the file rows explicitly. Completion labels are the reference that gets
inserted, such as `@plan:` and `@src/`. Document kinds (including dynamic sidecar
roles), indexed artifact files, Patches, beads, agents, and stitches are enumerated or
resolved from the selected project's local catalog roots and checkout paths. `bead` and
`agent` payloads resolve locally from generated sidecar pages, and `stitch` payloads are
enumerated from local git checkouts, excluding SDD sidecar repositories (`plans`,
`beads`, `agents`, `research`) since their commits are machine-written bookkeeping
rather than a human's recent work. A sidecar stitch reference still resolves when
written out in full, such as `@stitch:plans@<sha>` — the exclusion only curates what
completion offers. Historical aliases such as `@commit:`, `@plans:`, `@chat:`, and
`@bug:` are not offered by completion. The LSP never contacts git hosts, issue trackers,
or other network providers. Unknown `@kind:` text remains ordinary prose.

This canonical-only rule is specific to the editor LSP. ACE's prompt bar currently also
lists recognized aliases and historical kinds, and its repository-history payload picker
remains attached to `@commit:`; both `@commit:` and `@stitch:` resolve through the same
launch resolver.

Matching is **fuzzy and ranked on the server** for every enumerated kind — document
roles, indexed artifact files, Patches, beads, agents, and stitches — against the
inserted payload, the row's title, and, for scoped rows, the qualified `scope@title`
target. For example, `@stitch:core@fix` can match the `sase-core` repository scope and a
commit subject containing `fix` in the same query. Likewise, `@research:site` finds
`@research:202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md`,
`@agent:sase-b3` finds `@agent:bbugyi200.athena.sase-b3.5` from a mid-name fragment, and
`@file:panel` finds a `default:<hex>` indexed file by its file name. Rows are grouped
into tiers so a fuzzy hit never outranks a literal one, then ordered by score, provider
rank where a provider declares one, shorter text, and case-insensitive text:

| Tier | Meaning                                   | Example query against `202607/sase_sites_hub_and_pages/…` |
| ---- | ----------------------------------------- | --------------------------------------------------------- |
| 0    | query is a prefix of the primary text     | `202607/`                                                 |
| 1    | query is a prefix of the basename segment | `sase_sites`                                              |
| 2    | query is a contiguous substring           | `hub_and`                                                 |
| 3    | query is an ordered subsequence           | `site`, `shubp`                                           |

An empty query is not ranked at all: each group keeps its provider order (builtin order
for kinds, directories-before-files for paths, and provider order for payloads). Kind
rows and the trailing partial of a local path are matched the same way, but a `@` path
token's directory portion stays exact, so `@src/` still lists `src/` and `@src/fcb` can
still find `src/…/_file_completion_base.py`. Stitch SHA text is still part of the lowest
fuzzy tier, so hex-like queries such as `add` can subsequence-match a SHA; subject and
repository matches outrank those tier-3 rows.

Bounds are disclosed rather than silent. Filesystem-backed enumeration walks up to 5000
payloads per root, so a root larger than that is matched only over the rows the walk
reached. Stitch completion reads at most 200 revisions per repository, gives each
repository two seconds to answer, and merges at most 1000 commit rows across
repositories. Matching then returns at most 200 rows per group to the editor. Whichever
bound bites, the count of payloads left out is appended to every item's `detail` as
`at least N additional payloads not shown`, on top of the list's `isIncomplete: true`.
Because the walk is query-independent, the enumerated and titled inventory is cached
in-process per project and per catalog signature (path, mtime, size) with a two-second
TTL, so a keystroke re-ranks a warm corpus instead of re-walking the filesystem. A
watched catalog write or the `sase.xpromptLsp.refreshCatalog` command invalidates it
immediately.

Keeping server-ranked rows alive in the client is an explicit contract. Every
artifact-reference item sets `filterText` to the reference text **as typed**
(`@research:site` in the payload stage, `@rsch` in the kind stage) rather than to the
inserted reference, because a client that prefix-filters `@research:202607/…` against
`@research:site` would discard every fuzzy row. The response is a `CompletionList` with
`isIncomplete: true`, which makes clients re-request on each keystroke instead of
re-filtering a stale list and, in Neovim's native completion, disables the client's own
fuzzy re-sort so the server's `sortText` order survives. Insertion is unaffected: each
item carries the full reference in `textEdit.newText`.

Editors cannot highlight individual characters inside a completion label, so the "why is
this row here" affordance moves into the preview. `labelDetails.description` keeps the
group word (`artifact kind`, `file`, `directory`, or a payload kind such as `stitch`,
`patch`, `research`, `bead`, or `agent`). `labelDetails.detail` adds the row's title
when it differs from the label — a document's frontmatter title, an indexed file's
basename, a Patch or bead title, an agent's short name, or a commit subject — and
markdown `documentation` shows the matched payload with the matched runs wrapped in
`**`, followed by that title on a second line. Stitch rows also include the bounded
commit body when one is available.

Artifact-reference semantic tokens use the standard LSP legend: `namespace` for the
kind, `string` for the payload, and `number` for the fragment. Dynamic document-role
references carry the standard `documentation` modifier; builtin references do not.
Glossary phrases are emitted as standard `type` semantic tokens. Other editors style
those tokens with their normal semantic-token theme; `sase-nvim` keeps that color and
adds an overridable `SaseGlossaryTerm` underline on top through Neovim's
`LspTokenUpdate` hook.

## Helper Bridge

Editor integrations that do not need live LSP behavior can call fixed helper operations
directly:

```bash
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge xprompt-catalog
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge snippet-catalog
printf '{"schema_version":1}\n' | sase editor helper-bridge agent-catalog
printf '{"schema_version":1,"workflow":"gh","namespace":"sase-org"}\n' \
  | sase editor helper-bridge vcs-repo-catalog
```

`xprompt-catalog` returns the structured xprompt catalog used by mobile/editor clients,
including insertion text, reference prefix, kind, tags, typed inputs, display/source
fields, and `definition_path` when SASE can resolve a real file.

`snippet-catalog` returns the composed snippet registry:

- XPrompt-derived snippets from markdown files with `snippet` front matter.
- User snippets from `ace.snippets` in merged SASE config.
- Valid trigger words only; user snippets override xprompt snippets on collision.
- `#[trigger]` snippet references resolved after the xprompt/user merge.
- Generated initial-capital aliases (`foo` → `Foo`, uppercasing only the first character
  of the trigger and template) composed after that merge, so the registry matches ACE.
  Explicit `Foo` definitions are never overwritten.

`agent-catalog` requires only `{"schema_version":1}` and reads across projects. It
returns active and recent ordinary agent rows, de-duplicated by name, with `status` and
`project`; monitor rows use `kind: monitor`. When the same artifact snapshot contains
usable group metadata, the response adds the latest identifiable generation of each
family and clan plus `@tribe` references derived from stored tribe assignments and clan
declarations. Every row has `name`, `kind`, `member_count`, and display-ready `detail`;
clan rows also have aggregate `status`.

For the newest 20 families, the helper attempts to resolve an associated plan or bead.
On success, `detail` leads with plan kind, structure, and title, and optional Markdown
`documentation` supplies the available goal, epic phases, or phase/task context followed
by family member count and aggregate status. A launch-prompt title can fill the detail
when no structured preview exists. Older or unresolved families keep the stable
`family · N members` detail. Group enrichment is additive, so missing plans or malformed
legacy metadata never hide ordinary agent rows.

`vcs-repo-catalog` requires a `workflow` and `namespace`, then asks that workflow's
registered workspace provider for repositories. The response reports `status`,
`error_kind`, `message`, `provider_display`, and whether returned cache data is `stale`.
Each entry has a short `name` and a full `ref` such as `sase-org/sase`; replace the
current VCS ref with `ref` rather than appending it after the namespace.

All four helper operations read one JSON object from stdin and write one compact JSON
object to stdout. They are fixed catalog operations, not a general shell or filesystem
bridge.

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

Required xprompt inputs become snippet tabstops. Optional inputs are pre-filled from
defaults. XPrompts with complex Jinja control flow are skipped by snippet conversion so
the generated editor template stays predictable.

Snippet templates can reuse other snippets by trigger with `#[trigger]`. Positional
forms such as `#[trigger(value)]` and `#[trigger:value]` fill the referenced snippet's
tabstops before the composed template is renumbered.

When the composed registry is used in ACE, `Tab` moves forward through `$1`, `$2`, ...
and `$0`, while `Shift+Tab` retreats through visited tabstops. Expanding a second
trigger from inside an active snippet nests it instead of discarding the remaining outer
stops.

## Troubleshooting

| Symptom                        | Check                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `sase lsp` cannot start        | Run `sase lsp --version`; run a full editable SASE update, build `../sase-core`, or set `SASE_XPROMPT_LSP_CMD`.                      |
| Snippets do not appear         | Confirm the editor advertises LSP `completionItem.snippetSupport`; inspect `sase editor helper-bridge snippet-catalog`.              |
| Completion catalog looks stale | Restart the LSP session after changing installed plugin resources; for rewritten artifact catalogs, retry completion or diagnostics. |
| Jump-to-definition is missing  | Check whether the catalog entry has a real `definition_path`; plugin or built-in virtual entries may only have display paths.        |
| A user snippet is ignored      | Trigger names must contain only ASCII letters, digits, or `_`.                                                                       |

## Related Pages

- [XPrompt reference](xprompt.md) for xprompt syntax, discovery order, typed inputs,
  snippets, and workflows.
- [Integration APIs](integrations.md#editor-helper-bridge) for the Python helper facade.
- [Configuration](configuration.md#sase-editor) for CLI flag and environment-variable
  reference.
- [ACE snippets](ace.md#snippets) for the in-TUI prompt widget behavior.
