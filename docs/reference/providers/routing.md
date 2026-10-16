---
title: Provider routing
description: Per-prompt selection and temporary provider or model routing controls.
---

# Provider routing

This page describes how prompts select providers and how temporary routing controls
apply.

## Temporary Model Overrides

In addition to prompt-level
[launch-scoped overrides](models.md#launch-scoped-alias-overrides) and the tier-based
global override, sase supports **concrete** provider/model overrides that act as
temporary, time-bound machine-wide overrides of a model alias or launch-model setting.
sase's TUI `,m` chord opens the [**Launch Control**](../../ace.md#launch-control) for
setting, changing, and clearing these overrides — for the `default model`,
`epic lander`, and `big epic lander` settings, or any size/custom alias.

The panel also shows a two-line description for the highlighted alias, launch-model
setting, or bucket. Builtin aliases have fixed descriptions, custom aliases read
`llm_provider.model_aliases.custom.<name>.description`, selector aliases list each
member, its current availability, and the current selection, and each of the three
scalar launch-model-setting rows shows its configured/shipped target, resolved
provider/model, and provenance. The title shows the launch-effective default effort and
current effective `max_running_agents` capacity budget — occupied capacity units against
the host ceiling, where a serial session still carries one live claim while any of its
turns is live, including a monitor and its `--next` agent. Active temporary values
include their remaining time and configured provenance. Non-pool aliases that explicitly
carry an effort explain its provenance on the second description line.

Overrides are independent **per-alias** for the five size aliases and any custom alias,
and independent **per-setting** for the three scalar launch-model settings (namespaced
`setting:default_model`, `setting:epic_lander_model`, and
`setting:big_epic_lander_model` keys in the override store). An override takes effect
wherever that alias or setting is resolved. For example, an override on `@medium`
affects only that size alias, and an override on the `epic lander` setting affects only
below-threshold epic land agents. An active override on `@xlarge` suspends its fallback
selection for a single concrete target, just as overrides on `@xsmall`, `@small`,
`@medium`, and `@large` suspend their independent load-balanced rotations for the
override's duration. The three launch-model settings do not reference a shared alias, so
an override on the `default model` setting (`llm_provider.default_model`) does not move
phase/task/tale routing — which resolves through the size aliases directly — or
epic-land routing — which resolves through `epic_lander_model`/`big_epic_lander_model`;
override the size alias, or the specific launch-model setting, to move one of those
lanes. Machine-wide temporary overrides do not change:

- Already-running agents — they keep whatever provider/model they were launched with.
- Explicit concrete `%model` prompt targets — they still take precedence. A
  `%model(...)` alias keyword is a separate, higher-precedence launch-scoped override.
- An explicit `provider_name=` argument to `invoke_agent()` — it still wins.

Temporary **hard** provider disables can pause, but do not delete, these overrides. If
an active alias override resolves to a hard-disabled provider, SASE ignores that
override for live routing and falls through to the alias's configured or implicit
target. If the disable is cleared or expires before the alias override expires, the
stored override resumes automatically. A **soft** disable does not pause the override.

An override may carry a canonical reasoning-effort suffix, such as
`codex/gpt-6.1-sol@medium` or `@large@medium`. The write resolves and snapshots the
clean provider/model plus `medium`, while preserving the original `raw_model`. That
effort survives state reloads and shapes the next matching launch. An explicit outer
reference such as `@large@xhigh` still wins over the stored override effort.

`SASE_MODEL_TIER_OVERRIDE` / `SASE_MODEL_SIZE_OVERRIDE` still force the tier for
tier-based launches. A concrete temporary override supplies a provider and model
directly, so it is used only when no explicit model/provider was requested.

### Resolution Order (default provider/model)

When no positional `%model` target and no explicit `provider_name` are present, the
default is resolved as:

1. A launch-scoped keyword override from `%model(...)` matching the alias that
   `llm_provider.default_model` currently references (for example `large=...` under the
   shipped default), when present.
2. **Active machine-wide `setting:default_model` temporary override** at
   `~/.sase/llm_override.json` (if not expired and not paused by a provider disable).
3. `llm_provider.default_model`, configured or the shipped `@large` fallback, resolved
   through the normal alias/selector chain, otherwise the configured/autodetected
   provider's requested-tier model if the field is missing or malformed.

For every alias, `resolve_model_alias()` consults the launch-scoped map first, then that
alias's active machine-wide override, then its configured/implicit value. This order
applies at every nested alias hop, including whichever alias
`llm_provider.default_model` references — a namespaced `setting:default_model` temporary
override wins outright before any of that alias resolution runs (see
[`resolve_effective_default_provider_model()`](#public-api)). If the referenced alias
reaches a round-robin pool, the pool advances exactly once per real LLM invocation — the
runner's top-level metadata preparation only previews the selection (`consume=False`);
the anonymous workflow's prompt step performs the one authoritative, consuming
resolution immediately before invoking the provider, and reuses it for the step marker,
root `agent_meta.json`, and the saved chat's metadata. A no-`%model` launch and an
explicit `%model:@large` (or any other reference that resolves through the same
pool-owning alias) advance that same shared cursor. A runner re-exec reuses the stored
provider/model metadata and does not advance the cursor again.

A concrete temporary override sets both the default provider and a concrete
`model_override` for the next launch — so the agent metadata (running marker, plan
review badge, agent rows) reflects the actual model that will run, not just the
configured default.

## Temporary Provider Disables

sase's TUI Launch Control's `p=Providers` flow can temporarily disable a registered
provider for new routing without editing `sase.yml` or unregistering the plugin.
Provider-disable state is machine-wide runtime state in
`~/.sase/llm_provider_disables.json`, owned by the Rust core and exposed through
`src/sase/llm_provider/provider_disable.py`. The lock-free `provider_disable_peek.py`
reader is reserved for high-frequency display and completion paths; launches and writes
use the authoritative Rust-backed facade.

Every record carries a `source` tag. Launch Control writes `source: "ace"` and displays
it as a manual disable. Usage-limit detection writes `source: "usage_limit"` and
displays it as usage-limit automatic. The UI treats the field as an open vocabulary:
unknown non-empty sources are rendered as readable labels instead of being treated as
manual disables.

Every disable carries a `mode`: **hard** (today's fail-closed disable) or **soft** (a
deprioritizing "spare this provider" disable). Hard disables are an availability layer:

| Request                  | Disabled provider present? | Result                                             |
| ------------------------ | -------------------------- | -------------------------------------------------- |
| round-robin alias        | one member                 | next available member; cursor advances from winner |
| ordered fallback         | preferred member           | next available candidate                           |
| temporary alias override | override target            | override pauses; underlying alias resolves         |
| direct provider/model    | target provider            | actionable failure; no silent provider change      |
| every selector member    | all                        | member zero retained for diagnostic; launch fails  |
| running provider process | disabled after start       | process continues; future resolution changes       |

A **soft** disable never fails a launch; it only deprioritizes the provider:

| Request                  | Soft-disabled provider present? | Result                                                                                                                                                                                                                                                                           |
| ------------------------ | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| round-robin alias        | one member                      | that member is spared while another _non-soft_ member can cover, including when the other member is only a priority backup; it rotates in normally once every usable primary member is actually soft. A healthy last-resort tail does not spare or replace a soft primary member |
| ordered fallback         | first candidate                 | first candidate still wins; a soft disable never diverts an ordered fallback chain                                                                                                                                                                                               |
| direct provider/model    | target provider                 | launch proceeds on that provider; no failure, no rerouting                                                                                                                                                                                                                       |
| temporary alias override | override target                 | override stays applied; it is not paused                                                                                                                                                                                                                                         |
| autodetect               | preferred candidate             | preferred candidates win first; a soft candidate is only picked when no preferred candidate qualifies                                                                                                                                                                            |

`source` and `mode` are independent axes: a manual Launch Control disable may be set to
either mode, but usage-limit auto-disable (`source: "usage_limit"`) always writes a
**hard** disable — nothing in routing changes that. Create, flip, and inspect a soft
disable from sase's TUI Launch Control → Provider Routing (`p` from `,m`); see
[Provider routing controls](../../ace.md#provider-routing-controls). A hard disable can
additionally drain the agents it stranded — relaunching them elsewhere or reporting why
they cannot move; see
[Draining a Disabled Provider](usage.md#draining-a-disabled-provider).

Each top-level routing operation captures active disables once and passes that snapshot
through alias resolution, autodetection, model-picker rows, completion overlays, and the
final provider dispatch gate. Round-robin pools skip **hard**-disabled members without
rewriting membership or fingerprints, and spare **soft**-disabled members while another
member is preferred; re-enabling a provider lets it participate in later rotations
naturally. Ordered fallbacks choose the first installed member that is not hard-disabled
(a soft first candidate still wins) and return to a higher-priority provider on the next
resolution after a hard disable is cleared. When every selector member is hard-disabled
or otherwise unavailable, SASE preserves the diagnostic candidate rather than silently
rerouting to a default provider.

Direct intent remains direct. `%model:claude/opus`, a known bare model owned by Claude,
an explicit `provider_name="claude"`, or `SASE_LLM_EXEC_PROVIDER=claude` fails before
provider construction while Claude is **hard**-disabled; the error names the provider
and expiry or says `until cleared`. This proves the request was not silently changed to
another provider. The same explicit request proceeds while Claude is only
**soft**-disabled.

The state file is a versioned envelope with one independent record per provider:

```json
{
  "version": 2,
  "disables": {
    "claude": {
      "provider": "claude",
      "created_at": 1777470000.0,
      "expires_at": 1777473600.0,
      "source": "ace",
      "mode": "hard"
    }
  }
}
```

`expires_at: null` means until cleared. Finite expiries are exclusive:
`now >= expires_at` removes the record. Authoritative reads self-clean expired or
malformed per-provider records and delete the file when no active disables remain. A
malformed envelope/version fails closed to no active disables and is removed.

Manual Launch Control writes are replacements: choosing a new duration for an already
disabled provider extends, shortens, or changes it to until-cleared. Automatic
usage-limit writes create only the first active window for a provider; later usage-limit
detections while that record is active do not extend it or send another notification.
Clearing the provider early from Launch Control removes either kind of record and lets
normal routing resume immediately.

Public provider-disable helpers:

| Function                                                                          | Purpose                                                               |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `get_active_provider_disables(now=None)`                                          | Read every active disable, keyed by provider.                         |
| `get_active_provider_disable(provider, now=None)`                                 | Read one active provider disable, or `None`.                          |
| `disable_provider(provider, duration_seconds, source, mode="hard", now=None)`     | Disable one provider for a duration or until cleared.                 |
| `disable_provider_until(provider, expires_at, source, mode="hard", now=None)`     | Disable one provider until an exact Unix timestamp.                   |
| `try_disable_provider(provider, duration_seconds, source, mode="hard", now=None)` | First-writer relative disable; `inserted` is whether this caller won. |
| `try_disable_provider_until(provider, expires_at, source, mode="hard", now=None)` | First-writer exact-expiry disable; losers leave the record unchanged. |
| `enable_provider(provider)`                                                       | Clear one provider disable; returns whether it existed.               |
| `peek_active_provider_disables(now=None)`                                         | Read-only, lock-free display snapshot for TUI/completions.            |

### State File

Override state is keyed by alias under a versioned envelope:

```json
{
  "version": 2,
  "overrides": {
    "default": {
      "provider": "opencode",
      "model": "anthropic/claude-sonnet-4-5",
      "raw_model": "opencode/anthropic/claude-sonnet-4-5@medium",
      "effort": "medium",
      "created_at": 1777470000.0,
      "expires_at": 1777473600.0,
      "source": "ace"
    }
  }
}
```

Each entry under `overrides` has these fields:

| Field        | Type            | Description                                                              |
| ------------ | --------------- | ------------------------------------------------------------------------ |
| `provider`   | `str`           | Resolved provider name (e.g. `"claude"`, `"codex"`, `"opencode"`).       |
| `model`      | `str`           | Concrete model passed to the provider (e.g. `"o3"`, `"opus"`).           |
| `raw_model`  | `str`           | Original user input (e.g. `"codex/o3"`, `"opencode/anthropic/..."`).     |
| `effort`     | `str \| None`   | Canonical resolved effort suffix; `null` means no model-specific effort. |
| `created_at` | `float`         | Unix timestamp when the override was set.                                |
| `expires_at` | `float \| None` | Unix timestamp when the override expires; `null` means "until cleared".  |
| `source`     | `str`           | Free-form tag indicating who set the override (e.g. `"ace"`).            |

Version 1 files (a single flat override object with top-level `provider` / `model` / ...
keys) are migrated on read into `overrides.default`. Existing version 2 entries without
`effort` remain valid and are read as `effort: null`. See the
[provider override migration note](../upgrading/providers.md#provider-override-files).

Writes are atomic (temp file + `os.replace`). Reads are best-effort self-cleaning:
expired or unparseable entries are pruned and the file is deleted once no override
remains, so a forgotten override never lingers past its `expires_at`, even with no TUI
running.

Relative and exact-expiry writes use the same provider/model resolution and atomic v2
serialization path. Exact-expiry writes persist the caller's Unix timestamp unchanged
and reject non-finite or no-longer-future targets. The state schema is unchanged; an
exact target is represented by the same `expires_at` field.

### Model Resolution

The user-supplied `raw_model` is normalized through the same rules as `%model`:

- `provider/model` selects the provider explicitly (e.g. `codex/o3` or
  `opencode/anthropic/claude-sonnet-4-5`).
- A bare known model name infers its provider from plugin metadata (e.g. `sonnet` →
  claude).
- An unknown bare model is accepted and runs on the current default provider, matching
  `%model` behavior.
- A known trailing effort is split into the entry's `effort` field. Unknown trailing
  `@token` text remains part of the model identifier, and `@alias@effort` resolves the
  alias eagerly while retaining the raw reference for display.

### Duration Parsing

Durations accept compact unit suffixes: `15m`, `1h`, `1h30m`, `90m`, `2h15m30s`. Bare
integers are interpreted as minutes (`45` → 45 minutes). The case-insensitive sentinel
`until cleared` (or `until_cleared`) means "no expiry — persists until the user clears
it from the TUI or another sase process clears the state file."

### Public API

The override primitives live in `src/sase/llm_provider/temporary_override.py`. The
alias/setting-keyed functions are the primary API; the `*_temporary_override` wrappers
are back-compat shims that operate on the `setting:default_model` launch-model-setting
key:

| Function                                                | Purpose                                                                                                           |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `get_active_alias_overrides(now=None)`                  | Read every active override, keyed by alias or `setting:<field>` (auto-prunes expired/malformed).                  |
| `get_active_alias_override(alias, now=None)`            | Read the active override for one alias or setting key, or `None`.                                                 |
| `set_alias_override(alias, raw, dur, source=)`          | Set/replace one alias/setting's relative/no-expiry override.                                                      |
| `set_alias_override_until(alias, raw, expiry, source=)` | Set/replace one alias/setting's override with an exact future Unix expiry.                                        |
| `clear_alias_override(alias)`                           | Remove one alias/setting's override; returns whether an entry was present.                                        |
| `get_active_temporary_override(now=None)`               | Back-compat wrapper: the active `setting:default_model` override.                                                 |
| `set_temporary_override(raw, dur, source=)`             | Back-compat wrapper: set the `setting:default_model` override.                                                    |
| `clear_temporary_override()`                            | Back-compat wrapper: clear the `setting:default_model` override.                                                  |
| `parse_override_duration(value)`                        | Parse a user-facing duration string into seconds (or `None`).                                                     |
| `resolve_effective_default_provider_model()`            | Resolve the default launch target: an active `setting:default_model` override, else `llm_provider.default_model`. |

### Examples

- Launch Control (`,m`), highlight `default model`, `o`, pick `codex/o3`, duration `1h`
  → `~/.sase/llm_override.json` gains a `setting:default_model` entry; new launches with
  no `%model` default to CODEX(o3) for the next hour.
- Launch Control, highlight `medium`, `o`, pick `opencode/anthropic/claude-sonnet-4-5`,
  `Until cleared` → medium phases and tasks without an explicit model inherit that
  target until cleared.
- Launch Control, highlight `default model`, `o`, pick `sonnet`, duration `30m` → known
  bare model; provider resolves to claude via plugin metadata.
- Launch Control, highlight an alias, `x` → that alias's override is cleared; when the
  last override is removed the state file is deleted and defaults revert to permanent
  config / autodetect.

## Temporary Provider Priority

sase's TUI Launch Control's Provider Routing modal can set one machine-wide provider
priority for new routing. Press `p` on an enabled, installed, user-facing provider row,
then choose a relative duration, exact local time, or `Until cleared`. Press `c` from
the same modal to clear the active priority. The modal stays open after writes,
refreshes rows in place, and keeps selection stable so you can manage priority and
disables together.

Provider-priority state lives in `~/.sase/llm_provider_priority.json`, owned by the Rust
core and exposed through `src/sase/llm_provider/provider_priority.py`. Display-only
paths use the lock-free `provider_priority_peek.py` reader. Authoritative routing
captures disables and priority together as one `ProviderRoutingContext`, then carries
that snapshot through alias resolution, autodetection, model-picker rows, completion
overlays, and the final provider dispatch gate.

The top bar renders priority alone as `CODEX ★ priority 42m`. When disables are also
active, it compacts to a priority-led count such as `CODEX ★ 42m +1`; hover text lists
the exact priority and disable details.

Priority is a preference layer, not a disable:

| Request                  | Priority provider present?               | Result                                                                               |
| ------------------------ | ---------------------------------------- | ------------------------------------------------------------------------------------ |
| round-robin alias        | available pool member                    | priority provider wins; other usable members stay backups                            |
| round-robin alias        | only in the tail, absent, or unavailable | usable non-soft primary members still outrank actually soft-disabled primary members |
| ordered fallback         | any candidate                            | fallback order is unchanged                                                          |
| direct provider/model    | target provider                          | explicit target still runs directly                                                  |
| temporary alias override | override target                          | override still bypasses selector routing                                             |
| missing or hard-disabled | priority provider                        | priority intent remains; routing uses backups until the provider works               |

Writes are optimistic. Launch Control sends the provider facts and the priority record
seen in its current snapshot. If another process changed priority first, the write
returns `conflict`, the modal reloads the current state, and the user repeats `p` or `c`
against that fresh view. If the write commits but the follow-up refresh fails, the toast
says the routing write succeeded and the modal remains open for retry.

The state file is a versioned envelope with a single optional priority record:

```json
{
  "version": 1,
  "priority": {
    "version": 1,
    "provider": "codex",
    "created_at": 1777470000.0,
    "expires_at": 1777473600.0,
    "source": "ace"
  }
}
```

`expires_at: null` means until cleared. Finite expiries are exclusive:
`now >= expires_at` clears active priority. Malformed, expired, ineligible, or
non-user-facing priority records do not make an unavailable provider usable.

Public provider-priority helpers:

| Function                                                                                   | Purpose                                                          |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `get_active_provider_priority(now=None)`                                                   | Read the active priority, self-cleaning stale state.             |
| `set_provider_priority(provider, duration_seconds, source=, facts=, expected=, now=None)`  | Set or replace priority for a relative duration.                 |
| `set_provider_priority_until(provider, expires_at, source=, facts=, expected=, now=None)`  | Set or replace priority until an exact Unix timestamp.           |
| `clear_provider_priority(expected=, now=None)`                                             | Clear priority when live state matches the expected snapshot.    |
| `capture_provider_routing_context(now=None)`                                               | Capture disables and priority under one routing-state lock.      |
| `provider_routing_context_from_parts(disables, priority, captured_at=None)`                | Build a context from already decoded records without filesystem. |
| `resolve_provider_routing_context(routing_context=None, provider_disables=None, now=None)` | Normalize explicit or freshly captured routing inputs.           |
| `classify_provider_availability(context, facts)`                                           | Classify one provider against a captured routing context.        |
| `peek_active_provider_priority(now=None)`                                                  | Read-only display snapshot for high-frequency TUI paths.         |

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model selection and aliases.
