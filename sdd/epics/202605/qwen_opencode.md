---
create_time: 2026-05-07 02:01:59
status: done
prompt: sdd/prompts/202605/qwen_opencode.md
bead_id: sase-29
tier: epic
---
# Add Qwen CLI and OpenCode LLM Providers

## Context

SASE already has a pluggy-based `sase_llm` provider boundary. Built-in providers live in `src/sase/llm_provider/`,
register through `[project.entry-points."sase_llm"]` in `pyproject.toml`, and expose metadata through `LLMHookSpec`
hooks. Skills are generated from `src/sase/xprompts/skills/` by `sase init-skills`, and provider-specific skill target
paths come from `llm_skill_deploy_subpath()`.

The current tree is newer than the older LLM-provider-plugin epic: external provider support already lives outside this
repo, and the registry already aggregates provider metadata from entry points. This work should therefore add Qwen Code
and OpenCode as first-class built-in providers, not redesign provider discovery.

Research basis:

- `sdd/research/202605/cli_agent_harnesses_for_sase.md`
- OpenCode CLI docs, checked on 2026-05-07:
  - `opencode run [message..]`
  - `--format json`
  - `--model provider/model`
  - `--dangerously-skip-permissions`
  - `--dir`
  - `opencode serve` and `--attach` as a later optimization
  - `opencode acp` as a future protocol path
- Qwen Code headless docs, checked on 2026-05-07:
  - `qwen -p/--prompt`
  - `--output-format json|stream-json`
  - `--include-partial-messages`
  - `--yolo`
  - `--approval-mode`
  - `--continue` / `--resume`
  - `QWEN_CODE_UNATTENDED_RETRY=1` opt-in persistent retry
- Qwen README, checked on 2026-05-07:
  - Qwen OAuth free tier was discontinued on 2026-04-15.
  - User-facing setup should point users to API keys, Alibaba Cloud Coding Plan, OpenRouter, Fireworks, or other
    supported providers rather than OAuth free tier.

## Principles

- Treat Qwen and OpenCode like Claude, Codex, Gemini, and external providers: same hooks, skills, commit flow,
  telemetry, retry behavior, agent metadata, temporary overrides, and ACE display behavior.
- Keep providers thin. They should build CLI commands, isolate mutable CLI home/config where necessary, run
  subprocesses, and return `InvokeResult`. Prompt preprocessing, postprocessing, chat history, telemetry, and agent
  orchestration stay in shared code.
- Prefer structured output. Qwen should use `stream-json`; OpenCode should use `--format json`.
- Avoid a shared abstraction until it removes real duplication. Reuse `_subprocess.py` helpers where the event shapes
  match; add focused parser helpers when schemas differ.
- Every phase must leave `just check` passing. Since these phase agents run in ephemeral workspaces, run `just install`
  first if the environment is stale.

## Phase 1 - Qwen Code Provider

### Goal

Add working first-class support for Qwen Code through the existing LLM provider plugin boundary.

### Scope

Create `src/sase/llm_provider/qwen.py` with a `QwenProvider` implementing `LLMProvider` and the current `LLMHookSpec`
metadata hooks:

- `llm_provider_name() -> "qwen"`
- `llm_provider_short_name() -> "qwn"`
- `llm_resolve_model_name()`
- `llm_known_model_names()`
- `llm_model_short_aliases()`
- `llm_skill_template_context()`
- `llm_skill_deploy_subpath()` if Qwen skills should deploy somewhere other than `~/.qwen/skills`
- `llm_cli_status_color()`
- `llm_autodetect_priority()`
- `llm_autodetect_cli_name() -> "qwen"`
- `llm_default_retry_config()` only if there is a clear, non-duplicative SASE retry policy beyond Qwen's own
  `QWEN_CODE_UNATTENDED_RETRY`
- `llm_invoke()`

Register the provider in `pyproject.toml`:

```toml
qwen = "sase.llm_provider.qwen:QwenProvider"
```

Invocation should start with the lowest-risk headless command:

```bash
qwen -p - --output-format stream-json --yolo --model <model>
```

If Qwen does not accept `-p -` as stdin prompt input in practice, use one of these alternatives after verifying with a
real local CLI:

