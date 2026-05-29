---
create_time: 2026-05-29
status: research
---

# Fast Live Completion for the ACE TUI Prompt

## Question

Can the `sase ace` prompt input get Neovim-like, as-you-type completion for xprompts, slash skills, directives,
snippets, file references, and xprompt arguments without adding typing latency or disrupting the user's flow?

## Short Answer

Yes, but the TUI should copy Neovim's completion behavior, not its LSP transport.

The prompt already has a rich manual completion path behind `Ctrl+T`. The fastest useful path is:

1. Make the current in-process completion cache-backed so `Ctrl+T` is instant.
2. Add debounced, low-intrusion automatic suggestions from warm data only.
3. Keep automatic suggestions separate from explicit completion so `Enter` still submits the prompt.
4. Later expose the Rust `sase-core` editor completion engine through `sase_core_rs` and switch the TUI to that shared
   in-process engine.

Do not run a catalog rebuild, filesystem scan, subprocess call, or LSP JSON-RPC round trip on every keystroke.

## Verified Current State

This consolidates and supersedes the two intermediate notes:

- `sdd/research/202605/tui_prompt_autocomplete_options.md`
- `sdd/research/202605/tui_prompt_input_live_completion.md`

The important verified facts are:

- The ACE prompt widget is `PromptTextArea`, a Textual `TextArea`, not `Input`. Textual `Input` has a `suggester`
  constructor parameter in this workspace; `TextArea` does not. Ghost text would need custom prompt-widget rendering.
- `PromptTextArea._on_key()` currently maps `Ctrl+T` to `_try_file_completion_tab()`. `Tab` remains snippet/tabstop
  behavior. `Enter` accepts an active completion if `_file_completion_active` is true; otherwise it submits.
- `_refresh_file_completion_from_cursor()` already recomputes candidates after edits when explicit completion is active.
  Auto completion can reuse much of this state machinery, but not blindly, because the active-completion state changes
  `Enter` semantics.
- `PromptInputBar.show_file_completions()` renders the existing completion panel and increases prompt-bar height by the
  panel row count. A popup that appears automatically can therefore move the UI while the user types.
- Xprompt argument hints already cache `build_xprompt_assist_entries(project=...)` per prompt/project inside
  `PromptTextArea`. Plain xprompt completion does not: `build_xprompt_completion_candidates()` calls
  `build_xprompt_assist_entries()` every time.
- Path completion calls `os.scandir()`. It is fine for explicit `Ctrl+T`, but should not be automatic on every bare-word
  edit, especially on large directories or slow mounts.
- `sase lsp --version` reports `sase-xprompt-lsp 0.1.1`.
- `sase-core` already exports editor completion functions such as `editor_classify_completion_context`,
  `editor_build_xprompt_completion_candidates`, file completion, directive completion, snippet completion, hover, and
  definition support. The LSP server calls those functions.
- `sase-nvim` starts the LSP with `vim.lsp.start()` and enables native LSP completion with `autotrigger = true` by
  default when Neovim supports it.
- The Python `sase_core_rs` binding validation list does not include the editor completion functions, so the TUI cannot
  currently call the Rust completion engine in-process. Today it either uses its Python implementation or would have to
  spawn/talk to `sase lsp`.

## Timing Snapshot

Measured in this workspace on 2026-05-29 with `PYTHONPATH=src python3.12`; direct `python` is 3.10 here and is not the
right interpreter for the project.

| Operation | Count | p50 | Max | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `build_xprompt_assist_entries()` | 3 | 683 ms | 719 ms | Too slow for key handling or foreground debounce work. |
| `build_xprompt_completion_candidates("#")` | 3 | 651 ms | 669 ms | Too slow because it rebuilds the catalog. |
| `extract_token_around_cursor("#review path", 7)` | 5000 | 0.002 ms | 0.032 ms | Safe on every key. |
| Cached xprompt filter over 92 entries | 5000 | 0.016 ms | 0.090 ms | Safe on every key when the catalog is warm. |
| Cached arg-hint detection | 5000 | 0.013 ms | 0.062 ms | Safe on every key when the catalog is warm. |

