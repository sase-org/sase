# XPrompt LSP Server Research

Date: 2026-05-07

## Question

How should SASE factor editor-facing xprompt logic out of `../sase-nvim` and into a new LSP server defined in
`../sase-core`, so Neovim becomes a thin client and other editors can add xprompt support with less duplicate logic?

## Executive Summary

Build a new `sase_xprompt_lsp` Rust binary in `../sase-core`, backed by a reusable `sase_editor` or `sase_lsp` library
module. The LSP server should own editor-facing language intelligence: token classification, xprompt/file/file-history
completion, xprompt argument hints, hover text, diagnostics for invalid references, and schema discovery for SASE YAML.

The first version should not try to port all xprompt loading into Rust. Today the authoritative xprompt catalog is still
Python-owned in `src/sase/xprompt/*`, and the mobile gateway already uses a narrow JSON helper bridge to expose that
catalog. Reuse that bridge shape for the LSP server at first, then migrate the catalog loader into `sase_core` later
behind the same editor-facing API.

Recommended split:

1. `sase_xprompt_lsp` speaks standard LSP over stdio.
2. `sase_core` owns pure editor algorithms and wire structs: document snapshot, token extraction, completion context,
   completion candidates, hover payloads, diagnostic payloads, schema association metadata.
3. A small host bridge fetches xprompt catalog records and file-history records from the installed `sase` command.
4. `sase-nvim` only starts the LSP, opts into completion, and keeps Telescope pickers as optional UI for browse-style
   actions.
5. Keep legacy CLI helper paths (`sase xprompt list`, `sase file list`, `sase file-history list/delete`, `sase path`)
   until the LSP path reaches parity.

This aligns with the local core-boundary rule: if another editor, mobile app, CLI, or web UI needs the behavior to match
the TUI, treat it as core/backend logic.

## Current State

### `sase-nvim` Has Editor Logic That Wants To Move

The Neovim plugin is not only presentation glue. It currently implements several backend-ish rules in Lua:

- `lua/sase/complete/_token.lua`
  - token delimiters copied from `src/sase/ace/tui/widgets/file_completion.py`;
  - special `#!` handling;
  - xprompt, slash-skill, file path, and file-history classification;
  - `.sase/`, `@path`, `~/`, absolute, relative, and slash-containing path rules.
- `lua/sase/xprompt.lua`
  - calls `sase xprompt list`;
  - filters xprompts by `#`, `#!`, and `/skill`;
  - derives fallback insertion forms for older catalog output;
  - formats picker rows and input summaries.
- `lua/sase/complete/file.lua`
  - calls `sase file list -p <cwd> -t <token>`;
  - implements directory drill-down UI.
- `lua/sase/complete/file_history.lua`
  - calls `sase file-history list` and `delete`;
  - caches and invalidates recent file entries.
- `plugin/sase_yamlls.lua`
  - calls `sase path` three times and mutates `yamlls` settings.

The duplication is explicit: `_token.lua` says it mirrors the TUI's `file_completion.py` and `xprompt_completion.py`.
That is the strongest signal that this belongs behind a shared editor protocol.

### Python Already Has Better Structured XPrompt Metadata

The Python repo now exposes structured catalog metadata:

- `src/sase/xprompt/_catalog_models.py`
  - `StructuredCatalogInput`: `name`, `type`, `required`, `default_display`, `position`;
  - `StructuredCatalogEntry`: `name`, `display_label`, `insertion`, `reference_prefix`, `kind`, `description`,
    `source_bucket`, `project`, `tags`, `input_signature`, `inputs`, `is_skill`, `content_preview`,
    `source_path_display`.
- `src/sase/xprompt/_catalog_structured.py`
  - `build_structured_xprompts_catalog(project=None, source=None, tag=None, query=None, include_pdf=False, limit=None)`;
  - uses `workflow_reference_insertion()` and `workflow_reference_prefix()` so `#!` is authoritative;
  - filters step inputs and derives requiredness from `UNSET`.
- `src/sase/integrations/_mobile_helper_catalog.py`
  - projects this into a mobile-safe JSON helper response.

This is a better substrate for an editor server than `sase xprompt list`, because it already carries canonical insertion
text and structured inputs. The current `sase xprompt list` output is still useful, but the mobile catalog contract is
closer to what LSP completion, hover, and signature/help features need.

### `sase-core` Has Gateway Plumbing, Not An LSP Server

