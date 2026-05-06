# Rust TUI and Plugin Migration Research

Date: 2026-05-06 (revised 2026-05-05 with second-pass research: pluggy-semantics survey, Ratatui widget/precedent
mapping, WASI 0.2 status, panic-recovery and async-in-trait notes, alternate ABI/LLM/config options).

## Question

If SASE moves the remaining Python/Textual TUI into Rust with Ratatui, what is the risk that the current Python framework
surface cannot be carried over? The main concern is `pluggy`, but this note also checks the direct Python runtime and
dev frameworks in `pyproject.toml`.

## Executive Summary

Ratatui is viable for a Rust-native SASE TUI, but it is not a drop-in Textual replacement. Ratatui is intentionally
lower-level and immediate-mode: SASE would own the app loop, event routing, state model, focus model, async task
integration, and a chunk of widget behavior that Textual currently provides. `tui-realm` can recover some retained,
component-style structure on top of Ratatui, but it still is not Textual's CSS/reactive/widget framework.

The bigger migration risk is the plugin layer. Rust has good tools for several plugin patterns, but it does not have a
single mature equivalent to the combination SASE uses today:

- Python packaging entry-point discovery through `importlib.metadata.entry_points(group=...)`.
- `pluggy` hook specs, hook implementations, validation, ordering, and `firstresult=True` dispatch.
- External Python packages that can be installed into the same environment and discovered without recompiling SASE.

A grep-based survey of `src/sase/` (see "Pluggy Usage Survey" below) shows SASE uses only the **basic** pluggy
primitives — `firstresult=True` plus name-keyed selection. There are zero uses of `tryfirst`, `trylast`,
`hookwrapper`/`wrapper`, `historic=True`, or `set_blocked()`. That collapses the Rust dispatcher requirements to
"name-keyed registry plus iterate-until-`Some`," which is trivial. The hard part of the migration is therefore
**plugin discovery and packaging**, not hook semantics.

The practical recommendation is not to search for a pluggy clone. Make SASE's plugin boundary a versioned Rust contract
with request/response wire types, then support two plugin modes:

1. Built-in and in-tree providers: Rust traits plus explicit registry, optionally `inventory` or `linkme` for
   distributed registration inside the final binary.
2. External providers: process or WebAssembly plugins using a stable JSON/WIT-ish wire protocol. Extism/Wasmtime are the
   best current fit if SASE wants a cross-language plugin ecosystem. `abi_stable` is plausible for Rust-to-Rust dynamic
   libraries, but it adds ABI-specific type discipline and does not support unloading.

For a staged migration, preserve the existing Python plugin packages behind a Rust adapter at first. That can be a
subprocess protocol or PyO3 bridge. Migrate built-ins to Rust first, then move plugin authors to the new stable wire
contract.

## SASE Python Framework Surface

Direct runtime dependencies in `pyproject.toml`:

| Python dependency | How SASE uses it today | Rust migration status |
| --- | --- | --- |
| `textual[syntax]` | Main ACE TUI app, widgets, modals, screens, CSS, bindings, workers. | No exact equivalent. Ratatui plus local architecture or `tui-realm` is viable but manual. |
| `rich` | CLI output and Textual renderables: tables, panels, syntax, styled text, markdown-ish display. | No single exact equivalent, but Ratatui covers TUI rendering; CLI output can use smaller crates. |
| `pluggy` | LLM, VCS, and workspace provider hook dispatch plus installed package discovery. | No direct equivalent. Requires an explicit Rust plugin architecture. |
| `jinja2` | xprompt rendering, config/skill templates, strict undefined behavior. | Good equivalent: `minijinja`. |
| `pyyaml` | SASE config, xprompt YAML, SDD frontmatter, workflow files. | Equivalent exists, but YAML crate choice needs care. `serde_yaml` exists but is deprecated/unmaintained; consider `serde-saphyr` or `yaml-rust2` depending on typed vs raw-node needs. |
| `jsonschema` | Output and comment schema validation. | Good equivalent: `jsonschema` Rust crate. |
| `prometheus_client` | Metrics counters/gauges/histograms, scrape endpoint, pushgateway. | Good equivalent: `prometheus` crate. |
| `pyinstrument` | Optional TUI profiling flag. | Not exact. Use `tracing`, `tracing-tracy`, `pprof`, `flamegraph`, `criterion`, or tokio-console depending on profiling target. |
| `plotext` | Terminal charts inside Rich panels for telemetry dashboards. | Partial. Ratatui has chart widgets; richer plotting likely needs custom widgets or a crate audit. |
| `schedule` | Axe/lumberjack periodic jobs. | Good enough equivalents: `clokwerk`, `tokio-cron-scheduler`, or plain Tokio intervals. |
| `langchain-core` | Very light usage: mostly `AIMessage`/`HumanMessage` message types in wrappers/tests. | Easy to replace with local Rust message structs/enums. No need for a full LangChain equivalent. |
| `sase-core-rs` | Existing Rust bridge. | Already Rust; should become the center of shared contracts. |

