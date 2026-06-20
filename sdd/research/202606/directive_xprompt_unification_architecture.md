---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Directive and XPrompt Unification Architecture Research

## Question

Should SASE migrate prompt directives into xprompts so that the two features become one merged functionality?

This analysis intentionally ignores migration cost. It evaluates the plan as if SASE were being designed from scratch,
using the current codebase only as evidence for domain shape, failure modes, and architectural pressure.

## Short Answer

Merging the *implementation substrate* is a good idea. Migrating directives into ordinary xprompts is not.

The clean architecture is a shared prompt compiler with one intermediate representation for:

- prompt text;
- reusable prompt templates;
- workflow references;
- launch annotations such as model, name, wait, time, group, hide, approve, edit, and epic;
- launch transforms such as alt, multi-model, repeat, and multi-agent fan-out.

Xprompts should remain user-extensible prompt modules. Directives should become reserved, typed launch-control
operations in the same compiler and catalog ecosystem, not normal `#name` templates that can be shadowed by project,
user, or plugin xprompt definitions.

## Current Architecture Signals

The current documented resolver already puts directives and xprompts in one pipeline:

```text
xprompt expansion inside a prompt or prompt_part:
  alias substitution
  -> fenced-block and disabled-region protection
  -> iterative reference expansion
  -> directive extraction at the launch or workflow-step boundary
```

That is the right high-level order for today's text-based implementation, but it also exposes the core architectural
truth: xprompt expansion can emit directives, and directives are then consumed by the launch system.

Current code confirms this relationship:

- `src/sase/llm_provider/preprocessing.py` renders Jinja context, expands `#name` xprompts, then extracts `%name`
  directives.
- `src/sase/axe/run_agent_directives.py` expands xprompts before extracting directives so xprompt-injected `%model`,
  `%wait`, and related controls affect agent metadata.
- `src/sase/xprompt/directives.py` parses launch-control directives and expands `#` references inside directive
  arguments.
- `src/sase/xprompt/_directive_alt.py` treats `%alt` and multi-model `%model(...)` as launch fan-out transforms rather
  than simple metadata.
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` expands xprompts early when needed to discover fan-out
  shape before spawning agents.
- `xprompts/reads.md` uses `%name`, `%model`, `%group`, and `%wait` inside a reusable multi-agent xprompt, which is a
  strong real-world example of xprompts emitting launch controls.
- The sibling Rust core has `crates/sase_core/src/agent_launch/mod.rs` for launch fan-out planning and
  `crates/sase_core/src/editor/directive.rs` for editor directive metadata, showing that this behavior already wants a
  shared backend owner.

There is also evidence of drift from keeping multiple directive registries: Python `_KNOWN_DIRECTIVES` no longer
includes the removed `%plan` directive, while the Rust editor directive table still lists `plan` and alias `%p`. That is
an architecture smell, independent of migration cost.

## What "Migrate Directives to XPrompts" Could Mean

### Meaning 1: Literal directive xprompts

Under this model, `%model:opus` might become `#model(opus)`, `%wait:build` might become `#wait(build)`, and `%repeat:3`
might become `#repeat(3)`.

This is the weakest design. Ordinary xprompts are discoverable, overrideable prompt text macros. Directives are
privileged launch controls. Treating them as the same thing creates the wrong capability boundary: a project-local
`#wait.md`, plugin-provided `#model.yml`, or user override could accidentally or intentionally alter runner semantics.

It also overloads `#` with two incompatible return types. Some `#` references would return text, some would mutate
launch metadata, and some would transform one launch into many launches. That makes explainability, validation, and
editor tooling harder unless the system immediately reinvents a typed operation registry underneath ordinary xprompts.

### Meaning 2: Built-in xprompt-like controls

Under this model, directives share xprompt argument parsing, completion, hover, diagnostics, and documentation, but
resolve through a reserved built-in control registry rather than the normal xprompt discovery order.