The sibling Rust repo currently contains:

- `crates/sase_core`: pure Rust core modules for status, query, bead, agent scan, agent launch, git query, and cleanup.
- `crates/sase_gateway`: an HTTP gateway with host bridges into Python helper commands.
- `crates/sase_core_py`: Python bindings.

There is no `lsp-types`, `tower-lsp`, `tower-lsp-server`, or `lsp-server` dependency today, and no language-server crate.
The gateway README is relevant because it already makes one important architectural call: xprompt helper routes preserve
Python helper bridge metadata, and the Rust gateway does not parse xprompt arguments itself. The LSP should follow the
same pattern for v1: centralize editor protocol and cheap lexical analysis in Rust, but avoid prematurely reimplementing
the entire Python xprompt loader.

## LSP Fit

LSP is exactly the right protocol boundary for this problem. The official LSP project describes the motivation as
factoring language-specific smarts out of each editor so one server can be reused across tools. It also confirms the
latest stable specification is 3.17, although a 3.18 draft page exists. For implementation, target 3.17-compatible
features and avoid depending on proposed 3.18 behavior.

Useful standard methods for SASE:

- `initialize`
  - Advertise incremental text sync, completion, hover, diagnostics, code actions, and optionally inlay hints.
- `textDocument/completion`
  - Return xprompt references, slash skills, file candidates, file-history entries, named argument names, and path/value
    candidates inside xprompt arguments.
  - Use `triggerCharacters` such as `#`, `!`, `/`, `:`, `(`, `,`, `@`, and possibly path separators.
  - Use `CompletionItem.data` plus `completionItem/resolve` for expensive preview/description fields.
- `textDocument/hover`
  - On `#foo`, show kind, description, source, tags, required inputs, and content preview.
  - On an argument position, show the active input name/type/default.
- `textDocument/diagnostic` or `textDocument/publishDiagnostics`
  - Warn on unknown xprompt references, wrong standalone marker where the catalog knows the canonical insertion,
    malformed argument shapes, and references to standalone-only workflows used in inline contexts.
  - Start with pull diagnostics if the chosen Rust LSP crate makes that easy; push diagnostics are also acceptable for
    broad editor compatibility.
- `textDocument/codeAction`
  - Offer fixes such as "replace `#foo` with `#!foo`", "insert required argument skeleton", or "convert to named args".
- `textDocument/inlayHint`
  - Optional second phase for inline argument labels after `#foo:` or inside `#foo(...)`.

For Neovim specifically, current docs show `vim.lsp.start({ name = ..., cmd = ..., root_dir = ... })` as the direct
client startup path. Built-in LSP completion can be enabled with `vim.lsp.completion.enable(...)`, and autotrigger
behavior is controlled by the server's `completionProvider.triggerCharacters`. This means `sase-nvim` can become mostly
startup/config glue plus optional Telescope browse commands.

## Rust LSP Crate Choice

Two Rust options are plausible:

### Option A: `tower-lsp-server`

`tower-lsp-server` is an async LSP server abstraction over Tower. Its docs show a `LanguageServer` trait and built-in
`LspService`/`Server` setup for stdio. This fits `sase_gateway`'s existing async/Tokio workspace better than a custom
message loop.

Pros:

- Async-first and close to the existing `tokio` dependency set.
- Higher-level server trait reduces boilerplate for completion, hover, diagnostics, and shutdown.
- Good fit if the LSP server needs async host-bridge subprocess calls and file-system operations.

Cons:

- Adds Tower-flavored abstraction to `sase-core`.
- Need to verify compatibility and maintenance posture before committing; the crate name appears to be the actively
  documented package now, while older examples often refer to `tower-lsp`.

### Option B: `lsp-server` + `lsp-types`

`lsp-server` is the rust-analyzer-style scaffold. Its docs describe a synchronous, channel-based API that handles
handshaking and message parsing while the implementer controls dispatch.

Pros:

- Small and explicit.
- Proven architecture for rust-analyzer-style servers.
- Easy to keep state-machine behavior deterministic in tests.

Cons:

- More manual routing and concurrency work.
- Less convenient if the implementation wants async host bridge calls, cancellation, and background refresh tasks.

Recommendation: use `tower-lsp-server` for the first implementation unless a dependency audit reveals a problem. It
matches the current `tokio` workspace and should reduce protocol boilerplate.

