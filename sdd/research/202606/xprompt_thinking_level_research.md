---
create_time: 2026-06-22
updated_time: 2026-06-22
status: research
---

# XPrompt Thinking Level Research

## Question

How should SASE let an xprompt specify a model or LLM provider plus a "thinking level", for example `xhigh`?

The desired authoring shape is something like:

```text
%model:codex/gpt-5.5
%effort:xhigh
```

inside an xprompt, so reusable xprompts can choose both the model lane and the amount of reasoning effort to spend.

## Short Answer

Add a new reserved `%` directive for reasoning effort. Do not encode effort inside the `%model` string.

The recommended surface is:

```text
%model:codex/gpt-5.5
%effort:xhigh
```

Internally, parse this into typed invocation options, for example
`LLMInvocationOptions(reasoning_effort="xhigh")`, and pass those options through the LLM provider boundary. Providers
then translate the option into the provider-specific command-line or API shape:

- Codex: `codex exec ... -c model_reasoning_effort="xhigh"`
- Claude Code: `claude ... --effort xhigh`
- Antigravity: initially unsupported as a separate option; use model names or aliases that already include `(High)`,
  `(Medium)`, or `(Low)`.
- Qwen Code: initially unsupported unless its CLI grows a verified option.
- OpenCode: support only after verifying a stable per-run CLI/config path; its docs expose reasoning options in model
  and agent configuration, but this repository's provider invokes `opencode run` directly.

Add `%think:<level>` or `%reasoning:<level>` only as aliases if the extra spelling is worth the completion/UI cost. The
canonical directive should be `%effort` because it matches Claude Code's CLI, OpenAI's "reasoning effort" terminology,
and avoids overloading SASE's existing "thinking" UI concepts.

## Current SASE Shape

### XPrompts can already inject launch controls

SASE preprocesses prompts in a useful order:

1. render Jinja/workflow context;
2. canonicalize project aliases;
3. expand `#` xprompts;
4. extract `%` directives.

That means an xprompt can already emit `%model`, `%wait`, `%name`, and related launch controls. This is the right place
for a future `%effort` directive: it is a runner control, not text for the model.

Relevant files:

- `src/sase/xprompt/_directive_types.py:20` defines the closed directive vocabulary.
- `src/sase/xprompt/_directive_types.py:53` defines `PromptDirectives`, currently with `model` but no effort field.
- `src/sase/xprompt/directives.py` extracts `%` directives and strips them from the model prompt.
- `src/sase/llm_provider/preprocessing.py` expands xprompts before directive extraction.
- `xprompts/reads.md` is an existing example of an xprompt that emits `%model`, `%name`, `%group`, and `%wait`.

The existing research note `sdd/research/202606/directives_xprompts_architecture_consolidated.md` also recommends
keeping `#` for prompt/workflow modules and `%` for reserved launch controls. Effort belongs on the `%` side of that
boundary.

### Model selection is currently string-only

The current provider invocation path extracts only `PromptDirectives.model`, resolves it to a provider/model pair, and
passes a string model override to providers:

- `src/sase/llm_provider/_invoke.py:139` reads `result_directives.model`.
- `src/sase/llm_provider/_invoke.py:144` resolves explicit `provider/model` values.
- `src/sase/llm_provider/_invoke.py:212` calls `provider.invoke(..., model_override=model_override)`.
- `src/sase/llm_provider/base.py` and `src/sase/llm_provider/_hookspec.py` expose only `prompt`, `model_tier`,
  `suppress_output`, and `model_override`.

There is no typed invocation-options object today. Adding effort by appending syntax to `model_override` would make
this path more brittle instead of clarifying it.

### The config model is also string-only

`llm_provider.model_aliases` and `llm_provider.worker_models` currently clean config values as string mappings:

- `src/sase/llm_provider/config.py:33` reads `model_aliases`.
- `src/sase/llm_provider/config.py:54` reads `worker_models`.
- `src/sase/llm_provider/config.py:84` resolves model aliases.
- `config/sase.schema.json:632` defines `model_aliases`.

