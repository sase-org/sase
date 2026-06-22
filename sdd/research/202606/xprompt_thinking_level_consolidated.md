---
create_time: 2026-06-22
updated_time: 2026-06-22
status: research
---

# XPrompt Thinking Level Consolidated Research

## Request

Research how SASE xprompts could specify a "thinking level" such as `xhigh`
when specifying a model or LLM provider, then recommend a solution.

This note consolidates the two prior research files:

- `sdd/research/202606/xprompt_thinking_level_research.md`
- `sdd/research/202606/xprompt_thinking_level_directive.md`

## Summary

Add a typed reasoning-effort option to the LLM invocation path. The public
control should be canonicalized as `effort`, stored internally as
`reasoning_effort`, and translated by each provider adapter into that runtime's
native CLI or API option.

The best authoring surface is:

```text
%model:codex/gpt-5.5
%effort:xhigh
```

and, for the case Bryan specifically described - attaching the level at the
point where the model is named - also accept this shorthand:

```text
%model:codex/gpt-5.5@xhigh
%m(opus@xhigh,sonnet@low)
```

`%effort` should be the documented canonical directive because effort is runner
metadata, not part of a model identifier. The `@<effort>` suffix is still worth
supporting as syntax sugar because the current directive grammar already allows
`@` inside `%model` arguments and it solves per-model fan-out ergonomically.
Both forms should lower to the same `reasoning_effort` field before provider
resolution.

## Verification Of Prior Work

Both agents correctly found the main architectural constraint: current model
selection is a string-only path. `PromptDirectives` has `model` but no effort
field, `invoke_agent()` forwards only `model_override`, and provider hooks only
accept model tier, output suppression, and model override. Any real solution
therefore needs a typed option passed alongside the model.

The first note was strongest on the control-plane argument: reasoning effort is
a launch directive and should not be hidden inside ordinary prompt text or a
project-local xprompt. This matches the existing architecture note that keeps
`%` for reserved launch controls and `#` for prompt/workflow modules.

The second note was strongest on fan-out ergonomics: `%model:opus@xhigh` and
`%m(opus@xhigh,sonnet@low)` need no regex change because the colon-arg pattern
already includes `@`. That makes `@<effort>` a practical shorthand, even if it
should not be the only canonical surface.

Provider details needed correction:

- Codex should not clamp `xhigh` to `high`. Current Codex docs and the fetched
  Codex manual list `model_reasoning_effort` values including `xhigh`.
- OpenCode is not "unverified unsupported" in current public docs. The current
  OpenCode CLI docs list `opencode run --variant` as a provider-specific
  reasoning-effort/model-variant flag, although `opencode` is not installed in
  this workspace and should still be locally verified before implementing.
- Antigravity and Qwen do not expose a simple local CLI flag in this workspace,
  so they should not silently no-op. They should either map to a verified model
  variant/config path or return a clear unsupported-effort diagnostic.

## Current SASE Shape

Xprompt expansion already happens before directive extraction:

1. render workflow/Jinja context where applicable;
2. canonicalize project aliases;
3. expand `#` xprompts;
4. extract `%` directives from the expanded prompt.

That means an xprompt can already emit `%model`, `%name`, `%group`, `%wait`, and
other launch controls. A future `%effort` directive would work in the same
phase and would be stripped before the model sees the prompt.

Relevant local code:

- `src/sase/xprompt/_directive_types.py` defines `_KNOWN_DIRECTIVES`,
  `_DIRECTIVE_ALIASES`, and `PromptDirectives`.
- `src/sase/xprompt/directives.py` extracts directives and currently builds
  `PromptDirectives(model=...)`.
- `src/sase/xprompt/_directive_alt.py` handles `%model(a,b)` fan-out and repeated
  scalar `%model` directives.
- `src/sase/llm_provider/_invoke.py` reads `result_directives.model`, resolves
  provider/model, and calls `provider.invoke(..., model_override=model_override)`.
- `src/sase/llm_provider/base.py`, `_hookspec.py`, and `_plugin_manager.py` expose
  no typed invocation-options object today.

