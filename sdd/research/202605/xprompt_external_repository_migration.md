# XPrompt external repository migration research

Date: 2026-05-21

## Question

Should the xprompt system be migrated out of `sase` into its own repository? If so, how much work is it, what should
move, and what is the least risky path?

## Executive summary

Do not migrate **all** xprompt logic into a separate repository right now.

The codebase already treats xprompt as a first-class SASE subsystem, not an isolated library. The Python runtime surface
spans prompt expansion, YAML workflow loading, workflow execution, directives, catalog generation, skill generation,
TUI/editor assist, mobile helper responses, bead automation, VCS project routing, artifact state, HITL, and agent
launch. There is also now a Rust-side xprompt catalog and LSP implementation in `../sase-core`, so a new standalone repo
would create a third authority unless the boundary is chosen very carefully.

The practical move is staged:

1. Keep runtime xprompt execution in this repo for now.
2. Strengthen a small stable API around catalog metadata, syntax parsing, and reference expansion.
3. Move only pure/editor/catalog logic to `sase-core` or a future `sase-xprompt` package when there is a second
   non-SASE consumer and the adapter boundary is proven.
4. If a repository split is still wanted later, extract behind compatibility shims so `sase.xprompt.*` imports continue
   to work for at least one release window.

A useful intermediate move is available today and is the lowest-risk concrete win: extract bundled non-SASE-critical
xprompt definitions into a `sase-xprompts` (or split) resource package using the existing `sase_xprompts` entry point.
This requires zero new abstractions because the plugin mechanism already exists and is already used by `sase-github`.

## Related prior research

This is the latest in a sequence of repo-split investigations. Consult these before acting:

- [`sdd/research/202605/xprompt_repository_migration_research.md`](xprompt_repository_migration_research.md) — parallel
  investigation from the same day, with a similar conclusion and a slightly different option taxonomy. Reconciliation
  notes appear in the "Cross-reference reconciliation" section below.
- [`sdd/research/202604/standalone_workflow_xprompt_split.md`](../202604/standalone_workflow_xprompt_split.md) — earlier
  proposal to split workflow execution specifically, rather than the full xprompt subsystem.
- [`sdd/research/202602/pluggy_repo_separation.md`](../202602/pluggy_repo_separation.md) — broader plugin/repo separation
  groundwork that the current `sase_xprompts` entry-point mechanism descends from.
- [`sdd/research/202603/xprompt_snippet_integration.md`](../202603/xprompt_snippet_integration.md),
  [`xprompt_workflow_best_practices.md`](../202603/xprompt_workflow_best_practices.md), and
  [`xprompt_special_output_variables.md`](../202603/xprompt_special_output_variables.md) — context on how the xprompt
  subsystem has accreted features in the last few months. Each accretion has widened the API surface that a split would
  need to freeze.

## Current inventory

Local code and assets (verified 2026-05-21):

- `src/sase/xprompt/`: **54 Python files, 15,135 LOC**.
- `src/sase/xprompts/`, `src/sase/default_xprompts/`, repo-local `xprompts/`: **38 bundled/project xprompt files, 2,984
  LOC** (Markdown, YAML, JSON schema, and bundled skill prompts).
- Source files outside `src/sase/xprompt/` that directly import `sase.xprompt`: **67**.
- Test files referencing `sase.xprompt`: **123**.
- Test files with `xprompt` or `workflow` in the path: **106**.
- Rust-side xprompt code in `../sase-core` (catalog + editor + LSP): **8,865 LOC** across `xprompt_catalog.rs`, the
  `editor/` module, and the `sase_xprompt_lsp` crate. This is a parallel implementation that already shadows part of the
  Python surface.

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
- Built-in config-defined xprompts live in `src/sase/default_config.yml` (6 entries under the `xprompts:` key).
- Repo-local project workflows live under top-level `xprompts/`.

### Bundled definitions, split by extraction-friendliness

Verified by enumeration of `src/sase/xprompts/`, `src/sase/default_xprompts/`, and repo-local `xprompts/`:

**SASE-policy-critical (must stay version-locked with SASE):**

