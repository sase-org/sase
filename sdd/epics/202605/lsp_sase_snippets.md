---
create_time: 2026-05-09 00:57:55
status: done
prompt: sdd/prompts/202605/lsp_sase_snippets.md
bead_id: sase-2f
tier: epic
---
# Plan: Expose SASE Snippets Through The XPrompt LSP

## Context

The prompt input widget already has two snippet sources:

- xprompt snippets from `src/sase/xprompt/snippet_bridge.py`, where xprompts marked with `snippet: true` or
  `snippet: <trigger>` are converted into ACE snippet templates.
- user snippets from `ace.snippets` in the merged SASE config, loaded in `src/sase/ace/tui/actions/_state_init.py` and
  merged in `src/sase/ace/tui/actions/startup.py`.

The prompt widget expands those snippets in `src/sase/ace/tui/widgets/_snippets.py` by replacing a bare trigger word
immediately before the cursor. The template format supports `$1`, `$2`, and `$0` tabstops, continuation-line
indentation, and trigger names limited by the current word extraction behavior.

The xprompt LSP currently lives in `../sase-core/crates/sase_xprompt_lsp` and already supports LSP snippet completion
for xprompt reference skeletons and directives when the client advertises `completionItem.snippetSupport`. It does not
yet expose the prompt widget's snippet registry. Its xprompt catalog cache uses Rust-side catalog loading and/or the
Python helper bridge, but the editor wire structs do not include snippet metadata or full composed snippet templates.

## Product Goal

Editors such as Neovim should have access to the same SASE snippets as the prompt input widget, without reimplementing
snippet loading or xprompt composition in each editor plugin.

The MVP should make LSP completion return snippet items for ordinary snippet triggers, with template expansion behavior
matching the prompt widget as closely as LSP snippets allow. The editor plugin should remain thin: start the LSP, enable
snippet-capable completion, and let the server provide the entries.

## Key Design Decisions

- Python remains authoritative for snippet registry construction in the first version. `get_xprompt_snippets()` already
  composes nested xprompt references and respects Python plugin/config/project loading behavior.
- Add a typed editor helper bridge operation for snippets rather than piggybacking on the xprompt catalog. Snippets have
  different semantics from xprompt references: trigger word, template text, source attribution, and collision policy.
- Keep the helper response backward-compatible and editor-scoped. The operation should live under
  `sase editor helper-bridge snippet-catalog`; mobile can alias it only if useful.
- Add Rust wire types and cache support in `sase_core` / `sase_xprompt_lsp`, then convert entries into standard LSP
  `CompletionItemKind::SNIPPET` items.
- Gate snippet insertions on client `snippetSupport`. If a client cannot expand snippets, return no snippet catalog
  completions rather than inserting raw `$1` / `$0` markers.
- Treat ordinary bare-word snippet completion as distinct from xprompt reference completion. `#foo` completion should
  keep its existing xprompt-reference behavior; `foo` should be able to complete/expand a SASE snippet trigger.
- User-configured `ace.snippets` should continue to override xprompt-derived snippets on trigger collision, matching
  `AceApp.get_snippets()`.

## Dependency Graph

1. Phase 1 creates the Python helper contract and tests parity with the prompt widget source.
2. Phase 2 adds Rust wire/bridge/cache support for that helper operation.
3. Phase 3 teaches the core editor analyzer and LSP server how to classify bare snippet trigger contexts and emit LSP
   snippet completion items.
4. Phase 4 validates Neovim/editor behavior end to end and makes any thin client adjustments.
5. Phase 5 improves native Rust catalog parity and documentation after the helper-backed MVP is stable.

Each phase is intended for a distinct agent instance. Phase agents should avoid broad refactors outside their listed
files and report the exact commands they ran.

## Verification Rules

- In `sase_101`, run `just install` first if the workspace may be stale. For non-bead file changes, run focused tests
  and then `just check`.
- In `../sase-core`, run focused Rust tests for touched crates, then `cargo fmt --all -- --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`.
- In `../sase-nvim`, run any added tests or a headless Neovim smoke test. If there is still no repo-level check target,
  state that explicitly.

## Phase 1: Python Editor Snippet Helper

**Owner:** `sase_101` Python integration agent.

**Goal:** expose the same merged snippet registry used by ACE through a stable JSON helper operation.

**Primary files:**

