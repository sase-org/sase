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

### Reusable Host-Bridge Substrate Already Exists

`crates/sase_gateway/src/host_bridge.rs` is mature reusable plumbing the LSP should depend on rather than reimplement:

- `pub trait HelperHostBridge` (line 98) defines `xprompt_catalog`, `file_history`, and related methods returning typed
  wire structs.
- `pub struct CommandHelperHostBridge` (line 461) implements the trait by spawning `sase mobile helper-bridge <op>`,
  writing one-line JSON to stdin, parsing one-line JSON from stdout. It already reads
  `SASE_MOBILE_HELPER_BRIDGE_COMMAND` for command override and uses `split_command_words` for argv parsing.
- `pub enum HostBridgeError` (line 1294) already enumerates `BridgeUnavailable`, `HelperNotFound`,
  `InvalidActionRequest`, and update-status variants — directly mappable to LSP `window/showMessage` severity.
- `DynHelperHostBridge` is an `Arc<dyn HelperHostBridge>` for trait-object reuse; `StaticHelperHostBridge` is an
  in-process fake suitable for LSP integration tests.
- Wire structs `MobileXpromptCatalogRequestWire` / `MobileXpromptCatalogResponseWire` live in
  `crates/sase_gateway/src/wire.rs`.

The cleanest refactor is to lift `host_bridge.rs` and the relevant wire structs from `sase_gateway` into `sase_core`
(or a new `sase_host_bridge` crate) so both the gateway and the LSP depend on it. This avoids `sase_xprompt_lsp`
reaching across the gateway crate, which today also pulls HTTP routing, push notifications, and storage it doesn't
need.

Two real limitations of the current substrate that affect the LSP:

- **No request timeout.** `CommandHelperHostBridge::invoke` calls `child.wait_with_output()` with no upper bound. A
  hanging `sase` subprocess would block every subsequent completion. The LSP must wrap calls in
  `tokio::time::timeout` (suggest 5 s for completion, 30 s for refresh).
- **One subprocess per request.** Every call forks a Python interpreter, imports `sase`, runs the helper, and exits.
  In this codebase the cold path is empirically 300-800 ms — too slow for per-keystroke completion. See
  *Performance and Latency Targets* below.

### `tracing` Is Not Yet A Workspace Dependency

`../sase-core/Cargo.toml` does not declare `tracing` or `tracing-subscriber` as workspace deps today. Logging in the
gateway is mostly bare `eprintln!` and structured error returns. The LSP crate should introduce both, since LSP
servers must keep stdout free of any non-protocol bytes (a stray `println!` corrupts framing). The workspace's
existing `tokio` features (`rt-multi-thread`, `io-util`, `macros`, `signal`) and `rust-version = "1.78"` are already
sufficient for `tower-lsp-server`.

### `sase-nvim` Public API Surface To Preserve

The current public surface is small, which makes the migration low-risk:

- `lua/sase/init.lua` exposes only `M.setup({ complete = { keymap = true|"<C-t>" } })`.
- `lua/sase/complete.lua` binds `<C-t>` only when `opts.complete.keymap` is truthy (default off — opt-in).
- `plugin/sase_complete.lua` defines `:SaseFileHistoryRefresh`.
- `plugin/sase_xprompt.lua` registers the `#@` insert trigger.
- `plugin/sase_yamlls.lua` resolves three schema paths via `sase path config-schema | xprompts-schema |
  xprompts-collection-schema` and patches `yamlls`.

Migration constraints: keep the `setup({ complete = ... })` shape, keep `:SaseFileHistoryRefresh`, keep the `#@`
trigger, and find `sase` via `PATH` exactly as the existing `vim.fn.jobstart({ "sase", ... })` calls do. Add an
`opts.lsp = { enabled?: boolean, cmd?: string[] }` field for opt-in LSP startup, and an
`SASE_XPROMPT_LSP_CMD` env override for development.

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

### Option C: `async-lsp`

`async-lsp` is a third option worth naming as a Plan B. It is async/Tower-style like `tower-lsp-server`, actively
maintained, and notably keeps the `LanguageServer` trait dyn-compatible — useful if the server wants runtime-swappable
backends (e.g. a fake host bridge used in tests injected as `dyn LanguageServer`). It is published as
`async-lsp` on crates.io. If `tower-lsp-server`'s impl-Trait-in-trait constraints become a problem, `async-lsp` is the
closest drop-in.

### Status As Of 2026-05

The two main Tower-style options have diverged:

- The original `tower-lsp` (`ebkalderon/tower-lsp`) has stalled. Its last release is 0.20.0, and the upstream
  `lsp-types` crate it depends on is also unmaintained.
