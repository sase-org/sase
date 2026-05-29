# TUI Prompt Autocomplete Options

Date: 2026-05-29

## Question

How can the `sase ace` prompt input widget get Neovim-like xprompt/file/directive/snippet completion while staying fast
enough that typing never feels interrupted?

## Executive Summary

Do not add a per-keystroke subprocess call, per-keystroke LSP request, or per-keystroke Python catalog rebuild to the ACE
prompt widget. The current local timing makes that constraint concrete: `build_xprompt_assist_entries()` and
`build_xprompt_completion_candidates("#")` each took about 700 ms in this workspace for 92 catalog entries, while cached
filtering and token detection were below 0.1 ms. The expensive part is catalog construction, not matching.

The best path is a two-layer design:

1. Keep `Ctrl+T` as the deterministic manual completion path and make it cache-backed first.
2. Add a low-intrusion automatic layer that only runs cheap context detection on each edit, waits for a short debounce,
   and renders either ghost text or a small non-modal suggestion panel from already-warm data.

For implementation, the most durable architecture is to reuse `sase-core` editor logic in-process through new
`sase_core_rs` PyO3 bindings. `../sase-core` already has the editor completion engine and `sase_xprompt_lsp`; using the
same logic directly in ACE avoids duplicating the Neovim LSP behavior while avoiding JSON-RPC process overhead inside
the TUI.

Recommended order:

1. Add a prompt-completion cache/warmup in the Python TUI so existing `Ctrl+T` no longer rebuilds the xprompt catalog.
2. Add optional ghost-text completion for the top/shared candidate, accepted by an explicit key, never by `Enter`.
3. Add an optional small auto menu for xprompts/directives/argument names only; keep path completion manual until it is
   moved to a worker and cancellation/discard logic is in place.
4. Add PyO3 bindings for `sase_core::editor` and switch ACE prompt completion to the shared Rust classifier/builders.
5. Consider talking to `sase lsp` only if the TUI later wants full LSP features such as hover/diagnostics/definition as
   a separate process boundary.

## Current State

The ACE prompt widget is `PromptTextArea` inside `PromptInputBar`:

- `src/sase/ace/tui/widgets/prompt_text_area.py`
  - `Ctrl+T` calls `_try_file_completion_tab()`.
  - `Enter` accepts an active completion before submitting the prompt.
  - `Tab` is reserved for snippet expansion/tabstop advance.
  - After normal key handling, it refreshes active file completion and xprompt argument hints.
- `src/sase/ace/tui/widgets/_file_completion.py`
  - dispatches completion across file history, directives, xprompts, file paths, and xprompt arguments.
- `src/sase/ace/tui/widgets/xprompt_completion.py`
  - currently calls `build_xprompt_assist_entries()` inside `build_xprompt_completion_candidates()`.
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
  - already builds structured xprompt assist entries from `build_structured_xprompts_catalog()`.
  - detects typed xprompt argument contexts.
  - provides colon/named-arg skeletons and structured input hints.
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
  - renders the completion/hint panel in `Static#prompt-completion`.
  - grows the prompt bar height when the panel appears.

This means the TUI already has more than basic completion. The gap is automatic, Neovim-style triggering and a latency
model that makes that safe.

## Neovim/LSP State

The older `xprompt_lsp_server_research.md` has partially landed:

- `sase lsp --version` works in this workspace and reports `sase-xprompt-lsp 0.1.1`.
- `../sase-core` now has:
  - `crates/sase_xprompt_lsp`
  - `crates/sase_core/src/editor/*`
  - `editor_classify_completion_context`
  - `editor_build_xprompt_completion_candidates`
  - `editor_build_file_completion_candidates_with_base`
  - `editor_build_file_history_completion_candidates`
  - `editor_build_snippet_completion_candidates`
  - directive, hover, diagnostic, and definition support.
- The LSP server advertises trigger characters `#`, `!`, `/`, `%`, `.`, `@`, `:`, `(`, and `,`.
- The LSP cache has a 30 s TTL, a 5 s completion refresh timeout, and a 30 s explicit refresh timeout.
- The server invalidates catalog caches on watched xprompt/config/history files.
- `../sase-nvim/lua/sase/lsp.lua` starts the server with `vim.lsp.start()` and enables Neovim native completion with
  `vim.lsp.completion.enable(..., { autotrigger = true })` when appropriate.

