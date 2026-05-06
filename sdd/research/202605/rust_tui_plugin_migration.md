# Rust TUI and Plugin Migration Research

Date: 2026-05-06

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

### Option G: Keep Python plugins with PyO3 bridge

PyO3 can embed Python in a Rust binary or create Rust Python extension modules. SASE already has a PyO3 bridge in
`../sase-core/crates/sase_core_py`.

Pros:

- Preserves current plugin packages during migration.
- Lets Rust TUI call existing Python providers while contracts are stabilized.

Cons:

- Keeps Python runtime/packaging complexity.
- GIL and Python environment resolution become Rust app concerns.
- Not a clean final-state if the goal is "all Rust."

Use as a transition layer, not the long-term plugin architecture.

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
| Plugin ecosystem | High | No pluggy + entry-points equivalent in Rust. | Versioned provider protocol; process/Wasm plugins; Python bridge during transition. |
| TUI ergonomics | High | Ratatui is lower-level than Textual. | Build a local app framework; prototype one hard screen; consider `tui-realm`. |
| TUI feature parity | Medium-high | TextArea, OptionList, modal stack, async workers, CSS require recreation. | Port screen by screen; snapshot render and event tests. |
| YAML behavior | Medium | Rust YAML crates have maintenance/compatibility tradeoffs. | Pick typed serde path where possible; isolate YAML module. |
| Rich output parity | Medium | No one-package Rich equivalent. | Central render abstraction; use Ratatui/styling crates. |
| Scheduling/telemetry/schema/template | Low | Adequate Rust crates exist. | Migrate behind small adapters. |
| LangChain-core | Low | SASE uses it lightly. | Replace with local message types. |

## Bottom Line

Migrating SASE to Rust/Ratatui is feasible, but the success criterion should not be "find Rust Textual and Rust pluggy."
The safer path is to make the architecture more explicit:

- Ratatui for rendering.
- SASE-owned app state and event/update loop.
- `sase_core` for domain contracts and provider wire types.
- Rust traits for built-ins.
- Process/Wasm plugins for external extensibility.
- Temporary Python bridge for existing pluggy packages.

The only true "missing equivalent" that changes architecture is pluggy plus Python entry-point discovery. Textual is a
large engineering migration, but not an ecosystem blocker. The rest of the Python frameworks have acceptable Rust
replacements or narrow enough usage to rewrite directly.

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