Model aliases are also string-only today:

- `src/sase/llm_provider/config.py` cleans `llm_provider.model_aliases` as
  `dict[str, str]`.
- `config/sase.schema.json` defines `model_aliases` additional properties as
  strings.

That string-only alias model is fine for an MVP because `%model` and `%effort`
can be separate directives. Structured aliases can come later.

## Provider Landscape

| Provider/runtime | Current effort surface | Implementation implication |
| --- | --- | --- |
| OpenAI API | `reasoning.effort`; model-dependent values can include `none`, `minimal`, `low`, `medium`, `high`, `xhigh`. | Normalize to `reasoning_effort`; provider/API adapters translate. |
| Codex CLI | Config key `model_reasoning_effort`; current Codex manual/sample list `minimal`, `low`, `medium`, `high`, `xhigh`. Local `codex exec --help` supports generic `-c key=value`, not a dedicated reasoning flag. | Pass per-run args like `-c model_reasoning_effort="xhigh"`. Reject unsupported values such as `max` for Codex unless Codex later supports them. |
| Claude Code | Local `claude --help` and current docs expose `--effort <level>` with `low`, `medium`, `high`, `xhigh`, `max`; support is model-dependent. | Append `--effort <level>` for supported levels. Let Claude Code handle model-specific downgrade behavior where documented. |
| Gemini API | Uses `thinking_level` with model-dependent levels such as `minimal`, `low`, `medium`, `high`. | Relevant for future direct Gemini API integration; not directly exposed by SASE's current `agy` CLI adapter. |
| Antigravity (`agy`) | Local `agy --help` has `--model` but no effort flag. SASE's provider lists model names that already encode levels, such as `Gemini 3.5 Flash (High)` and Claude `(Thinking)` variants. | Initially unsupported as an independent effort option. Use exact model names or aliases today; add mapping later only for verified model families. |
| OpenCode | Current docs show `opencode run --variant` as "Model variant (provider-specific reasoning effort)"; local `opencode` is not installed. | Add support after verifying the installed version; likely `--variant <level>`. |
| Qwen Code | Local `qwen --help` has `--model` but no effort flag. Current Qwen docs support reasoning settings in `modelProviders` configuration with provider-specific wire mapping. | Unsupported for per-run `%effort` until SASE can inject or select a verified provider-model config. |

Existing environment escape hatches can be used today, but they are not the
feature requested:

```text
SASE_CODEX_LARGE_ARGS='-c model_reasoning_effort="xhigh"'
SASE_CLAUDE_LARGE_ARGS='--effort xhigh'
SASE_OPENCODE_LARGE_ARGS='--variant xhigh'
```

Those are process/tier scoped, not per xprompt, per fan-out branch, or visible
in agent metadata.

## Design Choices

### Dedicated `%effort` Directive

Example:

```text
%model:claude/opus
%effort:xhigh
```

This is the clearest control-plane design. Effort is a launch attribute that
must be parsed, validated, logged, stripped from the prompt, and translated by
providers. It belongs in the reserved `%` namespace beside `%model`, not in an
ordinary `#thinking(...)` xprompt.

This form also composes naturally with multi-model fan-out when all variants
use the same effort:

```text
%model(codex/gpt-5.5,claude/opus)
%effort:xhigh
```

### `@<effort>` Suffix On `%model`

Example:

```text
%model:claude/opus@xhigh
%m(opus@xhigh,sonnet@low)
```

This syntax is useful for the exact "when I specify a model" workflow and for
per-model fan-out. It also needs no directive-regex change because
`_DIRECTIVE_PATTERN` already permits `@` in colon arguments.

It should be treated as shorthand, not as a new model-string mini-language:

- split only a trailing `@<known-effort>` token;
- keep `directives.model` clean before alias/provider resolution;
- keep the normalized value in `directives.reasoning_effort`;
- support backtick-quoted `%model:\`literal@model\`` for any future literal
  model ID that would otherwise look ambiguous.