Important mismatch: `sase_core_rs` does not currently expose the editor completion functions to Python. ACE can reuse
the source algorithms only after adding bindings, or by embedding a JSON-RPC client to the LSP process.

## Local Timing Snapshot

Environment notes:

- Direct `python` was 3.10 and failed because the project requires Python 3.12.
- Timing was rerun with `python3.12` and `PYTHONPATH=src`.
- This is a directional local sample, not a benchmark suite.

Results:

| Operation | Count | p50 | Max | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `build_xprompt_assist_entries()` | 10 | 698 ms | 709 ms | Too slow for key handling or debounce-triggered foreground work. |
| `build_xprompt_completion_candidates("#")` | 10 | 697 ms | 732 ms | Too slow because it rebuilds the catalog. |
| `extract_token_around_cursor("#review path", 7)` | 10000 | 0.002 ms | 0.031 ms | Safe on every key. |
| Cached catalog filter over 92 entries | 5000 | 0.017 ms | 0.072 ms | Safe on every key if catalog is warm. |
| Cached arg-hint detection | 5000 | 0.014 ms | 0.073 ms | Safe on every key if catalog is warm. |

Conclusion: automatic completion is feasible, but only with a warm cache and a strict rule that all I/O/catalog building
happens outside the key handler.

## Options

### Option A: Python-Local Auto Completion With Warm Cache

Keep the current Python widget logic, but add a cache and an automatic trigger path:

- Warm `build_xprompt_assist_entries(project=...)` when the prompt bar mounts or receives focus.
- Refresh the cache after returning from the workflow editor/xprompt editor and on an explicit refresh action.
- On each key, run only cheap token/context detection.
- Use a short debounce, roughly 75-120 ms, before showing automatic suggestions.
- Discard stale results by comparing a generation counter, prompt text hash, cursor offset, and completion context.
- For path completion, do `os.scandir` in a worker or keep it manual.

Pros:

- Smallest change to ACE.
- No subprocess, no JSON-RPC, no packaging changes.
- Can improve `Ctrl+T` immediately.

Cons:

- Continues duplication with `sase-core` editor logic and Neovim LSP behavior.
- Needs careful cache invalidation for project-local/plugin xprompts.
- Automatic snippets/directives/xprompt args would drift unless tests compare against Rust editor fixtures.

Verdict: good first slice, but not the final architecture.

### Option B: Reuse `sase-core` Editor Logic Through PyO3

Expose a small editor-completion API from `sase_core_rs` and have ACE call it in-process:

```text
editor_classify_completion_context(text, line, character, entries_json) -> dict | None
editor_build_completion_candidates(context_json, entries_json, root_dir, file_history) -> dict
editor_extract_token_at_position(text, line, character) -> dict | None
editor_assist_entries_from_catalog(catalog_entries_json) -> list[dict]
```

Keep catalog loading separate at first:

- Python can still call `build_structured_xprompts_catalog()` during warmup.
- Convert its entries into Rust editor wire shape.
- The hot path uses Rust classifier/builders over an in-memory catalog.

Later, ACE can switch to the Rust native catalog loader if plugin/project parity is good enough.

Pros:

- Best long-term parity with Neovim LSP.
- No LSP process lifecycle inside the TUI.
- In-process calls avoid JSON-RPC framing and stdio risks.
- Matches the repo rule that shared editor behavior belongs in `../sase-core`.

Cons:

- Requires new `sase-core` PyO3 bindings and release/install coordination.
- Must keep wire conversion small and stable.
- File-history and xprompt catalog data still need Python-side cache ownership or additional bindings.

Verdict: recommended target architecture.

### Option C: Spawn And Talk To `sase lsp` From The TUI

ACE could start the same LSP server Neovim uses and send JSON-RPC messages for `textDocument/completion`.

Pros:

- Maximum behavioral parity with Neovim.
- Reuses the existing server cache, diagnostics, hover, definition, and code actions.
- No new PyO3 API surface.

Cons:

