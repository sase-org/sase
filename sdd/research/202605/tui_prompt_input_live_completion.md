---
create_time: 2026-05-28
status: research
---

# Live (As-You-Type) Autocompletion for the TUI Prompt Input

## Question

In NeoVim, the prompt-editing experience gets LSP-driven autocompletion that pops up *while you type*. The `sase ace`
TUI prompt input already has completion, but it is **manual** (you press `Ctrl+T` to summon it). Can we give the TUI the
same "as-you-type" feel — and what are the options — given the hard constraint that it must be **very fast** and must
**not break typing flow**?

## Short Answer

Yes, and most of the machinery already exists. The work is smaller than it sounds because the TUI already has (a) a
completion dropdown UI, (b) per-keystroke candidate recomputation, and (c) a debouncer utility. What's missing is
**auto-triggering** the existing completion on keystroke instead of only on `Ctrl+T`.

The decision is really three independent choices, not one:

1. **Trigger** — how completion is summoned (the actual ask: keystroke-driven instead of `Ctrl+T`).
2. **Engine** — what computes the candidates (Python in-process vs. Rust core in-process vs. LSP subprocess).
3. **UI** — how candidates render (already solved; reuse the existing dropdown).

Recommended path: keep the existing in-process engine and UI, add **debounced auto-triggering** on top
(Option T2 + Engine E1 below). This is the lowest-latency, lowest-risk way to get the NeoVim feel. Treat "share the
Rust core engine with NeoVim" (Engine E2) as a separate, later boundary-cleanup project, and avoid the LSP-subprocess
approach (Engine E3) for the TUI on latency grounds.

## Local Context Reviewed

### What already exists in the TUI

The prompt input is a multi-line **Textual `TextArea`**, not an `Input`. This matters: Textual's built-in `Suggester`
ghost-text API only attaches to `Input`, so it is not directly usable here.

- `src/sase/ace/tui/widgets/prompt_text_area.py` — `PromptTextArea(TextArea)`. Key handling in `_on_key()`
  (~line 189). Mixes in `FileCompletionMixin`, `SnippetExpansionMixin`, etc.
- `src/sase/ace/tui/widgets/prompt_input_bar.py` — `PromptInputBar`. Renders the completion **dropdown** panel
  (`show_file_completions()` ~line 182, `hide_file_completions()` ~line 329) and xprompt arg hints.
- `src/sase/ace/tui/widgets/_file_completion.py` — `FileCompletionMixin`. Crucially,
  `_refresh_file_completion_from_cursor()` (line 326) **already recomputes candidates on every edit/cursor move when
  completion is active**. The manual entry point is `_try_file_completion_tab()` (line 382), bound to `Ctrl+T`.
- `src/sase/ace/tui/util/debounce.py` — `DetailPanelDebouncer`. A ready-made coalescing timer (cancels-and-replaces,
  default 0.15s) built for exactly this kind of "collapse a burst of keystrokes into one expensive update" problem.
  Currently used for j/k detail-panel paints.

### The completion engine today (the important finding)

The TUI computes candidates in **pure Python**, reimplemented locally — it does **not** call the Rust core:

- `src/sase/ace/tui/widgets/xprompt_completion.py` — "Pure-logic xprompt completion engine"
  (`build_xprompt_completion_candidates`).
- `src/sase/ace/tui/widgets/directive_completion.py` — directive candidates.
- `file_completion.py` / `_file_completion.py` — file-path and file-history candidates.

These run in-process with no IPC and no serialization, over small candidate sets — i.e. already fast.

### The NeoVim engine (what the user is comparing against)

NeoVim talks to a **Rust LSP server** that lives in the sibling `sase-core` repo:

- `sase-core/crates/sase_xprompt_lsp/` — Tower-LSP server (`server.rs`, ~1979 lines). Entry point `sase lsp`
  (Python wrapper at `src/sase/integrations/xprompt_lsp.py`), resolving to a `sase-xprompt-lsp` binary.