- `commit.yml`, `propose.yml`, `pr.yml`, `git.yml`, `cd.yml` — set workspace/VCS environment consumed by SASE stop hooks
  and commit-skill enforcement.
- `mentor.yml`, `make_mentor_changes.yml`, `fix_hook.md` — encode SASE mentor/CR review semantics.
- `fork.yml`, `fork_by_chat.yml` — agent fan-out and rollover semantics.
- `skills/sase_*.md` — bundled commit/skill prompts that the runtime relies on for the commit workflow contract.
- `workflow.schema.json` — wire schema; must travel with the runtime that consumes it.

**Generic / extractable as a resource package:**

- `coder.md`, `summarize.md`, `pick_plan.md`, `pysplit.md` — content-only xprompts.
- `file.yml`, `json.yml`, `sync.yml`, `eval_ifs_loops.yml`, `eval_parallel.yml` — generic step-pattern demos.
- `audit_recent_bugs.yml`, `audit_recent_improvements.yml`, `fix_just.yml`, `pylimit_split.yml`, `refresh_docs.yml` —
  repo-local utilities; could live anywhere with `sase` installed.
- `default_xprompts/research_swarm.md` — generic research helper.

This split matters because Option A in the migration menu (below) becomes substantially less risky if it covers only the
generic bucket and uses the existing entry point.

## Coupling back into SASE — refined

The previous version of this note listed many `sase.*` imports without distinguishing their kind. The actual picture
inside `src/sase/xprompt/` is sharper:

**Module-top-level imports of non-xprompt SASE code (the only ones that block packaging):**

- `sase.config.load_xprompts_by_source`
- `sase.content` (`dump_yaml`, etc.)
- `sase.core.agent_artifact_index_lifecycle`
- `sase.env_contracts.SASE_ACTIVE_PROJECT_DIR_ENV`
- `sase.main.plugin_discovery.discover_plugin_resources`, `is_plugin_disabled`
- `sase.output.print_status`

That is six modules — small enough to wrap behind an explicit host interface in a single change.

**Deferred (function-body) imports — concentrated in two files:**

- In `_directive_alt.py`: `sase.llm_provider.registry`, `sase.llm_provider.config`, `sase.agent.names`,
  `sase.core.agent_launch_facade`, `sase.core.agent_launch_wire`, `sase.workspace_provider`,
  `sase.ace.changespec.project_spec_path`, `sase.ace.agent_tags`, `sase.bead.workspace`.
- In `workflow_executor_steps_prompt.py`: `sase.llm_provider`, `sase.llm_provider.preprocessing`,
  `sase.llm_provider.registry`, `sase.llm_provider.temporary_override`, `sase.notifications.senders`,
  `sase.history.chat`, `sase.gemini_wrapper.file_references`, `sase.workspace_provider`, `sase.vcs_provider`,
  `sase.core.paths`.

Two consequences:

1. The structural coupling is concentrated in **two files**: directive expansion and the prompt step executor. Any
   serious extraction work should start by carving these out into a SASE-specific adapter layer; the rest of the package
   is much closer to extraction-ready than a flat import grep suggests.
2. Workflow execution itself (`workflow_executor.py`, `workflow_runner.py`, `workflow_hitl.py`, the loop/parallel/script
   executors) has **zero direct `sase.*` imports at module level**. Its SASE coupling is delegated to the prompt-step
   executor it calls. That is a useful seam.

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

## Downstream consumers in sibling repos

This is the part the prior version of this file glossed over. Splitting the repo would require coordinated changes in:

- **`../sase-github`**: declares `[project.entry-points."sase_xprompts"]` in its `pyproject.toml`. Contributes
  `#gh`, `#new_pr_desc`, `#prdd`, `#pr_diff`. This is the **proof point that the entry-point mechanism works for an
  external package** — Option A (definitions-only) is already validated by an external consumer.
- **`../sase-telegram`**: imports directly from `sase.xprompt` and submodules:
  - `from sase.xprompt import extract_vcs_workflow_tag, replace_ref_in_vcs_tag, process_xprompt_references`
  - `from sase.xprompt.workflow_validator_extract import extract_xprompt_calls`
  - `from sase.xprompt.directives import extract_prompt_directives, plan_prompt_fanout_variants`
  - `from sase.xprompt.catalog import ...`