- Heavy for an in-process TUI widget.
- Requires a mini LSP client: initialize, document sync, request IDs, cancellation/discard, stderr logging, shutdown.
- The current server uses full text sync, which is fine for editors but unnecessary for the prompt widget.
- Warm completion can be fast, but startup/refresh failures now sit in the typing path unless carefully hidden.

Verdict: not the first choice. Use only if ACE wants broader LSP features beyond completion.

### Option D: Ghost Text Only

Use Textual's suggestion-style UX for one best completion/shared extension:

- Show ghost text for the top match or common extension.
- Accept with `Ctrl+L`, right-arrow-at-end, or another explicit key.
- Keep the existing `Ctrl+T` panel for lists and docs.

Pros:

- Least disruptive.
- Does not steal `Enter`, `Tab`, or navigation keys.
- Can feel like editor completion without a popup appearing on every character.

Cons:

- Only shows one candidate.
- Not enough for discovery-heavy cases like `#` with many xprompts.
- Textual's higher-level `Suggester` is primarily `Input`-oriented; `TextArea` may need direct suggestion state or a
  custom overlay depending on the exact Textual API surface in use.

Verdict: best default automatic UX. Pair it with manual `Ctrl+T`.

### Option E: Automatic Popup Menu

Show the existing completion panel automatically after trigger characters or prefix changes.

Pros:

- Closest to Neovim completion popup behavior.
- Good for discovery when users type `#rev`, `%mod`, or named xprompt args.

Cons:

- The current panel resizes the prompt bar, so opening it on every trigger can move the surrounding UI.
- Existing active-completion behavior makes `Enter` accept completion, which would break prompt-submission flow if a
  popup appears automatically.
- `Ctrl+N`/`Ctrl+P` already have prompt-bar meanings, including VCS MRU cycling.

Verdict: useful as an opt-in mode after ghost text. It needs different key semantics from explicit `Ctrl+T`.

## Recommended UX Contract

Keep three distinct states:

| State | Trigger | UI | Key behavior |
| --- | --- | --- | --- |
| Passive | Normal typing | No UI | Existing behavior. |
| Soft suggestion | Debounced cheap match | Ghost text or one-line hint | `Enter` submits. `Tab` keeps snippet behavior. Explicit key accepts. |
| Explicit completion | `Ctrl+T` or user opens menu | Existing rich panel | Existing navigation/accept keys can apply. |

Do not let an automatically opened suggestion change what `Enter` does. This is the single most important flow-safety
rule.

Suggested automatic triggers:

- `#`, `#!`, and `#name` for xprompts.
- `/name` for slash skills.
- `%name` and directive argument positions.
- `#foo:` and `#foo(...)` for xprompt argument names/values.
- Snippet trigger prefixes only after 2+ characters and only when a matching snippet exists.
- File paths only after an explicit `Ctrl+T` in phase 1; later behind a worker and debounce.

Suggested non-goals for v1:

- No automatic full file-history popup on empty prompt.
- No automatic file-system scan on every printable key.
- No automatic completion in feedback/approve modes unless explicitly enabled.
- No automatic panel with 10 detailed xprompt rows while the user is simply typing prose.

## Latency Budget

Use the existing TUI latency baseline as the bar: j/k navigation targets p95 key-to-paint under 16 ms. Prompt typing
should be held to the same standard.

Recommended budgets:

- Key handler synchronous work: p95 < 1 ms.
- Typing key-to-paint with autocomplete enabled: p95 < 16 ms.
- Automatic suggestion result availability: p95 < 50 ms when cache is warm.
- Debounce delay: 75-120 ms.
- Cache refresh: background only; never blocks visible typing.
- Catalog refresh timeout: reuse the LSP's 5 s completion-path timeout for worker refreshes, but continue using stale
  cache on timeout.

Add instrumentation before enabling auto mode broadly:

```text
SASE_TUI_PROMPT_COMPLETION_PERF=1
```

Emit JSONL with:

- key event timestamp
- context detection duration
- cache age
- candidate build duration
- render/update duration
- whether result was stale-discarded
- key-to-paint duration via `call_after_refresh`

## Implementation Sketch

### Phase 1: Cache Existing `Ctrl+T`