This is fine for an MVP because an xprompt can emit `%model` and `%effort` as separate directives. A later enhancement
could make aliases structured so a reusable alias can bundle model and effort:

```yaml
llm_provider:
  model_aliases:
    codex-hard:
      model: codex/gpt-5.5
      reasoning_effort: xhigh
```

Keep the current string form as backwards-compatible shorthand.

## Provider Landscape

### OpenAI / Codex

OpenAI's reasoning model docs expose a `reasoning.effort` parameter. Supported values are model-dependent and can
include `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`. Higher effort generally trades more latency and token
use for better answers on harder tasks.

Codex config exposes `model_reasoning_effort` with values `minimal`, `low`, `medium`, `high`, and `xhigh`, plus
`model_reasoning_summary`. The local `codex exec --help` did not show a dedicated reasoning flag, but it does support
`-c key=value`, so a per-run command can pass:

```text
-c model_reasoning_effort="xhigh"
```

Current SASE Codex adapter:

- `src/sase/llm_provider/codex.py:293` defines `invoke`.
- `src/sase/llm_provider/codex.py:325` passes `--model`.
- `src/sase/llm_provider/codex.py:338` appends extra args from `SASE_LLM_LARGE_ARGS` or `SASE_CODEX_LARGE_ARGS`.

The env-var arg escape hatch can set effort today, but it is process/tier scoped, not per xprompt or per launch. A
typed directive is a better fit.

### Anthropic / Claude Code

Claude Code exposes `--effort <level>` with levels `low`, `medium`, `high`, `xhigh`, and `max`; available levels depend
on the selected model. Claude Code model settings also include `effortLevel`, with `max` described as session-only.

Current SASE Claude adapter:

- `src/sase/llm_provider/claude.py:127` defines `invoke`.
- `src/sase/llm_provider/claude.py:206` passes `--model`.
- `src/sase/llm_provider/claude.py:153` appends tier/provider-specific extra args from env vars.

This is the cleanest adapter to support after Codex: append `--effort <level>` when the directive is present.

### Google Gemini / Antigravity

Gemini API documentation uses `thinking_level`, with values such as `minimal`, `low`, `medium`, and `high` depending
on the model. Gemini 3 docs describe defaults and recommend constraining thinking level to lower values for faster
low-latency cases.

The local Antigravity CLI path is different. `agy --help` showed `--model` but no standalone effort option, and
`agy models` exposed model names that already encode levels:

- `Gemini 3.5 Flash (Low)`
- `Gemini 3.5 Flash (Medium)`
- `Gemini 3.5 Flash (High)`
- `Gemini 3.1 Pro (Low)`
- `Gemini 3.1 Pro (High)`
- `Claude Sonnet 4.6 (Thinking)`
- `Claude Opus 4.6 (Thinking)`

Current SASE Antigravity adapter:

- `src/sase/llm_provider/agy.py:365` defines `invoke`.
- `src/sase/llm_provider/agy.py:397` passes `--model`.
- `src/sase/llm_provider/agy.py:406` appends tier/provider-specific extra args from env vars.

Because SASE already passes exact Antigravity model names, the first implementation should not invent an effort mapping
for `agy`. Prefer model aliases such as `flash-high -> agy/Gemini 3.5 Flash (High)` until Antigravity exposes a stable
per-run `thinking_level` option.

### OpenCode

OpenCode docs list built-in OpenAI model variants with reasoning efforts including `none`, `minimal`, `low`, `medium`,
`high`, and `xhigh`, and Anthropic variants including `high` and `max`. OpenCode agent docs also show provider-specific
model options such as `reasoningEffort`.

Current SASE OpenCode adapter:

- `src/sase/llm_provider/opencode.py:139` defines `invoke`.
- `src/sase/llm_provider/opencode.py:156` passes `--model`.
- `src/sase/llm_provider/opencode.py:164` appends tier/provider-specific extra args from env vars.

`opencode` was not installed in this workspace, so the direct `opencode run` flag shape could not be verified. Treat
per-run effort as unsupported until a local version or docs confirm the exact invocation shape.

### Qwen Code

