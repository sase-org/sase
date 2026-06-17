---
create_time: 2026-06-17
updated_time: 2026-06-17
status: research
---

# Consolidated Research: Unified Model Purpose Config

## Question

SASE currently has `llm_provider.worker_models`, which controls the worker lane used by delegated implementation work,
and a separate default model/provider surface. The desired change is to merge those concepts and let users configure
which model is used to:

- land epics;
- create epics;
- implement approved plans;
- implement phases of an epic.

The bottom two items are the current intended scope of `worker_models`, but the live code already applies the worker
lane to epic and legend creation follow-ups too.

## Key Findings

### There is not a real default-model scalar today

The default launch lane is currently provider-plus-tier, not a single configured model:

- `llm_provider.provider` selects the default provider, or leaves provider autodetection active
  (`src/sase/llm_provider/registry.py:277`).
- `resolve_effective_default_provider_model()` then asks that provider for `resolve_model_name(model_tier)`
  (`src/sase/llm_provider/temporary_override.py:333`).
- Built-in providers hard-code tier maps such as Claude `large -> opus`, `small -> sonnet`, and Codex
  `large -> gpt-5.5`, `small -> codex-mini-latest`.

`llm_provider.model_tier_map` is present in the JSON schema and docs (`config/sase.schema.json:585`), but in this
workspace it is not consumed by the provider-resolution path. If that is the "default model" field meant by the request,
this project should either implement it as legacy input or replace it with the new unified field.

### `worker_models` is context-sensitive

`llm_provider.worker_models` is a mapping from the effective primary lane to a worker target, not just a single worker
model. The lookup order in `get_configured_worker_model_entry_for_primary()` is:

1. exact `provider/model`;
2. bare model;
3. provider.

The resolver then applies this precedence:

1. active worker temporary override;
2. matching `worker_models` entry;
3. supplied primary provider/model.

This is implemented in `src/sase/llm_provider/config.py:54` and
`src/sase/llm_provider/temporary_override.py:380`. The context-sensitive mapping is important because it supports
config such as "when the primary lane is Claude, use Codex for worker agents; when the primary lane is Codex, use
Claude."

### Current behavior for the requested workflows

| Workflow | Current model source | Code path |
| --- | --- | --- |
| Land epic | Primary/default lane unless the epic plan bead has a stored `model` | `render_multi_prompt()` omits `%model` for the land segment unless `plan.land_model` exists (`src/sase/bead/work.py:351`) |
| Create epic | Worker lane resolved from the planner's concrete provider/model | `_resolve_followup_model()` is shared by `epic`, `legend`, and `approve` follow-ups (`src/sase/axe/run_agent_exec_plan_accept.py:93`, `:284`) |
| Implement approved plan | Worker lane resolved from the planner's concrete provider/model | `_resolve_followup_model()` then emits a concrete `%model:<provider>/<model>` when planner metadata exists (`src/sase/axe/run_agent_exec_plan_accept.py:126`) |
| Implement epic phase | `%model:worker`, which resolves late through the worker alias | `render_multi_prompt()` emits `%model:worker` when a phase bead has no explicit model (`src/sase/bead/work.py:341`) |

Legend workflows mirror the epic ones closely enough that the implementation should decide explicitly whether to add
`create_legend` and `land_legend` now or make them aliases of the epic purposes.

### Explicit per-work-item overrides must stay stronger

The new config should not override direct user intent:

- `%model` directives in prompts;
- approval dialog / CLI `coder_model`;
- custom coder prompts containing their own `%model`;
- per-phase bead `model`;
- epic/legend plan-bead `model`, including plan-frontmatter `model:` propagated by `bd/new_epic` and `bd/new_legend`.

This matters because bead-level model routing already exists and is tested.

## Alternatives

### Alternative A: flat per-purpose scalar fields

```yaml
llm_provider:
  default_model: claude/opus
  create_epic_model: codex/gpt-5.5
  implement_plan_model: codex/gpt-5.5
  implement_phase_model: codex/gpt-5.5
  land_epic_model: claude/opus
```

Pros: simplest schema and easiest to explain.

Cons: loses current `worker_models` by-primary routing unless every scalar grows a parallel mapping form. It also keeps
adding top-level fields for every future workflow purpose.