- Add a small prompt completion catalog cache keyed by project.
- Warm it in a worker when the prompt bar mounts/focuses.
- Change `build_xprompt_completion_candidates()` or its caller to accept cached `XPromptAssistEntry` values.
- Reuse the cache for `_get_xprompt_arg_assist_entries()`.
- Keep a manual refresh path, probably piggybacking on existing xprompt/workflow editor return points.

This phase should make manual completion feel instant and creates the substrate for automatic completion.

### Phase 2: Soft Suggestions

- Add a debounce timer to `PromptTextArea` after `TextArea.Changed` or post-key handling.
- Classify context from current text/cursor using cached entries.
- If exactly one candidate or a useful shared extension exists, render ghost text/one-line hint.
- Do not set `_file_completion_active`.
- Do not let `Enter` accept it.
- Add one explicit accept key. `Ctrl+L` is already the explicit completion accept key, so it is the natural candidate.

### Phase 3: Optional Auto Menu

- Add config such as:

```yaml
ace:
  prompt_completion:
    auto: soft        # off | soft | menu
    debounce_ms: 90
    auto_file_paths: false
    max_auto_rows: 5
```

- In `menu` mode, render a compact panel for xprompt/directive/argument contexts.
- Use a fixed small row limit for automatic panels.
- Keep detailed 10-row xprompt entries for explicit `Ctrl+T`.
- Preserve `Enter` as submit unless the menu was explicitly opened.

### Phase 4: Move Hot Logic To `sase_core_rs`

- Add editor PyO3 bindings in `../sase-core/crates/sase_core_py`.
- Add Python facade functions under `src/sase/core/`.
- Update ACE completion tests to compare Python-widget behavior against Rust editor fixtures.
- Gradually delete duplicated token/context logic from Python once the binding is stable.

### Phase 5: Optional LSP Client

Only revisit a TUI-to-LSP client if ACE needs hover, diagnostics, or definition navigation in the prompt widget itself.
For completion alone, PyO3 is simpler and faster.

## Risks And Open Questions

- **Catalog freshness:** TUI currently relies on Python catalog loading. The LSP can use Rust native catalog loading plus
  helper fallback. The first PyO3 slice should avoid changing catalog ownership and only share classification/building.
- **Panel layout shift:** The current completion panel increases prompt-bar height. Automatic popup mode should be
  compact or ghost-first to avoid moving the UI under the user's eyes.
- **Key conflicts:** `Enter`, `Tab`, `Ctrl+N`, and `Ctrl+P` already matter. Automatic suggestions must not reuse explicit
  completion semantics blindly.
- **File paths:** Directory reads can be fast locally but unpredictable on network mounts or large directories. Keep path
  auto-completion worker-backed and stale-discarded.
- **Client parity:** Neovim's native LSP completion and TUI completion do not need identical UI, but token
  classification, insertion text, snippet skeletons, and argument completions should come from the same core logic.

## Sources

Local source:

- `src/sase/ace/tui/widgets/prompt_text_area.py`
- `src/sase/ace/tui/widgets/_file_completion.py`
- `src/sase/ace/tui/widgets/file_completion.py`
- `src/sase/ace/tui/widgets/xprompt_completion.py`
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/integrations/xprompt_lsp.py`
- `../sase-core/crates/sase_xprompt_lsp/src/server.rs`
- `../sase-core/crates/sase_xprompt_lsp/src/catalog_cache.rs`
- `../sase-core/crates/sase_core/src/editor/*`
- `../sase-nvim/lua/sase/lsp.lua`
- `../sase-nvim/lua/sase/complete.lua`
- `sdd/research/202605/xprompt_lsp_server_research.md`
- `sdd/research/202605/tui_xprompt_argument_hints.md`

External reference:

- LSP 3.17 specification, completion provider/trigger characters/completion request:
  <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>
- Neovim LSP documentation, including `vim.lsp.start()` and `vim.lsp.completion.enable()`:
  <https://neovim.io/doc/user/lsp.html>
- Textual workers guide, for keeping slow work off the UI path:
  <https://textual.textualize.io/guide/workers/>
- Textual TextArea reference, for prompt widget/suggestion-related API surface:
  <https://textual.textualize.io/widgets/text_area/>