The local `qwen --help` output showed `--model` but no `--effort`, `--reasoning`, or `--thinking` option. Qwen's model
provider docs focus on provider/model configuration rather than a standard reasoning-effort flag.

Current SASE Qwen adapter:

- `src/sase/llm_provider/qwen.py:136` defines `invoke`.
- `src/sase/llm_provider/qwen.py:154` passes `--model`.
- `src/sase/llm_provider/qwen.py:160` appends tier/provider-specific extra args from env vars.

Support should remain unsupported-by-default until the CLI exposes a stable option.

## Design Alternatives

### Alternative A: Encode effort in `%model`

Example:

```text
%model:codex/gpt-5.5/xhigh
```

This is not recommended.

SASE already uses `provider/model` syntax, and some provider-local model IDs naturally contain slashes, for example
OpenCode-style identifiers such as `anthropic/claude-sonnet-4-5`. Adding another suffix grammar would make model
parsing ambiguous and would interfere with exact model names, aliases, short display aliases, and known-model provider
resolution.

The model string should identify the model. Effort should be a separate launch attribute.

### Alternative B: Use ordinary xprompts

Example:

```text
#thinking(xhigh)
```

This is also not recommended.

Effort is privileged launch metadata that must be parsed, validated, logged, and stripped before the model receives the
prompt. It belongs in the directive/control plane, not in the open prompt-module namespace. A project-local xprompt
should not be able to silently shadow a reserved launch control.

### Alternative C: Add a new `%effort` directive

Example:

```text
%model:claude/opus
%effort:xhigh
```

This is the recommended path.

It fits the existing control-plane boundary, composes naturally with current xprompt expansion order, and lets the
provider adapters translate one normalized option into provider-specific flags. It also composes with fanout:

```text
%model(codex/gpt-5.5,claude/opus)
%effort:xhigh
```

This means "run both model variants with the same effort." If SASE later needs per-variant effort, use the existing
alternative/fanout machinery instead of overloading `%model`:

```text
%alt(%model:codex/gpt-5.5 %effort:xhigh, %model:claude/opus %effort:high)
```

## Implementation Sketch

### 1. Add directive parsing

Extend `PromptDirectives`:

```python
@dataclass
class PromptDirectives:
    model: str | None = None
    reasoning_effort: str | None = None
```

Add `effort` to `_KNOWN_DIRECTIVES`, with optional aliases:

```python
_DIRECTIVE_ALIASES = {
    "think": "effort",
    "reasoning": "effort",
}
```

Normalize values to lowercase and validate against a global union:

```text
none, minimal, low, medium, high, xhigh, max
```

Provider adapters should still decide what is supported. For example, `max` is valid for Claude Code but should produce
a clear unsupported-effort error for Codex.

### 2. Add typed invocation options

Add a small dataclass near the LLM provider boundary:

```python
@dataclass(frozen=True)
class LLMInvocationOptions:
    reasoning_effort: str | None = None
```

Pass this through `invoke_agent()` and provider hooks:

```python
provider.invoke(
    query,
    model_tier=model_tier,
    suppress_output=suppress_output,
    model_override=model_override,
    invocation_options=invocation_options,
)
```

This is cleaner than using environment variables because the value is scoped to a single launch and works correctly
with workflows, prompt steps, retries, and fanout.

### 3. Translate in provider adapters

Codex:

```python
if options.reasoning_effort:
    cmd.extend(["-c", f'model_reasoning_effort="{options.reasoning_effort}"'])
```

Claude:

```python
if options.reasoning_effort:
    cmd.extend(["--effort", options.reasoning_effort])
```

Antigravity, Qwen, and OpenCode should raise or log a clear unsupported-option diagnostic until their per-run flag
shape is verified. For Antigravity specifically, prefer model aliases that select exact level-bearing model names.

### 4. Persist metadata

Add the normalized effort value to agent metadata so the run is inspectable later:

```json
{
  "model": "gpt-5.5",
  "llm_provider": "codex",
  "reasoning_effort": "xhigh"
}
```

Likely touch points:

- `src/sase/axe/run_agent_directives.py` for `agent_meta.json` creation.
- `src/sase/llm_provider/_invoke.py` for logging context / chat metadata.
- `src/sase/xprompt/workflow_executor_steps_prompt.py` for workflow step markers.
- retry metadata paths if they clone or reconstruct model/provider state.

### 5. Consider structured aliases later

After `%effort` works, add structured model aliases so common pairs are easy to reuse:

```yaml
llm_provider:
  model_aliases:
    hard:
      model: codex/gpt-5.5
      reasoning_effort: xhigh
    quick:
      model: claude/sonnet
      reasoning_effort: low
```

Then:

```text
%model:hard
```

could expand to both model and effort. This should be a second phase because it requires schema changes and a richer
alias return type.

## Test Plan

Add focused tests for:

- extracting `%effort:xhigh`, stripping it from prompt text, and preserving existing `%model` behavior;
- duplicate effort directives using the same last-wins behavior as `%model`;
- alias handling for `%think:xhigh` or `%reasoning:xhigh` if aliases are accepted;
- validation and provider-specific unsupported-effort diagnostics;
- passing `LLMInvocationOptions` from `invoke_agent()` to providers;
- Codex command construction with `-c model_reasoning_effort="xhigh"`;
- Claude command construction with `--effort xhigh`;
- metadata persistence in `agent_meta.json`;
- xprompt expansion that injects both `%model` and `%effort`;
- fanout where `%model(a,b)` shares one `%effort`, and `%alt(...)` can vary effort per branch.

No broad integration test is needed for the first slice unless provider hook signature changes affect plugin loading.

## Recommended Solution

Implement `%effort:<level>` as a new reserved xprompt/directive launch control, store it internally as
`reasoning_effort`, and pass it through a typed `LLMInvocationOptions` object to providers.

Support Codex and Claude first because both have verified per-run mechanisms:

- Codex via `-c model_reasoning_effort="<level>"`;
- Claude via `--effort <level>`.

Leave Antigravity, Qwen, and OpenCode unsupported for separate effort until their CLI surfaces are verified. For
Antigravity, use exact model names or aliases that encode the desired level.

Do not modify the `%model` grammar to carry effort. A separate directive is simpler, clearer, safer for existing model
IDs, and consistent with SASE's current split between reusable xprompt content and reserved launch controls.

## Sources

- SASE local code and docs:
  - `src/sase/xprompt/_directive_types.py`
  - `src/sase/xprompt/directives.py`
  - `src/sase/llm_provider/_invoke.py`
  - `src/sase/llm_provider/{codex,claude,agy,qwen,opencode}.py`
  - `docs/llms.md`
  - `docs/xprompt.md`
  - `sdd/research/202606/directives_xprompts_architecture_consolidated.md`
- OpenAI reasoning models: <https://developers.openai.com/api/docs/guides/reasoning>
- OpenAI latest model guide: <https://developers.openai.com/api/docs/guides/latest-model>
- OpenAI Codex config reference: <https://developers.openai.com/codex/config-reference>
- Anthropic Claude Code CLI reference: <https://docs.anthropic.com/en/docs/claude-code/cli-reference>
- Anthropic Claude Code model configuration: <https://docs.anthropic.com/en/docs/claude-code/model-config>
- Anthropic effort API docs: <https://platform.claude.com/docs/en/build-with-claude/effort>
- Google Gemini thinking docs: <https://ai.google.dev/gemini-api/docs/thinking>
- Google Gemini 3 docs: <https://ai.google.dev/gemini-api/docs/gemini-3>
- Google Antigravity models docs: <https://antigravity.google/docs/models>
- OpenCode model docs: <https://opencode.ai/docs/models/>
- OpenCode agent docs: <https://opencode.ai/docs/agents/>
- OpenRouter parameter docs: <https://openrouter.ai/docs/api-reference/parameters>
- Qwen Code model-provider docs:
  <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/>
- Local CLI checks:
  - `codex exec --help`
  - `claude --help`
  - `agy --help`
  - `agy models`
  - `qwen --help`
