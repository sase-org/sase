# XPrompt external repository migration research

Date: 2026-05-21

## Question

Should the xprompt system be migrated out of `sase` into its own repository? If so, how much work is it, what should move,
and what is the least risky path?

## Executive summary

Do not migrate **all** xprompt logic into a separate repository right now.

The codebase already treats xprompt as a first-class SASE subsystem, not an isolated library. The Python runtime surface
spans prompt expansion, YAML workflow loading, workflow execution, directives, catalog generation, skill generation,
TUI/editor assist, mobile helper responses, bead automation, VCS project routing, artifact state, HITL, and agent launch.
There is also now a Rust-side xprompt catalog/LSP implementation in `../sase-core`, so a new standalone repo would create
a third authority unless the boundary is chosen very carefully.

The practical move is staged:

1. Keep runtime xprompt execution in this repo for now.
2. Strengthen a small stable API around catalog metadata, syntax parsing, and reference expansion.
3. Move only pure/editor/catalog logic to `sase-core` or a future `sase-xprompt` package when there is a second
   non-SASE consumer and the adapter boundary is proven.
4. If a repository split is still wanted later, extract behind compatibility shims so `sase.xprompt.*` imports continue
   to work for at least one release window.

## Current inventory

Local code and assets:

- `src/sase/xprompt/`: 54 Python files, about 15.1k lines.
- `src/sase/xprompts/`, `src/sase/default_xprompts/`, repo-local `xprompts/`: 38 bundled/project xprompt files, about
  3.0k lines.
- Total obvious xprompt runtime/assets inventory: about 23.4k lines.
- Tests with `xprompt` or `workflow` in their path: 106 files.
- Source files outside `src/sase/xprompt/` that directly import `sase.xprompt`: 68.
- Test files directly importing or patching `sase.xprompt`: 123.

The xprompt package exports a large public facade from `src/sase/xprompt/__init__.py`: models, typed inputs, directives,
reference parsing, expansion, output validation, workflow execution, HITL, workflow state, output handling, and catalog
helpers. That public surface is already consumed throughout SASE.

## What xprompt actually owns

The subsystem is not just `#foo` text substitution.

Core runtime:

- Reference parsing and shorthand syntax: `src/sase/xprompt/_parsing.py`, `_parsing_args.py`,
  `_parsing_references.py`, `_parsing_shorthand.py`.
- Prompt expansion and aliases: `src/sase/xprompt/processor.py`.
- Typed models: `src/sase/xprompt/models.py`, `src/sase/xprompt/workflow_models.py`.
- YAML workflow loading and validation: `src/sase/xprompt/workflow_loader.py`,
  `workflow_loader_parse.py`, `workflow_validator*.py`.
- Workflow execution: `workflow_runner.py`, `workflow_executor*.py`, `workflow_hitl.py`, `workflow_output.py`.
- Directives: `directives.py`, `_directive_alt.py`, `_directive_time.py`, `_directive_types.py`.
- Output validation: `output_validation.py`, `_step_input_loader.py`.

Catalog and editor/mobile surfaces:

- PDF/HTML/structured catalog: `src/sase/xprompt/catalog.py`, `_catalog_*`.
- TUI argument assist: `src/sase/ace/tui/widgets/xprompt_arg_assist.py`.
- Mobile/editor helper bridge: `src/sase/integrations/_mobile_helper_catalog.py`,
  `src/sase/integrations/editor_helpers.py`.
- Rust LSP launcher: `src/sase/integrations/xprompt_lsp.py`.

Bundled definitions:

- Package workflows and skills live under `src/sase/xprompts/`.
- Built-in markdown xprompts live under `src/sase/default_xprompts/`.
- Built-in config-defined xprompts live in `src/sase/default_config.yml`.
- Repo-local project workflows live under top-level `xprompts/`.

## Coupling back into SASE

`src/sase/xprompt/` imports several non-xprompt SASE modules:

- Config and aliases: `sase.config`, `load_xprompts_by_source`, `load_merged_config`.
- Plugin discovery: `sase.main.plugin_discovery`.
- Workspace/VCS routing: `sase.workspace_provider`, `sase.vcs_provider`.
- Agent launch and fanout planning: `sase.core.agent_launch_*`, `sase.llm_provider`, `sase.agent.names`.
- Artifacts and state: `sase.core.agent_artifact_index_lifecycle`, `sase.core.paths`, `sase.history.chat`.
- Prompt preprocessing helpers: `sase.content`, `sase.gemini_wrapper.file_references`, `sase.memory.dynamic`.
- Notifications/HITL: `sase.notifications.senders`.
- Beads and ChangeSpec helpers in smaller places.

This is the key migration problem. A standalone repository cannot import `sase` without becoming a circularly coupled
extension of SASE. To make it real, these would need to become explicit host interfaces.

## Downstream consumers inside SASE

The direct consumers are broad:

- CLI:
  - `sase run` foreground and background launch paths.
  - `sase xprompt expand/list/explain/graph/catalog`.
  - `sase path xprompts-*`.
  - `sase init-skills`.
  - `sase editor helper-bridge xprompt-catalog`.
  - `sase mobile helper-bridge xprompt-catalog`.
- TUI:
  - Prompt completion, `#@` browser, argument hints, workflow execution, HITL modals, workflow state display, agent row
    rendering.
- Agent runtime:
  - Early/late preprocessing in `src/sase/llm_provider/preprocessing.py`.
  - Multi-agent xprompt fanout in `src/sase/agent/multi_agent_xprompt.py`.
  - Multi-prompt local xprompt serialization in `src/sase/agent/multi_prompt_xprompts.py`.