- `src/sase/integrations/editor_helpers.py`
- `src/sase/integrations/mobile_helpers.py` and/or a new editor-specific helper module
- `src/sase/main/parser_editor.py`
- `src/sase/xprompt/snippet_bridge.py`
- `tests/test_editor_helpers.py`
- `tests/test_xprompt_snippet_bridge.py`

**Design:**

- Add `sase editor helper-bridge snippet-catalog`, reading a JSON request from stdin.
- Request shape should include at least `schema_version` and optional `project`. Keep room for future `query`, `source`,
  or `limit`, but do not overbuild filtering in this phase.
- Response shape should include:
  - `schema_version`
  - `result` metadata matching existing helper style
  - `context` with project/scope
  - `entries`, each with `trigger`, `template`, `source`, optional `xprompt_name`, optional `description`, and optional
    `source_path_display`
  - `stats.total_count`
- Build entries from `get_xprompt_snippets(project=project)` plus merged config `ace.snippets`, with user snippets
  overriding xprompt snippets exactly like `AceApp.get_snippets()`.
- Preserve current trigger validation for xprompt snippets. For user snippets, decide explicitly whether to enforce the
  same bare-word trigger rule. Preferred MVP: filter to the same trigger characters the prompt widget can expand so the
  helper never advertises snippets the widget cannot trigger.
- Keep template strings in SASE/ACE snippet syntax (`$1`, `$2`, `$0`) in the helper response. LSP escaping belongs in
  Rust conversion, not in the Python registry.

**Tests:**

- Parser accepts `sase editor helper-bridge snippet-catalog`.
- Helper output includes an xprompt snippet converted by `get_xprompt_snippets`.
- Helper output includes `ace.snippets` config snippets.
- User config snippets override xprompt snippets with the same trigger.
- Invalid/unexpandable triggers are omitted consistently.
- Nested xprompt composition still works through the helper path.

**Acceptance criteria:**

- A command-backed editor integration can ask Python for the same snippet registry as ACE.
- Existing `xprompt-catalog` helper behavior is unchanged.

## Phase 2: Rust Snippet Wire And Helper Bridge

**Owner:** `../sase-core` bridge/cache agent.

**Goal:** make the Rust LSP able to call and cache the new snippet helper operation without coupling completion logic to
Python JSON details.

**Primary files:**

- `../sase-core/crates/sase_core/src/host_bridge.rs`
- `../sase-core/crates/sase_core/src/editor/wire.rs`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/catalog_cache.rs` or a new `snippet_cache.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/server.rs`

**Design:**

- Add `EditorSnippetCatalogRequestWire`, `EditorSnippetCatalogResponseWire`, and `EditorSnippetEntryWire` structs.
- Add `HelperHostBridge::snippet_catalog()` and implement it in `CommandHelperHostBridge` by invoking `snippet-catalog`.
- Extend `StaticHelperHostBridge` for deterministic LSP tests.
- Add a cache keyed by the same root/project context as the xprompt catalog. The TTL can match the xprompt catalog
  initially.
- Reuse the existing helper timeout/error policy: completion-path refresh should degrade to cached or empty entries,
  explicit refresh can wait longer, and warnings should be rate-limited by failure class.
- Invalidate snippet cache on watched changes to `sase.yml`, xprompt markdown/YAML files, and config/plugin paths that
  already invalidate the xprompt catalog.

**Tests:**

- Wire serde round trip for request/response.
- `CommandHelperHostBridge` invokes `snippet-catalog`.
- Static bridge returns fixture snippet entries.
- Cache returns stale entries on helper failure when a previous refresh succeeded.

**Acceptance criteria:**

- `sase_xprompt_lsp` can obtain snippet entries through the same helper infrastructure as xprompt catalog entries.
- Existing xprompt catalog cache tests still pass.

## Phase 3: LSP Snippet Completion

**Owner:** `../sase-core` editor/LSP agent.

**Goal:** return LSP snippet completion items for SASE snippet triggers in ordinary prompt text.

**Primary files:**

- `../sase-core/crates/sase_core/src/editor/token.rs`
- `../sase-core/crates/sase_core/src/editor/completion.rs`
- `../sase-core/crates/sase_core/src/editor/wire.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/lsp_convert.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/server.rs`
- `../sase-core/crates/sase_xprompt_lsp/tests/jsonrpc_stdio.rs`

**Design:**

- Add a snippet completion context for bare word tokens matching the prompt widget's trigger extraction behavior:
  alphanumeric plus underscore immediately before the cursor.
- Preserve higher-priority contexts:
  - xprompt references starting with `#`
  - slash skills
  - file/path contexts
  - directive contexts
  - xprompt argument contexts
  - empty cursor file-history context