Dev/test dependencies:

| Python dependency | Rust equivalent status |
| --- | --- |
| `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`, `pytest-xdist` | Rust has built-in tests plus `tokio::test`, `rstest`, `mockall`, `cargo-nextest`, `llvm-cov`. No single pytest clone, but the testing story is strong. |
| `hypothesis` | `proptest` or `quickcheck`. |
| `inline-snapshot` | `insta` is the common Rust snapshot-test equivalent. |
| `ruff`, `mypy`, `tox` | `rustfmt`, `clippy`, `cargo check`, `cargo nextest`, `cargo deny`, and CI matrices. No concern. |

## Current SASE Plugin Model

SASE has three Python plugin groups:

- `sase_llm`: `claude`, `codex`, `gemini`.
- `sase_vcs`: `bare_git`, with external providers such as GitHub/HG expected from plugin packages.
- `sase_workspace`: `bare_git`, `cd`, plus external workspace providers.

The plugin contract is not superficial. The VCS hook spec currently has a large surface: checkout, diff, patch apply,
commit/amend, branch naming, revision resolution, sync operations, review/CL operations, commit/proposal/PR dispatch,
classification, and metadata-like helpers. LLM hooks include invocation, model resolution, provider identity, model
aliases, skill deploy paths, CLI color, autodetection, and retry defaults. Workspace hooks cover workflow metadata,
workflow type detection, ref resolution, workspace allocation, submission, reviewer comment support, mail/PR prep, commit
description formatting, and workspace naming.

The important semantics to preserve:

- `firstresult=True`: first non-`None` hook result wins for most operations.
- Some calls dispatch to a single selected plugin; some aggregate metadata across all plugins.
- Plugin discovery is dynamic at Python environment install time, not Rust compile time.
- Hook signatures are validated by pluggy and mirrored by tests.
- Current provider selection relies on package entry-point names, not just in-repo imports.

## Pluggy Usage Survey

`rg -n "tryfirst|trylast|hookwrapper|@.*hookimpl|hookspec|historic|set_blocked" src/sase/` across the three hookspec
modules and every `_pluginimpl.py` returns:

- `HookspecMarker`/`HookimplMarker` for `sase_llm`, `sase_vcs`, `sase_workspace`.
- `firstresult=True` on essentially every hookspec — LLM 12 of 13 specs, VCS ~60 specs all firstresult,
  Workspace 12 of 13 (only the metadata aggregator at `src/sase/workspace_provider/_hookspec.py:58` aggregates).
- **Zero** uses of `tryfirst`, `trylast`, `hookwrapper`, `wrapper`, `historic=True`, or `set_blocked()`.
- Provider selection is by entry-point **name**, not registration order — the dispatcher resolves a single configured
  provider per call site rather than relying on pluggy's LIFO ordering.

What this changes: the often-cited "subtle pluggy semantics" risk evaporates. The Rust dispatcher needs only
(1) a `HashMap<&str, Arc<dyn Provider>>`, (2) iterate-until-`Some` for the rare aggregate hook, and (3) one
all-providers aggregator. Hook wrappers, historic call replay, and ordering knobs do not need replication.

For reference on what we are *not* using, pluggy supports:

- `tryfirst=True` / `trylast=True`: bias plugin order at the front/back of the LIFO chain
  (https://pluggy.readthedocs.io/en/latest/api_reference.html).
- `hookwrapper=True` (legacy) and `wrapper=True` (1.1+): generators that wrap hook calls; `wrapper=True` is the simpler
  return/raise form.
- `@hookspec(historic=True)` + `call_historic()`: replays past invocations to plugins that register later. Cannot return
  results to the caller.
- `PluginManager.set_blocked()`: prevent named plugins from registering.

## Ratatui and TUI Architecture

Ratatui is current and active. Version 0.30.0 reorganized the project into a modular workspace with `ratatui-core`,
`ratatui-widgets`, backend crates, and macros. It provides widgets, layout, styling, buffers, and backend integration.
The default backend is Crossterm, with Termion and Termwiz also available.

The key Textual-to-Ratatui difference is ownership of the application model. Textual widgets are retained objects, can be
styled with CSS, and each widget runs in its own asyncio task. Ratatui is immediate-mode: every frame renders the UI into
intermediate buffers, the app handles events explicitly, and Ratatui diffs the resulting frame before writing terminal
changes.

For SASE, that means the migration needs a local app framework:

- App state store for CLs, agents, notifications, artifacts, prompt input, folds, marks, modal state, and focused panel.
- Event router mapping key/mouse/timer/background events into state transitions.
- Rendering layer made of pure-ish functions from state to Ratatui widgets.
- Async task supervisor for filesystem scans, process status polling, artifact loading, telemetry refreshes, and agent
  launch/control actions.
- Focus/navigation model for the existing Vim-like keymaps, jump hints, modal controls, and multi-panel agent views.
- Test harness that can drive event sequences and assert state/render snapshots without a real terminal.

`tui-realm` is worth prototyping because it adds reusable components, properties/state, messages/events, and Elm-like
`update` routines on top of Ratatui. It may reduce the amount of local framework SASE needs. The tradeoff is another
framework dependency and a programming model that still will not match Textual's CSS and worker model.

Recommendation for TUI:

1. Use Ratatui directly for a spike if the goal is maximum control and minimum framework lock-in.
2. Evaluate `tui-realm` only against one real SASE screen, not a toy. The Agents tab or Artifacts panel is a good test
   because it stresses focus, nested grouping, async loading, and rich text.
3. Keep domain/query/scanning behavior in `../sase-core`; keep only presentation state in the TUI crate.

## Ratatui Widget Ecosystem Mapping

For each Textual widget SASE relies on, there is a credible Ratatui-ecosystem replacement on crates.io. None match
Textual's reactive/CSS feel, but they cover the rendering and behavior surface:

| Textual surface | Ratatui-ecosystem candidate | URL |
| --- | --- | --- |
| `TextArea` (multiline editor for prompt input) | `tui-textarea` | https://github.com/rhysd/tui-textarea |
| `Input` (single-line) | `tui-input`, `tui-prompts` | https://crates.io/crates/tui-input, https://crates.io/crates/tui-prompts |
| `Tree` / nested grouping | `tui-tree-widget` | https://crates.io/crates/tui-tree-widget |
| Modal/popup stack | `tui-popup`, `tui-overlay` | https://crates.io/crates/tui-popup |
| Log/console panel | `tui-logger` | https://github.com/gin66/tui-logger |
| Spinners | `throbber-widgets-tui` | https://crates.io/crates/throbber-widgets-tui |
| Markdown rendering | `tui-markdown`, `termimad` | https://crates.io/crates/tui-markdown |
| Syntax highlighting | `syntect` (+ `syntect-tui` bridge or hand-rolled `Span` mapping) | https://crates.io/crates/syntect |
| Keybinding parsing | `crokey` (parses `ctrl-shift-x` to `KeyEvent`) | https://crates.io/crates/crokey |

Showcase index: https://ratatui.rs/showcase/third-party-widgets/. The genuine gaps versus Textual are *composition*
concerns — focus stack, modal layering, theme/CSS, message routing — not raw widget availability.

## Real-World Ratatui Precedents

Useful architectural references for SASE:

- **Zellij** (https://zellij.dev/documentation/plugins.html, https://zellij.dev/news/new-plugin-system/):
  ratatui-style rendering plus a WASI plugin host. Built-in status bar, tab bar, file manager are themselves WASM
  plugins compiled to `wasm32-wasip1`. v0.44+ migrated host runtime from Wasmtime to `wasmi`; permissions are explicit
  per-plugin. Closest precedent to SASE's "Rust core + external plugin ecosystem" target.
- **gitui** (https://github.com/gitui-org/gitui): Ratatui + crossterm, with a `Component` trait per panel
  (`draw`/`event`). Direct match for SASE's panel/screen structure; worth reading before the Phase 1 spike.
- **atuin** (https://github.com/atuinsh/atuin): SQLite-backed history with a small immediate-mode loop.
- **bottom**, **yazi** (https://github.com/sxyazi/yazi): Elm-style update loops; yazi adds a Lua plugin layer atop the
  Rust core — alternative model to Wasm if scripting is preferred over compiled plugins.
- **Helix** (https://github.com/helix-editor/helix/issues/15265, https://github.com/helix-editor/helix/discussions/11783):
  uses `helix-tui` (private tui-rs fork, not Ratatui) with crossterm. Compositor refactor discussion is worth tracking
  as a precedent for making the renderer pluggable across TUI/web/native.
- TEA pattern reference: https://ratatui.rs/concepts/application-patterns/the-elm-architecture/.

The combined takeaway: gitui's `Component` trait is the cheapest credible foundation for SASE's panel layout, and
Zellij is the closest precedent for the plugin architecture we'd want long-term.

## TUI Testing Strategy

Ratatui ships `ratatui::backend::TestBackend`, an in-memory backend whose `Buffer` can be asserted directly. Combined
with `insta::assert_snapshot!` you get the same coverage Textual provides via `Pilot` snapshots. Events are not
generated by Ratatui — they come from the backend (crossterm), so tests inject `crossterm::event::KeyEvent`/`MouseEvent`
values directly into the `update` function rather than driving a real terminal. For PTY-level integration (terminal
queries, graphics protocols), `ratatui-testlib` runs the binary inside a real PTY emulator.

URLs: https://ratatui.rs/recipes/testing/snapshots/, https://ratatui.rs/concepts/backends/,
https://crates.io/crates/ratatui-testlib.

A TEA-style `update(state, event) -> state` decomposition makes the bulk of SASE's existing Pilot tests trivially
portable as `insta` snapshots over `TestBackend` buffers. Snapshot drift is the main maintenance cost.

## TUI Panic and Error Recovery

In Textual, terminal restoration on panic is mostly automatic. In Ratatui it is not: leaving raw mode + the alternate
screen on a panic strands the user's terminal. Since 0.28.1, `ratatui::init()` / `ratatui::restore()` install a panic
hook that restores terminal state before chaining to the original hook. The recipes integrate with `color-eyre`
(`with_color_eyre_hooks` on `CrosstermBackend`; color-eyre is now a default Ratatui feature) and `better-panic`/`human-panic`.
Critical rule: never panic *during* restoration — the original cause is lost.

URLs: https://ratatui.rs/recipes/apps/panic-hooks/, https://ratatui.rs/recipes/apps/color-eyre/,
https://ratatui.rs/recipes/apps/better-panic/.

The Phase 1 spike should wire `ratatui::init()` plus `color-eyre` from day one and add an integration test that panics
deliberately to assert terminal-state restoration. This is the single highest-leverage difference between a comfortable
Ratatui port and a frustrating one.

## Async Runtime and `async fn` in Trait

Tokio is the de-facto runtime; nearly every LLM/HTTP/async crate assumes it. Native AFIT (`async fn` in trait, stable
since Rust 1.75) is **not dyn-safe** — `dyn LlmProvider` with `async fn invoke(...)` does not compile. Workarounds:

- `#[async_trait]`: boxes futures, slight overhead, dyn-safe (https://docs.rs/async-trait).
- `trait-variant`: emits Send/non-Send variants of the trait.
- `dynosaur`: newer, generates dyn-dispatch shims over AFIT.
- A type cannot conditionally be `Send` based on generics, complicating providers used across spawn boundaries.

Reference: https://blog.rust-lang.org/2023/12/21/async-fn-rpit-in-traits/,
https://rust-lang.github.io/async-fundamentals-initiative/roadmap/dyn_async_trait.html.

For SASE's in-process Rust traits, use `#[async_trait]` for `VcsProvider`/`LlmProvider`/`WorkspaceProvider`. The boxing
cost is negligible compared to shelling out to git or making a network call. A process or Wasm plugin boundary
side-steps the problem entirely: the host trait wraps a sync transport call internally and exposes whatever async
shape it wants.

## Rust Plugin Options

### Option A: Rust traits plus explicit registry

Define `LlmProvider`, `VcsProvider`, and `WorkspaceProvider` traits in a stable SASE crate. Built-ins register in a
`HashMap<String, ProviderFactory>` or explicit array.

Pros:

- Simple, idiomatic, testable.
- Best for providers shipped in the SASE binary.
- No ABI or sandboxing complexity.
- Easy to type strongly with Rust structs/enums.

Cons:

- External plugin authors must be compiled into the final binary or enabled through features.
- Does not match Python entry-point install/discover behavior.

Use this for built-ins regardless of the external plugin plan.

### Option B: `inventory` or `linkme` distributed registration

`inventory` provides typed distributed plugin registration from any source file linked into the application. `linkme`
provides distributed slices whose elements can be defined in downstream crates and observed at runtime after being linked
into the final binary.

Pros:

- Nice replacement for local "register this provider" boilerplate.
- Good for large in-tree or feature-linked provider sets.
- Compile-time type checking.

Cons:

- Still compile/link-time, not install-time.
- Does not discover arbitrary installed packages the way Python entry points do.
- Linker/platform edge cases are possible.

Use this only if explicit registry boilerplate becomes painful. It is not enough for SASE's external plugin story.

### Option C: Native dynamic libraries with `libloading`

`libloading` gives a cross-platform wrapper over dynamic library loading. The host loads `.so`/`.dylib`/`.dll` and calls
exported symbols.

Pros:

- True runtime loading.
- Minimal abstraction.
- Works well when the boundary is a small C ABI.

Cons:

- Rust does not provide a stable Rust ABI for rich trait/object boundaries.
- Requires FFI-safe types, manual version checks, and unsafe loading discipline.
- Error handling, async, ownership, strings, maps, and callbacks get tedious quickly.

Use only for a narrow C ABI shim, not as the main SASE provider contract.

### Option D: Native Rust dynamic plugins with `abi_stable`

`abi_stable` is designed for Rust-to-Rust FFI, including libraries loaded at runtime even when built with different Rust
versions. It provides FFI-safe trait objects, stable wrapper types, load-time layout checks, and prefix types for
extensible modules.

Pros:

- Most Rust-native dynamic plugin option.
- Better type discipline than raw `libloading`.
- Plausible if SASE only wants Rust plugin authors.

Cons:

- Plugin interfaces must use `abi_stable`'s FFI-safe type ecosystem.
- No unloading support.
- Still a specialized ABI design burden.
- Less cross-language than process/Wasm.

Use only after a prototype proves the provider surface can be made ergonomic with ABI-safe request/response structs.

Alternative: `stabby` (https://github.com/ZettaScaleLabs/stabby, https://docs.rs/stabby) is a newer Rust-to-Rust ABI
crate with first-class **niche-optimized sum types** via its `IStable` trait (associated-type layout vs. `abi_stable`'s
`Stable` const-evaluation). It pins ABI for marked subsets while preserving Rust's normal layout optimizations
elsewhere. Like `abi_stable`, no unloading. crABI (`extern "crabi"`) is still an experimental compiler-team feature
gate (https://github.com/rust-lang/compiler-team/issues/631) with no stable RFC. If SASE chooses Rust-only dynamic
plugins, prefer `stabby` for any provider response that's a sum (e.g. `VcsResponse::Diff | NotApplicable | Error`) —
niche optimization matters when these cross the boundary frequently.

### Option E: WebAssembly plugins with Extism or Wasmtime

Wasmtime embeds WebAssembly modules/components and lets the host provide functions to guests. Extism layers a plugin
system over Wasm, with manifests, host functions, typed plugin wrappers, pools, and SDK/PDK support.

Pros:

- Stronger isolation boundary than native dynamic libraries.
- Cross-language plugin authoring is possible.
- Versioned contracts can be JSON, MessagePack, or WIT/component-model shaped.
- Good fit for "providers are capabilities" rather than "providers mutate host internals."

Cons:

- Provider API must be explicit and data-oriented.
- File/process/network access must be mediated by the host or WASI permissions.
- More overhead than in-process trait calls.
- Async streaming LLM invocation and long-running VCS operations need careful host callback design.

Best fit for SASE external providers if the project wants real install-time extensibility after the Rust migration.

WASI status (2025–2026): WASI 0.2 (Preview 2) shipped Jan 2024 with the Component Model and WIT IDL. Wasmtime, Spin,
and wasmCloud all fully implement it. WASI 0.3 work focuses on composable async (native futures/streams in WIT).
Production users include Fermyon Spin 2.x, Fastly Compute@Edge, wasmCloud, and Shopify Functions. Extism remains
**module-based** (core Wasm + host functions, not components) but added XTP Bindgen — an OpenAPI-flavored IDL that
generates PDK skeletons, analogous to but distinct from WIT.

URLs: https://eunomia.dev/blog/2025/02/16/wasi-and-the-webassembly-component-model-current-status/,
https://docs.wasmtime.dev/api/wasmtime/component/, https://extism.org/blog/announcing-xtp-bindgen/,
https://www.fermyon.com/blog/announcing-spin-2-2.

Practical SASE choice today: **Extism** for fastest time-to-prototype (Python/JS/Go/Rust PDKs ready, drop-in plugin
manifest); **Wasmtime + WIT/Component Model** for long-term type safety and composability. Async streaming LLM
responses are still awkward pre-WASI 0.3 — host-callback or polling patterns are required either way. Zellij is the
strongest precedent for shipping Wasm plugins in a Ratatui-style app (see "Real-World Ratatui Precedents").

### Option F: Process plugins

Run plugin executables with a stable stdin/stdout JSON protocol. This is the simplest external boundary.

Pros:

- Cross-language immediately.
- Easy to debug and version.
- Sandboxing can be delegated to OS/container policy.
- No Rust ABI risk.

Cons:

- More process overhead.
- Need robust timeout/cancellation/log streaming.
- Request/response protocol must be designed.

Good first external plugin boundary and a practical bridge for existing Python provider packages.

### Option G: Keep Python plugins via embedded CPython (reverse PyO3)

SASE already exposes Rust to Python via `sase-core-rs`/`sase_core_py`. Inversion: make the Rust binary the **host** and
keep Python plugins via an embedded CPython interpreter through PyO3 (`prepare_freethreaded_python` + `pyo3::Python`),
plus `importlib.metadata.entry_points(group=...)` for discovery — exactly the same plugin-author surface as today.

Pros:

- Zero protocol design — Python plugins call directly into the existing Rust core; entry-point discovery preserved.
- Unchanged plugin author experience; existing `sase_llm`/`sase_vcs`/`sase_workspace` packages keep working.
- Faster than process plugins (no IPC), simpler than Wasm.

Cons:

- Rust binary gains a CPython runtime dependency (~10 MB plus a Python install assumption).
- The GIL serializes plugin calls; concurrent plugin invocations contend.
- Async-Tokio ↔ asyncio bridging is non-trivial (`pyo3-asyncio` helps but adds latency).
- Panic safety across the FFI is fragile; cross-platform Python distribution becomes the host's problem.
- Couples plugin lifetimes/crashes with the host process (no isolation, unlike processes/Wasm).

Reference: https://pyo3.rs/main/.

Best used as the **lowest-risk Phase-3 transition layer**: built-ins move to Rust, external Python plugins keep working
via embedded CPython, and the eventual cutover to process or Wasm becomes optional rather than blocking.

## Pluggy Replacement Recommendation

Do not try to port pluggy behavior directly. Instead:

1. Define stable provider operation enums and request/response structs in `sase_core`.
   - Example: `VcsRequest::Diff { cwd } -> VcsResponse::TextResult`.
   - Example: `LlmRequest::Invoke { prompt, model_tier, model_override, suppress_output } -> LlmInvokeResponse`.
   - Example: `WorkspaceRequest::ResolveRef { ref, workflow_type } -> WorkspaceResolveRefResponse`.
2. Put provider dispatch behind Rust traits in the Rust application.
3. Preserve `firstresult` semantics in the dispatcher, not in plugins:
   - Single-provider calls select exactly one provider by name.
   - Classification/metadata calls iterate ordered providers and stop at first non-empty result, or aggregate when needed.
4. Use explicit provider manifests:
   - `name`, `kind`, `version`, `api_version`, `priority`, `capabilities`, `binary/wasm path`, optional config schema.
   - This replaces Python entry-point metadata and makes plugin loading deterministic.
5. Support external providers through process plugins first, then Wasm once the protocol is stable.
6. Keep a compatibility bridge that invokes current Python entry-point plugins for one or two releases.

This preserves the user-facing plugin story while avoiding Rust ABI traps.

## Other Framework Gaps

### Textual

This is the largest non-plugin migration effort. Ratatui is mature, but the Textual replacement is an app architecture,
not a crate. If SASE wants the ergonomics of retained widgets, `tui-realm` is the closest credible candidate found in
this pass. Still, SASE should expect to implement much of its own:

- CSS/theme translation.
- Widget focus and message conventions.
- Background worker cancellation.
- TextArea-equivalent behavior for prompt input.
- OptionList-equivalent selection behavior.
- Modal stack and keymap priority rules.

### Rich

There is no single Rust crate that feels like Rich across tables, panels, markdown, syntax highlighting, progress,
tracebacks, and pretty printing. Inside the TUI, Ratatui's `Text`, `Line`, `Span`, layout, and widgets replace much of
the rendered output path. Outside the TUI, compose smaller crates:

- `anstyle`/`owo-colors`/`nu-ansi-term` for styling.
- `comfy-table` or Ratatui tables for tables.
- `syntect` or `bat`-style integration for syntax highlighting.
- `pulldown-cmark`/`termimad` style crates for markdown if needed.

Not a blocker, but expect a render abstraction rather than a one-package swap.

### PyYAML

YAML deserves a deliberate choice. `serde_yaml` is convenient and still documented, but the broader Rust YAML ecosystem
has churn. For typed config where SASE controls schema, a maintained serde-based option is ideal. For preserving comments,
anchors, or exact frontmatter formatting, raw YAML node libraries may be required. SASE currently mostly reads and writes
config/frontmatter/workflow data, so a typed `serde` path should work if formatting preservation is not required.

### PyInstrument

No exact always-on TUI profiler equivalent. Rust should rely on:

- `tracing` spans around SASE app phases and expensive render/load paths.
- `tokio-console` if async task scheduling becomes opaque.
- `pprof`/flamegraph for CPU profiles.
- `criterion` for microbenchmarks and regression tracking.

This is an improvement opportunity, but not a migration blocker.

### Plotext

Ratatui has charting primitives, but SASE's telemetry dashboard may need custom widgets to match existing plotext output.
The migration should treat telemetry charts as a separate widget spike, not a core blocker.

### LangChain-core

Current usage appears narrow: message classes in wrappers/tests. Replace with a local SASE message enum/struct rather than
adopting a Rust LLM framework. Rust LLM frameworks exist, but SASE's provider model is already more specific than generic
agent/RAG orchestration.

For reference, the 2025–2026 Rust LLM SDK landscape if SASE ever wants direct HTTP (instead of shelling out to provider
CLIs):

- `async-openai` (https://github.com/64bit/async-openai): mature, reused by many wrappers.
- `clust` (https://github.com/mochi-neko/clust): typed Anthropic SDK.
- `genai` (https://github.com/jeremychone/rust-genai): unified multi-provider client (OpenAI, Anthropic, Gemini, xAI,
  Ollama, Groq, Cohere) — closest match for SASE's three-provider shape.
- `rig` (https://github.com/0xPlaygrounds/rig): agent/RAG framework with provider abstraction.
- `llm` (https://github.com/graniet/llm): broader unified API including voice/STT.
- `ollama-rs` (https://github.com/pepperoni21/ollama-rs): local Ollama HTTP wrapper.

SASE's claude/codex/gemini providers currently delegate to external CLIs, not HTTP, so adopting any of these is
optional. If a future provider needs direct HTTP, `genai` is the lowest-effort fit.

### Config and layered settings

SASE has `default_config.yml` plus user/project/env overrides — pluggy is unrelated, but it's the framework gap most
likely to bite during migration. Options:

- `config-rs` (https://docs.rs/config/): mature 12-factor layered config; YAML/TOML/JSON/env, file hierarchies,
  serde-driven. Best fit for SASE's existing layered YAML.
- `figment` (https://docs.rs/figment/): provider-based merging (used by Rocket); ergonomic and provides
  metadata-aware errors that point at the source provider — useful for "which override won?" debugging.
- `confique` (https://docs.rs/confique/): lighter, struct-driven, generates docs/templates from the config struct.

All three are serde-native; `config-rs` is the safest port and `figment` is the upgrade if error attribution matters.

## Proposed Migration Shape

Phase 1: TUI architecture spike

- Create a small Rust TUI crate that reads existing `sase_core` wire data.
- Implement one high-stress screen: Agents tab or Artifacts panel.
- Use explicit app state, action enum, event enum, and render functions.
- Compare direct Ratatui vs `tui-realm` for this screen only.

Phase 2: Provider contract extraction

- Move provider request/response DTOs into `sase_core`.
- Generate Python bindings for compatibility where useful.
- Add parity tests for Python pluggy dispatcher vs Rust dispatcher on representative VCS/LLM/workspace operations.

Phase 3: Built-in Rust providers

- Implement `bare_git`, `cd`, and the built-in LLM providers as Rust traits or process adapters.
- Keep external Python providers callable through the compatibility layer.

Phase 4: External plugin protocol

- Define provider manifest and protocol versioning.
- Start with process plugins for compatibility and easy debugging.
- Add Extism/Wasmtime only after the process protocol has stabilized.

Phase 5: Python retirement

- Remove Textual/Rich TUI after Rust TUI reaches feature parity.
- Deprecate pluggy entry-point loading after external providers have Rust/process/Wasm replacements.

## Risk Matrix

| Area | Risk | Reason | Mitigation |
| --- | --- | --- | --- |
| Plugin discovery/packaging | High | No Rust analogue to Python entry points + install-time discovery. | Versioned manifest + process/Wasm plugins; reverse-PyO3 bridge during transition. |
| Pluggy hook semantics | **Low (revised)** | Survey shows SASE uses only `firstresult` + name lookup; no wrappers/historic/ordering. | Name-keyed registry + iterate-until-`Some` is sufficient. |
| TUI ergonomics | High | Ratatui is lower-level than Textual. | Build a local app framework (gitui-style `Component` trait); prototype one hard screen; consider `tui-realm`. |
| TUI feature parity | Medium-high | TextArea, OptionList, modal stack, async workers, CSS require recreation. | Adopt `tui-textarea`/`tui-input`/`tui-tree-widget`/`tui-popup`; port screen by screen with `TestBackend` + `insta` snapshots. |
| Terminal-state recovery on panic | Medium | Ratatui needs an explicit panic hook; Textual handles it implicitly. | Wire `ratatui::init()` + `color-eyre` from day one; integration test with deliberate panic. |
| Async-trait dyn dispatch | Medium | Native AFIT is not dyn-safe. | Use `#[async_trait]` for in-process traits; sidestep entirely with process/Wasm plugins. |
| YAML behavior | Medium | Rust YAML crates have maintenance/compatibility tradeoffs. | Pick typed serde path where possible; isolate YAML module. |
| Rich output parity | Medium | No one-package Rich equivalent. | Central render abstraction; use Ratatui/styling crates. |
| Scheduling/telemetry/schema/template/config | Low | Adequate Rust crates exist (`config-rs`, `figment`, `prometheus`, `jsonschema`, `minijinja`). | Migrate behind small adapters. |
| LangChain-core | Low | SASE uses it lightly. | Replace with local message types; `genai` available if direct HTTP is ever needed. |

## Bottom Line

Migrating SASE to Rust/Ratatui is feasible, but the success criterion should not be "find Rust Textual and Rust pluggy."
The safer path is to make the architecture more explicit:

- Ratatui for rendering.
- SASE-owned app state and event/update loop.
- `sase_core` for domain contracts and provider wire types.
- Rust traits for built-ins.
- Process/Wasm plugins for external extensibility.
- Temporary Python bridge for existing pluggy packages.

The only true "missing equivalent" that changes architecture is **install-time plugin discovery** — Python entry
points have no Rust analogue. Pluggy's *hook semantics* turn out to be a non-issue: the SASE survey shows we use only
`firstresult` plus name-based selection, so the Rust dispatcher is small. Textual is a large engineering migration but
not an ecosystem blocker — `tui-textarea`, `tui-tree-widget`, `tui-popup`, and friends cover the widget surface, and
gitui's `Component` pattern plus Zellij's Wasm plugin host are concrete precedents to mirror. The rest of the Python
framework surface has acceptable Rust replacements or narrow enough usage to rewrite directly.

## Sources

- SASE dependency and plugin usage: `pyproject.toml`, `src/sase/vcs_provider/_hookspec.py`,
  `src/sase/llm_provider/_hookspec.py`, `src/sase/workspace_provider/_hookspec.py`.
- Ratatui docs: https://docs.rs/ratatui/latest/ratatui/
- Ratatui installation/backends: https://ratatui.rs/installation/
- Textual widget model: https://textual.textualize.io/guide/widgets/
- Rich docs: https://rich.readthedocs.io/en/stable/introduction.html
- Pluggy docs: https://pluggy.readthedocs.io/en/latest/
- Pluggy API reference: https://pluggy.readthedocs.io/en/latest/api_reference.html
- Python `importlib.metadata` entry points: https://docs.python.org/3.12/library/importlib.metadata.html
- `tui-realm`: https://docs.rs/tuirealm/latest/tuirealm/
- `inventory`: https://docs.rs/inventory/latest/inventory/
- `linkme`: https://docs.rs/linkme/latest/linkme/struct.DistributedSlice.html
- `libloading`: https://docs.rs/libloading/latest/libloading/
- `abi_stable`: https://docs.rs/abi_stable/latest/abi_stable/
- Wasmtime: https://docs.wasmtime.dev/api/wasmtime/
- Extism Rust SDK: https://docs.rs/extism/latest/extism/
- PyO3: https://pyo3.rs/main/doc/pyo3/
- MiniJinja: https://docs.rs/minijinja/latest/minijinja/
- Rust `jsonschema`: https://docs.rs/jsonschema/latest/jsonschema/
- Rust Prometheus client: https://docs.rs/prometheus/latest/prometheus/
- Clokwerk: https://docs.rs/clokwerk/latest/clokwerk/
- Tracing: https://docs.rs/tracing/latest/tracing/
- Rhai: https://docs.rs/rhai/latest/rhai/
- YAML alternatives: https://docs.rs/serde_yaml/latest/serde_yaml/, https://docs.rs/yaml-rust2/latest/yaml_rust2/,
  https://docs.rs/saphyr/latest/saphyr/
- Ratatui showcase / third-party widgets: https://ratatui.rs/showcase/third-party-widgets/
- `tui-textarea`: https://github.com/rhysd/tui-textarea
- `tui-input`: https://crates.io/crates/tui-input
- `tui-prompts`: https://crates.io/crates/tui-prompts
- `tui-tree-widget`: https://crates.io/crates/tui-tree-widget
- `tui-popup`: https://crates.io/crates/tui-popup
- `tui-logger`: https://github.com/gin66/tui-logger
- `throbber-widgets-tui`: https://crates.io/crates/throbber-widgets-tui
- `tui-markdown`: https://crates.io/crates/tui-markdown
- `crokey`: https://crates.io/crates/crokey
- Ratatui TestBackend / snapshot recipe: https://ratatui.rs/recipes/testing/snapshots/
- Ratatui backends: https://ratatui.rs/concepts/backends/
- `ratatui-testlib`: https://crates.io/crates/ratatui-testlib
- TEA pattern (Ratatui): https://ratatui.rs/concepts/application-patterns/the-elm-architecture/
- Ratatui panic-hook recipe: https://ratatui.rs/recipes/apps/panic-hooks/
- Ratatui color-eyre recipe: https://ratatui.rs/recipes/apps/color-eyre/
- gitui: https://github.com/gitui-org/gitui
- atuin: https://github.com/atuinsh/atuin
- yazi: https://github.com/sxyazi/yazi
- Zellij plugin docs: https://zellij.dev/documentation/plugins.html
- Zellij plugin system blog: https://zellij.dev/news/new-plugin-system/
- Helix compositor refactor: https://github.com/helix-editor/helix/issues/15265
- WASI / Component Model status (eunomia): https://eunomia.dev/blog/2025/02/16/wasi-and-the-webassembly-component-model-current-status/
- Wasmtime component API: https://docs.wasmtime.dev/api/wasmtime/component/
- Spin 2.x: https://www.fermyon.com/blog/announcing-spin-2-2
- Extism XTP Bindgen: https://extism.org/blog/announcing-xtp-bindgen/
- `stabby`: https://github.com/ZettaScaleLabs/stabby
- crABI tracking issue: https://github.com/rust-lang/compiler-team/issues/631
- AFIT release notes: https://blog.rust-lang.org/2023/12/21/async-fn-rpit-in-traits/
- async fundamentals roadmap: https://rust-lang.github.io/async-fundamentals-initiative/roadmap/dyn_async_trait.html
- `async-trait`: https://docs.rs/async-trait
- `async-openai`: https://github.com/64bit/async-openai
- `clust` (Anthropic): https://github.com/mochi-neko/clust
- `genai`: https://github.com/jeremychone/rust-genai
- `rig`: https://github.com/0xPlaygrounds/rig
- `llm`: https://github.com/graniet/llm
- `ollama-rs`: https://github.com/pepperoni21/ollama-rs
- `config-rs`: https://docs.rs/config/
- `figment`: https://docs.rs/figment/
- `confique`: https://docs.rs/confique/