- Automation:
  - `sase bead work` resolves xprompts by semantic tag via `src/sase/bead/xprompts.py`.
  - Axe workflows and hook runners rely on xprompt directives and workflow execution.
- Integrations:
  - Mobile helper catalog and launch normalization.
  - Rust xprompt LSP launcher environment setup.
  - Neovim still has legacy paths using `sase xprompt list`, though newer LSP work exists.

This is why a simple import-path move would be deceptively risky.

## Rust core overlap

The sibling `../sase-core` repo already contains xprompt-related shared logic:

- `crates/sase_core/src/editor/`: token classification, xprompt completion, argument diagnostics, hover, definition, and
  directive metadata.
- `crates/sase_core/src/xprompt_catalog.rs`: Rust catalog loader for editor/mobile-style metadata.
- `crates/sase_xprompt_lsp/`: `sase-xprompt-lsp` binary using `tower-lsp-server`.
- `crates/sase_core/src/host_bridge.rs`: command-backed helper bridge with xprompt catalog support.

That means the reusable editor-facing part is already moving toward the Rust core boundary. A new Python xprompt repo
would need to either:

- supersede the Rust catalog/editor work,
- depend on it,
- or duplicate it.

The third option is the worst one. The current architecture is already split: Python is the runtime authority, Rust is
becoming the editor/catalog acceleration layer. Any new repo should respect that split rather than reset it.

## Migration options

### Option A: full external Python package

Move `src/sase/xprompt`, packaged xprompt resources, schema files, and most xprompt tests to a new repository/package
such as `sase-xprompt`.

Required work:

- Define host interfaces for config loading, plugin resource discovery, workspace/project detection, VCS providers,
  command substitution, file references, LLM invocation, artifact index updates, HITL notifications, model resolution,
  agent name allocation, and temp paths.
- Rewrite `src/sase/xprompt` to call those interfaces rather than importing `sase.*`.
- Preserve `sase.xprompt` as a compatibility shim over `sase_xprompt`.
- Move or mirror bundled resources and update `importlib.resources` paths.
- Split tests into pure package tests and SASE integration tests.
- Update CLI, docs, schemas, packaging, LSP environment variables, mobile/editor helper bridges, and plugin contracts.
- Decide whether Rust `xprompt_catalog.rs` remains a parallel implementation or delegates to the new package.

Estimated effort: 4-8 weeks for a careful first version, plus follow-up stabilization. Risk is high because workflow
execution crosses agent launch, artifacts, HITL, and SASE project state.

### Option B: extract pure syntax/catalog library only

Move only pure pieces: models, reference parsing, argument parsing, frontmatter parsing, workflow classification,
structured catalog shape, and maybe static YAML parsing.

Keep workflow execution, SASE config/plugin discovery, launch, artifacts, and HITL in this repo.

Estimated effort: 1-3 weeks depending on compatibility goals. Risk is moderate. This can reduce duplication with editor
and mobile surfaces but does not deliver a standalone xprompt runtime.

### Option C: continue consolidating reusable logic in `sase-core`

Treat `../sase-core` as the shared backend for syntax/catalog/editor behavior. Keep the Python runtime where it is until
there is a clear product need for a non-SASE runtime.

Estimated effort: incremental. Risk is lowest because this matches the existing core-boundary rule and current LSP work.

### Option D: no extraction, just boundary cleanup

Do not move repositories. Instead, carve `src/sase/xprompt` internally into:

- `core` or `language`: models, parsing, rendering, validation.
- `runtime`: workflow execution and prompt preprocessing integration.
- `sources`: config/files/plugins/project discovery.
- `integrations`: catalog/mobile/TUI helpers.

Estimated effort: 1-2 weeks if kept mechanical. This is a useful precursor to any later split.

## Critique of the idea

The idea is directionally reasonable if the goal is to make xprompt a reusable language/runtime independent of SASE.
The current subsystem has grown large enough that clearer ownership would help.

But "all xprompt logic in its own repository" is too broad for the current state:

- XPrompt workflows are currently SASE workflows. They launch SASE agents, write SASE artifacts, use SASE model
  directives, read SASE project/workspace context, and update SASE UI-visible state.
- The most reusable parts are already being extracted into `sase-core` for editor/LSP use.
- A new repository would add release/version coordination across at least three repos: `sase`, `sase-core`, and the new
  xprompt repo.
- It would force premature API design around host hooks that are still changing quickly.
- It would make day-to-day feature work slower unless the package boundary is very stable.

The strongest argument for extraction is not code cleanliness; it is product reuse. If the plan is for other tools to
execute xprompt workflows without depending on SASE, then a separate runtime package could become worth it. If the only
consumer is SASE plus SASE-owned integrations, the repo split is likely process overhead.

## Recommended solution

Do not create a standalone xprompt repository yet.

Recommended path:

1. Create an explicit internal boundary in this repo first:
   - pure language/model/parsing/catalog helpers,
   - SASE source discovery adapters,
   - SASE runtime execution adapters.
2. Keep `sase.xprompt` as the runtime authority for workflow execution.
3. Continue moving editor/catalog parity logic into `../sase-core`, since the Rust LSP and mobile/editor helpers already
   use that direction.
4. Add a small contract document for the future split: the host services xprompt runtime would need, the stable wire
   catalog shape, and the compatibility promise for `sase.xprompt`.
5. Revisit a separate `sase-xprompt` repo only after the boundary has held for a few releases or there is a real
   external consumer that must run xprompt workflows without SASE.

If a split becomes necessary later, extract the pure language package first, not the runtime executor. The runtime
executor should move only after agent launch, artifact state, HITL, config, and plugin discovery are represented as
interfaces rather than direct `sase.*` imports.