- **`../sase-nvim`**: uses the Rust xprompt LSP when available, falls back to `sase xprompt list`. Touches `lua/sase/`
  and `lua/telescope/_extensions/sase.lua`.

Any extraction must therefore preserve `sase.xprompt` as a public Python import path for `sase-telegram`, or coordinate
a `sase-telegram` release at the same time.

## Loader precedence is a public contract

From `src/sase/xprompt/loader.py:103-113`:

```
1.  .xprompts/*.md (CWD, hidden)
2.  xprompts/*.md (CWD)
3.  ~/.xprompts/*.md (home, hidden)
4.  ~/xprompts/*.md (home)
5.  ~/.config/sase/xprompts/{project}/*.md (project-specific)
6.  memory/long/*.md auto-discovered (frontmatter keywords)
7.  sase.yml xprompts:/snippets: section
8.  Plugin packages (via sase_xprompts entry points)
9.  <sase_package>/default_xprompts/*.md
10. <sase_package>/xprompts/*.md (internal)
```

Five of these sources need host knowledge (CWD project detection, home config layout, `~/.config/sase/`, memory
auto-discovery, sase.yml merging). A standalone runtime cannot resolve them without a host-provided source registry —
which is the API design problem hiding behind every extraction option below.

## Tag enum is domain policy, not language

`XPromptTag` (`src/sase/xprompt/tags.py`) is currently a closed enum with these values:

`vcs`, `crs`, `fix_hook`, `rollover`, `mentor`, `commit`, `propose`, `make_mentor_changes`, `diff_file`, `append_to_pr`,
`append_to_commit_and_propose`, `memory`, `create_epic_bead`, `create_legend_bead`, `work_phase_bead`, `land_epic`,
`land_legend`.

Only three of those (`vcs`, `memory`, `rollover`) are arguably generic. The rest encode SASE-specific behavior: commit
intent enforcement, mentor/CR review, bead and SDD automation, PR/commit append flows. A language-level extraction must
either:

- treat tags as opaque strings and move the enum to SASE policy code, or
- ship the enum with the library and accept that the library is SASE-shaped.

The first option is correct but is itself a semantic migration that breaks `from sase.xprompt.tags import XPromptTag`
callers (the enum is currently used outside the xprompt package — see `sase.bead.xprompts`, `sase.ace.tui.*`).

## Directives are partly SASE launch policy

Directives like `%model`, `%alt`, `%wait`, `%name`, `%tag`, and multi-model fan-out parse cleanly as language constructs
but resolve through SASE-specific model aliases (`sase.llm_provider.registry`, `model_short_alias_map`,
`resolve_model_provider`), agent name allocation (`sase.agent.names`), and launch fan-out planning
(`sase.core.agent_launch_facade.plan_agent_launch_fanout`). A reusable library could parse them; only SASE can resolve
them.

## Rust core overlap and parity risk

The sibling `../sase-core` repo already contains substantial xprompt-related shared logic (8.9k LOC total):

- `crates/sase_core/src/editor/`: token classification, xprompt completion, argument diagnostics, hover, definition,
  directive metadata.
- `crates/sase_core/src/xprompt_catalog.rs`: Rust catalog loader for editor/mobile-style metadata (~2.7k LOC; shadows
  parts of the Python catalog).
- `crates/sase_xprompt_lsp/`: `sase-xprompt-lsp` binary using `tower-lsp-server` (~3.3k LOC plus tests).
- `crates/sase_core/src/host_bridge.rs`: command-backed helper bridge with xprompt catalog support.

That means the reusable editor-facing part is already moving toward the Rust core boundary. A new Python xprompt repo
would need to either supersede the Rust catalog/editor work, depend on it, or duplicate it. The third option is the
worst one. The current architecture is already split: Python is the runtime authority; Rust is becoming the
editor/catalog acceleration layer.

A non-obvious consequence: the Python catalog and the Rust catalog must stay in lockstep, and they are not currently
covered by a parity test suite. Any further extraction should add one before — not after — moving code.

## Migration options

### Option A: extract bundled definitions to a `sase-xprompts` (or split) resource package

