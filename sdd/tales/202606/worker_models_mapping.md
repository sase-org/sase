---
create_time: 2026-06-13 12:49:32
status: done
prompt: sdd/prompts/202606/worker_models_mapping.md
---
# Worker Models Mapping

## Context

The current worker lane is configured with a single string:

```yaml
llm_provider:
  worker_model: codex/gpt-5.5
```

That value is read by `sase.llm_provider.config.get_configured_worker_model()` and applied globally by
`resolve_effective_worker_provider_model()`. Worker-specific temporary overrides already win ahead of config, and when
no worker config exists the worker lane falls through to the effective primary lane.

The requested behavior changes the config shape to a mapping:

```yaml
llm_provider:
  worker_models:
    claude: codex/gpt-5.5
    codex: claude/opus
```

Each entry maps a primary model/provider to the worker model to use when the primary lane is on that model/provider.

## Goals

1. Rename the config field from `llm_provider.worker_model` to `llm_provider.worker_models`.
2. Parse `worker_models` as a mapping of string keys to string values, tolerating missing, blank, or malformed entries.
3. Resolve the worker lane from the current effective primary `(provider, model)`:
   - Exact `provider/model` key wins first, for example `claude/opus`.
   - Bare model key wins next, for example `opus`.
   - Provider key wins last, for example `claude`.
   - Provider keys are defaults only and must not override exact model-specific entries.
4. Keep the existing lane precedence:
   - Explicit `%model` / per-bead model still wins before the worker lane.
   - Active worker temporary override still wins before config.
   - If no `worker_models` entry matches, fall through to the primary lane exactly as today.
5. Update docs, schema, default config comments, tests, and Bryan's chezmoi `sase.yml` source config.

## Proposed Design

### Config parsing

Replace the single-value accessor with a mapping accessor, likely named `get_configured_worker_models()`. It should:

- Read `llm_provider.worker_models`.
- Return `{}` unless the value is a dict.
- Keep only string keys and string values after trimming whitespace.
- Drop blank keys and blank values.
- Not read `worker_model`; the public config field is being renamed.

Add a small helper for lookup against the effective primary lane, for example:

```python
def get_configured_worker_model_for_primary(
    primary_provider: str,
    primary_model: str,
) -> str | None:
    ...
```

This helper should try keys in this order:

1. `f"{primary_provider}/{primary_model}"`
2. `primary_model`
3. `primary_provider`

The key side should be an index, not another model-resolution expression. Values should continue to use the existing
model resolution syntax from the old `worker_model` field: explicit `provider/model`, known bare model names, configured
aliases, and unknown bare models with the existing default-provider fallback.

### Worker lane resolution

Update `resolve_effective_worker_provider_model()` so it:

1. Returns the active worker override when present.
2. Resolves the current effective primary lane with `resolve_effective_default_provider_model(model_tier)`.
3. Looks up a configured worker target with the helper above.
4. Resolves that worker target with `resolve_model_provider()` when present.
5. Preserves the current guard against `worker` self-reference.
6. Falls through to the primary lane from step 2 when no mapping entry applies.

This makes provider entries follow the current primary provider, including a primary temporary override. For example,
with `worker_models.codex: claude/opus`, a primary override to `codex/o3` will use `claude/opus` for worker launches
unless a more specific `codex/o3` or `o3` key exists.

### UI source labeling

The Model Overrides modal currently marks the worker row as `config` whenever a global worker config string exists. That
will be wrong for a mapping if no entry matches the current primary. Update the modal to ask the same helper using the
effective primary lane and show:

- `config` only when a `worker_models` entry matched.
- `follows primary` when the worker lane fell through to an active primary override.
- `default` when it fell through to the ordinary primary default.

### Schema, default config, docs

Update:

- `config/sase.schema.json`: replace `worker_model` string with `worker_models` object whose additional properties are
  strings.
- `src/sase/default_config.yml`: change the commented example to the new mapping shape.
- `docs/llms.md`, `docs/configuration.md`, `docs/beads.md`, and `docs/ace.md`: rename the field, document the mapping,
  and spell out exact-model versus provider-default precedence.

### Chezmoi config

Update the chezmoi source file:

`/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`

to:

```yaml
llm_provider:
  worker_models:
    claude: codex/gpt-5.5
    codex: claude/opus
  model_aliases:
    other: claude/opus
```

I do not plan to edit memory files.

## Test Plan

Add or update focused tests in the existing worker-lane test files:

- Config parser:
  - missing, non-dict, blank, and non-string `worker_models` entries are ignored.
  - valid keys and values are stripped.
- Worker alias / provider resolution:
  - `%model:worker` resolves through `worker_models`.
  - exact `provider/model` key beats bare model key and provider key.
  - bare model key beats provider key.
  - provider key applies when the current primary provider matches and no model-specific key exists.
  - provider key does not apply when the current primary provider differs.
  - active primary temporary override affects which mapping key is selected.
  - active worker temporary override still wins.
  - no matching mapping falls through to the primary lane.
  - `worker` self-reference is treated as unset/fallthrough.
- Agent metadata:
  - `%model:worker` writes the expected worker provider/model in `agent_meta.json`.
- TUI modal rendering:
  - worker row shows `config` only for a matching mapping.
  - worker row shows `follows primary` or `default` when no mapping matches.

After implementation, run `just install` if the workspace environment is stale, then run focused pytest for the changed
areas and `just check` before finishing.

## Risks and Notes

- This is a Python-side config and worker-lane resolution change. I do not expect a Rust core change because the current
  worker model behavior lives in `src/sase/llm_provider` and TUI Python callers.
- Removing the old `worker_model` key is a breaking config migration. That matches the requested rename and the chezmoi
  config will be updated in the same change. If a compatibility shim is desired, it can be added deliberately, but I
  would not document or schema-advertise the old field.
- Bare model keys can intentionally apply across providers if two providers expose the same model string. Users can use
  `provider/model` keys when provider-specific behavior matters.