- It delegates to `sase_core` functions: `editor_classify_completion_context()`,
  `editor_build_xprompt_completion_candidates()`, `editor_build_file_completion_candidates_with_base()`,
  `editor_build_directive_completion_candidates()`, `editor_build_snippet_completion_candidates()`, etc.
- NeoVim client config: `sase-nvim/lua/sase/lsp.lua`; completion trigger `<C-t>` (`sase_complete.lua`).

So NeoVim and the TUI run **two parallel completion implementations**: Rust (via LSP) and Python (in the TUI). This is
a latent divergence and a soft violation of `memory/short/rust_core_backend_boundary.md` (completion is backend logic
that a web/editor/TUI frontend would all want to match).

### The Python↔Rust binding boundary

The `sase_core_rs` PyO3 binding does **not** currently export any completion functions. `tools/validate_sase_core_rs`'s
`REQUIRED_BINDINGS` lists project parsing, query parsing, agent scan/cleanup, status, git parsing, and bead helpers —
**no `editor_*` / completion entries**. So today the Rust completion logic is reachable from Python *only* by spawning
the LSP subprocess. Reaching it in-process would require new bindings.

### Relevant prior art / discipline

- `sdd/research/202605/xprompt_lsp_server_research.md` — background on the LSP server itself.
- `memory/long/tui_jk_baseline.md` and the many `tui_*_perf_*` / `tui_blocking_audit` research files — this codebase
  has an established, measured discipline around **key-to-paint latency** and **not blocking the main thread**. Any
  live-completion work must respect it (run heavy work off the render path, debounce, and never block on I/O during a
  keystroke).

## The Three Decisions

### 1. Trigger (the actual feature request)

| Option | Description | Verdict |
| --- | --- | --- |
| **T1** | Keep `Ctrl+T` only (status quo). | Rejected — this is what the user wants to move past. |
| **T2 (recommended)** | Auto-trigger on keystroke, **debounced**. When the token under the cursor becomes "completable" (`#`, `/`, `%`, a path-like token, an xprompt arg), open the dropdown automatically; reuse `_refresh_file_completion_from_cursor()` for subsequent keystrokes. | Best. Reuses existing refresh + dropdown; smallest change. |
| **T3** | Inline ghost-text (single best suggestion) instead of a dropdown. | Possible later as a complement, but `TextArea` has no native suggester; dropdown already exists and is richer. |

T2 specifics:
- Gate auto-trigger so it only fires when there's an unambiguous trigger context (leading `#`/`/`/`%`, or inside an
  xprompt arg). Do **not** auto-pop a file dropdown on every bare word, or it becomes noise. Make this configurable
  (and respect a "manual only" opt-out via `default_config.yml`).
- Debounce with the existing `DetailPanelDebouncer` (or a sibling instance). ~80–150ms idle delay is the typical sweet
  spot; tune against the jk baseline methodology.
- Cheap-path/expensive-path split (same pattern as jk nav): the keystroke itself inserts the char inline and
  immediately; candidate recompute + dropdown paint happen on the debounced tail so a fast typist never waits.
- Cancel/refresh on cursor move, whitespace, and `Esc`; accept on `Enter`/`Ctrl+L`; navigate with `Ctrl+N`/`Ctrl+P`
  (all already implemented).

### 2. Engine

| Option | Description | Latency | Effort | Boundary |
| --- | --- | --- | --- | --- |
| **E1 (recommended now)** | Keep the existing **in-process Python** builders. | Lowest — no IPC, no serialization, small lists. | Smallest. | Keeps Python/Rust duplication. |
| **E2 (recommended later)** | Expose `editor_classify_completion_context` + `editor_build_*` through `sase_core_rs`; call them in-process from the TUI. Both NeoVim and TUI then share one Rust engine. | Very low — in-process FFI, still no subprocess. | Medium — add PyO3 bindings, extend `REQUIRED_BINDINGS` + `validate_sase_core_rs`, rewire TUI callers, delete the Python reimplementations. | Fixes the divergence; satisfies the core-backend boundary. |
| **E3 (avoid for TUI)** | Make the TUI a full **LSP client** to a spawned `sase lsp` subprocess (mirror NeoVim exactly). | Highest — process IPC + JSON-RPC + async round-trip on each `didChange`/`completion`; needs request cancellation to stay responsive. | Largest — subprocess lifecycle, JSON-RPC plumbing, document sync, cancellation. | Single source of truth, but the heaviest way to get it. |