Use the existing `sase_xprompts` entry point. Move only the **generic** bundled definitions listed in "Bundled
definitions, split by extraction-friendliness" above. Keep SASE-policy-critical definitions in this repo.

Required work:

- New package skeleton (`pyproject.toml`, `LICENSE`, CI, release flow).
- Move ~15 markdown/YAML files; update any tests that load them via package resources.
- Add the new package as a SASE install-time dependency so defaults stay shipped out of the box.
- Document override semantics for users.

Estimated effort: **2-5 days**. Risk: low. Validated by the existing `sase-github` pattern. Does not move any logic.

### Option B: extract a pure Python xprompt language library

Move only pure pieces: models, reference parsing, argument parsing, frontmatter parsing, workflow classification,
structured catalog shape, and static YAML parsing.

Keep workflow execution, SASE config/plugin discovery, launch, artifacts, HITL, and directive resolution in this repo.

Estimated effort: **1-3 weeks** depending on compatibility goals. Risk: moderate. Reduces duplication with editor and
mobile surfaces but does not deliver a standalone xprompt runtime.

### Option C: continue consolidating reusable logic in `sase-core`

Treat `../sase-core` as the shared backend for syntax/catalog/editor behavior. Keep the Python runtime where it is
until there is a clear product need for a non-SASE runtime.

Estimated effort: incremental. Risk: lowest. Matches the existing core-boundary rule
(`memory/short/rust_core_backend_boundary.md`) and current LSP work.

### Option D: no extraction, just boundary cleanup

Do not move repositories. Instead, carve `src/sase/xprompt` internally into:

- `core` or `language`: models, parsing, rendering, validation.
- `runtime`: workflow execution and prompt preprocessing integration.
- `sources`: config/files/plugins/project discovery.
- `integrations`: catalog/mobile/TUI helpers.

The refined coupling map above suggests this can be done relatively mechanically because the heavy SASE coupling is
already concentrated in `_directive_alt.py` and `workflow_executor_steps_prompt.py`.

Estimated effort: **1-2 weeks** if kept mechanical. Useful precursor to any later split.

### Option E: full external Python runtime package

Move `src/sase/xprompt`, packaged resources, schema files, and most xprompt tests to a new repository/package such as
`sase-xprompt`.

Required work:

- Define host interfaces for config loading, plugin resource discovery, workspace/project detection, VCS providers,
  command substitution, file references, LLM invocation, artifact index updates, HITL notifications, model resolution,
  agent name allocation, and temp paths.
- Rewrite `src/sase/xprompt` to call those interfaces rather than importing `sase.*`.
- Preserve `sase.xprompt` as a compatibility shim over `sase_xprompt` for `sase-telegram`'s direct imports.
- Move or mirror bundled resources and update `importlib.resources` paths.
- Split tests into pure package tests and SASE integration tests.
- Update CLI, docs, schemas, packaging, LSP environment variables, mobile/editor helper bridges, and plugin contracts.
- Decide whether Rust `xprompt_catalog.rs` remains a parallel implementation or delegates to the new package.
- Add parity tests against the Rust catalog to prevent drift.

Estimated effort: **4-8 weeks** for a careful first version, plus follow-up stabilization. Risk: high.

## Option comparison

| Option | What moves | Effort | Risk | Solves "reusable language"? | Solves "reusable runtime"? |
|--------|-----------|--------|------|------------------------------|-----------------------------|
| A | Generic bundled definitions only | 2-5 days | Low | No | No |
| B | Pure parser/catalog code | 1-3 weeks | Medium | Partial | No |
| C | Editor/catalog logic into Rust core | Ongoing | Low | Yes (for editors) | No |
| D | In-tree boundary refactor only | 1-2 weeks | Low | Sets up future Yes | Sets up future Yes |
| E | Full runtime to new repo | 4-8 weeks | High | Yes | Yes |

A + C + D in sequence is strictly dominated by E only if the goal is "everything in its own repo" rather than "xprompt
is a reusable, cleanly-bounded subsystem."

## Critique of the idea

The idea is directionally reasonable if the goal is to make xprompt a reusable language/runtime independent of SASE.
The current subsystem has grown large enough that clearer ownership would help.