- pass the prompt as the `-p` argument, using `subprocess.Popen(args, ...)` without shell interpolation;
- or use documented stdin text input with `--input-format text --output-format stream-json`.

Use `SASE_QWEN_PATH` for binary override, defaulting to `qwen`.

Support extra args with the same precedence pattern as Claude/Codex:

- `SASE_LLM_LARGE_ARGS`, then `SASE_QWEN_LARGE_ARGS`
- `SASE_LLM_SMALL_ARGS`, then `SASE_QWEN_SMALL_ARGS`

Use `stream-json` event parsing. Qwen's documented stream resembles Claude-style events:

- `assistant` events contain assistant content blocks.
- `result` events contain final result text, success/error metadata, `session_id`, and usage.

Start by reusing or lightly extending `stream_and_parse_json_output()` if its existing Claude-style parser captures Qwen
assistant/result events correctly. If Qwen's `result` text is the only reliable final answer, add Qwen-specific parser
coverage rather than weakening Claude parsing.

Preserve SASE interrupt behavior:

- call `start_interrupt_monitor()`;
- when interrupted, terminate the subprocess and relaunch with accumulated response plus the user message;
- do not rely on Qwen session continuation in the first pass unless local testing proves `--continue` is safe for
  interrupted SASE runs.

Decide on Qwen config isolation during implementation:

- First inspect whether Qwen writes to `~/.qwen/settings.json`, session state, or trusted-folder files during a headless
  run.
- If it mutates global config during normal invocation, add a SASE-managed shadow Qwen home equivalent to Codex's shadow
  `CODEX_HOME`.
- If it only reads config and writes session data, document the behavior and keep the provider simple.

### Tests

Add focused tests, likely `tests/test_llm_provider_qwen.py` plus parser tests if `_subprocess.py` changes:

- provider is an `LLMProvider`;
- tier mapping and model override behavior;
- command construction includes `-p`, `--output-format stream-json`, `--yolo`, and `--model`;
- `SASE_QWEN_PATH` binary override;
- generic env args beat Qwen-specific env args;
- missing executable error mentions `SASE_QWEN_PATH` and `PATH`;
- non-zero exit raises `subprocess.CalledProcessError` with useful stderr;
- stream parser extracts assistant/result text and usage from representative Qwen events;
- malformed/unknown JSON events are ignored;
- `resolve_model_provider("qwen/<model>")` works through entry-point registration;
- implicit model resolution works for explicitly listed Qwen model names.

### Docs

Update:

- `docs/llms.md`
- `docs/configuration.md`
- `docs/plugins.md` if the provider table lists built-ins

Documentation should include auth caveat: Qwen OAuth free tier ended on 2026-04-15; users should configure API keys or
another supported provider through Qwen's auth/settings path.

### Exit Criteria

- `just install`
- `just check`
- `sase init-skills --dry-run --provider qwen` shows expected skill targets.
- Manual smoke, if Qwen is installed and authenticated:

```bash
sase -m qwen/<known-model> "Reply with exactly: qwen ok"
```

If Qwen is not installed locally, record that manual smoke was skipped and why.

## Phase 2 - OpenCode Provider

### Goal

Add working first-class support for OpenCode after Qwen support is in place.

### Scope

Create `src/sase/llm_provider/opencode.py` with an `OpenCodeProvider` implementing `LLMProvider` and the current
provider metadata hooks:

- `llm_provider_name() -> "opencode"`
- `llm_provider_short_name() -> "opc"` or another unique, compact suffix
- `llm_resolve_model_name()`
- `llm_known_model_names()`
- `llm_model_short_aliases()`
- `llm_skill_template_context()`
- `llm_skill_deploy_subpath()` if OpenCode's skill path is not the default `~/.opencode/skills`
- `llm_cli_status_color()`
- `llm_autodetect_priority()`
- `llm_autodetect_cli_name() -> "opencode"`
- `llm_default_retry_config()` only if OpenCode exposes a clear retryable error pattern worth enabling by default
- `llm_invoke()`

Register the provider in `pyproject.toml`:

```toml
opencode = "sase.llm_provider.opencode:OpenCodeProvider"
```

Invocation should start with the documented non-interactive command:

```bash
opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> <prompt>
```

Use `SASE_OPENCODE_PATH` for binary override, defaulting to `opencode`.