## Proposed Architecture

### New Crates / Modules

Add to `../sase-core`:

```text
crates/
  sase_core/
    src/editor/
      mod.rs
      token.rs
      completion.rs
      diagnostics.rs
      hover.rs
      schema.rs
      wire.rs
  sase_xprompt_lsp/
    Cargo.toml
    src/main.rs
    src/server.rs
    src/host_bridge.rs
```

Alternative: start with a `sase_lsp` crate instead of `sase_xprompt_lsp` if the long-term scope is broader than
xprompts. The server name can still advertise as `sase-xprompt-lsp` initially.

### Library Boundary

Keep pure, testable logic in `sase_core::editor`:

- `extract_token_at_position(document, position) -> Option<TokenSpan>`
- `classify_completion_context(document, position) -> CompletionContext`
- `filter_xprompt_candidates(catalog, context) -> Vec<EditorCompletionCandidate>`
- `build_file_candidates(root, token) -> Vec<EditorCompletionCandidate>`
- `detect_xprompt_arg_context(document, position, catalog) -> Option<XpromptArgContext>`
- `diagnose_prompt_document(document, catalog) -> Vec<EditorDiagnostic>`
- `hover_for_position(document, position, catalog) -> Option<EditorHover>`
- `schema_associations() -> Vec<SchemaAssociation>`

Keep editor-specific JSON-RPC and LSP conversion in `sase_xprompt_lsp`:

- LSP position/range conversion.
- `CompletionItem` construction.
- `WorkspaceEdit` / `TextEdit` construction.
- client capability negotiation.
- document cache and background catalog refresh.

### Host Bridge

The LSP server should have a narrow host bridge abstraction:

```rust
trait EditorHostBridge {
    fn xprompt_catalog(&self, request: XpromptCatalogRequest) -> Result<XpromptCatalogResponse, HostError>;
    fn file_history_list(&self) -> Result<Vec<String>, HostError>;
    fn file_history_delete(&self, path: &str) -> Result<(), HostError>;
    fn schema_path(&self, name: SchemaName) -> Result<PathBuf, HostError>;
}
```

V1 implementation:

- invoke `sase mobile helper-bridge xprompt-catalog` over JSON stdin/stdout, or add a dedicated
  `sase editor helper-bridge xprompt-catalog` if the mobile route name feels wrong for editor code;
- invoke existing `sase file-history list/delete`;
- resolve schema paths with existing `sase path`;
- do file candidates directly in Rust to avoid a subprocess on every path completion request.

Using the mobile helper bridge for v1 is pragmatic because it already returns structured fields the LSP needs. A
dedicated editor bridge can be introduced as an alias later without changing the LSP-facing library API.

### Cache Model

Use a small cache inside the LSP server:

- cache xprompt catalog by `(root_uri, project, source, tag)` with a short TTL or explicit invalidation command;
- refresh on server start and when a completion request arrives with an expired cache;
- allow manual `workspace/executeCommand` commands:
  - `sase.refreshXpromptCatalog`
  - `sase.clearFileHistory`
  - `sase.openXpromptCatalog` (optional browse action)
- keep file candidates uncached or short-lived because directory contents change often.

Do not make completions wait on PDF generation. Always call the structured catalog with `include_pdf=false`.

## Completion Design

### Context Detection

The core detector should subsume the Lua dispatcher:

- empty/no token -> file-history completion;
- token starts with `#` -> xprompt completion;
- token starts with `/` and matches `^/[A-Za-z0-9_]*$` -> skill-only xprompt completion;
- path-like token -> file completion;
- inside `#foo:` or `#foo(...)` -> argument completion.

Important gotchas from existing research still apply:

- `:` is a token delimiter in current TUI/file completion logic, so argument-context detection cannot reuse only the
  simple token extractor.
- A bare trailing `#foo:` is not a full parsed xprompt reference in the Python parser; the detector must recognize the
  reference base and inspect the suffix up to the cursor.
- `#foo: text` is shorthand prose and should not trigger argument help after whitespace.
- `#foo+` is plus syntax and should not trigger argument hints.
- HITL suffixes `!!` and `??` sit between the name and arguments and must be stripped for catalog lookup.
- `__` aliases normalize to `/` for namespaced references.

### Candidate Kinds

Use LSP completion item kinds conservatively:

- xprompt/workflow -> `Function` or `Snippet`;
- slash skill -> `Function` or `Snippet`;
- file -> `File`;
- directory -> `Folder`;
- recent file -> `File`;
- argument name -> `Property`;
- argument value/type hint -> `Value` or `Text`.

Use `insertTextFormat = Snippet` when inserting required named-arg skeletons, but keep plain reference completion as
simple text by default. Users often want to choose between colon, parenthesized, or prose variants, so auto-mutating a
selected `#foo` into a full snippet should be an opt-in code action or separate completion item.

### Replacement Ranges

The server should return explicit text edits:

- completing `#fo|` replaces the whole token span with `#foo` or `#!foo`;
- completing `/sase_p|` replaces the slash token with `/sase_plan`;
- completing `./src/fo|` replaces the whole path token with the candidate insertion;
- completing an arg name inside `#foo(|` inserts `arg_name=$1` or `arg_name=`.

This removes the Neovim-specific range replacement code from `lua/sase/xprompt.lua` and `lua/sase/complete/_picker.lua`
for the normal LSP completion path.

## Hover, Diagnostics, And Code Actions

### Hover

Hover is a good replacement for picker preview in non-Telescope editors:

- `#foo`
  - display label, kind, canonical insertion, description;
  - inputs with required/optional/default display;
  - tags and source display path;
  - content preview, bounded to the existing mobile preview length.
- active input position
  - input name, type, required/default.

### Diagnostics

Initial diagnostics should be cheap and non-blocking:

- unknown `#name` / `#!name`;
- known `#foo` whose canonical insertion is `#!foo`;
- known `#!foo` whose canonical insertion is `#foo`;
- slash skill `/foo` where `foo` is not a skill;
- unsupported/malformed xprompt argument syntax in narrow cases where the detector is certain.

Avoid full expansion validation in the LSP. Launch-time Python remains authoritative.

### Code Actions

High-value actions:

- replace marker with canonical insertion (`#foo` -> `#!foo`);
- insert colon args skeleton after a known xprompt;
- insert parenthesized named-arg snippet;
- open source file for an xprompt when `source_path_display` resolves to a local path;
- refresh catalog.

## Schema Support

The current Neovim plugin configures `yamlls` by resolving schema paths with `sase path`. An LSP server can reduce this
logic, but there is a protocol mismatch: schema association is usually a YAML-LS configuration concern, not a generic
LSP capability.

Recommended v1:

- keep a tiny Neovim shim for `yamlls` schema registration;
- move schema path resolution into the SASE LSP via a custom request/command only after another editor needs it;
- or provide a non-LSP helper command `sase_xprompt_lsp --schema-associations` that prints editor-neutral JSON.

Do not force YAML validation through the SASE xprompt LSP at first. YAML-LS already handles JSON Schema validation well.
SASE LSP diagnostics can supplement it for cross-file semantics later.

## Neovim Plugin End State

Target minimal `sase-nvim` logic:

- setup:
  - find `sase_xprompt_lsp` or `sase core editor-lsp`;
  - call `vim.lsp.start({ name = "sase-xprompt-lsp", cmd = { ... }, root_dir = ... })`;
  - enable built-in LSP completion when requested;
  - optionally set keymaps for manual completion and refresh command.
- UI:
  - keep Telescope picker commands as optional browse surfaces;
  - for normal completion, rely on LSP completion items and text edits;
  - for previews, rely on hover or `completionItem/resolve`.
- compatibility:
  - keep `:SaseXPrompts`, `#@`, and `<C-t>` legacy paths initially;
  - add config to choose `completion_backend = "lsp" | "legacy" | "auto"`;
  - default to `auto`: use LSP when executable exists, fall back to current CLI helpers.

This lets the plugin shrink without creating a flag day for users.

## Implementation Plan

### Phase 1: Core Editor Contract

In `../sase-core`:

- Add editor wire structs mirroring the structured catalog fields.
- Port token extraction and classification from Lua/Python into Rust tests.
- Port file candidate generation from Python's `file_completion.py`.
- Add JSON fixtures generated from current Python helper outputs.

In `sase_100`:

- Add an editor helper bridge alias or document that the LSP v1 intentionally calls `mobile helper-bridge
  xprompt-catalog`.

Tests:

- golden tests for tokens: `#`, `#!`, `#foo:`, `/skill`, `@src/foo`, `.sase/foo`, empty cursor;
- parity tests against existing Python examples where feasible.