But "all xprompt logic in its own repository" is too broad for the current state:

- XPrompt workflows are currently SASE workflows. They launch SASE agents, write SASE artifacts, use SASE model
  directives, read SASE project/workspace context, and update SASE UI-visible state.
- The most reusable parts are already being extracted into `sase-core` for editor/LSP use, and an undefended split would
  create a third source of truth for catalog/editor semantics.
- A new repository would add release/version coordination across at least four repos (`sase`, `sase-core`, the new
  xprompt repo, and `sase-telegram` because of its direct imports) and put release coupling between Python and Rust
  catalogs that does not exist today.
- It would force premature API design around host hooks that are still changing quickly (the prompt-step executor and
  directive resolver in particular).
- It would make day-to-day feature work slower unless the package boundary is very stable — and the most recent six
  months of research (`xprompt_snippet_integration.md`, `xprompt_special_output_variables.md`,
  `xprompt_workflow_best_practices.md`) show that the boundary is still moving.

The strongest argument for extraction is **product reuse**, not code cleanliness. If the plan is for other tools to
execute xprompt workflows without depending on SASE, then a separate runtime package could become worth it. If the only
consumer is SASE plus SASE-owned integrations (`sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`), the repo split
is mostly process overhead.

## When to revisit (triggers)

Revisit a full-repo split when at least one of the following becomes true:

1. A non-SASE consumer wants to run xprompt workflows (not just parse them or read the catalog).
2. The Python and Rust catalog implementations have a documented parity contract and parity tests passing in CI.
3. `_directive_alt.py` and `workflow_executor_steps_prompt.py` have been refactored so their SASE-specific calls go
   through a single explicit host-interface module.
4. `XPromptTag` is no longer a closed enum, or its non-generic members have moved to a SASE-side policy module.
5. The `sase.xprompt` public facade has been frozen with a documented stability promise for at least one release.

If fewer than three of those conditions hold, choose Option A, C, or D over Option E.

## Cross-reference reconciliation

This note and the sibling [`xprompt_repository_migration_research.md`](xprompt_repository_migration_research.md) cover
the same question and reach the same headline recommendation. Differences worth knowing:

- The sibling note presents the loader precedence and the `XPromptTag` enum as standalone risk factors. This note
  treats them as part of the broader "host policy vs language" framing and quantifies the enum's SASE/generic split.
- The sibling note's options A-D map to options A, B, E, C here, respectively. This note adds Option D (in-tree boundary
  cleanup) as a distinct path, because the refined coupling map shows it is cheaper than it first appears.
- This note adds explicit sibling-repo consumer enumeration, an LOC-verified inventory, the deferred-vs-top-level
  import distinction, the SASE-critical-vs-generic split of bundled definitions, an option-comparison table, and a
  trigger list for revisiting.

Either note is sufficient as a standalone reference; reading both is only useful if reconciling the option taxonomies.

## Recommended solution

Do not create a standalone xprompt repository yet.

Recommended path:

1. **Do Option A now.** Extract generic bundled definitions into a `sase-xprompts` (or similarly named) resource package
   using the existing `sase_xprompts` entry point. This is 2-5 days, validates the packaging story, and reduces the
   in-repo asset footprint without touching logic.
2. **Do Option D next.** Carve `src/sase/xprompt/` into internal `language` / `runtime` / `sources` / `integrations`
   subpackages, with the bulk of SASE-specific deferred imports collected into a single adapter module called from
   `_directive_alt.py` and `workflow_executor_steps_prompt.py`.
3. **Continue Option C in parallel.** Keep moving editor/catalog parity logic into `../sase-core`; add a parity test
   suite between the Python and Rust catalogs before that work continues much further.
4. **Hold Options B and E.** Revisit only when the triggers above are met.
5. **Write a short contract document** for the eventual split: the host services xprompt runtime would need, the stable
   wire catalog shape, and the compatibility promise for `sase.xprompt`. This document should land in `sdd/` and be
   updated when any of the trigger conditions change.

If a split becomes necessary later, extract the pure language package first, not the runtime executor. The runtime
executor should move only after agent launch, artifact state, HITL, config, and plugin discovery are represented as
interfaces rather than direct `sase.*` imports.
