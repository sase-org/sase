# XPrompt Repository Migration Research

Date: 2026-05-21

## Question

How much work would it be to migrate all xprompt logic out of `sase` and into its own repository? Is the idea worth
doing? If so, what solution should SASE use?

## Executive Summary

Do **not** migrate all xprompt logic into a separate standalone repository as a single move. The current xprompt system is
not just a reusable prompt-template library; it is part of SASE's orchestration kernel. Moving it wholesale would either
create a circular dependency (`sase-xprompt` depending back on `sase`) or force a large host-interface refactor around
agent launch, workspace providers, VCS providers, artifact indexing, dynamic memory, notifications, model resolution,
and commit workflow semantics.

There is a worthwhile extraction, but it should be narrower:

1. Keep runtime workflow execution and SASE-specific prompt semantics in `sase` for now.
2. Continue putting editor/catalog cross-frontend logic in `../sase-core`, where a Rust xprompt catalog and LSP already
   exist.
3. Extract only a pure Python xprompt language/core library after introducing explicit host adapter interfaces inside
   this repo.
4. Optionally move bundled xprompt definitions into plugin/resource packages using the existing `sase_xprompts` entry
   point, but treat core commit/VCS/bead workflows as version-locked SASE features.

The realistic effort is:

- **Definition-only repo:** 2-5 days for a small `sase-xprompts` resource package, plus release/CI/docs wiring.
- **Pure parser/catalog library:** 1-2 weeks if done in-tree first, 2-4 weeks if immediately split into another repo.
- **Full runtime extraction:** 4-8+ weeks and high ongoing coordination cost. I do not recommend it.

## Current XPrompt Surface

The xprompt system spans several layers.

### Python core package

`src/sase/xprompt/` is about **15.1k lines** across 54 Python files. It includes:

- data models (`models.py`, `workflow_models.py`);
- reference parsing and shorthand syntax (`_parsing*.py`, `_fenced_blocks.py`, `_disabled_regions.py`);
- Markdown/config/plugin/workflow loading (`loader*.py`, `workflow_loader*.py`);
- Jinja rendering and typed argument validation (`_jinja.py`);
- prompt expansion (`processor.py`);
- workflow validation and graph/explain/catalog rendering;
- workflow execution, loops, parallel steps, HITL, output validation, and embedded workflow pre/post-step expansion;
- prompt directives and fan-out (`directives.py`, `_directive_alt.py`, `_directive_time.py`).

The bundled xprompt assets add another **2.4k lines** under:

- `src/sase/xprompts/`
- `src/sase/default_xprompts/`
- `src/sase/default_config.yml` `xprompts:` entries

Adjacent Python xprompt-facing glue adds at least another **1.8k lines** in:

- `src/sase/agent/multi_agent_xprompt.py`
- `src/sase/agent/multi_prompt.py`
- `src/sase/agent/multi_prompt_xprompts.py`
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/main/xprompt_handler.py`
- `src/sase/main/parser_xprompt.py`
- `src/sase/integrations/xprompt_lsp.py`
- `src/sase/bead/xprompts.py`
- `src/sase/history/vcs_xprompt_mru.py`

ACE xprompt UI adds about **3.0k lines** across xprompt select/browser/location/config modals and completion widgets.

There are **123 test files** under `tests/` that directly import or patch `sase.xprompt.*`. **103 source files** under `src/` outside the xprompt package import from it. These are not just call-site counts — many tests patch internal modules (`sase.xprompt.workflow_executor`, `sase.xprompt.loader_sources`, etc.), so a rename to `sase_xprompt.*` cannot be done with a sed pass without also rewriting test fixtures.

The package's public facade (`src/sase/xprompt/__init__.py`) re-exports about **50 names** — models, parsing helpers, directives, processor entry points, output validation, workflow execution types, and HITL handlers. Any external repository would inherit that surface as its v1 API or break every consumer at once.

### Existing Rust extraction

`../sase-core` already owns substantial editor-facing xprompt logic:

- `crates/sase_core/src/xprompt_catalog.rs` is **2.7k lines**.
- `crates/sase_core/src/editor/` is **3.3k lines** across token classification, completion, argument diagnostics,
  hover, definition, and directive metadata.
- `crates/sase_xprompt_lsp/` is about **6.0k lines** including catalog cache and LSP conversion.

This is important because "move xprompt logic out of `sase`" has already started, but the current direction is
`sase-core` for shared editor/catalog behavior, not a third repository.

The Rust catalog and the Python loader must produce equivalent catalog records for editor/LSP integration to be
trustworthy. Today that parity is asserted only at the catalog-shape level, not at the loader-source level. If a new
xprompt repo took over Python-side loading, the Rust catalog would need either a stable wire boundary or a generated
spec; otherwise the two implementations will drift the first time a loader source is added (memory xprompts, plugin
discovery, or project-local search are the most likely drift points).

### External consumers

Several sibling repos consume xprompt behavior from `sase`:

- `../sase-github` contributes GitHub-specific xprompt workflows through the `sase_xprompts` entry point
  (`#gh`, `#new_pr_desc`, `#prdd`, `#pr_diff`). It is a concrete precedent for how a `sase-default-xprompts` plugin
  package could be structured — see the [Concrete Plugin Precedent](#concrete-plugin-precedent) section below.
- `../sase-nvim` uses the xprompt LSP when available and falls back to `sase xprompt list`.
- `../sase-telegram` launches prompts through SASE and imports from `sase.xprompt`, `sase.xprompt.catalog`,
  `sase.xprompt.directives`, and `sase.xprompt.workflow_validator_extract` — at least **12 import sites** including
  internal helpers like `plan_prompt_fanout_variants` and `PdfEngineUnavailable`. Most imports are intentionally lazy
  (function-scoped) to keep `sase` optional at import time, but they still pin the API surface.

So an extraction would not only touch this repo. It would also need compatibility shims or coordinated releases for
plugins and clients. The `sase-telegram` coupling is the trickiest: it depends on private-looking submodule names, which
means even a "pure parser library" split would need either re-exports for those names or a coordinated PR there.

### Plugin discovery and disablement levers

Plugin xprompt sources are loaded through `sase.main.plugin_discovery.discover_plugin_resources("sase_xprompts")`. The
existing env-var contract — `SASE_DISABLE_PLUGINS` (global) and `SASE_DISABLE_PLUGIN_XPROMPTS` (per-group) — already
behaves as a feature switch. A new `sase-default-xprompts` package would slot into this mechanism without code changes
to the loader.

## Coupling Points

The strongest reason not to move everything at once is that the "xprompt logic" boundary is not clean today.

### The package is already fighting circular imports

`src/sase/xprompt/` has only **7 module-level** imports from non-xprompt `sase.*` modules (`sase.config`,
`sase.content`, `sase.core.agent_artifact_index_lifecycle`, `sase.env_contracts`, `sase.main.plugin_discovery`,
`sase.output`). But it has roughly **25 additional function-scoped imports** from modules like
`sase.agent.names`, `sase.agent.multi_prompt`, `sase.ace.agent_tags`, `sase.bead.workspace`,
`sase.core.agent_launch_facade`, `sase.gemini_wrapper.file_references`, `sase.history.chat`,
`sase.llm_provider` (4 submodules), `sase.notifications.senders`, `sase.vcs_provider`, and
`sase.workspace_provider` (5 functions).

Function-scoped imports inside a package usually mean the import graph could not be expressed top-of-module without a
cycle. That is exactly the entanglement an external repo would inherit. Counting only top-level imports
under-estimates the coupling by roughly a factor of four.

### Runtime workflow execution is SASE-bound

`WorkflowExecutor` and its mixins are not generic prompt-template code. They call back into SASE for:

- agent invocation (`sase.llm_provider.invoke_agent`);
- model/provider resolution and temporary overrides;
- VCS diff capture through `sase.vcs_provider`;
- workspace tag and ref parsing through `sase.workspace_provider`;
- artifact index updates through `sase.core.agent_artifact_index_lifecycle`;
- temp directory allocation through `sase.core.paths`;
- chat history persistence;
- HITL notifications;
- dynamic memory rewrites;
- environment contracts such as `_chdir` and `SASE_ACTIVE_PROJECT_DIR`;
- embedded workflow metadata files used by the TUI and agent index.

If this moves to a standalone repo without first defining host interfaces, the new repo would have to import `sase`.
That would be an extraction in name only and would likely create dependency cycles once SASE imports the extracted
package.

### Tags are domain semantics, not generic language semantics

`XPromptTag` includes generic-ish tags such as `vcs`, `rollover`, and `memory`, but also SASE-specific roles:

- `commit`, `propose`, `append_to_pr`, `append_to_commit_and_propose`;
- `mentor`, `make_mentor_changes`, `fix_hook`, `crs`;
- bead/SDD automation tags such as `create_epic_bead`, `work_phase_bead`, `land_legend`.

A reusable xprompt library should probably treat tags as strings. The fixed enum belongs in SASE policy code. Changing
that is feasible, but it is a semantic migration, not a file move.

### Prompt directives are partly SASE launch policy

The directive parser looks like language logic, but `%model`, `%alt`, `%wait`, `%name`, `%tag`, and multi-model fan-out
connect to SASE-specific agent naming, model aliases, provider short names, launch fan-out planning, and deferred
workspace allocation. A reusable library could parse directive syntax, but SASE still needs to own what those directives
mean at launch time.

### Loader behavior depends on SASE config and plugin discovery

The loader order is a user-facing contract:

1. CWD `.xprompts/`
2. CWD `xprompts/`
3. home `.xprompts/`
4. home `xprompts/`
5. project-specific `~/.config/sase/xprompts/{project}/`
6. memory xprompts
7. `sase.yml` config xprompts
8. plugin packages through `sase_xprompts`
9. built-in default xprompts
10. built-in package xprompts

This currently depends on `sase.config`, SASE plugin discovery, known project workspaces, default config files, and
package resource paths. Moving this cleanly requires a host-provided source registry.

### Commit and VCS workflows are especially integrated

The VCS workflows are xprompt workflows, but their semantics are SASE semantics:

- `#git`, `#gh`, and `#cd` determine workspace setup and teardown.
- `#commit`, `#propose`, and `#pr` set environment that is consumed by stop hooks, skills, commit workflow code, and
  provider plugins.
- Embedded workflow expansion has special behavior for `SASE_COMMIT_METHOD`, appending provider-specific tagged context.

These are not good candidates for a generic runtime repo. They can be data files in plugin/resource packages, but their
meaning is tightly versioned with SASE.

## Migration Options

### Option A: Move only bundled xprompt definitions to a resource package

This is the lowest-risk extraction.

Create a `sase-xprompts` or `sase-default-xprompts` package that exposes a `sase_xprompts` entry point and contains
Markdown/YAML resources under `xprompts/`.

Pros:

- Uses the existing plugin mechanism.
- Keeps the runtime engine where it is.
- Lets bundled prompt/workflow definitions be released or overridden independently.
- Matches the `sase-github` pattern.

Cons:

- Does not move the actual logic.
- Core built-ins still need to be installed by default, so SASE packaging must depend on this package.
- Some definitions are not just content. Commit, VCS, bead, and mentor workflows encode SASE contracts and need
  synchronized versioning.
- `src/sase/default_config.yml` xprompt entries need a decision: keep them in SASE config, move them to file-backed
  resources, or add a config-entry plugin package.

Effort: **2-5 days**, depending on how much documentation and packaging polish is required.

### Option B: Extract a pure Python xprompt language library

Move only syntax/model/catalog behavior into a library, then keep a SASE adapter around it.

Good candidates:

- `models.py` and portable pieces of `workflow_models.py`;
- `_parsing_args.py`, `_parsing_references.py`, `_parsing_shorthand.py`;
- `_fenced_blocks.py`, `_disabled_regions.py`, `segment_separators.py`;
- `loader_parsing.py`;
- argument validation and Jinja placeholder substitution, minus SASE global template variables;
- structured catalog projection, if it receives preloaded source records.

Poor candidates without adapter work:

- `loader.py` and `loader_sources.py`, unless source discovery is injected;
- `directives.py` and `_directive_alt.py`, unless launch/model/name policy is injected;
- `workflow_executor*.py`, because execution calls SASE directly;
- `tags.py`, unless tags become strings;
- catalog PDF rendering, unless SASE paths/assets are injected.

This option is worth doing only if there is a clear external consumer besides SASE itself. Otherwise it creates a new
release boundary for code that still changes with SASE behavior.

Effort: **1-2 weeks in-tree first**, or **2-4 weeks** if split to a new repo immediately with packaging, CI, versioning,
and compatibility shims.

### Option C: Move the whole runtime executor to a new repo

This means moving `WorkflowExecutor`, workflow loading, embedded workflow expansion, directives, output validation,
HITL, and prompt preprocessing into a standalone package.

This is technically possible, but it requires a host API for:

- invoking agents;
- resolving models/providers;
- resolving workspace provider names and ref regexes;
- applying VCS diffs and workspace changes;
- artifact writes and index updates;
- SASE config and plugin discovery;
- notifications and HITL responses;
- temp dirs and environment contracts;
- dynamic memory writes;
- chat persistence;
- SASE-specific tags and commit intent behavior.

At that point, most of the work is designing a mini SASE host runtime API. The result is likely worse than the current
design unless another application truly wants to run SASE-style xprompt workflows without depending on SASE.

Effort: **4-8+ weeks**, plus high ongoing release coordination. Not recommended.

### Option D: Continue Rust core/editor extraction

This is already happening in `../sase-core`: native catalog loading and the xprompt LSP exist. This path fits the
existing architecture rule that shared backend/domain behavior needed by multiple frontends belongs in the Rust core.

Pros:

- Keeps editor/mobile/web shared behavior in the backend core.
- Avoids another repo and another package graph.
- Gives non-Python clients a stable wire/API boundary.
- Does not force the runtime executor out before its host dependencies are clean.

Cons:

- Rust and Python semantics can drift.
- The native Rust catalog loader must track the Python loader exactly or have a documented narrower scope.
- Runtime execution remains Python-owned.

Effort: ongoing, but lower risk than a full new repo because the boundary already exists.

## Concrete Plugin Precedent

The cheapest, lowest-risk option (Option A) already has a working template inside the org. `../sase-github` is a
separate repo published as the `sase-github` distribution. Its layout is small and easy to copy:

```
src/sase_github/
  __init__.py
  plugin.py
  workspace_plugin.py
  config.py
  default_config.yml
  xprompts/
    gh.yml
    new_pr_desc.yml
    pr_diff.yml
    prdd.yml
  scripts/
    gh_setup.py
    new_pr_desc_get_context.py
```

`pyproject.toml` declares one line:

```toml
[project.entry-points."sase_xprompts"]
sase_github = "sase_github"
```

A `sase-default-xprompts` package would copy this shape, contain only the non-SASE-critical bundled xprompts
(`research_swarm.md`, the `xprompts:` entries from `default_config.yml`, etc.), and leave SASE-critical workflows
(`commit.yml`, `propose.yml`, `git.yml`, `gh.yml`, `cd.yml`, `mentor.yml`, `make_mentor_changes.yml`, `fix_hook.md`,
the `skills/` directory, and the `workflow.schema.json`) in `sase` itself. The reason to keep those in `sase` is that
they encode SASE contracts that are consumed by stop hooks, the commit workflow, bead automation, and the ChangeSpec
COMMITS drawer.

## Host Adapter Surface (For Any Real Extraction)

If a future xprompt repo is ever extracted, the most important up-front design is the host-services interface it will
require from SASE. Based on the function-scoped imports listed in the coupling section, the minimum surface is roughly:

- `XPromptSourceProvider`: returns ordered list of `(SourceTag, root_dir | resource_iter)` pairs covering all 10 loader
  positions (CWD, home, project-specific, memory, config, plugins, defaults, package).
- `WorkspaceProvider`: `get_workspace_name`, `get_ref_patterns`, `get_vcs_tag_pattern`, `get_embedded_vcs_tag_pattern`,
  `get_workflow_names`.
- `VCSProvider`: project-tag parsing, diff capture, ref resolution.
- `AgentLauncher`: `plan_agent_launch_fanout`, `get_next_auto_name`, `get_most_recent_agent_name`, `invoke_agent`.
- `ModelResolver`: `resolve_model_alias`, `resolve_model_provider`, `model_short_alias_map`, temporary overrides.
- `ArtifactSink`: append/replace artifact index entries; write embedded workflow metadata.
- `NotificationSink`: HITL request, HITL response wait, snooze.
- `ChatHistorySink`: persist chat turns for a step.
- `EnvironmentContract`: provide `SASE_ACTIVE_PROJECT_DIR_ENV` and other contract env vars to subprocess steps.
- `TagPolicy`: validate tag names; classify tags as workflow vs commit vs mentor vs bead.
- `CommandSubstitutionPolicy`: how `$(...)` inside prompt bodies is evaluated.
- `DynamicMemoryWriter`: append/rewrite memory entries from workflow steps.

This is at least 12 interface surfaces. Designing those right takes longer than the file move itself. That is the
reason every option below that does not include this design is implicitly a "lift and shift with import-back-to-sase"
plan, which is the worst outcome.

## Trigger Conditions For A Future Split

The recommendation below is "not now." It is worth being concrete about what would change that.

Move ahead with a separate xprompt repo when **two or more** of the following are true:

1. A non-SASE host (a different orchestrator, a CI integration, a code-review bot) needs to execute xprompt workflows
   and that host cannot reasonably depend on `sase`.
2. Workflow execution stops changing weekly. If the executor's interface to `sase.llm_provider`,
   `sase.workspace_provider`, and `sase.core.agent_launch_*` is unchanged for one quarter, the host adapter surface is
   probably stable enough to freeze.
3. The Rust catalog/LSP and the Python loader produce divergent outputs at least once in production, forcing a
   formalized wire boundary anyway.
4. SASE plugin authors ship more than one out-of-tree workflow whose lifecycle is uncoupled from a SASE release.
5. The `sase.xprompt.*` public facade is reduced to the ~25 names actually used externally (currently ~50). That is a
   precondition, not a trigger — but if it is done first, the split becomes mechanical.

Until then, every "split" gain is more cheaply gotten by an in-tree subpackage boundary plus continued investment in
`../sase-core`.

## Critique Of The Idea

The idea is directionally reasonable if the goal is "make xprompt a cleaner subsystem with reusable pieces." It is not
worth doing if the goal is "move everything named xprompt into another repo."

The clean abstraction is not "xprompt repo vs SASE repo." The clean abstraction is:

- **language/core:** parse references, validate typed args, read Markdown/YAML definitions, classify workflow kind,
  produce catalog records;
- **host policy:** where definitions come from, what tags mean, what `%model` does, how workspace refs resolve, how
  agents launch, how artifacts are indexed, how commit intent is enforced;
- **presentation:** CLI, TUI, editor, mobile, Telegram, catalog PDF.

Today those layers are mixed. Moving the mixed package to another repo preserves the problem and adds coordination cost.

The strongest argument for extraction is reducing duplicate editor/catalog implementations. That is already being solved
in `sase-core` and the LSP. The strongest argument against extraction is the runtime executor: it is the heart of how
SASE turns prompts into orchestrated agent runs, not a generic templating engine.

## Recommended Migration Shape

If SASE pursues this, use a staged split:

1. **Define the boundary in-tree first.**
   Create a pure subpackage boundary inside this repo, such as `sase.xprompt_core` or `sase_xprompt_core`, and make it
   import nothing from `sase.*` except its own package. Move only parser/model/loader-parsing code there first.

2. **Add SASE host adapters.**
   Keep `sase.xprompt` as the public facade, but have it provide SASE-specific source discovery, tag policy, config,
   plugin loading, workspace/VCS regexes, global template variables, and launch/execution callbacks to the pure core.

3. **Keep workflow execution in SASE.**
   Do not move `WorkflowExecutor`, embedded workflow pre/post-step execution, commit intent handling, dynamic memory, or
   agent invocation until those dependencies are explicit interfaces and there is a real non-SASE host.

4. **Use `sase-core` for editor/catalog consumers.**
   Continue making the Rust catalog/LSP the shared API for Neovim and future editor/mobile/web surfaces. Add parity tests
   against Python catalog outputs instead of creating a third repo for the same concern.

5. **Optionally split definitions later.**
   Once the code boundary is stable, move non-core bundled xprompt definitions to a `sase-default-xprompts` plugin
   package. Keep SASE-critical definitions version-locked unless there is a clear compatibility matrix.

## Recommended Solution

Do **not** create a standalone repository for all xprompt logic now. Instead, do an in-repo architectural split: extract a
pure xprompt language/catalog core behind host adapters, keep runtime workflow execution and SASE-specific policies in
`sase`, and continue using `../sase-core` as the shared editor/catalog backend. After that boundary is proven by tests,
consider a small separate resource package for bundled xprompt definitions, not the full runtime engine.

Concretely, the next steps in priority order are:

1. **In-tree subpackage split.** Move the pure pieces (`models.py`, `_parsing*.py`, `_fenced_blocks.py`,
   `_disabled_regions.py`, `segment_separators.py`, `loader_parsing.py`, `_jinja.py`, parts of `output_validation.py`)
   into `sase.xprompt.core`. Forbid imports from `sase.*` outside that subpackage via a lint rule.
2. **Host adapter shims.** Move the function-scoped imports listed above behind a small set of `Protocol` classes
   passed into loader/processor/executor constructors. This is the work that an external repo would have needed to do
   anyway, so doing it in-tree first is not wasted.
3. **Reduce the public facade.** Audit the ~50 names exported from `sase.xprompt.__init__` against actual call sites
   (103 source files, 123 test files, 12 telegram sites) and shrink to what is actually consumed externally. Hide the
   rest behind submodule paths.
4. **Sase-core parity tests.** Add a parity test suite that runs the Python loader and the Rust catalog over the same
   fixtures and asserts equal output. This makes the boundary safe before any further split.
5. **Optional resource plugin.** Once the above is stable, create a `sase-default-xprompts` package using the
   `sase-github` template for non-critical bundled definitions. Keep `commit.yml`, `propose.yml`, `git.yml`, `gh.yml`,
   `cd.yml`, `mentor.yml`, the `skills/` directory, and the `workflow.schema.json` in `sase` itself because they
   encode SASE contracts.

Defer a standalone `sase-xprompt` repo until at least two of the trigger conditions listed above are met. The
recommendation in this document should be revisited when that happens, not before.
