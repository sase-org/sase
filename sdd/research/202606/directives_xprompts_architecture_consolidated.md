---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Directives and XPrompts Architecture Recommendation

## Question

Should SASE migrate `%` directives into xprompts so the two features become one merged functionality?

This analysis intentionally ignores migration cost and evaluates the question as if the architecture were being designed
from scratch. The current codebase is used only as evidence for domain shape, semantic boundaries, and likely failure
modes.

## Short Answer

Do not migrate directives into ordinary xprompts.

The right architecture is to merge the plumbing, not the namespace:

- keep `#` for prompt modules and workflows that expand into prompt content or workflow execution;
- keep `%` for reserved launch controls that configure, delay, name, hide, repeat, or fan out agent runs;
- keep `/` for skill invocation;
- compile all of them through one prompt-control substrate with typed effects, source spans, diagnostics, completion
  metadata, and a side-effect-free launch plan.

This gives SASE the real benefits behind the merge instinct: one parser model, one tooling surface, one explain trace,
and one backend source of truth. It does that without collapsing a useful control-plane / data-plane distinction into a
single ambiguous token type.

## Verified Current Shape

### Directives are runner controls

Directives are `%` tokens that modify runner behavior and are stripped from the prompt before the model receives it.
The core runtime set in `src/sase/xprompt/_directive_types.py` is a closed vocabulary:

- `approve`, `edit`, `epic`, `hide`, `model`, `name`, `group`, `repeat`, `time`, `wait`;
- aliases such as `%m`, `%n`, `%w`, `%r`, `%g`.

Those controls do not return text. They populate `PromptDirectives` and feed runner behavior: model routing, agent
identity, wait dependencies, hidden/autonomous/edit modes, group metadata, repeat count, and deferred start timing.

Some directive-like controls live outside that exact runtime set:

- `%alt` / `%(...)` are launch fan-out transforms owned by `src/sase/xprompt/_directive_alt.py`.
- `%xprompts_enabled:false/true` is a parser-control marker for disabled regions.

That split is itself evidence that the domain is broader than "one directive dataclass." SASE has at least three `%`
effect classes today: launch metadata, launch topology, and parser behavior.

Several directives require bespoke engine logic that ordinary data-defined xprompts cannot express by themselves:

- bare `%name` allocates an auto-name;
- `%name:foo-@` and `%wait:foo-@` use name-template planning;
- bare `%wait` resolves against agent history;
- `%time` parses durations and absolute wall-clock targets;
- `%repeat` creates serial launch slots chained by `%wait`;
- `%model(a,b)` is treated as a model fan-out axis;
- `%alt(a,b)` computes a Cartesian product of prompt variants.

These are not prompt snippets. They are operations against launch planning, scheduling, state snapshots, and persistent
agent metadata.

### XPrompts are open prompt and workflow modules

Xprompts are `#` references backed by data: markdown files, config entries, plugin resources, built-ins, and local
frontmatter definitions. They are user and plugin extensible without engine changes.

The core xprompt model has a typed input system (`word`, `line`, `text`, `path`, `int`, `bool`, `float`) and a content
body rendered into prompt text. Workflow xprompts extend this into multi-step automation with `agent`, `bash`, `python`,
`prompt_part`, loops, conditions, parallel steps, hidden steps, environment values, and workflow-local xprompts.

That extensibility is the point of xprompts. A project-local or user-local `#review` can override or augment prompt
composition safely because its normal output is text or workflow behavior, not privileged runner configuration.

### They already interact

The current preprocessing order intentionally lets xprompts emit directives:

1. render workflow/Jinja context where applicable;
2. canonicalize project aliases;
3. expand `#` xprompt references;
4. extract `%` directives from the expanded prompt.

`xprompts/reads.md` is a concrete example. It defines several research agents using `%name`, `%model`, `%group`, and
`%wait` inside a reusable xprompt. The final agent then consumes `wait_chats` from those `%wait` dependencies.

The TUI launch path also expands xprompts early when it needs to discover launch fan-out. A raw prompt can contain
`%alt`, and an xprompt can inject `%model(...)`; both must participate in the same planned Cartesian fan-out before
agents are spawned. The Python fan-out path already calls a Rust-backed facade,
`sase.core.agent_launch_facade.plan_agent_launch_fanout`, and the wire type is a normalized `LaunchFanoutPlanWire`.

The completion UI has also moved toward a shared substrate. `_try_auto_prompt_reference_completion()` dispatches `%`,
`#`, `/`, and VCS-project triggers through one menu-opening path while still using kind-specific candidate builders.
That is the right direction: shared presentation and token infrastructure, distinct semantics.

## What "Merge Directives Into XPrompts" Could Mean

The proposal bundles three different architectural moves. They should be judged separately.

### 1. Literal semantic merge: a directive becomes an xprompt