- Filter snippet entries by case-insensitive prefix on `trigger`.
- Completion items should:
  - use `CompletionItemKind::SNIPPET`
  - use `InsertTextFormat::SNIPPET`
  - replace only the trigger word range
  - label by trigger, with detail/source metadata
  - include bounded docs from description/source when available
- Convert SASE snippet templates into LSP snippet syntax. `$1`, `$2`, and `$0` should remain tabstops; literal `$`, `}`,
  and `\` in snippet content must be escaped so LSP clients do not misinterpret them.
- Do not return SASE snippet completion items when `snippetSupport` is false.
- Keep xprompt-reference skeleton completion unchanged. This phase adds bare trigger snippets; it should not change
  existing `#foo` behavior.

**Tests:**

- Core context classification detects `foo|` as snippet context but does not steal `#foo|`, `/foo|`, `@foo|`, `%model|`,
  `./foo|`, or empty cursor contexts.
- Prefix filtering returns matching triggers.
- LSP conversion preserves `$1`/`$0` tabstops and escapes literal special characters.
- Server-level completion test with snippet support returns `CompletionItemKind::SNIPPET` for `foo|`.
- Server-level completion test without snippet support omits bare snippet items.
- Regression tests prove existing xprompt and directive snippet completions still work.

**Acceptance criteria:**

- An LSP client with snippet support can invoke completion after a bare trigger word and receive the same template text
  ACE would expand.
- Existing LSP completion behavior for xprompts, directives, files, and history is unchanged.

## Phase 4: Editor / Neovim End-To-End Validation

**Owner:** `../sase-nvim` or cross-repo editor agent.

**Goal:** prove Neovim can use the new LSP snippet items without adding snippet registry logic to Lua.

**Repos:**

- `../sase-nvim`
- `sase_101`
- `../sase-core`

**Primary work:**

- Confirm `sase-nvim` starts `sase lsp` with snippet-capable completion client capabilities.
- If the plugin has a custom completion backend path that filters completion kinds, allow LSP snippet items through.
- Add or update a headless Neovim smoke test if the repo has a practical harness. Otherwise, document a reproducible
  manual check.
- Manual smoke target: define a test `ace.snippets` entry, open a markdown/sase prompt buffer, type the trigger prefix,
  invoke LSP completion, accept the item, and verify tabstops are active.

**Acceptance criteria:**

- Neovim can complete at least one user-config snippet and one xprompt-derived snippet through the LSP.
- No Lua code shells out to load the snippet registry directly.

## Phase 5: Native Rust Parity And Documentation

**Owner:** follow-up core/docs agent.

**Goal:** reduce helper dependency where practical and document the behavior for future editor clients.

**Primary files:**

- `../sase-core/crates/sase_core/src/xprompt_catalog.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/catalog_cache.rs`
- `README.md`
- `docs/xprompt.md` or editor integration docs

**Design:**

- Consider adding `snippet` parsing to the native Rust xprompt loader only after the helper-backed path is stable.
- If native Rust snippet loading is added, it must match Python behavior for:
  - `snippet: true` trigger derivation
  - `snippet: <trigger>`
  - required/defaulted inputs
  - simple Jinja input substitution
  - legacy `{1}` and `{1:default}` placeholders
  - skipping complex Jinja templates
  - nested xprompt composition or a documented fallback to helper when composition is needed
- Document the LSP behavior, client requirements (`snippetSupport`), and troubleshooting path
  (`sase editor helper-bridge snippet-catalog`).

**Acceptance criteria:**

- Documentation explains how editor clients obtain SASE snippets.
- Any native Rust optimization remains parity-tested against Python or falls back to the helper for incomplete cases.

## Open Questions For Phase Agents

- Should bare snippet completions trigger automatically on every word character, or only on explicit completion request?
  Preferred MVP: advertise support through normal LSP completion and let clients decide trigger behavior; do not add new
  trigger characters solely for snippets.
- Should non-snippet-capable clients receive plain-text snippet expansions with tabstops stripped? Preferred MVP: no,
  because silently losing tabstop behavior is surprising.
- Should `ace.snippets` support namespaced or non-word triggers in the future? Current MVP should mirror the prompt
  widget's actual trigger extraction and omit entries it cannot expand.
