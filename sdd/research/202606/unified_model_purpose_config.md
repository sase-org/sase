---
create_time: 2026-06-17
status: research
---

# Unified Model Purpose Config Research

## Question

How should SASE merge the existing worker-model configuration with default-model configuration, while also allowing users
to configure the model used to:

- land epics;
- create epics;
- implement approved plans;
- implement phases of an epic?

The requested split matters because the current `llm_provider.worker_models` field covers more than one launch purpose.
It currently affects plan-implementation handoffs and epic phase agents, and the code also routes epic/legend creation
follow-ups through the same worker resolver.

## Executive Summary

The best implementation is a new unified purpose-based model routing field under `llm_provider`, tentatively
`llm_provider.models`. It should contain a `default` route plus named routes for `create_epic`, `implement_plan`,
`implement_phase`, and `land_epic` (likely also `create_legend` / `land_legend` aliases or shared semantics, because the
current code handles legend work beside epic work).

The important design choice is to preserve the current lane-sensitive `worker_models` behavior. A plain
`coder_model: codex/gpt-5.5` style config would be simpler, but it would lose the current ability to say "when the
planner/default lane is Claude, use Codex for implementation; when the planner/default lane is Codex, use Claude for
implementation." That context-sensitive routing was added deliberately and is covered by tests.

Recommended shape:

```yaml
llm_provider:
  models:
    default:
      large: claude/opus
      small: claude/sonnet

    create_epic:
      by_primary:
        claude: codex/gpt-5.5
        codex: claude/opus
      fallback: implement_plan

    implement_plan:
      by_primary:
        claude: codex/gpt-5.5
        codex: claude/opus
      fallback: primary

    implement_phase:
      by_primary:
        claude: codex/gpt-5.5
        codex: claude/opus
      fallback: primary

    land_epic:
      model: default
```

Support shorthand strings where they are unambiguous:

```yaml
llm_provider:
  models:
    default: claude/opus
    land_epic: claude/opus
    implement_plan: codex/gpt-5.5
    implement_phase:
      by_primary:
        claude: codex/gpt-5.5
```

## Current Behavior

### Default model routing

Default provider/model routing lives in the LLM provider layer:

- `src/sase/llm_provider/registry.py` chooses the provider from active temporary override, `llm_provider.provider`, or
  autodetection.
- `src/sase/llm_provider/temporary_override.py::resolve_effective_default_provider_model()` returns an active primary
  override if present, otherwise asks the selected provider for `resolve_model_name(model_tier)`.
- Built-in providers currently hard-code tier maps, for example `claude` maps `large -> opus` and `small -> sonnet`,
  while `codex` maps `large -> gpt-5.5`.

The docs and schema advertise `llm_provider.model_tier_map.large` / `.small`, but in this workspace `rg
"model_tier_map"` only finds docs, schema, and research. The built-in providers do not read it. If that is the "default
model" field being referenced, the new work should either implement it as a legacy source or replace it explicitly with
`llm_provider.models.default`.

### Worker model routing

`llm_provider.worker_models` is parsed in `src/sase/llm_provider/config.py`.

Current key precedence for a supplied primary lane is:

1. exact `provider/model`, for example `claude/opus`;
2. bare model, for example `opus`;
3. provider, for example `claude`.

The resolver is `resolve_worker_provider_model_for_primary(primary_provider, primary_model)` in
`src/sase/llm_provider/temporary_override.py`. Its precedence is:

1. active worker temporary override;
2. matching `llm_provider.worker_models` entry;
3. supplied primary provider/model.

`resolve_effective_worker_provider_model()` first resolves the current effective default/primary lane, then calls the
contextual worker resolver. The reserved model alias `worker` in `src/sase/llm_provider/config.py` resolves through that
effective worker lane.

### Approved plan implementation

Plan approval follow-up model selection lives in `src/sase/axe/run_agent_exec_plan_accept.py`.

`_resolve_followup_model()` currently:

1. honors explicit approval `coder_model`, except literal `worker`;
2. otherwise resolves the worker lane from the planner agent's concrete provider/model using
   `resolve_worker_provider_model_for_primary()`;
3. emits a concrete `%model:<provider>/<model>` prefix when planner provider/model metadata is present;
4. falls back to `%model:worker` only when planner metadata is incomplete.

This contextual freezing was added to avoid drift when global model overrides change after the planner runs but before
the follow-up starts. Tests in `tests/test_axe_run_agent_exec_plan_followup_model_selection.py` cover this behavior for
`approve`, `epic`, and `legend`.

### Epic and legend creation