Why E3 is the wrong tool *here*: the LSP architecture exists to serve an **external editor** (NeoVim) that can't call
Rust in-process. The TUI is already a Python process that can call Rust directly via PyO3. Routing the TUI's own
keystrokes out to a subprocess and back over JSON-RPC adds latency and failure modes (subprocess crash/restart,
version skew) for no benefit the in-process binding doesn't give more cheaply. "Same *behavior* as NeoVim" is best
achieved by sharing the **engine** (E2), not by adopting the **transport** (E3).

### 3. UI

Already solved — reuse the existing dropdown in `prompt_input_bar.py`. No new dependency (e.g. `textual-autocomplete`)
is needed; the repo's bespoke dropdown already renders display text, metadata, dir indicators, and cursor selection.

## Latency & Flow-Preservation Requirements

These are non-negotiable given the user's constraint and this codebase's perf discipline:

1. **Never block the keystroke.** Character insertion stays on the inline cheap path; candidate computation and paint
   run on the debounced tail.
2. **Debounce + coalesce.** A burst of fast typing must collapse to one recompute when the user pauses (the
   `DetailPanelDebouncer` contract).
3. **Cancel stale work.** If a newer keystroke arrives, the pending compute/paint is dropped. (Trivial with the
   cancel-and-replace timer for E1; for E2 keep computes synchronous-and-cheap or move to an exclusive Textual worker;
   for E3 you'd *need* LSP request cancellation.)
4. **Bounded candidate sets.** Cap the dropdown (e.g. top N) so rendering cost is constant regardless of matches.
5. **Measure.** Reuse the jk key-to-paint methodology (`memory/long/tui_jk_baseline.md`, `tui/util/perf.py`) to verify
   no regression in typing latency before/after.

## Recommendation

- **Phase 1 (the feature):** Engine **E1** + Trigger **T2**. Auto-open the existing dropdown on debounced keystrokes
  for clear trigger contexts (`#`, `/`, `%`, xprompt args; path tokens opt-in). Add a config toggle in
  `default_config.yml` for auto vs. manual. This delivers the NeoVim "as-you-type" feel with minimal risk and the best
  possible latency, because nothing leaves the process.
- **Phase 2 (the cleanup, separable):** Engine **E2**. Expose the Rust `editor_*` completion functions via
  `sase_core_rs`, swap the TUI's Python builders for them, and retire the duplicated Python engine. This makes the TUI
  and NeoVim share one implementation and brings the code into line with the core-backend boundary — without changing
  the user-visible Phase 1 behavior.
- **Do not** build an LSP-client transport into the TUI (E3) for latency reasons.

## Risks / Open Questions

- **Trigger noise.** Auto-popping must be conservative; aggressive path completion on every word would harm flow. Needs
  tuning and an opt-out. (Mitigated by gating + config.)
- **Debounce tuning.** 80–150ms is a starting guess; validate against real typing with the jk harness.
- **xprompt arg hints interaction.** The existing post-acceptance arg-hint flow (`:` / `(`) must still feel coherent
  when the dropdown auto-opens; verify the state machine in `_file_completion.py` handles auto-open transitions.
- **E2 scope.** Confirm the `editor_*` functions' signatures/return types map cleanly onto what the TUI dropdown needs,
  and that wiring `validate_sase_core_rs` + the build doesn't bloat startup. (Out of scope for Phase 1.)
- **TextArea vs Input.** Confirmed `TextArea`, so no reliance on Textual's `Input.Suggester`; the bespoke dropdown is
  the right surface.