If both `%model:...@x` and `%effort:y` appear in the same final prompt branch,
the safest behavior is to raise a `DirectiveError` unless `x == y`. Silent
precedence makes launch cost and quality too easy to misread.

### Structured Aliases Later

Configured aliases are currently string-to-string. After the directive works,
SASE can add a backward-compatible structured form:

```yaml
llm_provider:
  model_aliases:
    hard:
      model: codex/gpt-5.5
      effort: xhigh
    quick:
      model: claude/sonnet
      effort: low
```

That should be phase 2 because it touches config loading, schema, alias
resolution return types, and docs.

## Implementation Sketch

### 1. Add A Typed Effort Field

Add `reasoning_effort` to `PromptDirectives` and add `effort` to
`_KNOWN_DIRECTIVES`.

Do not use `%e` as a short alias because `%e` already means `%edit`. Optional
aliases such as `%think` or `%reasoning` can wait; adding one canonical spelling
first keeps completion and docs simpler.

Use a global accepted vocabulary:

```text
none, minimal, low, medium, high, xhigh, max
```

The global parser validates spelling only. Provider adapters decide whether a
level is supported for that runtime.

### 2. Parse Both Surfaces Into One Field

In `extract_prompt_directives()`:

- read `%effort:<level>` into `reasoning_effort`;
- split a trailing `@<level>` from `%model` / `%m` values when the suffix is in
  the known effort vocabulary;
- store the clean model string in `directives.model`;
- store the effort in `directives.reasoning_effort`;
- reject conflicting `%effort` and `@effort` values in the same final branch.

If `@effort` is supported, also update fan-out naming helpers in
`src/sase/xprompt/_directive_alt.py` so generated model suffixes do not include
the effort token unless deliberately desired.

### 3. Thread Invocation Options Through Providers

Add a small invocation-options dataclass, likely in `src/sase/llm_provider/types.py`:

```python
@dataclass(frozen=True)
class LLMInvocationOptions:
    reasoning_effort: str | None = None
```

Then pass it through:

- `invoke_agent()`;
- `LLMProvider.invoke()`;
- `LLMHookSpec.llm_invoke()`;
- `LLMPluginManager.invoke()`;
- built-in provider `llm_invoke()` hook methods;
- `run_commit_finalizer()` follow-up invocations, so fix/commit follow-ups keep
  the same effort as the original turn.

A single `invocation_options` parameter is better than adding one kwarg per new
provider knob. It leaves room for future typed launch options without repeatedly
breaking provider signatures.

### 4. Translate In Provider Adapters

Provider translation should live on provider classes, not in `invoke_agent()`.
A base helper can make the contract uniform:

```python
def invocation_option_args(self, options: LLMInvocationOptions) -> list[str]:
    return []
```

Suggested initial behavior:

- Claude: support `low`, `medium`, `high`, `xhigh`, `max` via
  `["--effort", effort]`; reject `none` and `minimal`.
- Codex: support `minimal`, `low`, `medium`, `high`, `xhigh` via
  `["-c", f'model_reasoning_effort="{effort}"']`; reject `none` and `max`.
- OpenCode: after local verification, support likely `["--variant", effort]`.
- Antigravity: reject independent effort initially. Recommend `%model:agy/<exact
  level-bearing model>` or aliases such as `flash-high`.
- Qwen: reject independent effort initially unless SASE adds a temporary config
  injection path for `modelProviders`/reasoning settings.

Avoid silent no-ops. If a prompt explicitly asks for `xhigh`, launching a
default-effort model is worse than a clear unsupported-option error.

### 5. Persist And Display Metadata

Record effort separately from model:

```json
{
  "model": "gpt-5.5",
  "llm_provider": "codex",
  "reasoning_effort": "xhigh"
}
```

Likely touch points:

- `src/sase/axe/run_agent_directives.py` for `agent_meta.json`;
- `src/sase/llm_provider/types.py` / `postprocessing.py` for chat metadata;
- `src/sase/xprompt/workflow_executor_steps_prompt.py` for step markers;
- retry/follow-up paths that clone model/provider state.