Support extra args with the same precedence pattern:

- `SASE_LLM_LARGE_ARGS`, then `SASE_OPENCODE_LARGE_ARGS`
- `SASE_LLM_SMALL_ARGS`, then `SASE_OPENCODE_SMALL_ARGS`

Model handling needs extra care because OpenCode expects `provider/model`:

- Default large/small model names should be concrete OpenCode model IDs that include provider prefix.
- `%model:opencode/<provider/model>` should work. Since SASE's explicit provider syntax splits on the first `/`,
  `resolve_model_provider("opencode/anthropic/claude-sonnet-4-5")` should pass `anthropic/claude-sonnet-4-5` to the
  provider unchanged.
- For unknown bare model names, current SASE behavior will route to the default provider. Do not try to guess OpenCode's
  provider from a bare model string unless `llm_known_model_names()` lists the exact full OpenCode model ID.

Add OpenCode JSON event parsing from observed fixtures. The docs call `--format json` "raw JSON events", but the exact
assistant/result event shape must be validated against a real CLI or checked from upstream docs/source before merging.
The parser should:

- stream stdout into `live_reply.md`;
- collect final assistant text;
- capture error events into stderr on non-zero exit;
- capture usage when OpenCode events expose token counts, without failing when usage is absent;
- ignore unknown event fields so OpenCode event schema changes do not break SASE immediately.

Keep `opencode serve` / `--attach` out of the first implementation. Add notes in docs or comments only if needed; a
persistent server introduces lifecycle, port, auth, and cleanup behavior that belongs in a later feature.

Decide on OpenCode config isolation during implementation:

- Auth data lives under `~/.local/share/opencode/auth.json` according to docs.
- Inspect where OpenCode writes config/session state during `opencode run`.
- If it rewrites config during invocation, use a SASE-managed shadow config/data home.
- If it only reads auth and writes session data, keep direct environment passthrough for Phase 2.

### Tests

Add `tests/test_llm_provider_opencode.py` plus parser tests:

- provider is an `LLMProvider`;
- tier mapping and model override behavior;
- command construction includes `run`, `--format json`, `--dangerously-skip-permissions`, `--model`, and `--dir`;
- prompts are passed without shell interpolation;
- `SASE_OPENCODE_PATH` binary override;
- generic env args beat OpenCode-specific env args;
- missing executable error mentions `SASE_OPENCODE_PATH` and `PATH`;
- non-zero exit raises `subprocess.CalledProcessError` with useful stderr;
- parser extracts assistant/final text from captured OpenCode JSON events;
- parser ignores unknown events;
- explicit provider/model syntax preserves OpenCode's nested `provider/model` model string.

### Docs

Update:

- `docs/llms.md`
- `docs/configuration.md`
- `docs/plugins.md`

Mention that OpenCode model names normally include a provider prefix and that users can list models with
`opencode models`.

### Exit Criteria

- `just install`
- `just check`
- `sase init-skills --dry-run --provider opencode` shows expected skill targets.
- Manual smoke, if OpenCode is installed and authenticated:

```bash
sase -m opencode/<provider/model> "Reply with exactly: opencode ok"
```

If OpenCode is not installed locally, record that manual smoke was skipped and why.

## Phase 3 - Cross-Provider Integration Polish

### Goal

Make Qwen and OpenCode feel fully native across SASE's UI, metadata, docs, skills, and model-selection flows.

### Scope

Audit all places that aggregate provider metadata rather than provider execution:

- `src/sase/llm_provider/registry.py`
- `src/sase/main/init_skills_handler.py`
- `src/sase/agents/cli_status.py`
- ACE model picker / temporary override modal
- agent naming and provider suffix behavior
- thinking/live reply panels
- telemetry labels and retry display
- mobile launch provider/model handling

Most of these should already work through hooks. Only make code changes where Qwen/OpenCode expose a gap in the generic
provider contract.

Recommended checks:

- `python - <<'PY'` smoke snippets for `iter_plugins()`, `model_to_provider_map()`, `provider_short_name_map()`, and
  `model_short_alias_map()` show Qwen/OpenCode entries.
- `%model:qwen/<model>` and `%model:opencode/<provider/model>` metadata pre-resolution writes correct `agent_meta.json`
  provider/model fields.