### Phase 2: LSP Skeleton

In `../sase-core`:

- Add `crates/sase_xprompt_lsp`.
- Implement `initialize`, `shutdown`, text sync, and manual completion.
- Return xprompt completions using helper-bridge catalog data.
- Return file and file-history completions.

In `../sase-nvim`:

- Add optional LSP setup in `require("sase").setup({ lsp = { enabled = true } })`.
- Keep old `<C-t>` dispatcher as fallback.

Tests:

- Rust unit tests for LSP conversion.
- Integration test that sends JSON-RPC initialize + completion over stdio with a static host bridge.
- Minimal Neovim smoke test can stay manual until the server stabilizes.

### Phase 3: Hover, Diagnostics, Code Actions

- Hover for xprompt refs and input positions.
- Diagnostics for unknown refs and canonical marker mismatches.
- Code actions for canonical marker replacement and arg skeleton insertion.

### Phase 4: Thin Plugin Migration

- Switch `sase-nvim` default to LSP when available.
- Delete duplicated Lua token logic after one release cycle.
- Keep Telescope browse commands, but back them from LSP custom requests or the same JSON helper response instead of
  `sase xprompt list`.

### Phase 5: Move XPrompt Catalog Loading Into Rust

Only after the editor LSP API is stable:

- port xprompt discovery/load/catalog logic to `sase_core`;
- use Python parity fixtures to prevent behavior drift;
- remove the Python helper subprocess from the LSP hot path.

## Risks And Constraints

- **Python ownership of xprompt semantics.** Full xprompt parsing/loading is complex and plugin-extensible. Bridge first,
  port later.
- **Catalog freshness.** Editors are long-lived. Add manual refresh and conservative TTL before adding file watching.
- **Trigger-character noise.** Triggering on `/` and `:` can produce too many completion requests. The server must return
  quickly when context is not SASE-relevant.
- **LSP client differences.** VS Code, Neovim, Zed, and Helix differ in snippet support, trigger behavior, and custom
  requests. Keep core features standard LSP; make custom commands optional.
- **Schema association is not generic LSP.** Keep YAML-LS setup separate until there is a clear cross-editor contract.
- **Source paths and security.** Do not expose arbitrary host paths beyond existing safe display fields. For "open
  source" actions, resolve only paths the host bridge explicitly marks as local and safe.

## Open Questions

- Should the server be named narrowly (`sase_xprompt_lsp`) or broadly (`sase_lsp`)?
- Should v1 call the existing mobile helper bridge or add `sase editor helper-bridge` as a clearer stable surface?
- Should slash skills be represented as `/name` completions only, or also as xprompt `#name` completions with a `Skill`
  tag?
- Should the LSP attach to all Markdown/plaintext buffers, or only SASE prompt buffers plus explicitly configured
  filetypes? Attaching everywhere improves prompt drafting but risks noisy completions.
- How should project context be inferred in editors: root dir, current file path, leading VCS xprompt in the buffer, or
  a client-supplied setting?

## Sources

Local code reviewed:

- `../sase-nvim/lua/sase/complete/_token.lua`
- `../sase-nvim/lua/sase/xprompt.lua`
- `../sase-nvim/lua/sase/complete/file.lua`
- `../sase-nvim/lua/sase/complete/file_history.lua`
- `../sase-nvim/plugin/sase_yamlls.lua`
- `src/sase/ace/tui/widgets/file_completion.py`
- `src/sase/ace/tui/widgets/xprompt_completion.py`
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
- `src/sase/xprompt/_catalog_models.py`
- `src/sase/xprompt/_catalog_structured.py`
- `src/sase/xprompt/reference_display.py`
- `src/sase/integrations/_mobile_helper_catalog.py`
- `../sase-core/crates/sase_gateway/README.md`
- `../sase-core/crates/sase_gateway/src/wire.rs`

External references:

- Microsoft LSP overview and latest stable spec note:
  <https://microsoft.github.io/language-server-protocol/>
- LSP 3.18 draft/spec page inspected for current protocol surface:
  <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification/>
- Neovim LSP client and completion documentation:
  <https://neovim.io/doc/user/lsp/>
- `tower-lsp-server` crate docs:
  <https://docs.rs/tower-lsp-server/latest/tower_lsp_server/>
- `lsp-server` crate docs:
  <https://rust-lang.github.io/rust-analyzer/lsp_server/index.html>