The same `_resolve_followup_model()` path is used when plan approval action is `epic` or `legend`. That means
`bd/new_epic` and `bd/new_legend` follow-up agents currently use the worker lane by default, even though conceptually
they are "create epic/legend" agents rather than ordinary coders.

This is a mismatch with the simplified mental model that `worker_models` only covers approved-plan coders and phase
agents. The implementation has already expanded it to epic/legend creation follow-ups.

### Epic phases and landing

`src/sase/bead/work.py::render_multi_prompt()` renders executable epic work:

- phase segment with bead `model`: emits `%model:<assignment.model>`;
- phase segment without bead `model`: emits `%model:worker`;
- land segment with epic plan-bead `model`: emits `%model:<plan.land_model>`;
- land segment without epic plan-bead `model`: emits no `%model` directive, so it uses the primary/default lane.

`render_legend_multi_prompt()` similarly keeps intermediate epic-planning segments on the primary/default lane and only
emits `%model:<plan.land_model>` for the final `bd/land_legend` segment when the legend bead has a stored model.

The built-in `bd/new_epic` / `bd/new_legend` xprompts in `src/sase/default_config.yml` already tell agents to propagate
top-level plan frontmatter `model:` into the epic/legend plan bead, and per-phase `model:` into phase beads.

## Requirements And Constraints

- Explicit user intent must still win:
  - `%model` directives;
  - approval dialog/CLI `coder_model`;
  - bead `model` fields for phase and land agents;
  - plan frontmatter propagated into bead `model`.
- Current `worker_models` context sensitivity should be preserved unless deliberately removed.
- Plan follow-up defaults should still resolve from the planner's concrete provider/model, not from whatever the global
  default happens to be later.
- Leaving new fields unset should preserve current behavior.
- The new config should have a clean schema and not require separate per-purpose field names forever.
- Temporary primary and worker overrides need an explicit compatibility story. Current worker override affects plan
  follow-ups and phases; the new purpose split should not silently break that.
- The current `model_tier_map` documentation/code gap should be resolved as part of the migration.

## Alternative 1: Add Separate Fields For Each Purpose

Example:

```yaml
llm_provider:
  default_model: claude/opus
  create_epic_model: codex/gpt-5.5
  implement_plan_model: codex/gpt-5.5
  implement_phase_model: codex/gpt-5.5
  land_epic_model: claude/opus
```

Pros:

- Very easy to explain.
- Straightforward schema and parser.
- Direct mapping from user request to config keys.

Cons:

- Does not preserve the current `worker_models` by-primary mapping unless each field grows a parallel
  `*_models` mapping.
- Adds a new top-level field for every future purpose.
- Does not compose well with large/small tiers.
- Does not "merge" the existing model configuration into a coherent model-routing system; it just adds more fields.

This is only attractive if SASE is willing to abandon context-sensitive worker routing. I do not recommend that.

## Alternative 2: Generalize `worker_models` Into Nested Purpose Maps

Example:

```yaml
llm_provider:
  default_model: claude/opus
  worker_models:
    create_epic:
      claude: codex/gpt-5.5
    implement_plan:
      claude: codex/gpt-5.5
    implement_phase:
      claude: codex/gpt-5.5
    land_epic:
      claude: claude/opus
```

Pros:

- Minimal conceptual change from today's `worker_models`.
- Preserves by-primary lookup semantics.
- Existing resolver can evolve into `resolve_worker_model_for_purpose()`.

Cons:

- The name `worker_models` is wrong for `default` and `land_epic`.
- It does not actually merge the default model field.
- It keeps "worker" as the central concept even after splitting worker scope.
- It is awkward for fixed purpose targets such as "always use Claude Opus to land epics."

This is a plausible incremental migration, but it bakes in the wrong name.

## Alternative 3: Unified Purpose Routes Under `llm_provider.models`

Example:

```yaml
llm_provider:
  models:
    default:
      large: claude/opus
      small: claude/sonnet
    create_epic:
      by_primary:
        claude: codex/gpt-5.5
      fallback: implement_plan
    implement_plan:
      by_primary:
        claude: codex/gpt-5.5
        codex: claude/opus
      fallback: primary
    implement_phase:
      by_primary:
        claude: codex/gpt-5.5
      fallback: primary
    land_epic:
      model: default
```

Route grammar:

- A route may be a string target, for example `land_epic: claude/opus`.
- A route may define `model: <target>` for a fixed target.
- A route may define `large` / `small` for tiered default behavior.
- A route may define `by_primary` with the current exact `provider/model`, bare model, provider key precedence.
- A route may define `fallback`, with reserved values:
  - `primary`: supplied contextual provider/model, or current default lane for non-contextual launches;
  - `default`: resolved `models.default`;
  - another purpose name, for example `implement_plan`;
  - an explicit model target, for example `claude/opus`.