This is much better. It gives users one authoring grammar and one support surface while preserving a hard boundary
between prompt content and runner control. It also allows controls to have typed schemas, structured errors, and stable
metadata for every frontend.

The remaining issue is that it still describes the user-facing surface more than the architecture. The important
internal artifact is not "xprompt" or "directive"; it is a compiled launch plan.

### Meaning 3: Shared prompt compiler with typed IR

Under this model, both xprompt references and directives compile into a common prompt IR. A prompt module can emit text
nodes, local helper definitions, workflow references, launch annotations, and launch transforms. The compiler validates
and normalizes the full document before any irreversible side effects such as name claiming, workspace claiming, or
agent spawning.

This is the best architecture. It keeps the user model compositional while giving the system a typed boundary between
"text to send to the LLM" and "control metadata for the runner".

## Architectural Trade-offs

## Benefits of a Shared Substrate

### One canonical resolver order

SASE already has several launch surfaces: TUI, CLI, xprompt CLI, workflow executor, mobile helper paths, and editor/LSP
support. A shared compiler eliminates per-surface decisions about when to expand xprompts for fan-out, when to strip
directives, and when to preserve protected regions.

The compiler should expose one ordered pipeline:

1. Parse prompt document, frontmatter, protected regions, and segment separators.
2. Resolve aliases and project references that must be canonical before lookup.
3. Resolve pure prompt modules and local helpers.
4. Collect and validate launch-control operations.
5. Produce a side-effect-free launch plan.
6. Execute the plan, applying name/workspace claims only after validation.
7. Render the final prompt text for each slot.

### Better tooling parity

Directives and xprompts currently have parallel tooling surfaces: completions, diagnostics, docs, catalog entries, and
tests. A unified compiler registry can expose both as typed entries:

| Entry kind | Example | Output |
| --- | --- | --- |
| Prompt module | `#coder(plan.md)` | prompt text |
| Embeddable workflow | `#git:sase` | pre/post workflow plus prompt text |
| Standalone workflow | `#!sync` | workflow execution |
| Launch annotation | `%model:worker` | model metadata |
| Launch transform | `%alt(a,b)` | multiple launch slots |

This preserves conceptual differences while giving frontends one API for completion, hover, diagnostics, explain, and
catalog display.

### Cleaner xprompt-defined orchestration

Multi-agent xprompts already need launch controls. `xprompts/reads.md` is a good example: it defines three named,
model-specific research agents and a final waited consolidation agent. In a compiler architecture, that xprompt would
not "expand to some text that later regexes happen to parse"; it would expand to a structured set of prompt segments
with launch annotations.

That is more robust because the compiler can validate names, waits, model aliases, and fan-out relationships before
spawning anything.

### More explicit side-effect boundaries

Directive parsing currently knows about dynamic state in places: bare `%name` asks for the next auto-name, bare `%wait`
asks for the most recent named agent, name templates resolve against existing agent state, and wait-derived names may be
allocated. A from-scratch compiler should make that explicit:

- compile phase: produce requested controls and unresolved symbolic references;
- planning phase: resolve dynamic references against an agent-state snapshot;
- execution phase: claim names/workspaces and spawn agents.

This keeps prompt expansion deterministic and testable while still supporting dynamic launch behavior.

### Easier cross-frontend consistency

Project memory says shared backend behavior belongs in Rust core when multiple frontends need parity. Prompt control
parsing clearly qualifies: CLI, TUI, editor, mobile, and workflow execution all need the same semantics. A core compiler
or core registry would prevent drift such as the current Python/Rust `%plan` mismatch.

## Risks of Literal Merger

### Loss of a privilege boundary

Xprompt definitions are intentionally overrideable through project directories, home directories, config, plugins, and
built-ins. That is a feature for prompt text. It is dangerous for runner controls.

