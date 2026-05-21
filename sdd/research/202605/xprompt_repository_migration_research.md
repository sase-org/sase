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

`src/sase/xprompt/` is about **15.8k lines** across 57 non-cache files. It includes:

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

There are at least **101 Python test files** whose names target xprompt, workflow, or directive behavior.

### Existing Rust extraction

`../sase-core` already owns substantial editor-facing xprompt logic:

- `crates/sase_core/src/xprompt_catalog.rs` is about **2.7k lines**.
- `crates/sase_core/src/editor/xprompt_args.rs` is about **500 lines**.
- `crates/sase_xprompt_lsp/` is about **3.3k source lines** plus tests.

This is important because "move xprompt logic out of `sase`" has already started, but the current direction is
`sase-core` for shared editor/catalog behavior, not a third repository.

### External consumers

Several sibling repos consume xprompt behavior from `sase`:

- `../sase-github` contributes GitHub-specific xprompt workflows through the `sase_xprompts` entry point
  (`#gh`, `#new_pr_desc`, `#prdd`, `#pr_diff`).
- `../sase-nvim` uses the xprompt LSP when available and falls back to `sase xprompt list`.
- `../sase-telegram` launches prompts through SASE and directly imports xprompt parsing, directive, catalog, and VCS-tag
  helpers.

So an extraction would not only touch this repo. It would also need compatibility shims or coordinated releases for
plugins and clients.

## Coupling Points

The strongest reason not to move everything at once is that the "xprompt logic" boundary is not clean today.

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