- `tower-lsp-server` (`tower-lsp-community/tower-lsp-server`) is the active community fork. Recent releases (0.23.x in
  early 2026) bumped MSRV to 1.77 and switched to the community-maintained `tower-lsp-community/lsp-types` fork.
  Notable behavior change: the `LanguageServer` trait is no longer `dyn`-compatible because it now uses
  impl-Trait-in-trait, so older tutorials that pass a `Box<dyn LanguageServer>` will not compile.

Recommendation: use `tower-lsp-server` for the first implementation unless a dependency audit reveals a problem. It
matches the current `tokio` workspace and should reduce protocol boilerplate. Treat `async-lsp` as the documented
fallback.

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

In practice this should reuse `HelperHostBridge` from `sase_gateway::host_bridge` (or its lifted-into-`sase_core`
form) rather than introduce a parallel trait. Add only the editor-specific methods that don't already exist there.

V1 implementation:

- invoke `sase mobile helper-bridge xprompt-catalog` over JSON stdin/stdout, or add a dedicated
  `sase editor helper-bridge xprompt-catalog` if the mobile route name feels wrong for editor code;
- invoke existing `sase file-history list/delete`;
- resolve schema paths with existing `sase path`;
- do file candidates directly in Rust to avoid a subprocess on every path completion request.

Using the mobile helper bridge for v1 is pragmatic because it already returns structured fields the LSP needs. A
dedicated editor bridge can be introduced as an alias later without changing the LSP-facing library API.

#### Concrete Wire Envelope (V1)

The existing `CommandHelperHostBridge` flow is:

1. `Command::new("sase").args(["mobile", "helper-bridge", "xprompt-catalog"])` (override via
   `SASE_MOBILE_HELPER_BRIDGE_COMMAND`).
2. Spawn with piped stdin/stdout, stderr captured but discarded.
3. Write `serde_json::to_writer(stdin, &MobileXpromptCatalogRequestWire { .. })` followed by `\n`, close stdin.
4. `child.wait_with_output()` (no timeout today — LSP must add one).
5. Parse `serde_json::from_slice::<MobileXpromptCatalogResponseWire>(&output.stdout)`.
6. Map non-zero exit codes to `HostBridgeError` variants; exit 4 has overloaded meaning depending on op.

The LSP wraps each call in `tokio::time::timeout` and on timeout returns `CompletionList { isIncomplete: true,
items: vec![] }` rather than failing the request, so editors don't see a hard error mid-typing.

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

## Additional LSP Methods Worth Considering

The original outline focused on completion, hover, diagnostics, code actions, and inlay hints. The following methods
are also a natural fit for xprompts and should be in the v2+ scope. Each maps directly onto fields the structured
catalog already exposes.

- `textDocument/definition`: jump from `#foo` to its source `.md`/`.yml` using `StructuredCatalogEntry.source_path_display`.
  High value, low cost.
- `textDocument/documentSymbol` and `workspace/symbol`: list xprompts referenced in the buffer (document) or available
  in the project (workspace). Lets editors expose a SASE outline / fuzzy-finder without a Telescope-equivalent.
- `textDocument/references`: find buffers referencing `#foo`. Medium value; needs a cross-buffer index.
- `textDocument/semanticTokens`: highlight xprompt references uniformly across editors instead of duplicating
  Tree-sitter queries. This is the cleanest way to retire the per-editor syntax files in `sase-nvim/syntax/` and the
  TUI's manual highlighter.
- `workspace/executeCommand`: maps cleanly to `sase.refreshXpromptCatalog`, `sase.clearFileHistory`,
  `sase.openXpromptSource`. The original outline mentioned this; it should be promoted to a first-class capability
  rather than an afterthought.
- `workspace/didChangeWatchedFiles`: register xprompt source globs (`xprompts/**/*.md`, `xprompts/**/*.yml`,
  `~/.config/sase/sase.yml`) and `~/.sase/file_reference_history.json` so the catalog auto-invalidates without manual
  refresh.
- `window/workDoneProgress`: report progress for cold catalog loads. With a 300-800 ms cold helper-bridge call this
  matters more than it does for typical LSPs.
- `$/cancelRequest`: cancel stale completion requests while a slow helper-bridge call is in flight. Without this the
  server will serialize on the bridge.

## Document Filter and Filetype Strategy

The original draft asked whether to attach to all Markdown buffers or only SASE-specific ones, but did not commit to a
strategy.

