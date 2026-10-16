---
title: Models and aliases
description:
  Model names, reasoning effort, model tiers, and aliases used for provider routing.
---

# Models and aliases

This page describes model selection, model tiers, reasoning effort, and aliases.

## Overview

The LLM provider layer decouples prompt handling from the underlying LLM backend. All
providers share a common preprocessing pipeline, subprocess streaming mechanism, and
postprocessing workflow. The actual LLM invocation is delegated to a pluggable provider
selected at runtime.

Key design principles:

- **Providers are thin**: They only construct CLI commands and run subprocesses. All
  preprocessing and postprocessing lives in the shared orchestration layer.
- **Registry-based selection**: Providers register themselves by name and are resolved
  via config or explicit override.
- **Tier-based model selection**: Callers request a "large" or "small" tier; the
  provider maps it to a concrete model.
- **Runtime-uniform commit enforcement**: SASE agent runs use a shared commit finalizer
  instead of provider-specific native stop hooks.

<a id="source-layout"></a> Moved to
[LLM invocation internals](../../contribute/llm-invocation.md#source-layout).

## Per-Prompt Provider Switching

The `%model` directive (see [macro directives](../../macros.md#directives)) can switch
both the model and the LLM provider for a single prompt. Provider resolution uses
configured aliases first, then concrete provider/model syntax and known model metadata.

### Configured Model Aliases

Use `llm_provider.model_aliases.custom` to define launch-time aliases for reusable
prompts. Each custom alias must carry a short description:

```yaml
llm_provider:
  model_aliases:
    custom:
      fast:
        model: claude/sonnet
        description: Quick follow-up agents.
```

Use `llm_provider.model_aliases.builtin` only to override the five size aliases (see
below):

```yaml
llm_provider:
  model_aliases:
    builtin:
      large: "@xlarge"
      medium: codex/gpt-6.1-sol@xhigh
```

Then prompts can use the alias with a leading `@`:

```
%model:@fast
%{%m:@fast | %m:gpt-6.1-sol}
```

Agents launched through the `@<alias>` spelling show that launch-time provenance in
their `Model:` field, for example `Model: CLAUDE(sonnet) ← @fast` or
`Model: CLAUDE(sonnet) @ high ← @fast`. The chip records the alias named at launch and
is never re-resolved, so completed agents keep telling the truth after an alias is
retargeted, overridden, or deleted. Launches without a `%model` directive record
whichever alias `llm_provider.default_model` currently references the same way —
`← @large` under the shipped default — and omit the chip entirely when `default_model`
resolves to a concrete model with no alias reference.

Alias values may point at another alias (for example `@large` or `@medium`), a bare
known model such as `opus`, an explicit provider/model string such as `claude/opus`, or
a nested provider-local path such as `opencode/anthropic/claude-sonnet-4-5`. An alias
reference may carry a trailing effort such as `@large@high`, which overrides the
referenced alias's effort; an effort on the outer reference still wins. Alias-to-alias
chains are followed with cycle and depth protection; a cyclic or unresolved reference
falls back to the raw input rather than crashing a launch. The `@` marker is only
directive surface syntax: alias keys and macro values stay bare. A bare
configured/implicit alias raises with a migration hint, and `@` in front of a non-alias
raises.

An alias value can instead use one of two selector operators, or a parenthesized
last-resort form that combines them. `A | B` is an availability-filtered round-robin
pool: each real LLM invocation advances the machine-global cursor in
`~/.sase/llm_lb.json` exactly once, under a machine-wide lock, immediately before the
provider is called — never during metadata preparation, a display/marker preview, or a
doctor/dry-run check, which only peek. The cursor is the next position in that pool's
weighted cycle (identical to a member index when every weight is 1). Any alias that
merely delegates to a pool-owning alias (directly or through further aliasing) shares
that pool-owning alias's cursor rather than keeping one of their own. `A || B` is an
ordered fallback chain: the first registered provider whose CLI is installed and not
**hard**-disabled always wins — a **soft**-disabled first candidate still wins, so a
soft disable never diverts the chain — and resolution never reads or changes the
round-robin cursor, including during a real launch. `(A | B) || C` is a last-resort
expression: the parenthesized `|` pool is primary, and the `||` tail is used only when
every pool member is **unavailable** (CLI missing, unregistered, or **hard**-disabled).
An all-**soft** pool still rotates among itself and does not divert. Selecting a
last-resort candidate does not consume the pool cursor. A real soft disable is not the
same thing as a priority backup: usable primary members without an actual soft disable
outrank actually soft-disabled members even when the priority provider is only in the
tail, absent, or unavailable. A queued pool reservation can be invalidated before
invocation — redemption re-checks the reserved primary member, spends it when an actual
soft disable now has a usable non-soft primary alternative, and then performs one fresh
consuming resolution. Priority-only backups stay redeemable, and a healthy tail alone
does not invalidate a soft primary reservation. Unparenthesized `A | B || C` is still
rejected. Fallback and last-resort selection are based on the cached CLI-installation
probe (including `SASE_<PROVIDER>_PATH`) plus a captured active-disable snapshot, not a
later model or runtime failure; SASE does not relaunch with the next candidate after
such a failure. If every provider is unavailable, both modes preserve a candidate for
the ordinary provider lookup to report: fallback (and a last-resort tail) preserves its
first member, while a pool with no tail preserves its current rotation choice.

A temporary provider priority is a preference layer for `|` pools. When the priority
provider is an available member, that member is preferred and other usable providers
remain labeled backups; the selector expression, weights, and cursor are not rewritten.
Priority does not reorder `||` fallback chains and does not displace direct
`%model:provider/model` intent. Hard disables and missing CLIs still make a provider
unavailable, even if it has active priority intent. Priority backups are not actual soft
disables, so a usable non-soft primary member still outranks an actually soft-disabled
member when the two would otherwise share the same `sparing` label.

Both selectors accept two or more members using the same single-target grammar,
including candidate-specific trailing reasoning effort. A load-balanced pool member may
be prefixed with a positive integer weight and at least one space (`A | 3 B` selects B
three times as often as A, spreading B's turns through the cycle). Valid weights are
1–99; weight 1 is the default and is omitted from the canonical spelling. Weights are
invalid in `||` ordered fallback chains and last-resort tails. Whitespace is trimmed and
empty members are invalid. Unparenthesized `|` and `||` cannot be mixed in one value. A
member may follow an ordinary alias chain but cannot reach another pool or fallback,
including when it sits in a last-resort tail. Selector expressions are config-only:
`%model` values, launch-scoped alias overrides, and temporary overrides remain single
targets. sase's TUI Launch Control's persistent Edit path authors selectors directly —
hand-typed in the custom input or assembled with a guided pool/fallback builder (`w`/`W`
raise and lower a pool member's weight; `f` adds a last-resort candidate) — while its
temporary Override path refuses a typed pool or fallback outright, pointing at Edit,
rather than silently accepting and corrupting it. An override on the alias that owns a
selector bypasses that expression for the override's lifetime. sase's TUI Launch Control
shows every member's availability, an aggregate `pool <available>/<total>` chip that
counts only pool members (not the last-resort tail), and a `→` on the current selection.
A temporary alias override labels the member list suspended only while its provider is
available. If its provider is **hard**-disabled, the stored override is paused, the live
selector target is shown instead, and the override resumes automatically after the
provider disable is cleared or expires while the override itself is still active. A
**soft** disable does not pause the override.

To verify pool fairness from real launches, count recorded `llm_provider`/`model` pairs
for agents whose metadata has a matching `model_alias` value for the alias being audited
— a no-`%model` launch's `model_alias` records whichever alias
`llm_provider.default_model` currently references, `@large` under the shipped default.
Over a full weighted cycle the member counts should match the configured weight ratio
(an unweighted two-member pool stays within one launch of each other), ignoring periods
where provider availability caused a member to be skipped.

When the same name appears in both maps, `model_aliases.custom` wins.
`sase doctor -C config.model_aliases` warns about legacy flat keys in `model_aliases`,
removed top-level `custom_model_aliases`, custom names under `model_aliases.builtin`,
builtin names under `model_aliases.custom`, collisions between the two maps, missing
custom descriptions/models, dangling `@alias` references, empty or mixed selectors, and
nested selectors. Unavailable selector providers are reported as informational notes;
for an ordered fallback the note also identifies the current winner. In sase's TUI,
Launch Control shows descriptions from config; a user alias without one shows the
`llm_provider.model_aliases.custom.<name>.description` path to fix.

The same alias vocabulary appears in the `%model:` / `%m:` completion menu in sase's TUI
and in editors through the macro LSP: alias rows sit beneath the concrete model names
with their kind, resolved `PROVIDER(model)` target, and provenance, and typing `@` right
after the colon narrows the menu to aliases only. Concrete model rows and provider-scope
rows for **hard**-disabled providers are omitted, while aliases remain and show their
current fallback target. **Soft**-disabled providers stay in the menu, annotated `soft`;
priority providers are annotated `priority`, and providers left behind the active
priority provider are annotated `backup`. Provider rows such as `claude/` sit at the
bottom of the broad menu; accepting one opens that provider's scoped model list and
inserts qualified values such as `claude/opus`. See
[macro directive syntax](../../macros.md#syntax) for the row anatomy. The completion
menu is read-only; sase's TUI Launch Control (`,m`) remains the authoritative place to
edit alias targets and to set or clear temporary overrides.

There are no built-in Launch Control buckets: the compact five-size-alias contract ships
no automatic grouping. sase's TUI Launch Control instead shows the three scalar
[launch model settings](#implicit-role-aliases) (`default model`, `epic lander`,
`big epic lander`) as their own rows, alongside the five size aliases and any custom
aliases. Optional `model_aliases.buckets.<name>` metadata still creates a display-only
bucket for custom aliases: a collapsed bucket summarizes its effective-model mix and
active overrides, opening it exposes independently editable aliases, and a custom alias
tagged with `bucket: <name>` coalesces into that bucket.

A bare `%model` token that is _not_ a configured alias, an explicit `provider/model`
target, or a known provider model silently falls back to the default provider rather
than erroring. To catch this drift — for example a removed `model_aliases` entry that
quietly reroutes a `#m_<provider>_*` preset to the default provider — `sase doctor`
(`-C config.model_macros`) scans configured model presets and warns with
`<macro> -> <token> does not resolve to a provider; it will fall back to the default provider`.
The check is provider-neutral and read-only. For retired prompt directive syntax such as
`%wait(priority=...)`, use `sase doctor -C config.macro_directives`.

### Macro model inputs

A macro input declared with `type: model` (see
[Supported Types](../../macros.md#supported-types)) is valid exactly when
`%model:<value>` would be accepted by the directive parser and would route to a provider
without the default-provider fallback. Aliases need `@` (`@large` routes; bare `large`
does not). `provider/model` is open for unknown model ids (`codex/new-model` routes) and
closed for unknown providers (`cluade/opus` does not). A trailing `@<level>` peels only
when `<level>` is one of the seven effort levels; any other `@suffix` is rejected unless
the body before it would route on its own. Validation never moves the alias cursor,
never checks provider availability, and never changes `%model` fallback: `%model:opsu`
still parses and still falls back to the default provider at launch.

#### Implicit role aliases

On top of any aliases you configure, SASE always exposes a fixed set of **implicit role
aliases** that resolve even when you have not defined them: `@xsmall`, `@small`,
`@medium`, `@large`, and `@xlarge`. Each is a direct selector — a concrete model, an
`A | B` round-robin pool, an `A || B` ordered fallback, or a parenthesized
`(A | B) || C` last-resort — with no further alias indirection. Three related scalar
config fields, `llm_provider.default_model`, `llm_provider.epic_lander_model`, and
`llm_provider.big_epic_lander_model`, are not aliases themselves, but ship with the same
kind of automatic, shipped-default target and accept the same model-expression grammar;
this section covers both. The current shipped size-alias defaults are generated from
`src/sase/llm_provider/models.yml`:

<!-- BEGIN GENERATED: model-alias-defaults -->

| Alias     | Description                                                                          | Shipped default                                                                                                                   |
| --------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `@xsmall` | Extra-small launch alias for lookup, formatting, and tiny edits with obvious checks. | `claude/claude-haiku-5-5@xhigh \| codex/gpt-6-luna@medium \| agy/gemini-3.8-flash-high \| muse/muse-spark-1.3-contributor@medium` |
| `@small`  | Small launch alias for straightforward task and phase work.                          | `claude/sonnet@high \| codex/gpt-6-luna@high \| grok/grok-4.6@medium \| muse/muse-spark-1.3-contributor@high`                     |
| `@medium` | Medium launch alias for ordinary implementation work.                                | `claude/sonnet@xhigh \| codex/gpt-6-luna@xhigh \| grok/grok-4.6@high \| muse/muse-spark-1.3-contributor@xhigh`                    |
| `@large`  | Large launch alias for planning-heavy work and default launches.                     | `claude/opus@high \| codex/gpt-6.1-sol@xhigh \| grok/grok-4.7@xhigh`                                                              |
| `@xlarge` | Extra-large launch alias for maximum-effort work.                                    | `claude/opus@xhigh \|\| codex/gpt-6.1-sol@xhigh \|\| grok/grok-4.7@xhigh`                                                         |

<!-- END GENERATED: model-alias-defaults -->

Override any of the five size aliases by configuring
`llm_provider.model_aliases.builtin.<size>` with a matching name (`xsmall`, `small`,
`medium`, `large`, or `xlarge`). Override the three scalar launch-model settings
directly under `llm_provider` instead — they are plain config fields, not
`model_aliases.builtin` entries:

| Field                                | Shipped default | Purpose                                                                                                |
| ------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------ |
| `llm_provider.default_model`         | `@large`        | Used when a launch has no explicit `%model` directive.                                                 |
| `llm_provider.epic_lander_model`     | `@large`        | Used by epic land agents when the epic has fewer authored phases than `bead.big_epic_phase_threshold`. |
| `llm_provider.big_epic_lander_model` | `@xlarge`       | Used by epic land agents when the epic has `bead.big_epic_phase_threshold` or more authored phases.    |

An outer effort suffix and an approval-time concrete model remain authoritative over
either kind of override. Accepted tale follow-ups without an explicit model use the
validated tale size to choose the matching size alias directly; legacy sizeless tales
normalize to `@medium`. Threshold-selected epic land agents diverge from the launch
default entirely: `epic_lander_model` governs below-threshold epics and
`big_epic_lander_model` governs epics at or above `bead.big_epic_phase_threshold`,
independent of `default_model` and of each other — see
[Role Aliases for Delegated Work](#role-aliases-for-delegated-work) for the full
per-role breakdown. A configured alias value or temporary override still takes
precedence over a role's shipped target.

```yaml
llm_provider:
  default_model: "@large"
  epic_lander_model: "@large"
  big_epic_lander_model: codex/gpt-6.1-sol # large epic land agents only
  model_alias_history_limit: 10
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low
      small: claude/haiku | codex/gpt-4.1-mini
      medium: codex/o3@xhigh | claude/sonnet@xhigh
      large: codex/gpt-6.1-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max
```

Source: `src/sase/llm_provider/models.yml` (built-in model catalogs, tier defaults, and
shipped size-alias defaults — the single edit point),
`src/sase/llm_provider/model_launch_settings.py` (the three scalar launch-model
settings), `src/sase/llm_provider/model_alias_policy.py`

#### Launch-scoped alias overrides

A prompt can override the five size aliases (or a custom alias) for its SASE-created
launch lineage with keyword arguments on `%model(...)`:

```text
%model(opus, medium=codex/gpt-6.1-sol)
%model(medium=claude/sonnet)
```

The positional value, when present, selects the current agent's model. Without one, the
current agent starts from `llm_provider.default_model` and resolves through the normal
alias chain using the map at every hop — so a keyword matching the alias that
`default_model` currently references (`large=` under the shipped default) changes the
current launch directly, while a keyword for an unrelated alias normally affects only a
later delegated launch that routes through that alias. Keyword keys are bare size or
custom alias names — `llm_provider.default_model`, `epic_lander_model`, and
`big_epic_lander_model` are config fields, not keys accepted here. Values may be
concrete model targets or `@other_alias` references. The map is stored in agent metadata
and inherited by SASE-created plan/coder follow-ups. An explicit
`%id(suffix, session=parent)` attachment inherits it only when the attached prompt
supplies no alias keywords. Ordinary nested launches do not inherit it. This is a
propagation rule, not a change to `sase.yml` or `~/.sase/llm_override.json`.

Launch-scoped values have the highest alias-resolution precedence. They beat
machine-wide per-alias temporary overrides and configured/implicit aliases at every hop;
a launch-scoped keyword matching the alias `default_model` references also beats the
machine-wide temporary override on the `default model` setting. An explicit concrete
model for the current agent remains concrete, while an explicit alias is resolved
through this launch map. See
[Launch-Scoped Model Alias Overrides](../../macros.md#launch-scoped-model-alias-overrides)
for syntax and validation rules.

> **Migration note:** `@worker`, `@other`, `@coder`, registered `@<provider>_coder`
> aliases, `@epic_creator`, `@phase_worker`, and its `<size>_phase_worker` aliases were
> retired in epic sase-5d — accepted tales route by tale size, and there is no
> epic-creator role. Epic sase-mf then retired the entire generation that replaced them:
> `@default`, `@epic_lander`, `@big_epic_lander`, the five `@<size>_worker` aliases, the
> capability/cost aliases `@smart`, `@smarter`, `@smartest`, `@cheap`, `@cheaper`,
> `@cheapest`, and the automatic `worker` bucket. Use `llm_provider.default_model`,
> `epic_lander_model`, and `big_epic_lander_model`, plus the five `@xsmall`...`@xlarge`
> size aliases, going forward. `sase doctor -C config.model_aliases` flags stale config
> and names the exact replacement for each retired name.

### Explicit Provider/Model Syntax

Use `provider/model` to specify both explicitly:

```
%model:codex/o3
%model:claude/opus
%model:agy/gemini-3.6-flash-high
%model:qwen/qwen3.6-plus
%model:opencode/anthropic/claude-sonnet-4-5
%model:muse/muse-spark-1.3
%model:grok/grok-4.7
%model:fakey/fakey-large
```

In sase's TUI and macro-aware editors, `%model:` completion includes provider rows such
as `claude/`, `codex/`, and `opencode/` after concrete models and aliases. Typing or
accepting a visible provider prefix scopes the menu to that provider, so `%m:claude/`
offers `claude/opus`, `claude/sonnet`, and the rest of Claude's model catalog while
`%m:opencode/anthropic/` continues narrowing inside OpenCode's slash-bearing model
names.

### Automatic Provider Resolution

Known model names are automatically mapped to their provider. The per-provider catalog
is the generated [Built-in Model Catalog](#built-in-model-catalog) below — consult it
for the current names rather than any list here.

Each installed plugin contributes its own model names via the `llm_known_model_names()`
hook.

`fakey` is deliberately hidden from sase's TUI model picker and the `%model` completion
menu (a provider opts in via the `llm_hidden_from_model_pickers()` hook) since it exists
only for testing. Routing, resolution, autodetect, and short aliases are unaffected —
`%model:fakey-large` and the explicit `fakey/fakey-large` syntax above still work, and
typing either by hand (or via the picker's `Custom...` entry) still selects it.

For unrecognized model names, the prompt falls back to the default provider and a
warning is logged at invocation time.

Source: `src/sase/llm_provider/registry.py`, `src/sase/llm_provider/_invoke.py`

### Built-in Model Catalog

The bundled manifest catalogues every model each built-in provider knows by name, in
picker and completion order. This table is generated from
`src/sase/llm_provider/models.yml`:

<!-- BEGIN GENERATED: known-models -->

| Provider | Known models                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| agy      | `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low`, `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, `gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `gemini-3.7-flash-low`, `gemini-3.6-flash-high`, `gemini-3.6-flash-medium`, `gemini-3.6-flash-low`, `gemini-3.5-flash-high`, `gemini-3.5-flash-medium`, `gemini-3.5-flash-low`, `gemini-3.1-pro-high`, `gemini-3.1-pro-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium` |
| claude   | `opus`, `sonnet`, `haiku`, `claude-haiku-5-5`, `claude-haiku-4-5`, `claude-fable-5`                                                                                                                                                                                                                                                                                                                                                                                                                       |
| codex    | `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `codex-mini-latest`, `o3`, `o4-mini`, `gpt-5.4`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`                                                                                                                                                                                                                                                        |
| grok     | `grok-4.7`, `grok-4.6`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| muse     | `muse-wonder-1.0`, `muse-wonder-1.0-contributor`, `muse-wonder-full-1.0`, `muse-wonder-full-1.0-contributor`, `muse-spark-1.3`, `muse-spark-1.3-contributor`, `muse-spark-1.2`, `muse-spark-1.2-contributor`, `muse-spark-1.1`                                                                                                                                                                                                                                                                            |
| opencode | `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`, `openai/gpt-5`, `openai/gpt-5-mini`, `google/gemini-3-flash-preview`, `qwen/qwen3-coder-plus`                                                                                                                                                                                                                                                                                                                                                 |
| qwen     | `qwen3.6-plus`, `qwen3-coder-plus`, `qwen3-coder-flash`, `qwen3-max`, `qwen-plus`, `qwen-max`                                                                                                                                                                                                                                                                                                                                                                                                             |

<!-- END GENERATED: known-models -->

### Model Short Aliases

Providers also declare compact display shorthands for long model ids via the
`llm_model_short_aliases()` hook. These shorthands appear in
[provider/model agent-name suffixes](../tui/agent-workflows.md#providermodel-suffixes)
on the Agents tab and act as filter terms in the coder model picker. They are
display-only: `%model` resolution uses known model names and
[configured model aliases](#configured-model-aliases), not these shorthands. For
example, `%model:fable` does _not_ select `claude-fable-5` — it falls back to the
default provider (with a warning) unless you define `fable` as a configured model alias
yourself.

<!-- BEGIN GENERATED: model-short-aliases -->

| Provider | Shorthands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| agy      | `gemini-4-argon-high` → `argon4h`, `gemini-4-argon-medium` → `argon4m`, `gemini-4-argon-low` → `argon4l`, `gemini-3.8-flash-high` → `flash38h`, `gemini-3.8-flash-medium` → `flash38m`, `gemini-3.8-flash-low` → `flash38l`, `gemini-3.7-flash-high` → `flash37h`, `gemini-3.7-flash-medium` → `flash37m`, `gemini-3.7-flash-low` → `flash37l`, `gemini-3.6-flash-high` → `flash36h`, `gemini-3.6-flash-medium` → `flash36m`, `gemini-3.6-flash-low` → `flash36l`, `gemini-3.5-flash-high` → `flash35h`, `gemini-3.5-flash-medium` → `flash35m`, `gemini-3.5-flash-low` → `flash35l`, `gemini-3.1-pro-high` → `pro31h`, `gemini-3.1-pro-low` → `pro31l`, `claude-sonnet-4-6` → `sonnet46`, `claude-opus-4-6-thinking` → `opus46t`, `gpt-oss-120b-medium` → `gptoss120m` |
| claude   | `claude-haiku-5-5` → `haiku55`, `claude-haiku-4-5` → `haiku45`, `claude-fable-5` → `fable`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| codex    | `gpt-6-astra` → `astra`, `gpt-6.1-sol` → `gpt61sol`, `gpt-6-luna` → `gpt6luna`, `codex-mini-latest` → `mini`, `gpt-5.6-sol` → `gpt56sol`, `gpt-5.6-terra` → `gpt56terra`, `gpt-5.6-luna` → `gpt56luna`, `gpt-5.5` → `gpt55`, `gpt-5.4` → `gpt54`, `gpt-5.3-codex-spark` → `gpt53spark`, `gpt-5.3-codex` → `gpt53`, `gpt-4.1` → `gpt41`, `gpt-4.1-mini` → `gpt41m`, `gpt-4o-mini` → `gpt4om`                                                                                                                                                                                                                                                                                                                                                                             |
| grok     | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| muse     | `muse-wonder-1.0` → `wonder10`, `muse-wonder-1.0-contributor` → `wonder10c`, `muse-wonder-full-1.0` → `wonderfull10`, `muse-wonder-full-1.0-contributor` → `wonderfull10c`, `muse-spark-1.3` → `spark13`, `muse-spark-1.3-contributor` → `spark13c`, `muse-spark-1.2` → `spark12`, `muse-spark-1.2-contributor` → `spark12c`, `muse-spark-1.1` → `spark11`                                                                                                                                                                                                                                                                                                                                                                                                              |
| opencode | `anthropic/claude-sonnet-4-5` → `sonnet45`, `anthropic/claude-opus-4-5` → `opus45`, `openai/gpt-5` → `gpt5`, `openai/gpt-5-mini` → `gpt5m`, `google/gemini-3-flash-preview` → `flash3`, `qwen/qwen3-coder-plus` → `qwen3cp`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| qwen     | `qwen3.6-plus` → `qwen36p`, `qwen3-coder-plus` → `qwen3cp`, `qwen3-coder-flash` → `qwen3cf`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

<!-- END GENERATED: model-short-aliases -->

The hidden `fakey` test provider is not part of the shipped manifest; it additionally
declares `fakey-large` → `fakeyl` and `fakey-small` → `fakeys` for tests.

Source: `src/sase/llm_provider/models.yml` (built-in providers answer the
`llm_model_short_aliases()` hook from the manifest)

### Model Advisories

A provider can flag individual models with an advisory through the
[`llm_model_advisories()`](../../plugins.md#llm-provider-install-metadata-and-advisories)
hook — a discounted tier that trains on its inputs, a preview model with no stability
guarantee, and so on. Each advisory is
`{"severity": "warn"|"info", "label": <short>, "detail": <sentence>}`. Providers that
omit the hook contribute nothing, so the map is empty on an install with no
advisory-flagged models.

Advisories render at every point a user meets the model, all reading from the registry
so no render site hardcodes a model id:

| Surface                                                              | Rendering                                                      |
| -------------------------------------------------------------------- | -------------------------------------------------------------- |
| [sase's TUI model picker](../tui/agent-workflows.md#custom-approval) | `⚠ <label>` suffix on the row, with `detail` as secondary text |
| `%model` completion detail                                           | `— ⚠ <label>` appended to the completion description           |
| [Resolved model label](#model-tier-system)                           | An inline `⚠` marker for the run's whole life                  |
| `sase doctor -C llm.model_advisory`                                  | A **warning** naming each configured route that lands on one   |

`⚠` (orange) marks `severity: "warn"`; `ⓘ` (blue) marks `severity: "info"`.

The doctor check resolves the configured default and every configured model alias and
warns — it never fails — when one routes SASE traffic to an advisory-flagged model.
Opting in globally is the user's call; doing it without being told is not. For that
reason, no bundled provider's tier map points at an advisory-flagged model, and a test
asserts that so a future cost optimization cannot quietly reintroduce the problem. The
tier map is not the only automatic route, though: whichever shipped size aliases include
an advisory-flagged member (see the generated
[shipped size-alias defaults](#implicit-role-aliases)) warn on a stock install,
whichever member the round-robin cursor currently selects. Override
`llm_provider.model_aliases.builtin.<size>` to drop the member.

The bundled advisories are the manifest's `advisories` entries (see
[Muse Code Integration](muse.md#muse-code-integration) for the Contributor rationale,
and [Antigravity (`agy`) Integration](agy.md#antigravity-agy-integration) for the
informational Gemini 4 Argon entitlement advisory). Muse Wonder Full also carries an
informational advisory because Muse Code offers it only on Power and Maximum plans and
Meta does not serve it through the Meta Model API.

Source: `model_advisory_map()` / `model_advisory_for()` in
`src/sase/llm_provider/registry.py`, `src/sase/doctor/checks_providers_advisory.py`

## Reasoning Effort

A prompt can request a reasoning-effort level for its agent, and a config default can
apply one to every launch. The public surface spells it `effort`; the threaded/stored
field is named `reasoning_effort` everywhere internally.

### Requesting an Effort

There are five ways an effort reaches a launch, in precedence order:

1. An explicit per-prompt `%effort:<level>` directive, or the `@<level>` suffix on a
   `%model`/alias reference (`%model:opus@xhigh`, `%model:@large@medium`). See
   [Effort Directive](../../macros.md#effort-directive) for the directive syntax and
   per-branch fan-out (`%{%m:opus@xhigh | %m:sonnet@low}`).
2. A trailing effort on the selected alias target, temporary model override, or pool
   member (for example `claude/opus@medium`). An outer alias-reference suffix wins over
   effort carried by the alias target.
3. An active machine-wide temporary default-effort override from
   `~/.sase/llm_effort_override.json`.
4. The `llm_provider.default_effort` config value, applied when none of the
   higher-precedence sources sets effort.
5. Nothing — the provider runs at its own built-in default.

The canonical effort vocabulary, ordered least → most, is `none`, `minimal`, `low`,
`medium`, `high`, `xhigh`, `max`. Spelling is validated globally; _which_ levels a given
provider honors is decided per provider (below).

sase's TUI Launch Control shows the launch-effective default in its header
(`default effort: @ <level>`), or says `provider default` when none is configured. The
top-bar launch-default pill shows the same launch-effective default as
`<shortest %model value>[@<effort>]` (for example `grok-4.7@high`, or `codex/o3@high`
when the bare model name does not unambiguously name its provider), omitting the suffix
when that value is unset. The pill is toned with the launch default's provider — the
model in that provider's model hue and the `@<effort>` suffix in a recessive tone from
the same hue family — while its hover tooltip keeps the unchanged `PROVIDER(model)`
form. An active temporary value carries an override countdown plus an annotation for the
underlying configured value. Alias-borne effort appears only on rows that explicitly pin
or inherit a suffix, beside the provider/model badge; the description strip compares it
with the current effective default. For pools, each member keeps its own suffix in the
member list and the row badge reflects the next selected member.

Press `Ctrl+E` in Launch Control for the global default-effort workflow. `e` opens a
permanent Edit and `o` opens a temporary Override; when an override is active, `x`
clears it. Both paths use the canonical single-key ladder (`1` `none` through `7`
`max`). Edit additionally offers `0` Provider default and writes the empty sentinel to
the user-base `sase.yml` after a source-preserving preview. With `use_chezmoi`, the
preview names and writes the chezmoi source, applies its home target, and offers the
standard tracked commit/pull/push flow when that source is dirty in Git.

Temporary Override reuses the full alias duration UI: `15m`, `30m`, `1h`, `2h`, `4h`,
Until cleared, combined custom durations, and `t` for an exact configured-timezone end.
The versioned `~/.sase/llm_effort_override.json` record contains `effort`, `created_at`,
optional `expires_at`, and `source`. Writes are atomically replaced under a bounded
advisory lock; malformed and expired state self-cleans, with `now >= expires_at`
considered expired. A permanent edit does not displace an active temporary override, and
neither kind of change mutates already-running agents.

### Explicit vs. Default Semantics

The distinction between an explicitly requested effort and a config-default effort
governs what happens on a provider that cannot honor the requested level:

- **Explicit** (`%effort`/`@effort`): an unsupported level raises an error — SASE never
  silently launches at a different effort than you asked for.
- **Config-derived** (an alias-target suffix, temporary default override, or
  `llm_provider.default_effort`): best-effort. Unsupported levels are logged and skipped
  so shared configuration never breaks an `agy`/`qwen` run.

### Provider Support Matrix

| Provider            | Mechanism                             | Supported levels                   | Rejected           |
| ------------------- | ------------------------------------- | ---------------------------------- | ------------------ |
| Claude              | `--effort <level>`                    | low, medium, high, xhigh, max      | none, minimal      |
| Codex               | `-c model_reasoning_effort="<level>"` | minimal, low, medium, high, xhigh  | none, max          |
| OpenCode            | `--variant <level>`                   | all (validated by OpenCode/model)  | —                  |
| Antigravity (`agy`) | none today                            | —                                  | all                |
| Qwen                | none today                            | —                                  | all                |
| Muse Code           | `--reasoning-effort <level>`          | all seven (`max` for standard 1.3) | —                  |
| Grok Build          | `--effort <level>`                    | low, medium, high, xhigh           | none, minimal, max |
| Fakey               | `--effort <level>`                    | all                                | —                  |

For `agy` and `qwen` (no reasoning-effort mechanism today), every level is
"unsupported": an explicit effort raises, while a config-default effort is skipped with
a warning. The effort args are appended alongside the existing
[`SASE_LLM_*_ARGS` / `SASE_<P>_LARGE_ARGS`](../environment-variables.md#environment-variable-reference)
escape hatches, which remain available.

Source: `src/sase/macro/effort.py` (vocabulary + `split_model_effort`),
`src/sase/llm_provider/config.py` (`resolve_effective_effort`, the temporary-effort
facade, and the public `default_reasoning_effort` config reader),
`src/sase/llm_provider/_effort_args.py` (per-provider translation).

## Model Tier System

The model tier system abstracts away specific model names. Callers request either
`"large"` (most capable) or `"small"` (faster/cheaper), and the provider maps the tier
to a concrete model.

### Type Definition

```python
ModelTier = Literal["large", "small"]
```

### Provider Tier Defaults

Each built-in provider maps the two tiers to one of its catalogued models. This table is
generated from `src/sase/llm_provider/models.yml`; each provider section above carries
its own generated tier table with the same values:

<!-- BEGIN GENERATED: provider-tier-defaults -->

| Provider | Large tier                    | Small tier             |
| -------- | ----------------------------- | ---------------------- |
| agy      | `gemini-3.7-flash-high`       | `gemini-3.7-flash-low` |
| claude   | `opus`                        | `sonnet`               |
| codex    | `gpt-6.1-sol`                 | `codex-mini-latest`    |
| grok     | `grok-4.7`                    | `grok-4.6`             |
| muse     | `muse-wonder-1.0`             | `muse-spark-1.3`       |
| opencode | `anthropic/claude-sonnet-4-5` | `openai/gpt-5-mini`    |
| qwen     | `qwen3.6-plus`                | `qwen3-coder-flash`    |

<!-- END GENERATED: provider-tier-defaults -->

### Legacy Mapping

The old `"big"`/`"little"` terminology is still supported for backward compatibility:

| Old Value  | New Tier  | Display Label |
| ---------- | --------- | ------------- |
| `"big"`    | `"large"` | `BIG`         |
| `"little"` | `"small"` | `LITTLE`      |

The `model_size` parameter on `invoke_agent()` is deprecated. Use `model_tier` instead.

### Global Override

The model tier can be overridden globally via environment variable or CLI flag. The
override forces ALL invocations to use the specified tier regardless of what the caller
requests.

**Resolution order:**

1. `SASE_MODEL_TIER_OVERRIDE` env var (accepts `"large"`, `"small"`, `"big"`,
   `"little"`)
2. `SASE_MODEL_SIZE_OVERRIDE` env var (legacy, same values)
3. `--model-tier` / `--model-size` CLI flag (sets the env var)
4. Caller's `model_tier` parameter (default: `"large"`)

### Maintaining the Built-in Catalog

A routine built-in model addition, tier change, or size-pool retune is a one-file edit:

```bash
# 1. Edit the bundled manifest.
$EDITOR src/sase/llm_provider/models.yml
# 2. Regenerate the mirrored tables in this document.
just fix
# 3. Verify formatting, policy, and tests.
just check
```

`just check` (and CI) fails on stale generated content or invalid manifest policy, so a
forgotten regeneration or a policy breach is caught before landing. The generated
Markdown is an expected review diff — no hand edits to prose tables are needed.

Three concepts share the manifest but mean different things:

- **Catalog membership** ([Built-in Model Catalog](#built-in-model-catalog)) is what a
  provider knows by name: picker rows, `%model:provider/model` routing, and completion.
- **Tier defaults** ([Provider Tier Defaults](#provider-tier-defaults)) are each
  provider's `"large"`/`"small"` invocation choices.
- **Pool selection** ([Implicit role aliases](#implicit-role-aliases)) is which catalog
  members the five shipped size aliases (`@xsmall` … `@xlarge`) route to, at which
  effort.

## Role Aliases for Delegated Work

Delegated launches do not use a separate "worker lane". Instead, each delegated role
resolves through a size-specific [implicit role alias](#implicit-role-aliases), or, for
epic land agents, through one of the two epic-lander launch-model settings:

- **Coder follow-ups** from an accepted tale use the validated tale size to select
  `@xsmall`, `@small`, `@medium`, `@large`, or `@xlarge` directly. Legacy tale plans
  without size metadata use `@medium`.
- **`sase bead work` phase agents** without an explicit per-bead model use the size
  alias matching their normalized size: `@xsmall`, `@small`, `@medium`, `@large`, or
  `@xlarge`. See [Implicit role aliases](#implicit-role-aliases) for the current shipped
  defaults. `xsmall`, `small`, and `medium` phases implement directly; only `large` and
  `xlarge` phases receive `#plan`. An explicit per-bead model is accepted at every size
  and always wins without changing the size-based planning policy.
- **Standalone task-bead workers** use the task's explicit model when set. Otherwise, a
  stored task size selects the matching size alias above, while a legacy task without
  size metadata uses `@small`. Like epic phases, `large` and `xlarge` tasks receive an
  automatic `#plan`; xsmall, small, and medium tasks implement directly. New tasks
  require an explicit size, and agents use `/sase_new_task` before creation to rule out
  duplicates and active epic work; the legacy fallback exists only for stored historical
  records.
- **Epic land agents** without an explicit land model use
  `llm_provider.epic_lander_model`, or `llm_provider.big_epic_lander_model` when their
  authored phase count meets `bead.big_epic_phase_threshold` (default `5`). Both
  settings resolve independently of `llm_provider.default_model` and of the size
  aliases, and each ships with its own default (`@large` and `@xlarge` respectively) —
  see [Implicit role aliases](#implicit-role-aliases).

Validated Epic approvals create beads and launch `sase bead work` directly; there is no
epic-creator model lane.

Planning agents stay on `llm_provider.default_model` (shipped `@large`) unless their
prompt explicitly asks for a different model. To send delegated work to a second
provider, configure the matching size alias under `llm_provider.model_aliases.builtin`,
or point one of the three scalar launch-model settings at a different target:

```yaml
llm_provider:
  provider: claude
  default_model: "@large"
  epic_lander_model: "@large"
  big_epic_lander_model: codex/gpt-6.1-sol # threshold-selected epic landers run on Codex
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low
      small: claude/haiku | codex/gpt-4.1-mini
      medium: codex/gpt-5.5@xhigh | claude/sonnet@xhigh
      large: codex/gpt-6.1-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max # xlarge phase/epic maximum-effort target
```

Xsmall phases/tasks/tale-follow-ups use the `@xsmall` pool, small ones the `@small`
pool, medium ones `@medium`, large ones `@large`, and xlarge ones the `@xlarge` ordered
fallback. Sizeless standalone tasks fall back to `@small`; sizeless tale follow-ups fall
back to `@medium`. Normal epic landers use `llm_provider.epic_lander_model`, and
threshold-selected epic landers use `llm_provider.big_epic_lander_model`, independent of
the size aliases and of `llm_provider.default_model`. See
[Implicit role aliases](#implicit-role-aliases) for the current shipped defaults.
Explicit `%model` directives, approval-picker model choices, direct alias overrides, and
per-bead/land model metadata always win over role defaults.

> The previous `llm_provider.worker_models` map, the `~/.sase/llm_worker_override.json`
> worker temporary override, and the later
> `@default`/`@epic_lander`/`@big_epic_lander`/`@<size>_worker`/capability-alias
> generation were all removed (epics sase-5d and sase-mf). See the
> [migration note](#launch-scoped-alias-overrides) above.

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Provider routing](routing.md) — temporary selection controls.