The established TUI responsiveness bar from `memory/long/tui_jk_baseline.md` is p95 key-to-paint under 16 ms. Prompt
typing should use that same discipline: do cheap context detection inline, move all I/O and catalog refresh off the key
path, and discard stale work.

## Options

### Option A: Python-Local Cache Plus Debounced Auto Suggestions

Keep the current Python candidate builders, but introduce a prompt completion cache and automatic trigger layer:

- Warm xprompt/snippet/catalog data when the prompt bar mounts or receives focus.
- Reuse the cached entries for both plain xprompt completion and xprompt argument hints.
- On each edit, run only token/context detection.
- After a short debounce, compute suggestions from warm data and current text/cursor generation.
- Keep path completion manual at first, or worker-backed with stale-result discard.

Pros:

- Smallest feature slice.
- No subprocess, JSON-RPC, packaging, or cross-repo release coordination.
- Immediately fixes slow `Ctrl+T` xprompt completion.

Cons:

- Keeps duplicated Python/Rust completion logic.
- Needs explicit cache invalidation or refresh after xprompt/config/workflow edits.

Verdict: best first implementation step.

### Option B: Expose `sase-core` Editor Completion Through PyO3

Add a small `sase_core_rs` API for the Rust editor completion engine, then call it from ACE in-process. Candidate API
surface:

```text
editor_classify_completion_context(text, position, entries) -> context | None
editor_build_xprompt_completion_candidates(token, replacement_range, entries) -> candidates
editor_build_file_completion_candidates_with_base(token, root_dir) -> candidates
editor_build_directive_completion_candidates(token) -> candidates
editor_build_snippet_completion_candidates(token, replacement_range, snippets) -> candidates
editor_assist_entries_from_catalog(catalog_entries) -> entries
```

Keep catalog ownership in Python for the first binding slice if that reduces risk; the hot path only needs warm entry
data plus the classifier/builders.

Pros:

- Best long-term parity with Neovim.
- Matches the Rust core backend boundary: shared editor behavior belongs in `sase-core`, not only in the TUI.
- Avoids LSP process lifecycle and JSON-RPC overhead.

Cons:

- Requires changes in `sase-core`, the PyO3 binding crate, `tools/validate_sase_core_rs`, packaging/install flow, and
  TUI tests.

Verdict: recommended target architecture after Option A.

### Option C: Make the TUI an LSP Client

Start `sase lsp` from ACE and send `textDocument/didChange` plus `textDocument/completion` requests.

Pros:

- Maximum reuse of the existing Neovim path.
- Gives a route to future hover, diagnostics, definition, and code action features.

Cons:

- Heavy for a prompt widget: initialize/shutdown, document sync, request IDs, cancellation, stderr logging, crash
  handling, and version skew.
- The server uses full text sync, which is fine for editors but unnecessary inside the TUI.
- Any startup or cache-refresh problem must be hidden carefully or it will sit near the typing path.

Verdict: avoid for completion alone. Revisit only if the prompt needs broader LSP features as a separate process
boundary.

## UX Recommendation

Resolve the prior notes' main conflict this way: default to soft suggestions first, and make automatic popup menus an
opt-in mode.

| State | Trigger | UI | Key behavior |
| --- | --- | --- | --- |
| Passive | Normal typing | No completion UI | Existing behavior. |
| Soft suggestion | Debounced warm match | Ghost text or one-line hint | `Enter` submits. `Tab` keeps snippet behavior. Explicit key accepts. |
| Explicit completion | `Ctrl+T` | Existing rich panel | Existing completion navigation and accept keys apply. |
| Auto menu | Optional config | Compact existing panel | `Enter` still submits unless the user explicitly opened/focused completion. |

This matters because the current explicit completion state makes `Enter` accept a candidate. If an automatic suggestion
sets `_file_completion_active` without a separate mode flag, it will break the prompt submission flow.

Suggested defaults:

- Automatic mode: `soft`.
- Debounce: 75-120 ms.
- Auto triggers: `#`, `#!`, `/`, `%`, xprompt arg names/values, and snippet prefixes after at least two characters.
- Auto file paths: off for v1.
- Automatic row limit if menu mode is enabled: 5.
- Manual `Ctrl+T`: keep the richer existing 10-row panel and detailed xprompt metadata.

Potential config shape:

```yaml
ace:
  prompt_completion:
    auto: soft        # off | soft | menu
    debounce_ms: 90
    auto_file_paths: false
    max_auto_rows: 5
```

## Implementation Plan

1. Cache and instrument the current path.
   Add a project-keyed prompt completion cache for xprompt assist entries and snippets. Change plain xprompt completion
   to accept cached entries instead of rebuilding the catalog. Add prompt-completion perf logging before enabling auto
   mode broadly.

2. Add debounced soft suggestions.
   After text/cursor changes, classify the current context cheaply, schedule a debounce, and render one safe suggestion
   from warm data if the text generation still matches. Do not set explicit completion state. Accept only with an
   explicit key such as `Ctrl+L` or right-arrow-at-end.

3. Add optional compact auto menu.
   Reuse the existing panel for xprompt, directive, slash skill, and xprompt-argument contexts only. Add a separate
   auto-open state so `Enter`, `Tab`, `Ctrl+N`, and `Ctrl+P` keep their existing prompt meanings unless the user
   explicitly enters completion interaction.

4. Move shared logic to `sase_core_rs`.
   Expose the Rust editor classifier/builders through PyO3. Add tests that compare ACE completion results with
   `sase-core` editor fixtures. Retire duplicated Python logic gradually once parity is proven.

5. Revisit LSP-client integration only for non-completion features.
   If ACE later wants prompt hover, diagnostics, definition, or code actions, evaluate a real LSP client then. It is not
   the right first dependency for typing completion.

## Validation Criteria

- Inline key-handler work for ordinary typing stays below 1 ms p95.
- Prompt typing key-to-paint with automatic completion enabled stays below 16 ms p95.
- Warm suggestion computation is below 50 ms p95, preferably far below.
- Cache refreshes run in a worker or timer path and never block visible typing.
- Stale suggestions are discarded using a generation counter plus text/cursor/context identity.
- Widget tests cover: `Enter` submit with auto suggestion visible, `Ctrl+T` explicit completion, `Tab` snippet behavior,
  `Ctrl+N`/`Ctrl+P` VCS MRU behavior, feedback/approve modes, xprompt arg hints, and path-completion opt-out.

## Open Questions

- What exact custom rendering should soft suggestions use in a multiline `TextArea`: inline ghost text, a one-line
  overlay, or a compact hint in `#prompt-completion` that does not resize the prompt?
- Which events should invalidate the warm xprompt catalog besides prompt focus and returns from workflow/xprompt
  editors?
- Should slash-skill completion share the xprompt cache directly, or maintain a filtered skill-only projection?
- When PyO3 bindings land, should Python keep catalog loading initially, or should the TUI switch to Rust catalog
  loading in the same change?

## Sources Verified

- Current repo: `src/sase/ace/tui/widgets/prompt_text_area.py`
- Current repo: `src/sase/ace/tui/widgets/_file_completion.py`
- Current repo: `src/sase/ace/tui/widgets/file_completion.py`
- Current repo: `src/sase/ace/tui/widgets/xprompt_completion.py`
- Current repo: `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
- Current repo: `src/sase/ace/tui/widgets/prompt_input_bar.py`
- Current repo: `src/sase/ace/tui/util/debounce.py`
- Current repo: `tools/validate_sase_core_rs`
- Sibling `sase-core`: `crates/sase_xprompt_lsp/src/server.rs`
- Sibling `sase-core`: `crates/sase_xprompt_lsp/src/catalog_cache.rs`
- Sibling `sase-core`: `crates/sase_core/src/editor/*`
- Sibling `sase-nvim`: `lua/sase/lsp.lua`
- Audited memory: `memory/long/tui_jk_baseline.md`