Pros:

- One field holds default and purpose-specific models.
- Preserves current `worker_models` behavior where it matters.
- Lets SASE split `implement_plan` and `implement_phase` without losing the mapping feature.
- Gives future purposes a natural home.
- Can preserve tier semantics through `models.default.large` / `.small`.
- Makes current behavior easy to document in one table.

Cons:

- More parser/resolver code than scalar fields.
- Needs cycle detection for fallback chains.
- Needs careful naming of "primary" versus "default" so planner-context fallback remains understandable.
- Requires new reserved aliases if prompts should use purpose names directly.

This is the best long-term shape.

## Alternative 4: Profiles Plus Purpose Assignments

Example:

```yaml
llm_provider:
  models:
    profiles:
      default:
        large: claude/opus
        small: claude/sonnet
      worker:
        by_primary:
          claude: codex/gpt-5.5
          codex: claude/opus
      finisher:
        model: claude/opus
    purposes:
      create_epic: worker
      implement_plan: worker
      implement_phase: worker
      land_epic: finisher
```

Pros:

- Avoids duplicating the same mapping under `implement_plan` and `implement_phase`.
- Makes it easy to name reusable profiles like `worker`, `cheap`, `finisher`, or `review`.
- Clean separation between "what models exist" and "what purpose uses what."

Cons:

- More indirection than SASE needs right now.
- Harder to explain in docs and UI.
- Users have to understand profiles before configuring one purpose.
- Migration from current `worker_models` is less direct.

This is attractive if SASE expects many more model purposes soon. For the current request, it is probably overbuilt.

## Alternative 5: Keep Global Config Small And Use Bead/Plan Metadata

Example:

- Use plan frontmatter `model:` for land agents.
- Use phase-level `model:` annotations for phase agents.
- Use approval-time model picker or `%model` directives for plan coders.
- Add a `model:` convention to epic-creation prompts.

Pros:

- Very little core config work.
- All overrides are attached to the work item that needs them.
- Existing bead model routing already supports much of this.

Cons:

- Does not solve default behavior.
- Requires repetitive annotation.
- Does not give users a single place to configure their preferred routing.
- Does not answer the request to merge config fields.

This remains useful as an explicit override layer, but it should not be the primary solution.

## Recommended Approach

Implement Alternative 3: a unified `llm_provider.models` purpose-routing field.

### Proposed Purpose Names

Start with these names:

| Purpose | Applies to | Current default behavior |
| --- | --- | --- |
| `default` | normal launches with no explicit `%model` | primary temporary override, configured provider, provider tier default |
| `create_epic` | plan approval action `epic`, `bd/new_epic` follow-up | worker resolver from planner context |
| `create_legend` | plan approval action `legend`, `bd/new_legend` follow-up | worker resolver from planner context |
| `implement_plan` | approved plan/tale coder follow-up | worker resolver from planner context |
| `implement_phase` | `sase bead work` phase agents without bead `model` | `%model:worker` effective worker lane |
| `land_epic` | `bd/land_epic` when epic bead has no `model` | no directive, primary/default lane |
| `land_legend` | `bd/land_legend` when legend bead has no `model` | no directive, primary/default lane |

The user request only names epic creation/landing, but the code has parallel legend paths. Either include the legend
purposes immediately or make them aliases of the epic purposes so behavior stays coherent.

### Resolver Design

Add a public resolver in the LLM provider layer:

```python
ModelPurpose = Literal[
    "default",
    "create_epic",
    "create_legend",
    "implement_plan",
    "implement_phase",
    "land_epic",
    "land_legend",
]

def resolve_model_for_purpose(
    purpose: ModelPurpose,
    *,
    primary_provider: str | None = None,
    primary_model: str | None = None,
    model_tier: ModelTier = "large",
) -> ModelPurposeResolution:
    ...
```

`ModelPurposeResolution` should include provider, model, source, purpose, matched key, configured target, and the
contextual primary provider/model used for lookup. That mirrors the useful `WorkerModelResolution` metadata already
used by UI/tests.

Default precedence:

1. explicit launch model (`%model`, approval picker, bead `model`) - handled by callers before purpose resolution;
2. active temporary override:
   - primary override for `default`;
   - existing worker override for `create_epic`, `create_legend`, `implement_plan`, and `implement_phase` during
     migration;
3. configured `llm_provider.models.<purpose>`;
4. legacy compatibility source:
   - `model_tier_map` for `default`, if present;
   - `worker_models` for `create_epic`, `create_legend`, `implement_plan`, and `implement_phase`;