Keep display labels readable, for example `agent [gpt-5.5 @ xhigh]`, but do not
pollute the canonical model string.

### 6. Rust/Core Boundary

Provider CLI translation stays in Python. The Python provider layer owns the
actual `claude`, `codex`, `agy`, `qwen`, and `opencode` subprocess commands.

If editor/mobile frontends need validation or completion for effort values, the
canonical effort vocabulary and the `@effort` split rules should be mirrored in
`sase-core` with golden test vectors. If the first slice is Python-only prompt
execution, this can wait.

## Test Plan

Add focused tests for:

- `%effort:xhigh` extraction and stripping;
- `%model:codex/gpt-5.5@xhigh` splitting into clean model plus effort;
- `%m(opus@xhigh,sonnet@low)` fan-out preserving the correct per-branch effort;
- conflict handling for `%model:...@low` plus `%effort:xhigh`;
- provider-specific unsupported-level errors;
- Codex command construction with `-c model_reasoning_effort="xhigh"`;
- Claude command construction with `--effort xhigh`;
- OpenCode command construction with `--variant xhigh` once locally verified;
- metadata persistence in `agent_meta.json` and chat logs;
- xprompt expansion that injects `%model` and `%effort`;
- commit-finalizer and retry/follow-up invocations preserving effort.

## Sources

Local code and docs:

- `src/sase/xprompt/_directive_types.py`
- `src/sase/xprompt/directives.py`
- `src/sase/xprompt/_directive_alt.py`
- `src/sase/llm_provider/_invoke.py`
- `src/sase/llm_provider/base.py`
- `src/sase/llm_provider/_hookspec.py`
- `src/sase/llm_provider/_plugin_manager.py`
- `src/sase/llm_provider/{codex,claude,agy,qwen,opencode}.py`
- `src/sase/llm_provider/commit_finalizer.py`
- `src/sase/axe/run_agent_directives.py`
- `src/sase/xprompt/workflow_executor_steps_prompt.py`
- `docs/xprompt.md`
- `docs/llms.md`
- `sdd/research/202606/directives_xprompts_architecture_consolidated.md`

Local CLI checks:

- `codex exec --help`
- `claude --help`
- `agy --help`
- `qwen --help`
- `command -v opencode` (not installed in this workspace)

External docs checked on 2026-06-22:

- OpenAI reasoning models: <https://developers.openai.com/api/docs/guides/reasoning>
- OpenAI Codex config reference: <https://developers.openai.com/codex/config-reference>
- OpenAI Codex sample config/manual: <https://developers.openai.com/codex/config-sample>
- Anthropic Claude Code CLI reference: <https://docs.anthropic.com/en/docs/claude-code/cli-reference>
- Anthropic Claude Code model config: <https://docs.anthropic.com/en/docs/claude-code/model-config>
- Google Gemini thinking docs: <https://ai.google.dev/gemini-api/docs/thinking>
- Google Antigravity models: <https://antigravity.google/docs/models>
- OpenCode CLI docs: <https://opencode.ai/docs/cli/>
- Qwen Code model-provider docs: <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/>

## Recommended Solution

Implement `%effort:<level>` as the canonical reserved directive, and support
`%model:<model>@<level>` as model-attached shorthand. Both should parse into a
new typed `reasoning_effort` field while keeping `model` clean.

Thread that field through a new `LLMInvocationOptions` object to all provider
invocations. Support Codex and Claude first because their per-run mechanisms are
verified locally and in current docs:

- Codex: `-c model_reasoning_effort="<level>"`;
- Claude: `--effort <level>`.

Add OpenCode support after verifying the installed CLI version's `--variant`
behavior. Leave Antigravity and Qwen unsupported for independent `%effort`
until SASE has a verified mapping to exact model variants or temporary provider
config. Return clear diagnostics for unsupported provider/level combinations.

This preserves the clean `%` launch-control architecture, gives xprompt authors
the compact `@xhigh` form they want when naming a model, and avoids turning the
provider/model string itself into the only place where reasoning behavior can be
hidden.