- ACE provider/model display does not truncate or mis-label nested OpenCode model strings.
- Agents tab grouping/search can find `provider:qwen` and `provider:opencode`.
- `sase agents status` displays the provider suffixes and colors without special cases.

If skill deployment paths require provider-specific behavior, implement it here after both providers exist. Do not
hand-edit generated skill files; update `src/sase/xprompts/skills/`, run `sase init-skills --force`, and follow the
chezmoi workflow if applicable.

### Tests

Add or extend tests for:

- provider metadata aggregation includes both providers;
- model/provider resolution for nested OpenCode model names;
- temporary override state for Qwen and OpenCode;
- agent metadata extraction for prompts containing `%model:qwen/...` and `%model:opencode/...`;
- model picker data includes the new providers if the picker consumes `model_to_provider_map()`;
- `init-skills` provider filtering accepts `qwen` and `opencode`.

### Docs

Update cross-cutting docs if not already covered in Phases 1 and 2:

- `README.md` provider summary if present;
- `docs/llms.md` provider table and per-provider sections;
- `docs/configuration.md` environment variable table;
- `docs/xprompt.md` provider/model syntax examples if useful.

### Exit Criteria

- `just install`
- `just check`
- `rg -n "claude|codex|gemini|external" src/sase docs tests` audit shows no hardcoded list that should include
  Qwen/OpenCode but was missed.
- `sase init-skills --dry-run --provider qwen` and `--provider opencode` both work.

## Phase 4 - End-to-End Runtime Validation and Hardening

### Goal

Validate both providers with real CLIs and harden failures before declaring the feature complete.

### Scope

This phase should run on a machine where both `qwen` and `opencode` are installed and authenticated, or explicitly
record which real-runtime validations were impossible.

Validate:

- direct `sase -m qwen/<model> ...`;
- direct `sase -m opencode/<provider/model> ...`;
- `sase run` background agents for each runtime;
- live output updates in `live_reply.md`;
- `agent_meta.json`, `done.json`, chat logs, and notifications record the right provider/model;
- interrupt flow via `interrupt_request.json`;
- retry behavior for representative transient errors if they can be simulated safely;
- `sase init-skills` generated output locations;
- no config corruption in user-level Qwen/OpenCode settings after repeated runs.

If parser assumptions differ from real CLI output, update parsers and fixture tests in this phase. Keep changes focused
to runtime hardening, not broad refactoring.

### Tests

Add integration-style tests where practical using small fake CLI executables placed on `PATH`:

- fake `qwen` emits representative stream-json and exits 0/1;
- fake `opencode` emits representative JSON events and exits 0/1;
- provider invocation writes expected output and errors without requiring real network auth.

These fake-CLI tests should live in the normal test suite and make the real-runtime manual checks less brittle.

### Exit Criteria

- `just install`
- `just check`
- Manual smoke results recorded in the phase notes, including exact CLI versions:

```bash
qwen --version
opencode --version
```

- Any skipped validation is explicitly documented with the blocker.

## Open Questions for Phase Agents

- Qwen model defaults: pick conservative defaults only after checking what Qwen Code reports for configured models in
  the target environment. Avoid embedding a fast-moving exhaustive Qwen model catalog unless needed for implicit model
  routing.
- OpenCode model defaults: because OpenCode delegates to many providers, SASE may need a default such as
  `anthropic/claude-sonnet-4-5` only for users who have that provider configured. If there is no universally valid
  default, document that users should invoke with `%model:opencode/<provider/model>` or set `llm_provider.provider` plus
  provider-specific extra args/config.
- Skill paths: verify actual Qwen/OpenCode skill discovery paths before overriding `llm_skill_deploy_subpath()`. The
  default `~/.<provider>/skills` is acceptable only if the runtime actually reads it.
- Shadow homes: do not add home isolation speculatively. Add it only if local inspection shows headless runs mutate
  global config or trust state in a way that can affect other SASE agents.
- Auto-detection priority: suggested order after this work is `claude=0`, `codex=10`, `qwen=15`, `opencode=18`, external
  `external=20`, `gemini=30`. If this surprises existing users, make Qwen/OpenCode opt-in only by omitting autodetect
  priority in the first provider phase and revisit in Phase 3.