Example surface: `%model:opus` becomes `#model(opus)`, `%wait:build` becomes `#wait(build)`, and `%repeat:3` becomes
`#repeat(3)`.

This is the wrong cut. It makes `#` mean both "insert prompt content" and "mutate launch state." It also puts
privileged runner operations into a namespace that is intentionally overrideable by projects, users, configs, and
plugins.

If `#model` is ordinary data, the scheduler cannot honor it without new engine code. If `#model` is a privileged
built-in, then it is not really an ordinary xprompt. The design has merely hidden the directive registry under a new
sigil while losing the readable type signal that `%` currently provides.

### 2. Shared substrate: directives are reserved xprompt-like controls

This is a good idea. Directives and xprompts should share:

- tokenization and protected-region handling;
- argument parsing where possible;
- source spans and source maps;
- completion, hover, diagnostics, and documentation metadata;
- trace/explain output;
- tests and golden cases for cross-frontend parity.

The key constraint is that reserved launch controls must not be resolved through the ordinary xprompt discovery and
override chain. They need a control registry, typed schemas, capability boundaries, and phase restrictions.

### 3. Unified orchestration IR: directives and workflows lower to one launch plan

This is the strongest long-term architecture. The deep overlap is not between directives and text xprompts. It is
between inline orchestration directives and workflow orchestration:

- `%wait` is a dependency edge;
- `%time` is a scheduling constraint;
- `%repeat` is serial launch topology;
- `%alt` and `%model(a,b)` are fan-out axes;
- `%name`, `%model`, `%group`, `%hide`, `%approve`, and `%edit` are per-agent attributes.

Workflow files express richer versions of the same domain: ordered steps, agent steps, loops, parallelism, hidden
steps, conditions, and environment. From scratch, both inline syntax and workflow files should lower into a shared
agent-spec or launch-plan IR.

## Architectural Trade-offs

### Why a literal merge is harmful

**Control/data boundary.** A directive configures the run and is stripped. An xprompt normally contributes content or a
workflow that the system executes. Those are different value types, and the distinction is useful to both readers and
tools.

**Closed/open boundary.** Directives are closed because the engine must know how to honor each one. Xprompts are open
because users can add prompt modules without modifying the engine. Treating them as one category either makes runner
controls unsafe to override or makes "custom directives" illusory.

**Evaluation timing.** Some controls must be known before launch side effects:

- `%wait` and `%time` can defer workspace claims;
- `%name` affects collision checks, derived names, and dependent waits;
- `%alt`, `%model(...)`, and `%repeat` decide how many agents exist;
- `%edit` can change whether the prompt launches at all.

If any arbitrary xprompt can secretly mutate launch shape, the launcher must expand more of the prompt earlier and
loses a clean boundary between pure discovery, validation, planning, and execution.

**Trust and capability boundaries.** Prompt modules are commonly project-local, user-local, or plugin-provided.
Launch controls can consume resources, change scheduling, hide agents, force autonomous behavior, or request name
reuse. Those effects need explicit capability rules, not accidental shadowing by a file named `model.md` or `wait.yml`.

**Explainability.** SASE should be able to show which modules contributed text, which controls changed metadata, which
controls created more launch slots, and which controls were injected by a reusable xprompt. A typed IR makes this
straightforward. A literal merge disguises control effects as text substitution.

### Why a shared substrate is beneficial

SASE has many launch and authoring surfaces: CLI, TUI, workflow executor, prompt history, editor/LSP support, mobile
helpers, and plugin-provided prompts. They all need the same answer to:

- where does a token begin and end;
- is this token protected by a fenced block or disabled region;
- what arguments does it accept;
- is it valid in this phase;
- what did it expand into;
- what launch effects did it emit;
- which final prompt text did each agent receive.

Keeping separate scanners and catalogs guarantees drift. Current Python code already has separate paths for ordinary
directive extraction, `%alt` planning, disabled-region parsing, directive completion, and xprompt completion. The
architecture should consolidate those into one compiler/registry while preserving typed entry kinds.

### Why orchestration should converge with workflows

The real duplication is not `%model` versus `#model`. It is inline launch topology versus workflow topology.

Inline controls are terse and excellent for ad hoc launches:

```text
%name:review
%model(opus,sonnet)
%wait:build
Review the migration.
```

Workflow files are better for named, reusable, multi-step automation. Both should lower to the same launch-plan concepts:
slots, dependencies, model targets, names, hidden/autonomous modes, prompt parts, step attributes, and source maps.

That gives SASE one place to reason about agent graphs while keeping two ergonomic surfaces: compact inline controls
and expressive workflow files.

## From-Scratch Design

Model the system as a prompt compiler that produces a side-effect-free launch plan.

Core concepts:

| Concept | Role |
| --- | --- |
| `PromptDocument` | Parsed user-authored text, frontmatter, segments, protected regions, and source spans |
| `PromptModule` | Data-defined `#` module or workflow resolved from local, project, user, plugin, or built-in sources |
| `LaunchControl` | Reserved operation that mutates runner metadata, scheduling, identity, or mode |
| `LaunchTransform` | Reserved operation that changes launch cardinality or topology |
| `CompiledPrompt` | Pure compiler output: text candidates, effect nodes, diagnostics, source maps, unresolved dynamic refs |
| `LaunchPlan` | Resolved slots, names, dependencies, models, workspace policy, metadata, env deltas, and prompt text |

Compiler pipeline:

1. Parse prompt text, YAML frontmatter, segment separators, fenced blocks, and disabled regions.
2. Resolve aliases and project references that must be canonical before lookup.
3. Resolve pure prompt modules and local helper modules.
4. Collect launch controls and launch transforms as structured effect nodes.
5. Validate schemas, allowed phases, trust/capability rules, and conflicts.
6. Produce a side-effect-free compiled prompt and fan-out plan.
7. Resolve dynamic references against an agent-state snapshot.
8. Claim names/workspaces and spawn agents only after validation and planning succeed.
9. Render final prompt text and an explain trace for each slot.

Effect classes should be explicit:

| Effect | Examples | Meaning |
| --- | --- | --- |
| `text` | `#coder`, local `#_helper` | expands into prompt text |
| `workflow_embed` | `#gh:sase` | attaches workflow behavior around a prompt part |
| `workflow_standalone` | `#!sync` | dispatches a workflow |
| `metadata` | `%model`, `%group`, `%hide` | changes agent metadata |
| `dependency` | `%wait`, `%time` | changes scheduling or workspace policy |
| `identity` | `%name` | requests or derives agent identity |
| `fanout` | `%alt`, `%model(a,b)`, `%repeat` | changes launch slots |
| `mode` | `%approve`, `%edit`, `%epic` | changes launch or follow-up mode |
| `parser_control` | `%xprompts_enabled:false` | changes parsing only |

Registry shape:

```text
prompt_modules:
  coder
  reads
  project-local helpers

workflows:
  gh
  sync
  user/plugin workflows

launch_controls:
  model
  name
  wait
  time
  hide
  approve
  edit
  epic
  group

launch_transforms:
  alt
  model_fanout
  repeat
  segment_fanout

parser_controls:
  xprompts_enabled
```

Project/user/plugin sources can freely extend `prompt_modules` and normal workflows. Launch controls and transforms
should be reserved to trusted core code, or to explicit plugin capability APIs if SASE ever wants third-party runner
extensions.

## Conflict Resolution From Prior Reports

Both prior reports reached the same architectural conclusion: reject a literal semantic merge; unify the compiler,
tooling, and launch-planning substrate.

The useful nuance to preserve is that not every `%` feature is represented in the same Python structure today. `%alt`
is user-facing and documented, but is planned by the fan-out path rather than stored in `_KNOWN_DIRECTIVES`.
`%xprompts_enabled` is a parser-control marker. A final architecture should not simply move `_KNOWN_DIRECTIVES` into
another table; it should model the different effect classes explicitly.

The prior reports also cited Rust-core editor and launch modules as already treating prompt references as sibling token
kinds and launch fan-out as a core planning concern. In this checkout, the sibling Rust source tree is not populated, so
the exact Rust file-level claims should be re-verified before implementation. The current Python facade and project
memory still support the same architectural direction: cross-frontend parsing and launch planning belong behind a core
backend API, not duplicated in every UI or runner edge.

## Recommended Solution

Do not migrate directives into the xprompt vocabulary.

Instead, implement a shared prompt compiler and launch-plan IR:

1. Keep `#` for prompt modules and workflows.
2. Keep `%` for reserved launch controls and launch transforms.
3. Keep `/` for skills.
4. Add or formalize `launch:` frontmatter as the structured long-form equivalent of inline `%` controls.
5. Put tokenization, argument parsing, protected-region handling, schemas, source spans, diagnostics, completion, hover,
   and explain traces behind one compiler/registry API.
6. Lower inline directives, multi-prompt separators, and workflow constructs into one launch-plan IR.
7. Allow xprompts to emit launch controls, but represent those controls as structured effect nodes rather than raw text
   that later regex passes happen to rediscover.
8. Keep launch-control extension behind an explicit trusted capability boundary, not ordinary xprompt name resolution.

Decision rule for new capabilities:

- If it is honored by the orchestrator, has closed engine-known meaning, and is stripped before the model sees the
  prompt, make it a directive or launch-control effect.
- If it is reusable prompt content, model-facing context, or a data-defined helper users/plugins can author safely, make
  it an xprompt.
- If it is a multi-step pipeline with control flow, non-prompt steps, or reusable agent automation, make it a workflow
  xprompt that lowers to the same orchestration IR.

The final architecture is therefore: merge the architecture, not the namespace. Directives should become first-class
launch-control nodes in the same compiler that resolves xprompts; they should not become ordinary xprompts.