5. configured fallback for the purpose;
6. built-in fallback:
   - `primary` for `implement_plan` / `implement_phase` to preserve current behavior;
   - `implement_plan` for create-epic/create-legend if preserving current worker behavior;
   - `default` for land-epic/land-legend.

Use existing `resolve_model_provider()` to interpret configured targets, so explicit provider/model syntax, known bare
models, aliases, and nested provider-local model paths keep working.

### Call-Site Changes

- `src/sase/llm_provider/temporary_override.py`
  - Keep `resolve_effective_default_provider_model()` as a wrapper around `resolve_model_for_purpose("default")`.
  - Keep `resolve_worker_provider_model_for_primary()` as a compatibility wrapper around either
    `implement_plan` or a shared legacy worker route while callers are migrated.

- `src/sase/llm_provider/_invoke.py`
  - When there is no explicit model override and no explicit provider, resolve `default` through the new resolver.
  - This is where `models.default` should become real behavior, replacing the current docs-only `model_tier_map`
    promise.

- `src/sase/axe/run_agent_exec_plan_accept.py`
  - For `approve` / `tale`, resolve `implement_plan` from the planner context.
  - For `epic`, resolve `create_epic` from the planner context.
  - For `legend`, resolve `create_legend` from the planner context.
  - Continue emitting concrete `%model:<provider>/<model>` prefixes when planner context exists.
  - Keep custom coder prompt `%model` precedence unchanged.

- `src/sase/bead/work.py`
  - Phase bead `model` still wins.
  - Empty phase bead `model` should use a purpose-specific alias or resolver for `implement_phase` rather than the
    generic `worker` alias.
  - Land bead `model` still wins.
  - When `land_epic` / `land_legend` is configured to a non-default target, emit a model directive for the land segment.
    If the route is missing or equivalent to `default`, keep no directive to avoid unnecessary prompt churn.

- `src/sase/llm_provider/config.py`
  - Keep `%model:worker` as a deprecated compatibility alias.
  - Add reserved purpose aliases only if needed for rendered prompts, for example `%model:implement_phase`.
  - Guard against self-referential aliases and fallback cycles.

- TUI
  - The current Model Overrides modal can initially continue to show primary/default and legacy worker override lanes.
  - Later UI can display purpose resolutions if needed, but the first implementation does not need a modal row for every
    purpose.

### Migration Plan

1. Add `llm_provider.models` support while still accepting current fields.
2. Treat `llm_provider.model_tier_map` as legacy input for `models.default.large` / `.small`.
3. Treat `llm_provider.worker_models` as legacy input for:
   - `models.implement_plan.by_primary`;
   - `models.implement_phase.by_primary`;
   - and, for strict backward compatibility with current code, `models.create_epic.by_primary` and
     `models.create_legend.by_primary`.
4. Update docs to mark `worker_models` and `model_tier_map` deprecated in favor of `models`.
5. Keep schema accepting old fields for one release if backward compatibility matters. If SASE wants hard cleanup
   instead, update the schema to reject old fields only after Bryan's config and docs have been migrated.
6. Keep `%model:worker` working as a compatibility alias, but stop emitting it from internal renderers once
   purpose-specific routing exists.

### Tests To Add

- Config parser:
  - valid shorthand string route;
  - valid `{large, small}` default route;
  - valid `{model: ...}` route;
  - valid `{by_primary: ..., fallback: ...}` route;
  - invalid/malformed entries ignored or schema-rejected according to existing config style.
- Resolver:
  - exact `provider/model` beats bare model and provider for each by-primary purpose;
  - fallback `primary` preserves planner context;
  - fallback `default` resolves configured default;
  - fallback purpose chains work;
  - fallback cycles do not crash launches;
  - active primary override affects `default`;
  - legacy worker override still affects compatibility worker-like purposes.
- Plan handoff:
  - approve/tale uses `implement_plan`;
  - epic uses `create_epic`;
  - legend uses `create_legend`;
  - explicit picker model still wins;
  - custom coder prompt `%model` still wins.
- Bead work rendering:
  - empty phase model uses `implement_phase`;
  - explicit phase bead model still wins;
  - land segment emits model only when bead model or configured land route requires it;
  - missing land route keeps current no-directive behavior.
- Schema/docs:
  - `llm_provider.models` examples validate;
  - migration examples for old `worker_models` and `model_tier_map` are documented.

## Final Recommendation

Use a single `llm_provider.models` field with purpose routes and by-primary mappings. Do not add separate scalar fields
for each purpose, and do not keep expanding the `worker_models` name.

This approach preserves the important behavior SASE already has, gives the user one place to configure all model
purposes, makes the requested split between approved-plan implementation and epic-phase implementation explicit, and
fixes the current gap where default-model configuration is documented but not actually consumed by built-in providers.