Controls such as model selection, force name reuse, wait dependencies, hidden agents, autonomous approval, repeat
fan-out, and workspace-deferred launches are not ordinary prompt fragments. They affect resources, scheduling,
metadata, UI state, and sometimes trust boundaries. They need a reserved namespace and explicit capability model.

### Ambiguous evaluation timing

Some controls must be known before full launch:

- `%wait` and `%time` determine whether a workspace claim should be deferred.
- `%alt` and multi-model `%model(...)` determine how many agents to spawn.
- `%repeat` determines serial slot creation and wait chaining.
- `%name` affects validation, collision checks, family grouping, and dependent waits.

If these become ordinary xprompts, the launcher must expand enough xprompts to discover them before planning. That is
already happening in selected places today, but a literal merger would make the ambiguity worse: any prompt macro could
secretly be a launch transform.

The compiler should instead make effect types explicit. A prompt module that can emit launch controls should be marked
as such in metadata, and the compiler should collect its effects as structured nodes.

### Mixed return types in one namespace

An ordinary xprompt returns text. A workflow reference can execute steps and return a prompt part. `%alt` returns a
Cartesian product of prompt variants. `%repeat` returns a serial launch plan. `%wait` returns no text but changes
scheduling. `%model` may be scalar metadata or a fan-out axis.

Those are fundamentally different return types. Forcing them all into "xprompt expansion" hides the most important
domain distinctions. A typed IR can unify them without flattening them.

### Harder explainability

SASE needs good `explain`, trace, catalog, and history behavior. Users should be able to see:

- which xprompts contributed text;
- which controls changed launch metadata;
- which controls created additional slots;
- which controls were stripped from the final prompt;
- which controls were injected by a reusable prompt module.

A literal xprompt migration makes this harder because control effects are disguised as text substitution. A compiler
trace can make it straightforward.

### Security and trust confusion

Some xprompt workflows can run Python or bash steps. Directive parsing should not require executing arbitrary workflow
code just to decide whether a launch is hidden, delayed, named, repeated, or multi-model. The control-discovery pass
must be pure and bounded. Executable workflow steps belong later in the workflow execution phase.

## From-Scratch Design

If SASE were built from scratch, I would model this as a prompt module compiler.

### Core concepts

`PromptDocument`
: The parsed user-authored document, including frontmatter, body segments, protected regions, and source spans.

`PromptModule`
: A reusable definition resolved by `#name`, local frontmatter helpers, project-local xprompts, plugin xprompts, or
built-ins. It may emit prompt text and, if explicitly allowed, launch-control nodes.

`LaunchControl`
: A typed, reserved operation that affects runner behavior. Examples: `model`, `name`, `wait`, `time`, `hide`,
`approve`, `edit`, `epic`, `group`.

`LaunchTransform`
: A typed operation that changes launch cardinality or topology. Examples: `alt`, multi-model fan-out, repeat,
multi-agent segment fan-out.

`CompiledPrompt`
: Side-effect-free output containing final text candidates, controls, diagnostics, source maps, and unresolved dynamic
references.

`LaunchPlan`
: Resolved plan containing slots, names, dependencies, workspace policy, model/provider targets, metadata, local
xprompt payloads, timestamps, and execution environment deltas.

### Recommended authoring surface

Keep two user-visible syntaxes because they communicate different effects:

- `#name(...)` means "insert or execute a prompt module/workflow".
- `%name(...)` or `%name:...` means "apply a launch control".

Then make both syntaxes compile through the same registry and IR. The distinction is semantic, not an implementation
split.

For larger prompts, support structured frontmatter as the canonical long-form representation:

```yaml
---
launch:
  name: review
  model: worker
  wait: [build]
  group: review
xprompts:
  _rules: "Check error handling and rollback behavior."
---
#_rules
Review the auth migration.
```

Inline `%` directives then become ergonomic sugar for the same `launch:` controls. Xprompt files and multi-agent
segments can use either form, and the compiler normalizes both into the same `LaunchControl` nodes.

### Registry shape