Recommendation: advertise a permissive `documentSelector` covering `markdown`, `gitcommit`, and a custom `sase` /
`saseprompt` language id, then *gate xprompt completion on token detection inside the analyzer* rather than on
filetype. This mirrors how Copilot, codeium, and tabnine attach broadly without taking over irrelevant buffers — the
server returns an empty completion list when no SASE token is present, which is cheap.

For Neovim the client side becomes:

```lua
vim.lsp.start({
  name = "sase-xprompt-lsp",
  cmd = { "sase-xprompt-lsp" },
  filetypes = { "markdown", "gitcommit", "sase" },
  root_dir = vim.fs.root(0, { ".sase", ".git" }),
})
```

`sase-nvim/ftdetect/` currently only handles `.gp` ChangeSpec files. Adding a `saseprompt` filetype detector for
prompt-style buffers (e.g. `*.sase.md`, files under `xprompts/`) lets users opt in explicitly when they want richer
diagnostics or want to suppress xprompt completion in vanilla Markdown.

## Performance and Latency Targets

The original draft mentioned that the server "must return quickly when context is not SASE-relevant" but did not set
targets or quantify the helper-bridge cost.

Concrete targets:

- VS Code's built-in completion budget is ~100 ms per keystroke before the UI feels laggy.
- Neovim's `vim.lsp.completion.enable` debounces at 150 ms by default.
- Empirical cold cost of `sase mobile helper-bridge xprompt-catalog` in this codebase: ~300-800 ms (Python interpreter
  startup + `sase` import + catalog build). Several catalog calls per keystroke is a non-starter.

Mitigation hierarchy, in order of complexity:

1. **In-process catalog cache.** Load once on `initialize` (with a `window/workDoneProgress` token), serve subsequent
   completion requests from memory. Invalidate on `workspace/didChangeWatchedFiles`. This alone makes warm latency
   sub-millisecond.
2. **Background refresh.** A Tokio task periodically refreshes the cache (e.g. every 60 s) so the helper-bridge cost
   never lands on a user keystroke. Combined with watched-file invalidation, this covers most edits.
3. **Long-lived helper subprocess.** Replace the one-shot `sase mobile helper-bridge` invocation with a persistent
   `sase mobile helper-bridge --stdio` process speaking newline-delimited JSON-RPC. This is how `pyright` and
   `pyrefly` keep latency down. Requires changes on the Python side.
4. **In-process via PyO3.** `sase_core_rs` is already shipped via maturin (`just rust-install`), so the LSP could
   theoretically call into Python directly without a subprocess at all. This is the lowest-latency option but couples
   the Rust binary to a specific Python install.

V1 should ship with options 1 and 2. Option 3 is the right next step if user reports indicate cold-start lag on first
completion. Option 4 should not be pursued unless 1-3 prove insufficient — it gives up the clean process boundary the
gateway architecture deliberately enforces.

## Capability Negotiation Gates

The original draft listed features the server should advertise but did not gate behavior on what the client actually
supports. Older clients (Helix until recently, plain Neovim before 0.10) lack pieces that VS Code takes for granted.
Concrete checks to make against `InitializeParams.capabilities` before sending:

- `textDocument.completion.completionItem.snippetSupport` — required before returning
  `CompletionItem.insertTextFormat = Snippet`. If false, downgrade to plain text and skip placeholder syntax.
- `textDocument.completion.completionItem.resolveSupport.properties` — required before returning items that depend on
  `completionItem/resolve` to fill `documentation` or `detail`. If absent, inline expensive fields up front or omit
  them.
- `textDocument.completion.completionItem.tagSupport.valueSet` — controls whether the server can mark a stale `#foo`
  with `CompletionItemTag.Deprecated` when the catalog says `#!foo` is canonical.
- `textDocument.codeAction.codeActionLiteralSupport` — required before returning `CodeAction` literals. Older clients
  only handle `Command` payloads, so the server must fall back to commands plus `workspace/executeCommand`.
- `textDocument.publishDiagnostics.tagSupport.valueSet` — controls `DiagnosticTag.Unnecessary` for warnings such as
  "this should be `#!foo`".
- `workspace.workspaceFolders` — if absent, fall back to single-root mode using `rootUri`.

## Snippet Portability

The original draft mentioned `insertTextFormat = Snippet` for required-arg skeletons but did not flag editor-side
gaps. TextMate-style placeholders (`$1`, `${1:default}`, `$0`) are LSP-standard, but support is uneven:

- Neovim 0.10+ has built-in support via `vim.lsp.completion.enable`. Earlier versions need `vim-vsnip` or similar.
- Helix added LSP snippet support relatively recently (PR #5864 era); placeholder navigation with Tab/Shift-Tab is
  still incomplete in some versions.
- Known Neovim issue: snippet placeholders are not pre-selected in some configurations (issue #29251).
- VS Code is the reference implementation and has the most complete behavior.

The server must always check `snippetSupport` before emitting placeholder-bearing insert text. Even when supported,
prefer simple completion items by default (plain `#foo`), and surface "insert with required-arg skeleton" as a
separate completion item (different `label`) or as a code action. This gives users a predictable default and a
clearly-opt-in snippet path.

## Error and Recovery Model

The original draft did not specify what the server should do when the host bridge fails. Concrete model:

- **Subprocess returns malformed JSON or non-zero exit:** map to `HostBridgeError`, log via `tracing::warn!`, send a
  one-time `window/showMessage` (severity Warning), and emit a sticky `publishDiagnostics` entry on a synthetic URI
  such as `sase:catalog` summarizing the failure. Do not crash the server. Subsequent completion requests return
  empty `CompletionList { isIncomplete: true, items: [] }`.
- **Subprocess hangs:** wrap calls in `tokio::time::timeout` (5 s for completion path, 30 s for explicit refresh).
  On timeout treat as transient — return empty completions, log a warning, and let the next request retry.
- **`sase` binary not on PATH:** detect at `initialize`, send `window/showMessage` (severity Error) once, and continue
  serving an empty catalog so the editor still loads. Do not exit — exiting would cause clients to repeatedly restart
  the server.
- **Catalog refresh races with shutdown:** background tasks must observe `CancellationToken` (or
  `tower-lsp-server`'s shutdown signal) and abort cleanly so the process exits within the LSP shutdown grace period.

The general principle: an LSP server that exits or crashes during normal operation is worse than one that returns
degraded results, because clients aggressively restart and the user sees flicker plus repeated error popups.

## Logging and Observability

LSP servers must keep stdout clean — every byte on stdout is part of the JSON-RPC framing. All logging must go to
stderr. Clients capture stderr automatically: Neovim writes it to `vim.lsp.get_log_path()` (controlled by
`vim.lsp.set_log_level`), VS Code routes it to the "Output" channel selected by server name.

Because `sase-core` does not currently use `tracing`, the LSP crate should:

- Add `tracing` and `tracing-subscriber` (with `env-filter` and `json` features).
- Initialize a `tracing_subscriber::fmt()` writer pinned to `std::io::stderr`, controlled by `SASE_XPROMPT_LSP_LOG`
  (e.g. `SASE_XPROMPT_LSP_LOG=info,sase_xprompt_lsp=debug`).
- Avoid all `println!` / `print!` in the LSP crate. Add a clippy lint or a `#![deny(clippy::print_stdout)]` at the
  crate root to prevent regressions.
- Emit structured events at request boundaries (`initialize`, `completion`, `hover`, `executeCommand`) with request
  IDs and durations so a user can paste a log into a bug report.

A `--log-file <path>` flag on the binary is also worth supporting for users who can't easily access editor log files.

## Distribution and Install Path

The original draft did not address how users get the binary. Today:

- `sase` ships as a Python entrypoint via `pip install -e ".[dev]"` (see `Justfile`) or `uv tool install sase`;
  `pyproject.toml` declares the console script `sase = "sase.main.entry:main"`.
- The Rust extension `sase_core_rs` is built via maturin into the venv (`just rust-install`), so a Rust toolchain is
  already on the install critical path for full installs.
- `sase-nvim` finds `sase` purely via `PATH` (`vim.fn.jobstart({ "sase", "path", ... })`). There is no env override.

Three viable distribution options for `sase_xprompt_lsp`:

1. **Ship as a `sase lsp` subcommand.** Simplest user-facing change — no new binary, no new install step. The Python
   subcommand `exec`s into the Rust binary which is bundled inside the wheel (similar to how `ruff` ships its Rust
   binary inside a Python wheel). `sase-nvim` invokes `vim.lsp.start({ cmd = { "sase", "lsp" } })`.
2. **Standalone `sase-xprompt-lsp` binary.** Built by `cargo build --release` in `../sase-core`, copied into
   `~/.local/bin` (or a `just lsp-install` step). Cleaner for editors that don't want a Python on the user's PATH,
   but adds a second install workflow.
3. **Maturin-shipped console script.** Add a second console script entry to `pyproject.toml` that wraps the bundled
   binary. Minimal user surface but couples release cadence.

Recommendation: option 1 for v1 (zero new install steps), with option 2 documented for users who want to run the LSP
without installing the full `sase` Python package. For dev iteration, support an `SASE_XPROMPT_LSP_CMD` env var so
contributors can point at a `cargo run` target without rebuilding the wheel.

## Prior Art

A few open-source projects worth studying before writing the first version:

- **marksman** (`artempyanykh/marksman`) — Markdown LSP in F#. Single-binary distribution, completion + diagnostics +
  goto-definition + references over wiki-style references; very close conceptually to "complete `#xprompt` cross
  references in prose." The structure of its workspace symbol search and reference resolution is directly applicable.
- **hx-lsp** (`erasin/hx-lsp`) — Rust LSP that wraps a *static catalog* of VS Code-format snippets and code actions
  for Helix. Closest analog to the xprompt-catalog use case, including how it watches catalog files for changes.
- **taplo** (`tamasfe/taplo`) — TOML LSP in Rust. Demonstrates the snapshot-test pattern for completion / hover output
  and a clean separation between the protocol layer and the analyzer crate; the two-crate split this draft proposes
  matches taplo's `taplo` / `taplo-lsp` boundary.
- **lsp-cli** (`valentjn/lsp-cli`) — drives an arbitrary LSP from the shell. Useful as an end-to-end test harness
  invoked from the existing `tests/` tree.
- **Prefab "LSP from zero to completion" tutorial** — concrete walkthrough of building a completion-only LSP
  (TypeScript / `vscode-languageserver`). The catalog-fetching pattern transfers cleanly to Rust.

## Test Harness Choices

The draft's "integration test that sends JSON-RPC initialize + completion over stdio" stayed abstract. Concrete
options:

- For unit tests of the analyzer (`sase_core::editor::*`), plain `cargo test` with golden JSON fixtures generated
  from current Python helper output. Snapshot via `insta` to keep diffs reviewable.
- For LSP integration tests inside `sase_xprompt_lsp`, drive the server via `tower::ServiceExt::oneshot` against the
  `LspService` directly — `tower-lsp-server`'s own examples do this. No subprocess needed.
- For end-to-end smoke tests, use rust-analyzer's pattern: `lsp_server::Connection::memory()` (in-memory channel
  pair) wired to the same server entry point used in production.
- For cross-tool sanity, run `lsp-cli` against the release binary from a shell script in CI, asserting on
  completion / hover output for fixture buffers.

A `StaticHelperHostBridge` (already exists in `sase_gateway`) is the right fake for all of the above — tests can
preload it with deterministic catalog responses and avoid spawning Python entirely.

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

Additional local code reviewed in this revision:

- `../sase-core/crates/sase_gateway/src/host_bridge.rs` (`HelperHostBridge`, `CommandHelperHostBridge`,
  `HostBridgeError`, `StaticHelperHostBridge`)
- `../sase-core/Cargo.toml` (workspace deps and Rust version)
- `../sase-nvim/lua/sase/init.lua`, `lua/sase/complete.lua`
- `../sase-nvim/plugin/sase_complete.lua`, `plugin/sase_xprompt.lua`, `plugin/sase_yamlls.lua`
- `pyproject.toml` and `Justfile` (distribution / install path)

External references:

- Microsoft LSP overview and latest stable spec note:
  <https://microsoft.github.io/language-server-protocol/>
- LSP 3.18 draft/spec page inspected for current protocol surface:
  <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification/>
- Neovim LSP client and completion documentation:
  <https://neovim.io/doc/user/lsp/>
- `tower-lsp-server` (active community fork): <https://github.com/tower-lsp-community/tower-lsp-server>
- `tower-lsp` (original, stalled): <https://github.com/ebkalderon/tower-lsp>
- `tower-lsp-server` crate docs: <https://docs.rs/tower-lsp-server/latest/tower_lsp_server/>
- `async-lsp` crate (Plan B): <https://lib.rs/crates/async-lsp>
- `lsp-server` crate docs: <https://rust-lang.github.io/rust-analyzer/lsp_server/index.html>
- marksman (Markdown LSP, prior art for cross-reference completion): <https://github.com/artempyanykh/marksman>
- hx-lsp (Rust LSP wrapping a static snippet catalog): <https://github.com/erasin/hx-lsp>
- taplo (TOML LSP — analyzer/protocol crate split pattern): <https://github.com/tamasfe/taplo>
- lsp-cli (CLI-driven LSP test harness): <https://github.com/valentjn/lsp-cli>
- Prefab "LSP from zero to completion" tutorial:
  <https://prefab.cloud/blog/lsp-language-server-from-zero-to-completion/>
- Helix LSP snippet support PR (placeholder gaps): <https://github.com/helix-editor/helix/pull/5864>
- Neovim snippet placeholder issue: <https://github.com/neovim/neovim/issues/29251>
- vim-vsnip (legacy Neovim snippet support): <https://github.com/hrsh7th/vim-vsnip>