Verdict: too limited unless SASE intentionally drops context-sensitive routing.

### Alternative B: generalize `worker_models` into per-purpose maps

```yaml
llm_provider:
  provider: claude
  role_models:
    implement_plan:  { claude: codex/gpt-5.5, codex: claude/opus }
    implement_phase: { claude: codex/gpt-5.5 }
    create_epic:     { claude: codex/gpt-5.5 }
    land_epic:       { claude: claude/opus }
```

Pros: preserves current primary-lane keying and is close to the current resolver.

Cons: does not really merge the default model lane. It also keeps the uncommon map shape as the only shape, making
simple config verbose.

Verdict: a reasonable intermediate refactor, but not the best final user surface.

### Alternative C: one `llm_provider.models` map with scalar-or-keyed values

```yaml
llm_provider:
  provider: claude  # kept as autodetect/default-provider seed
  models:
    default: claude/opus
    create_epic: codex/gpt-5.5
    implement_plan:
      claude: codex/gpt-5.5
      codex: claude/opus
    implement_phase: codex/gpt-5.5
    land_epic: claude/opus
```

Each role value can be:

- a scalar model target such as `codex/gpt-5.5`, `opus`, or a configured alias;
- a primary-keyed map using today's `provider/model -> model -> provider` match order;
- optionally, for `default`, a tier map such as `{large: claude/opus, small: claude/sonnet}` if SASE wants to preserve
  tier semantics explicitly.

Pros: one field satisfies the merge, split, and expansion. Simple configs stay short; power users keep the current
cross-provider routing behavior.

Cons: polymorphic values add modest schema and resolver complexity. The docs must clearly explain scalar versus keyed
maps.

Verdict: best long-term shape.

### Alternative D: named lanes plus role assignments

```yaml
llm_provider:
  lanes:
    worker: { claude: codex/gpt-5.5 }
    finisher: claude/opus
  roles:
    implement_plan: worker
    implement_phase: worker
    create_epic: worker
    land_epic: finisher
```

Pros: avoids duplicating the same route under several roles and scales to many future purposes.

Cons: introduces a second level of indirection and more terminology than the current four-purpose request needs.

Verdict: attractive if SASE expects many model purposes soon, otherwise overbuilt.

### Alternative E: keep `worker_models` and add sibling fields

```yaml
llm_provider:
  provider: claude
  worker_models: { claude: codex/gpt-5.5 }
  create_epic_model: codex/gpt-5.5
  land_epic_model: claude/opus
```

Pros: smallest initial diff.

Cons: does not merge the default lane and does not split `implement_plan` from `implement_phase`. It preserves the exact
inconsistency the request is trying to remove.

Verdict: acceptable only as a throwaway stopgap.

## Recommended Approach

Adopt Alternative C: add a single `llm_provider.models` role map and route launch purposes through it.

Recommended initial roles:

| Role | Applies to | Missing-role fallback |
| --- | --- | --- |
| `default` | ordinary launches with no explicit `%model` | current provider/autodetect + tier behavior |
| `implement_plan` | approved plan/tale coder follow-ups | current contextual worker behavior |
| `implement_phase` | epic phase agents without bead `model` | current contextual worker behavior |
| `create_epic` | `#bd/new_epic` follow-up after epic-plan approval | `implement_plan` for backward compatibility |
| `land_epic` | `#bd/land_epic` when the epic plan bead has no `model` | `default` |

Also add or reserve `create_legend` and `land_legend`, because the code already has parallel legend paths. If SASE does
not want separate legend config yet, make `create_legend` fall back to `create_epic` and `land_legend` fall back to
`land_epic`.

### Resolver shape

Add a role-aware resolver in the LLM provider layer, for example:

```python
def resolve_model_for_purpose(
    purpose: ModelPurpose,
    *,
    primary_provider: str | None = None,
    primary_model: str | None = None,
    model_tier: ModelTier = "large",
) -> ModelPurposeResolution:
    ...
```

Resolution should follow this order:

1. explicit launch model, handled by callers before purpose resolution;
2. temporary override:
   - primary override for `default`;
   - existing worker/secondary override for non-default roles, at least during migration;