Use separate namespaces under one registry:

```text
prompt_modules:
  coder
  git
  reads

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
```

The registry should expose typed metadata for all entries: name, aliases, argument schema, allowed phases, whether it
can be emitted from a prompt module, whether it affects launch shape, and whether it requires dynamic state resolution.

Project/user/plugin xprompts can extend `prompt_modules`. Only trusted core or explicit plugin capabilities should
extend `launch_controls` and `launch_transforms`.

### Effect typing

Every operation should declare one of these effect classes:

| Effect | Examples | Compile-time behavior |
| --- | --- | --- |
| `text` | `#coder`, `#_helper` | expands into prompt text |
| `workflow_embed` | `#git:sase` | records pre/post workflow plus prompt part |
| `workflow_standalone` | `#!sync` | dispatches workflow |
| `metadata` | `%model`, `%group`, `%hide` | adds launch metadata |
| `dependency` | `%wait`, `%time` | changes scheduling and workspace policy |
| `identity` | `%name` | requests or derives agent identity |
| `fanout` | `%alt`, `%model(a,b)`, `%repeat` | changes launch slots |
| `mode` | `%approve`, `%edit`, `%epic` | changes launch or follow-up mode |
| `protection` | `%xprompts_enabled:false` | changes parser behavior only |

This is where "merged functionality" should happen. The compiler can handle all effects in one pass without pretending
they are the same kind of object.

## Assessment of Options

### Option A: Keep directives and xprompts fully separate

This is simple conceptually but misses the real architecture pressure. Xprompts already emit directives, directives
already expand xprompt arguments, and fan-out planning already needs partial xprompt expansion. Keeping two unrelated
systems guarantees more duplicated parser and tooling work.

Verdict: acceptable only for a small product. Not the best SASE architecture.

### Option B: Replace directives with ordinary xprompts

This gives a superficial merge but weakens the system model. It mixes trusted controls with overrideable prompt text,
creates ambiguous return types, and makes launch-shape discovery depend on arbitrary template expansion.

Verdict: not recommended.

### Option C: Make directives reserved xprompt-like built-ins

This is a good intermediate architecture. Directives would share argument parsing, schema metadata, completion, hover,
diagnostics, and explain output with xprompts. The system would still reserve control names and prevent project-local
prompt modules from shadowing runner behavior.

Verdict: good, but incomplete unless backed by a real prompt IR and launch planner.

### Option D: Build a shared prompt compiler and launch-control IR

This is the strongest architecture. Xprompts and directives become two authoring syntaxes over one compiler substrate.
The compiler emits structured text, workflow, metadata, dependency, and fan-out nodes. Frontends consume one core API.
Side effects happen only after planning and validation.

Verdict: recommended.

## Recommended Solution

Do not migrate directives into ordinary xprompts. Instead, merge the systems one layer lower by building a shared prompt
compiler with a typed launch-control IR.

The target architecture should be:

1. Keep `#` for prompt modules and workflows.
2. Keep `%` for launch controls as a clear, compact authoring signal.
3. Add or formalize `launch:` frontmatter as the structured long-form equivalent of inline `%` controls.
4. Put prompt-module expansion, directive parsing, protected-region handling, fan-out planning, and directive metadata
   behind one core registry/compiler API.
5. Treat directives as reserved built-in control operations with typed schemas, aliases, source spans, diagnostics, and
   explain traces.
6. Allow xprompts to emit launch controls, but represent those controls as structured compiler nodes rather than as raw
   text that a later regex happens to discover.
7. Let trusted plugins extend launch controls only through an explicit control-extension API, not by defining ordinary
   xprompts with special names.

In short: merge the architecture, not the namespace. Xprompts should remain the reusable prompt composition mechanism;
directives should become first-class launch-control nodes in the same compiler. That gives SASE one mental model, one
tooling surface, and one backend source of truth without sacrificing the privilege boundary and timing guarantees that
runner controls need.