3. `llm_provider.models.<purpose>`;
4. legacy compatibility input, if retained for a transition:
   - `model_tier_map` for `default`;
   - `worker_models` for `implement_plan`, `implement_phase`, and, to preserve current behavior, `create_epic` /
     `create_legend`;
5. purpose fallback;
6. built-in fallback to current behavior.

The result should include provider, model, source, purpose, matched key, configured target, and contextual
primary-provider/model. That preserves the provenance currently exposed by `WorkerModelResolution` and used in tests/UI.

### Alias and call-site changes

Keep using the existing `%model:<spec>` mechanism, but add purpose aliases:

- `%model:implement_phase` for phase work, replacing internal emission of `%model:worker`;
- `%model:land_epic` for land agents when a configured land route should be applied;
- `%model:implement_plan` and `%model:create_epic` where a late-bound alias is needed.

For plan approval follow-ups, prefer resolving to a concrete `%model:<provider>/<model>` when planner metadata is
available, as the current `_resolve_followup_model()` does. This avoids drift if the global config or overrides change
between planner completion and follow-up launch.

Keep `%model:worker` as a deprecated compatibility alias. Mapping it to `implement_phase` protects hand-written
xprompts and matches the historical internal bead-phase injection site. Schema-level config can be migrated more
strictly than prompt text because prompt text is user-authored and harder to find.

### Temporary overrides

Do not create one temporary override lane per purpose in the first implementation. The current override type is exactly
`primary | worker` (`src/sase/llm_provider/types.py:7`), and the TUI modal is built around those two lanes
(`src/sase/ace/tui/modals/temporary_llm_override_modal.py:255`).

Recommended policy:

- `primary` backs `models.default`;
- the existing worker override becomes a "secondary" override that blankets non-default purposes.

Rename user-facing "worker" wording to "secondary" when practical, but keep storage/action compatibility unless there
is a separate migration plan for keymaps and `~/.sase/llm_worker_override.json`.

### Migration

A staged migration is safer than immediate hard rejection:

1. Add `llm_provider.models` while still accepting `worker_models` and `model_tier_map`.
2. Interpret `worker_models` as legacy input for `implement_plan`, `implement_phase`, `create_epic`, and
   `create_legend` when the new role is unset.
3. Interpret `model_tier_map` as legacy input for `models.default` only if SASE wants to honor the documented field
   before retiring it.
4. Update docs and examples to prefer `models`.
5. After Bryan's config and docs are migrated, remove `worker_models` from the schema and add a targeted validation
   message. The project already schema-rejects the older singular `worker_model`, so hard rejection is consistent once
   the migration window closes.

## Implementation Surface

- `config/sase.schema.json`: add `llm_provider.models`, including role keys and scalar-or-map validation.
- `src/sase/llm_provider/config.py`: parse configured role routes and add reserved purpose aliases.
- `src/sase/llm_provider/temporary_override.py`: generalize default/worker resolution into a role resolver while
  keeping compatibility wrappers.
- `src/sase/llm_provider/_invoke.py`: make no-explicit-model launches resolve `models.default` instead of only provider
  tier defaults.
- `src/sase/axe/run_agent_exec_plan_accept.py`: use `implement_plan`, `create_epic`, and `create_legend` based on
  `plan_result.action`.
- `src/sase/bead/work.py`: use `implement_phase` for phase defaults and `land_epic` / `land_legend` for landing
  defaults while keeping bead `model` stronger.
- TUI override modal: optionally relabel worker as secondary and surface role-resolution provenance later.

Focused tests should cover schema validation, scalar and primary-keyed role resolution, fallback precedence, legacy
field compatibility, approve/epic/legend follow-up model selection, bead phase rendering, and land-segment routing.

## Final Recommendation

Implement `llm_provider.models` as a unified purpose-routing map with scalar-or-primary-keyed values. Keep
`llm_provider.provider` as the default provider/autodetect seed rather than deleting it in the same change. Treat
`models.default` as the new real default-model config, preserve the useful `worker_models` context sensitivity under
role-specific keys, and split the current worker lane into at least `implement_plan`, `implement_phase`, `create_epic`,
and `land_epic`.

This gives users one coherent model configuration surface, preserves existing advanced routing behavior, fixes the
current docs/schema gap around default models, and avoids over-expanding temporary override state.
