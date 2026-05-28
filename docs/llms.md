# LLM Provider Integration

This document describes the LLM provider abstraction layer in sase. The system supports pluggable LLM backends (Claude
Code, Codex, Gemini CLI, Qwen Code, and OpenCode are bundled; additional providers can ship as external plugins) behind
a shared orchestration layer that handles preprocessing, invocation, and postprocessing.

## Table of Contents

- [Overview](#overview)
- [Provider Architecture](#provider-architecture)
- [Commit Finalization](#commit-finalization)
- [Claude Code Integration](#claude-code-integration)
- [Gemini CLI Integration](#gemini-cli-integration)
- [Codex CLI Integration](#codex-cli-integration)
- [Qwen Code Integration](#qwen-code-integration)
- [OpenCode Integration](#opencode-integration)
- [External Provider Plugins](#external-provider-plugins)
- [Configuration](#configuration)
- [Per-Prompt Provider Switching](#per-prompt-provider-switching)
- [Model Tier System](#model-tier-system)
- [Temporary Default Override](#temporary-default-override)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)
- [Retry and Fallback](#retry-and-fallback)
- [Token Usage Tracking](#token-usage-tracking)
- [Prompt Preprocessing Pipeline](#prompt-preprocessing-pipeline)
- [Subprocess Streaming](#subprocess-streaming)
- [Postprocessing](#postprocessing)
- [Chat History](#chat-history)
- [Invocation Lifecycle](#invocation-lifecycle)

## Overview

The LLM provider layer decouples prompt handling from the underlying LLM backend. All providers share a common
preprocessing pipeline, subprocess streaming mechanism, and postprocessing workflow. The actual LLM invocation is
delegated to a pluggable provider selected at runtime.

Key design principles:

- **Providers are thin**: They only construct CLI commands and run subprocesses. All preprocessing and postprocessing
  lives in the shared orchestration layer.
- **Registry-based selection**: Providers register themselves by name and are resolved via config or explicit override.
- **Tier-based model selection**: Callers request a "large" or "small" tier; the provider maps it to a concrete model.
- **Runtime-uniform commit enforcement**: SASE agent sessions use a shared commit finalizer instead of provider-specific
  native stop hooks.

### Source Layout

| File                                        | Purpose                                             |
| ------------------------------------------- | --------------------------------------------------- |
| `src/sase/llm_provider/__init__.py`         | Public API exports                                  |
| `src/sase/llm_provider/base.py`             | `LLMProvider` abstract base class                   |
| `src/sase/llm_provider/_hookspec.py`        | Pluggy hook specifications (`LLMHookSpec`)          |
| `src/sase/llm_provider/_plugin_manager.py`  | Plugin manager wrapping pluggy (`LLMPluginManager`) |
| `src/sase/llm_provider/claude.py`           | Claude Code provider implementation                 |
| `src/sase/llm_provider/codex.py`            | Codex CLI provider implementation                   |
| `src/sase/llm_provider/gemini.py`           | Gemini CLI provider implementation                  |
| `src/sase/llm_provider/qwen.py`             | Qwen Code provider implementation                   |
| `src/sase/llm_provider/opencode.py`         | OpenCode provider implementation                    |
| `src/sase/llm_provider/registry.py`         | Provider registration and lookup                    |
| `src/sase/llm_provider/config.py`           | Config file reader (`sase.yml`)                     |
| `src/sase/llm_provider/commit_finalizer.py` | Provider-neutral dirty-workspace finalizer          |
| `src/sase/llm_provider/types.py`            | `ModelTier`, `InvokeResult`, `LoggingContext` types |
| `src/sase/llm_provider/_invoke.py`          | `invoke_agent()` orchestrator                       |
| `src/sase/llm_provider/_subprocess.py`      | Provider stream-parser compatibility exports        |
| `src/sase/llm_provider/_plan_utils.py`      | Shared plan utilities                               |
| `src/sase/llm_provider/preprocessing.py`    | Shared prompt preprocessing pipeline                |
| `src/sase/llm_provider/postprocessing.py`   | Logging, chat history, audio                        |
| `src/sase/llm_provider/retry_config.py`     | `ProviderRetryConfig` (per-provider retry defaults) |

## Provider Architecture

### Base Class

All providers implement the `LLMProvider` abstract base class:

```python
class LLMProvider(ABC):
    @abstractmethod
    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult: ...
```

| Parameter         | Type          | Description                                                       |
| ----------------- | ------------- | ----------------------------------------------------------------- |
| `prompt`          | `str`         | Already-preprocessed prompt text                                  |
| `model_tier`      | `ModelTier`   | `"large"` or `"small"`                                            |
| `suppress_output` | `bool`        | If `True`, suppress real-time console output                      |
| `model_override`  | `str \| None` | Concrete model name from `%model`, a temporary override, or retry |

Returns `InvokeResult(content=..., usage=...)`. Providers raise `subprocess.CalledProcessError` for failed CLI exits or
a provider-specific exception for launch/configuration failures.

### Registry

Providers are discovered via `importlib.metadata.entry_points(group="sase_llm")`. The built-in providers are packaged
the same way as external provider plugins; their entry points live in `pyproject.toml`:

```toml
[project.entry-points."sase_llm"]
claude = "sase.llm_provider.claude:ClaudeCodeProvider"
codex  = "sase.llm_provider.codex:CodexProvider"
gemini = "sase.llm_provider.gemini:GeminiProvider"
opencode = "sase.llm_provider.opencode:OpenCodeProvider"
qwen   = "sase.llm_provider.qwen:QwenProvider"
```

External plugin packages declare additional entries under the same group.

To get a provider instance:

```python
provider = get_provider()          # Uses default from config
provider = get_provider("claude")  # Explicit provider name
```

### Selection Logic

1. If `provider_name` is passed to `invoke_agent()`, use that.
2. If the prompt has a `%model` directive, resolve explicit `provider/model` syntax first, then known model names from
   installed plugin metadata.
3. If no explicit provider/model was supplied, use an active temporary override from `~/.sase/llm_override.json`.
4. Otherwise, read the `llm_provider.provider` field from `~/.config/sase/sase.yml`.
5. If no config exists (or provider is empty), auto-detect by walking registered plugins in ascending
   `llm_autodetect_priority()` order and picking the first whose `llm_autodetect_cli_name()` is on `PATH`. Built-in
   priorities: `claude=0`, `codex=10`, `qwen=15`, `opencode=18`, `gemini=30`. External plugins slot in by declaring
   their own priority. Gemini returns no CLI name and is the final always-eligible fallback.

## Commit Finalization

After a provider returns successfully, `invoke_agent()` runs the provider-neutral commit finalizer before success
postprocessing when the process is a SASE agent session (`SASE_AGENT_TIMESTAMP` is set). The finalizer checks the active
project workspace through the active VCS provider and checks configured sibling repositories as Git worktrees at their
resolved `workspace_dir`. If it finds dirty enforced work, it sends the same provider a bounded follow-up prompt that
lists the dirty files and instructs the agent to use the appropriate commit skill, such as `/sase_git_commit`. Dirty
static siblings (`workspace.strategy: none`) are included in that prompt only as advisory work and do not fail the run
if they remain dirty. A narrow generated SDD plan closeout, where the only enforced change is one markdown file's
frontmatter `status: wip` becoming `status: done`, is committed directly with a `TYPE=sdd` commit instead of consuming a
provider follow-up pass.

The finalizer skips when the call is outside a SASE agent session, when `commit.finalizer.enabled` is false, or when
`SASE_DISABLE_COMMIT_STOP_HOOK=1` is set. When an artifacts directory is available, each follow-up pass writes
`commit_finalizer_pass_<N>_prompt.md` and `commit_finalizer_pass_<N>_response.md`; the final outcome is written to
`commit_finalizer_result.json`. If the workspace remains dirty after `commit.finalizer.max_passes`, the invocation is
converted into an `LLMInvocationError` rather than being logged as a successful clean run.

The older provider-native commit hook scripts are no longer shipped; SASE-launched agent sessions rely on the shared
finalizer path.

## Claude Code Integration

The `ClaudeCodeProvider` invokes the `claude` CLI tool.

### Command Construction

```
claude -p --verbose --model <alias> --output-format stream-json --dangerously-skip-permissions --session-id <uuid> [extra_args...]
```

The prompt is written to stdin. Output is streamed as JSON events; SASE extracts assistant text and token usage from the
stream.

### Model Mapping

| Tier    | Claude CLI Alias |
| ------- | ---------------- |
| `large` | `opus`           |
| `small` | `sonnet`         |

### Environment Variables

| Variable                 | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`    | Extra CLI args for `large` tier (generic, preferred)       |
| `SASE_LLM_SMALL_ARGS`    | Extra CLI args for `small` tier (generic, preferred)       |
| `SASE_CLAUDE_LARGE_ARGS` | Extra CLI args for `large` tier (Claude-specific fallback) |
| `SASE_CLAUDE_SMALL_ARGS` | Extra CLI args for `small` tier (Claude-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence. Values are split on whitespace and appended to the command.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for Claude")` spinner is shown (unless `suppress_output` is
`True`).

### Claude Tool-Call Hooks

To record what tools an agent actually invoked (file reads, edits, bash commands, etc.), `ClaudeCodeProvider.invoke()`
asks Claude Code to call back into SASE every time a tool runs. It does this by writing a pair of `PreToolUse` and
`PostToolUse` hook entries into the workspace's `.claude/settings.local.json` for the duration of the agent run. Each
entry matches all tools (`"matcher": "*"`) and invokes the `sase_claude_tool_hook` console script, which reads the
Claude-supplied JSON payload from stdin and appends one normalized record (schema version 3) to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl`:

- The `PreToolUse` hook writes a pending entry capturing the tool name and a redacted version of its input.
- The `PostToolUse` hook writes the matching result entry: success/failure/interrupted status, the call's duration, and
  a length-bounded preview of the response.

The ACE Tools panel reads this same `tool_calls.jsonl` to render the per-agent timeline — see
[Agents Tab Tools Panel](ace.md#agents-tab-tools-panel).

Installation and cleanup are wrapped in a `claude_hooks_session()` context manager that is careful not to corrupt
user-managed Claude settings:

- Writes to `.claude/settings.local.json` go through `tmp + os.replace` so a killed agent cannot leave a half-written
  file behind.
- Each SASE-installed hook command carries a `_sase_managed` sentinel value. On exit, cleanup removes only entries
  carrying that sentinel; any pre-existing user or project hooks (including hooks for unrelated events such as
  `Notification`) are left untouched.
- "Home-mode" launches — agents started outside a tracked workspace, identified by the absence of all three of
  `SASE_GIT_WORKSPACE_DIR`, `SASE_CD_WORKSPACE_DIR`, and `SASE_ACTIVE_PROJECT_DIR` — skip the settings mutation
  entirely. They emit a `claude_hooks_skipped` diagnostic to `tool_calls_writer_errors.jsonl` so the operator can see
  why the hook records are missing, and rely on the stream-derived fallback writer (below) to populate the timeline.
- If `.claude/settings.local.json` exists but is malformed JSON, it is left alone, the run logs a diagnostic, and the
  fallback writer takes over.
- If SASE created the file (it did not pre-exist) and only SASE entries remain at exit, both the file and an empty
  `.claude` directory are removed so the workspace is left clean.

The collector script itself is intentionally non-blocking: malformed JSON, non-object payloads, exceptions inside the
collector, a missing `SASE_ARTIFACTS_DIR`, and unrecognized hook event names all produce a best-effort diagnostic (or a
silent no-op when stdin is empty) and exit 0. This guarantees that a SASE-side bug can never make Claude surface the
hook as a tool-call failure to the agent.

The hook-based writer coexists with a stream-derived fallback writer in the LLM provider layer, which parses tool calls
out of the Claude streaming response. Both writers append to the same artifact, and the Tools-panel reader accepts
schema versions 1, 2, and 3. When hook and stream records describe the same `tool_use_id`, the reader keeps the
hook-derived record and suppresses the duplicate stream-derived row; otherwise, older stream-only artifacts remain
readable.

The normalized tool-call artifact is still Python/TUI-owned glue rather than a shared `sase-core` contract. Move it into
`../sase-core` only if another frontend or integration needs to produce or consume exactly the same schema through the
Rust boundary.

Source: `src/sase/llm_provider/claude.py`, `src/sase/llm_provider/_claude_hooks.py`,
`src/sase/llm_provider/_tool_calls.py`, `src/sase/scripts/sase_claude_tool_hook.py`, `src/sase/ace/tui/tools/reader.py`

## Gemini CLI Integration

The `GeminiProvider` invokes Google's internal Gemini CLI tool.

### Command Construction

```
gemini --output-format stream-json --yolo --model <model>
```

The prompt is written to stdin, and stream-json events are parsed from stdout in real-time. SASE accumulates the
assistant reply text and per-cycle usage totals, and writes normalized tool-call records (see
[Gemini Tool-Call Capture](#gemini-tool-call-capture)).

### Default Model

The Gemini provider uses `gemini-3-flash-preview` as its default model. This can be overridden per-prompt using the
`%model` directive (e.g., `%model:gemini-2.5-flash`).

### Environment Variables

| Variable           | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `SASE_GEMINI_PATH` | Path to the Gemini CLI binary (default: `"gemini"`). |

### Gemini Tool-Call Capture

SASE captures Gemini tool calls from the `gemini --output-format stream-json` event stream; it does not install Gemini
hooks. When `SASE_ARTIFACTS_DIR` is present, the stream parser appends normalized Gemini records to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for the ACE [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel) with
`runtime: "gemini"` and `source: "stream"`. Start/completion events collapse into one Tools-panel row that preserves
pending state while a tool is still running and surfaces result previews, failure/interruption status, and durations
when the stream exposes them. Malformed or unsupported tool-shaped events are skipped with a diagnostic instead of
producing a malformed record.

### Skill Deployment

`sase skills init` writes Gemini skills to both `~/.gemini/skills/` and `~/.gemini/jetski/skills/`. With
`use_chezmoi: true`, those targets are remapped to the matching chezmoi-managed paths under
`~/.local/share/chezmoi/home/dot_gemini/`.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for Gemini")` spinner is shown (unless `suppress_output` is
`True`).

## Codex CLI Integration

The `CodexProvider` invokes the OpenAI `codex` CLI tool.

### Command Construction

Normal mode:

```
codex exec --model <model> --dangerously-bypass-approvals-and-sandbox --json --color never --skip-git-repo-check - [extra_args...]
```

The prompt is written to stdin. Output is streamed as NDJSON events, with assistant text extracted from `item.completed`
events.

### Model Mapping

| Tier    | Codex Model         |
| ------- | ------------------- |
| `large` | `gpt-5.5`           |
| `small` | `codex-mini-latest` |

### Plan Handling

The Codex provider does not enable Codex CLI's native plan mode. SASE planning flows are implemented at the
orchestration layer through workflows, xprompts, and the `sase_plan` skill, so provider behavior stays consistent across
runtimes.

### Environment Variables

| Variable                         | Description                                                |
| -------------------------------- | ---------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`            | Extra CLI args for `large` tier (generic, preferred)       |
| `SASE_LLM_SMALL_ARGS`            | Extra CLI args for `small` tier (generic, preferred)       |
| `SASE_CODEX_PATH`                | Path to the Codex CLI binary (default: PATH, then NVM_BIN) |
| `SASE_CODEX_LARGE_ARGS`          | Extra CLI args for `large` tier (Codex-specific fallback)  |
| `SASE_CODEX_SMALL_ARGS`          | Extra CLI args for `small` tier (Codex-specific fallback)  |
| `SASE_CODEX_DISABLE_SHADOW_HOME` | Set to `1` to disable the disposable Codex home            |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_CODEX_*_ARGS`.

By default, SASE launches Codex with a per-invocation shadow `CODEX_HOME` under `~/.cache/sase/codex_home/`. The shadow
home copies `config.toml` and symlinks other Codex home entries back to the real Codex home so Codex can read auth,
hooks, skills, logs, and caches while any config rewrites stay disposable. The shadow directory is removed after each
Codex subprocess exits. Set `SASE_CODEX_DISABLE_SHADOW_HOME=1` to pass through the inherited environment directly for
debugging or emergency compatibility.

### Codex Tool-Call Capture

SASE captures Codex tool calls from the `codex exec --json` NDJSON stream; it does not install Codex hooks or mutate
user Codex configuration for telemetry. When `SASE_ARTIFACTS_DIR` is present, the stream parser appends normalized Codex
records to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for the ACE [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel).

Current fixture coverage is based on Codex CLI `0.130.0`. For stream items that expose both start and completion events
(`command_execution`, `file_change`, and named tool items), SASE writes `ToolUse` and `ToolResult` rows with
`runtime: "codex"` and `source: "stream"`. The Tools-panel reader collapses those pairs into one row, preserving pending
rows while a command is still running and showing result previews, failure/interruption status, and duration when the
stream exposes enough data to compute it.

Older Codex stream shapes that only expose a completed `function_call` item remain readable as legacy `FunctionCall`
rows. Those records can show the tool name and compact input target, but they do not invent response summaries,
durations, or failure details that Codex did not emit.

Codex tool-call summaries use the same bounded and redacted artifact helpers as the other providers. Set
`SASE_TOOL_LOG_FULL=1` only for explicit debugging sessions when raw tool input or output is needed in the local
artifact.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for Codex")` spinner is shown (unless `suppress_output` is
`True`).

## Qwen Code Integration

The `QwenProvider` invokes the `qwen` CLI tool.

### Command Construction

```
qwen --input-format text --output-format stream-json --yolo --model <model> [extra_args...]
```

The prompt is written to stdin using Qwen's text input mode. Output is streamed as JSON events; SASE extracts assistant
text from `assistant` events and falls back to the final `result` text when no assistant text is emitted.

### Model Mapping

| Tier    | Qwen Model          |
| ------- | ------------------- |
| `large` | `qwen3.6-plus`      |
| `small` | `qwen3-coder-flash` |

### Authentication

Configure Qwen Code through its supported auth and settings flow before using it from SASE. Qwen OAuth free tier access
ended on 2026-04-15; use API keys, Alibaba Cloud Coding Plan, OpenRouter, Fireworks, or another Qwen-supported provider
instead of relying on the discontinued OAuth free tier.

### Environment Variables

| Variable               | Description                                              |
| ---------------------- | -------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`  | Extra CLI args for `large` tier (generic, preferred)     |
| `SASE_LLM_SMALL_ARGS`  | Extra CLI args for `small` tier (generic, preferred)     |
| `SASE_QWEN_PATH`       | Path to the Qwen Code CLI binary (default: `qwen`)       |
| `SASE_QWEN_LARGE_ARGS` | Extra CLI args for `large` tier (Qwen-specific fallback) |
| `SASE_QWEN_SMALL_ARGS` | Extra CLI args for `small` tier (Qwen-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_QWEN_*_ARGS`.

Qwen Code config is left in Qwen's normal locations (`~/.qwen/settings.json` and project `.qwen/settings.json`). SASE
does not create a shadow Qwen home in the first implementation because local Qwen was unavailable during this phase, so
no normal headless-run config mutation could be verified.

### Qwen Tool-Call Capture

SASE captures Qwen tool calls from the `qwen --output-format stream-json` event stream; it does not install Qwen hooks.
When `SASE_ARTIFACTS_DIR` is present, the stream parser normalizes Qwen's nested `tool_use` and `tool_result` blocks
into records appended to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for the ACE
[Agents Tab Tools Panel](ace.md#agents-tab-tools-panel) with `runtime: "qwen"` and `source: "stream"`. Malformed or
unsupported tool-shaped events emit a diagnostic instead of producing a malformed record. The Tools-panel reader
collapses each start/result pair into a single row.

### Commit Finalization

SASE-launched Qwen runs use the shared provider-neutral commit finalizer described above; active SASE settings do not
need repo-local or global Qwen commit-hook configuration.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for Qwen")` spinner is shown (unless `suppress_output` is
`True`).

## OpenCode Integration

The `OpenCodeProvider` invokes the `opencode` CLI tool.

### Command Construction

```
opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> [extra_args...] <prompt>
```

The prompt is passed as OpenCode's `run [message..]` argument without shell interpolation. Output is streamed as JSONL
events; SASE extracts assistant text from `text` events, captures errors from `error` events, and accumulates token
counters from `step_finish` events when OpenCode reports them.

### Model Mapping

OpenCode model IDs normally include an upstream provider prefix. Use `%model:opencode/<provider/model>` to route a
single SASE prompt to a concrete OpenCode model.

| Tier    | OpenCode Model                |
| ------- | ----------------------------- |
| `large` | `anthropic/claude-sonnet-4-5` |
| `small` | `openai/gpt-5-mini`           |

### Authentication and Config

Configure OpenCode through its normal auth and settings flow before using it from SASE. OpenCode stores auth under its
XDG data directory and reads config from its XDG config directory plus project `.opencode` config. Use `opencode models`
to inspect the models available in your configured OpenCode environment.

SASE deploys OpenCode skills under `~/.config/opencode/skills/`, which OpenCode scans as part of its config directory.
SASE does not create a shadow OpenCode data/config home in this first implementation because OpenCode's normal headless
run writes session/database state under its XDG data directory while reading auth/config from the standard locations.

### Environment Variables

| Variable                   | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `SASE_LLM_LARGE_ARGS`      | Extra CLI args for `large` tier (generic, preferred)         |
| `SASE_LLM_SMALL_ARGS`      | Extra CLI args for `small` tier (generic, preferred)         |
| `SASE_OPENCODE_PATH`       | Path to the OpenCode CLI binary (default: `opencode`)        |
| `SASE_OPENCODE_LARGE_ARGS` | Extra CLI args for `large` tier (OpenCode-specific fallback) |
| `SASE_OPENCODE_SMALL_ARGS` | Extra CLI args for `small` tier (OpenCode-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_OPENCODE_*_ARGS`.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for OpenCode")` spinner is shown (unless `suppress_output` is
`True`).

## External Provider Plugins

Additional LLM providers are shipped as external packages that declare `[project.entry-points."sase_llm"]` in their own
`pyproject.toml`. Plugins carry all their own metadata (model names, skill deploy path, CLI status color, auto-detect
priority, retry defaults) via pluggy `@hookimpl` methods — sase core has no plugin-specific branching.

External provider packages own their CLI invocation details, model metadata, skill deployment path, auto-detect
priority, and retry defaults. Install the provider package in the same environment as sase to make its `sase_llm` entry
point available.

## Configuration

The LLM provider reads its configuration from `~/.config/sase/sase.yml` under the `llm_provider` key.

### Config File

```yaml
llm_provider:
  provider: claude # or "qwen", "opencode", "gemini" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
  model_aliases:
    other: claude/opus
```

### Config Fields

| Field                               | Type   | Default     | Description                                                                                                                                          |
| ----------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`             | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; built-ins default to claude → codex → qwen → opencode → gemini.          |
| `llm_provider.model_tier_map.large` | string | -           | Model identifier for the `large` tier                                                                                                                |
| `llm_provider.model_tier_map.small` | string | -           | Model identifier for the `small` tier                                                                                                                |
| `llm_provider.model_aliases`        | dict   | -           | Model aliases for `%model:<alias>` / `%m:<alias>`. Values can be bare known models, explicit `provider/model`, or nested provider-local model paths. |

## Per-Prompt Provider Switching

The `%model` directive (see [xprompt directives](xprompt.md#directives)) can switch both the model and the LLM provider
for a single prompt. Provider resolution uses configured aliases first, then concrete provider/model syntax and known
model metadata.

### Configured Model Aliases

Use `llm_provider.model_aliases` to define launch-time aliases for reusable prompts:

```yaml
llm_provider:
  model_aliases:
    other: claude/opus
```

Then prompts can use:

```
%model:other
%m(other,gpt-5.5)
```

Alias values may point at another alias, a bare known model such as `opus`, an explicit provider/model string such as
`claude/opus`, or a nested provider-local path such as `opencode/anthropic/claude-sonnet-4-5`. Cycles are ignored and
fall back to the raw input.

#### Reserved alias: `other`

The literal alias name `other` is reserved as a context-aware key. When a
[temporary default override](#temporary-default-override) is active, `%model:other` (and `%m:other`) resolves to the
`(provider, model)` that was the effective default _immediately before_ the override was set — captured in the
override's `pre_override_*` snapshot. When no override is active, `other` falls back to whatever the user configured
under `llm_provider.model_aliases.other` (or the literal model name `other` if no alias is configured).

This makes `%m(other, …)` always pair "the alternate model" with the current default, even when the user has temporarily
switched their default via the ACE `,P` chord. Without the snapshot, `%m(other, …)` on an override-displaced default
could otherwise launch the override's model side-by-side with itself.

### Explicit Provider/Model Syntax

Use `provider/model` to specify both explicitly:

```
%model:codex/o3
%model:claude/opus
%model:gemini/gemini-2.5-pro
%model:qwen/qwen3.6-plus
%model:opencode/anthropic/claude-sonnet-4-5
```

### Automatic Provider Resolution

Known model names are automatically mapped to their provider:

| Model Name                                                                                                                                                | Provider |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `opus`, `sonnet`, `haiku`                                                                                                                                 | claude   |
| `gpt-5.5`, `gpt-5.3-codex`, `codex-mini-latest`, `o3`, `o4-mini`, `gpt-5.4`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`                           | codex    |
| `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-3.1-pro`, `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-2.0-flash`                            | gemini   |
| `qwen3.6-plus`, `qwen3-coder-plus`, `qwen3-coder-flash`, `qwen3-max`, `qwen-plus`, `qwen-max`                                                             | qwen     |
| `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`, `openai/gpt-5`, `openai/gpt-5-mini`, `google/gemini-3-flash-preview`, `qwen/qwen3-coder-plus` | opencode |

Each installed plugin contributes its own model names via the `llm_known_model_names()` hook.

For unrecognized model names, the default provider is used.

Source: `src/sase/llm_provider/registry.py`

## Model Tier System

The model tier system abstracts away specific model names. Callers request either `"large"` (most capable) or `"small"`
(faster/cheaper), and the provider maps the tier to a concrete model.

### Type Definition

```python
ModelTier = Literal["large", "small"]
```

### Legacy Mapping

The old `"big"`/`"little"` terminology is still supported for backward compatibility:

| Old Value  | New Tier  | Display Label |
| ---------- | --------- | ------------- |
| `"big"`    | `"large"` | `BIG`         |
| `"little"` | `"small"` | `LITTLE`      |

The `model_size` parameter on `invoke_agent()` is deprecated. Use `model_tier` instead.

### Global Override

The model tier can be overridden globally via environment variable or CLI flag. The override forces ALL invocations to
use the specified tier regardless of what the caller requests.

**Resolution order:**

1. `SASE_MODEL_TIER_OVERRIDE` env var (accepts `"large"`, `"small"`, `"big"`, `"little"`)
2. `SASE_MODEL_SIZE_OVERRIDE` env var (legacy, same values)
3. `--model-tier` / `--model-size` CLI flag (sets the env var)
4. Caller's `model_tier` parameter (default: `"large"`)

## Temporary Default Override

In addition to the tier-based global override, sase supports a **concrete** provider/model override that acts as a
temporary session-level default. This is the override the ACE `,P` chord writes (see
[docs/ace.md](ace.md#temporary-model-override) for the TUI flow).

The temporary override only changes the _default_ provider/model selection for new agent launches. It does **not**
override:

- Already-running agents — they keep whatever provider/model they were launched with.
- Explicit `%model` prompt directives — they still take precedence.
- An explicit `provider_name=` argument to `invoke_agent()` — it still wins.

`SASE_MODEL_TIER_OVERRIDE` / `SASE_MODEL_SIZE_OVERRIDE` still force the tier for tier-based launches. A concrete
temporary override supplies a provider and model directly, so it is used only when no explicit model/provider was
requested.

### Resolution Order (default provider/model)

When no `%model` directive and no explicit `provider_name` are present, the default is resolved as:

1. **Active temporary override** at `~/.sase/llm_override.json` (if not expired).
2. `llm_provider.provider` from the merged `sase.yml` config.
3. Auto-detection by plugin-declared priority (built-ins: claude, codex, qwen, opencode, then gemini).

A concrete temporary override sets both the default provider and a concrete `model_override` for the next launch — so
the agent metadata (running marker, plan review badge, agent rows) reflects the actual model that will run, not just the
configured default.

### State File

```json
{
  "provider": "opencode",
  "model": "anthropic/claude-sonnet-4-5",
  "raw_model": "opencode/anthropic/claude-sonnet-4-5",
  "created_at": 1777470000.0,
  "expires_at": 1777473600.0,
  "source": "ace",
  "pre_override_provider": "claude",
  "pre_override_model": "opus",
  "pre_override_raw_model": "opus"
}
```

| Field                    | Type            | Description                                                                                                                 |
| ------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `provider`               | `str`           | Resolved provider name (e.g. `"claude"`, `"codex"`, `"opencode"`).                                                          |
| `model`                  | `str`           | Concrete model passed to the provider (e.g. `"o3"`, `"opus"`).                                                              |
| `raw_model`              | `str`           | Original user input (e.g. `"codex/o3"`, `"opencode/anthropic/..."`).                                                        |
| `created_at`             | `float`         | Unix timestamp when the override was set.                                                                                   |
| `expires_at`             | `float \| None` | Unix timestamp when the override expires; `null` means "until cleared".                                                     |
| `source`                 | `str`           | Free-form tag indicating who set the override (e.g. `"ace"`).                                                               |
| `pre_override_provider`  | `str \| None`   | Snapshot of the effective provider _before_ the override was set. Used to resolve the reserved `"other"` alias dynamically. |
| `pre_override_model`     | `str \| None`   | Snapshot of the effective model _before_ the override. Pairs with `pre_override_provider` to form the `"other"` target.     |
| `pre_override_raw_model` | `str \| None`   | Cosmetic copy of the displaced model's raw user-input form. May be `None` on legacy state files written before this field.  |

Writes are atomic (temp file + `os.replace`). Reads are best-effort self-cleaning: an expired or unparseable file is
deleted on next access, so a forgotten override never lingers past its `expires_at`, even with no TUI running.

### Model Resolution

The user-supplied `raw_model` is normalized through the same rules as `%model`:

- `provider/model` selects the provider explicitly (e.g. `codex/o3` or `opencode/anthropic/claude-sonnet-4-5`).
- A bare known model name infers its provider from plugin metadata (e.g. `sonnet` → claude).
- An unknown bare model is accepted and runs on the current default provider, matching `%model` behavior.

### Duration Parsing

Durations accept compact unit suffixes: `15m`, `1h`, `1h30m`, `90m`, `2h15m30s`. Bare integers are interpreted as
minutes (`45` → 45 minutes). The case-insensitive sentinel `until cleared` (or `until_cleared`) means "no expiry —
persists until the user clears it from the TUI or another sase process clears the state file."

### Public API

The override primitives live in `src/sase/llm_provider/temporary_override.py`:

| Function                                     | Purpose                                                          |
| -------------------------------------------- | ---------------------------------------------------------------- |
| `get_active_temporary_override(now=None)`    | Read the active override (auto-deletes expired/malformed files). |
| `set_temporary_override(raw, dur, source=)`  | Write a new override, replacing any existing one.                |
| `clear_temporary_override()`                 | Remove the override file. Safe to call when nothing is active.   |
| `parse_override_duration(value)`             | Parse a user-facing duration string into seconds (or `None`).    |
| `resolve_effective_default_provider_model()` | Centralized helper used by metadata pre-resolution paths.        |

### Examples

- ACE chord `,P`, pick `codex/o3`, duration `1h` → `~/.sase/llm_override.json` is written; new launches default to
  CODEX(o3) for the next hour.
- ACE chord `,P`, pick `opencode/anthropic/claude-sonnet-4-5`, duration `1h` → new launches default to
  OPENCODE(anthropic/claude-sonnet-4-5).
- ACE chord `,P`, pick `sonnet`, duration `30m` → known bare model; provider resolves to claude via plugin metadata.
- ACE chord `,P`, choose **Clear override** → `~/.sase/llm_override.json` is removed; defaults revert to permanent
  config / autodetect.

## Environment Variables

Complete reference of environment variables used by the LLM provider layer.

### Generic (Provider-Agnostic)

| Variable                   | Description                                    |
| -------------------------- | ---------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`      | Extra CLI args for `large` tier invocations    |
| `SASE_LLM_SMALL_ARGS`      | Extra CLI args for `small` tier invocations    |
| `SASE_MODEL_TIER_OVERRIDE` | Force all invocations to a specific model tier |
| `SASE_MODEL_SIZE_OVERRIDE` | Legacy alias for `SASE_MODEL_TIER_OVERRIDE`    |

### Claude-Specific

| Variable                 | Description                                 |
| ------------------------ | ------------------------------------------- |
| `SASE_CLAUDE_LARGE_ARGS` | Claude-specific extra args for `large` tier |
| `SASE_CLAUDE_SMALL_ARGS` | Claude-specific extra args for `small` tier |

### Codex-Specific

| Variable                         | Description                                     |
| -------------------------------- | ----------------------------------------------- |
| `SASE_CODEX_PATH`                | Path to the Codex CLI binary                    |
| `SASE_CODEX_LARGE_ARGS`          | Codex-specific extra args for `large` tier      |
| `SASE_CODEX_SMALL_ARGS`          | Codex-specific extra args for `small` tier      |
| `SASE_CODEX_DISABLE_SHADOW_HOME` | Set to `1` to disable the disposable Codex home |

### Qwen-Specific

| Variable               | Description                               |
| ---------------------- | ----------------------------------------- |
| `SASE_QWEN_PATH`       | Path to the Qwen Code CLI binary          |
| `SASE_QWEN_LARGE_ARGS` | Qwen-specific extra args for `large` tier |
| `SASE_QWEN_SMALL_ARGS` | Qwen-specific extra args for `small` tier |

### Gemini-Specific

| Variable           | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `SASE_GEMINI_PATH` | Path to the Gemini CLI binary (default: `"gemini"`). |

### OpenCode-Specific

| Variable                   | Description                                   |
| -------------------------- | --------------------------------------------- |
| `SASE_OPENCODE_PATH`       | Path to the OpenCode CLI binary               |
| `SASE_OPENCODE_LARGE_ARGS` | OpenCode-specific extra args for `large` tier |
| `SASE_OPENCODE_SMALL_ARGS` | OpenCode-specific extra args for `small` tier |

External provider plugins document their own environment variables in their respective repos.

### VCS Provider

| Variable            | Description                                          |
| ------------------- | ---------------------------------------------------- |
| `SASE_VCS_PROVIDER` | Override VCS provider (`"git"`, `"hg"`, or `"auto"`) |

## CLI Flags

### ace

| Flag               | Values              | Description                                 |
| ------------------ | ------------------- | ------------------------------------------- |
| `-m, --model-tier` | `large`, `small`    | Override model tier for all LLM invocations |
| `--model-size`     | `big`, `little`     | Deprecated alias for `--model-tier`         |
| `--vcs-provider`   | `git`, `hg`, `auto` | Override VCS provider                       |

### axe

| Flag             | Values              | Description           |
| ---------------- | ------------------- | --------------------- |
| `--vcs-provider` | `git`, `hg`, `auto` | Override VCS provider |

The `ace` command wires `--model-tier` / `--model-size` into the `model_tier_override` parameter of `AceApp`. The
`--vcs-provider` flag is wired to the `SASE_VCS_PROVIDER` environment variable for downstream resolution.

## Retry and Fallback

The LLM provider layer supports per-provider retry and fallback configuration. When an agent encounters a retryable
error, it can automatically wait and retry, then optionally fall back to an alternate model.

### Configuration

Retry behavior is configured per provider under `llm_provider.retry` in `sase.yml`:

```yaml
llm_provider:
  retry:
    gemini:
      max_retries: 3
      error_patterns:
        - "An unexpected critical error occurred:"
      wait_times: [60, 300, 1800]
      fallback_model: "gemini-3-flash-preview"
```

### Config Fields

| Field                 | Type          | Default | Description                                                                                                                                                                                      |
| --------------------- | ------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `max_retries`         | int           | `0`     | Maximum retry attempts. `0` disables retrying.                                                                                                                                                   |
| `error_patterns`      | list[str]     | `[]`    | Case-insensitive substring patterns matched against error output.                                                                                                                                |
| `wait_times`          | list[int]     | `[30]`  | Per-retry wait times in seconds. Last value reused if list is too short.                                                                                                                         |
| `fallback_model`      | `str \| null` | `null`  | Alternate model to use after exhausting all retries.                                                                                                                                             |
| `continuation_prompt` | `str \| null` | `null`  | Text prepended to `state.current_prompt` on every retry (used to nudge the agent).                                                                                                               |
| `preserve_workspace`  | bool          | `false` | Preserve on-disk edits across legacy in-process retry attempts.                                                                                                                                  |
| `spawn_new_agent`     | bool          | `false` | Opt in to spawn-on-retry: a retryable error spawns a fresh detached child agent (as if `sase run -d` had been invoked) instead of in-process retry. See [Spawn-on-Retry](#spawn-on-retry) below. |

### Default Configuration

Retry defaults can come from two places: configured policy under `llm_provider.retry` and provider-supplied defaults
from the `llm_default_retry_config()` hook. The bundled `default_config.yml` already provides configured policy for
Gemini and Claude; user config can replace or extend it through the normal config merge.

**Gemini:**

- **max_retries**: 3
- **error_patterns**: `["An unexpected critical error occurred:"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"gemini-3-flash-preview"`

**Claude:**

- **max_retries**: 3
- **error_patterns**: `["API Error: 500", "API Error: 529", "Internal server error", "overloaded_error"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"sonnet"`

### Provider-Supplied Retry Defaults

Providers can also declare retry defaults through the `llm_default_retry_config()` hook. Claude declares a recovery
entry that is merged with the configured Claude policy:

- **error patterns**: `"Prompt is too long"`, `"socket connection was closed unexpectedly"`, and `"API Error"`
- **max_retries**: 3
- **wait_times**: `[0]` — used only when no config layer supplies `wait_times`; the bundled Claude policy supplies
  `[60, 300, 1800]`, so that is the out-of-the-box backoff
- **continuation_prompt**: A short nudge that tells the coder to inspect `git status` / `git diff` before resuming,
  since prior edits are preserved on disk after a context-limit, socket-close, or API-error retry
- **preserve_workspace**: `true`

Configured `llm_provider.retry.<provider>` values are merged on top of provider-supplied defaults: explicit falsy values
(`max_retries: 0` to opt out entirely, `continuation_prompt: ""` to disable the nudge) override the built-in via
key-presence checks. `error_patterns` is a de-duplicated union of built-in and configured lists.

On every retry attempt the `continuation_prompt` (if non-empty) is idempotently prepended to `state.current_prompt`
before the next invocation — the prepend is gated on a `startswith` check so repeated retries don't stack duplicate
nudges. Workspaces are preserved across Claude's built-in context-limit, socket-close, and API-error retries (no
workspace wipe), so on-disk edits remain available to the restarted session.

### Retry Flow

```
Error detected
│
├── Does error match error_patterns? (case-insensitive substring)
│   ├── No  → fail immediately
│   └── Yes → retry_count < max_retries?
│       ├── Yes → wait (wait_times[retry_count]) → retry
│       └── No  → fallback_model configured and not already using fallback?
│           ├── Yes → set fallback model override → retry once
│           └── No  → fail
```

Wait periods are interruptible — if the agent is killed during a wait, it stops immediately.

### TUI Display

The ACE Agents tab reflects retry state (see [Retry/Fallback Display](ace.md#retryfallback-display)):

- **RETRYING (Ns)** — Waiting before the next attempt (bold orange, with countdown)
- **↻N** — Retry count annotation on running agents
- **▸Model** — Fallback model annotation (e.g., `↻3▸flash`)

### Metadata Tracking

After execution completes, retry metadata is written to `done.json` in the agent's artifacts directory:

```json
{
  "retry_count": 2,
  "retry_errors": ["An unexpected critical error occurred: ..."],
  "used_fallback": false
}
```

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/axe/run_agent_exec.py`

### Spawn-on-Retry

When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh detached child agent (as if
`sase run -d` had been invoked) instead of running the next attempt in-process. The failing parent transfers its
workspace claim to the child via `transfer_workspace_claim()` and exits with status `FAILED (RETRIED)`. This trades the
small cost of a fresh process for two benefits:

- The workspace is preserved by design — the child skips `prepare_workspace()` and inherits the parent's in-progress
  edits via the transferred workspace claim. (Legacy in-process retry runs `prepare_workspace()` between attempts and
  wipes uncommitted file edits unless `preserve_workspace=True`.)
- A retry boundary becomes a real process boundary, which is more robust against memory leaks, lingering child
  processes, and stale interpreter state.

**Linkage fields** (written to both `agent_meta.json` and `done.json` so retry chains are queryable from either side):

| Field                        | Meaning                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `retry_of_timestamp`         | Backward link: the parent agent's run timestamp.                                  |
| `retried_as_timestamp`       | Forward link: the child agent's run timestamp (written on the parent at handoff). |
| `retry_chain_root_timestamp` | The root agent's timestamp — stable across the entire chain.                      |
| `retry_attempt`              | Depth in the chain (1-based).                                                     |

State is carried across the boundary by a `retry_handoff.json` file written to the parent's artifacts directory; the
child reads it before launch.

**Fallback behavior**: spawn-on-retry is opt-in (default `false`). If spawning fails (e.g. workspace transfer fails),
the legacy in-process retry runs as a fallback so the user is never worse off.

Source: `src/sase/axe/run_agent_retry_spawn.py`, `src/sase/llm_provider/retry_config.py`

## Legacy Thinking Metadata

Older parser helpers can still read provider thinking/reasoning artifacts when a caller uses them directly. For Claude
extended-thinking events whose `thinking` text is empty but whose payload contains an opaque `signature`, those helpers
produce an encrypted-thinking placeholder instead of hiding the block. When Claude also reports
`message.usage.output_tokens`, the placeholder includes an approximate output-token count so the caller can tell that
reasoning occurred even though the raw thought text is not available. The Agents tab now uses the Tools panel for
provider tool activity instead of exposing these thinking helpers as a panel.

## Token Usage Tracking

The LLM provider layer tracks token usage for providers that emit parseable usage events. Claude and Qwen usage is read
from their stream-json result events. OpenCode usage is accumulated from `step_finish` token counters. Codex currently
captures assistant text and reasoning summaries but does not emit `usage.json`.

When usage is available, input tokens, output tokens, cache-creation tokens, and cache-read tokens are persisted as a
`usage.json` artifact in the agent run directory.

### Artifact Format

```json
{
  "input_tokens": 12345,
  "output_tokens": 6789,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 3456
}
```

When telemetry is enabled, token counts are also recorded as Prometheus counters (`sase_llm_input_tokens_total`,
`sase_llm_output_tokens_total`, `sase_llm_cache_read_tokens_total`) for monitoring and dashboards. See
[docs/telemetry.md](telemetry.md) for the full telemetry reference.

Source: `src/sase/llm_provider/_subprocess.py`, `src/sase/llm_provider/types.py`

## Prompt Preprocessing Pipeline

Before any prompt reaches a provider, it passes through the shared preprocessing pipeline defined in `preprocessing.py`.
The pipeline has an early phase used for xprompt expansion and directive extraction, then a late phase used for command,
file, template, and formatting work.

### Steps

| Phase | Step                       | Syntax                                     | Description                                               |
| ----- | -------------------------- | ------------------------------------------ | --------------------------------------------------------- |
| Early | Optional workflow Jinja2   | `{{ var }}`                                | Render workflow-supplied template context before xprompt  |
| Early | xprompt references         | `#name`                                    | Expand reusable prompt snippets or workflows              |
| Early | Prompt directives          | `%model`, `%m`, other `%...` directives    | Extract directives after xprompt expansion                |
| Late  | Disabled/fenced protection | `%xprompts_enabled:false`, fenced code     | Protect regions that should not be rewritten              |
| Late  | Command substitution       | `$(cmd)`                                   | Execute shell commands and inline their output            |
| Late  | Dynamic memory rewrite     | `@.sase/memory/long-*.md`                  | Ensure dynamic memory files exist relative to current CWD |
| Late  | File references            | `@path`                                    | Process, validate, or skip file references                |
| Late  | Top-level Jinja2           | `{{ var }}`                                | Render remaining top-level Jinja2 templates               |
| Late  | Prettier formatting        | -                                          | Format with prettier for consistent markdown              |
| Late  | Comment stripping          | `<!-- ... -->`                             | Remove HTML/markdown comments                             |
| Late  | Restore protected regions  | fenced code / disabled-region placeholders | Restore protected content after rewrites                  |

### Order Matters

The pipeline runs in strict order. Prompt directives are extracted after xprompt expansion, so directives embedded in
xprompts are honored. Late-phase command substitution and file-reference processing run with fenced blocks protected, so
examples inside code fences are not executed or rewritten.

### Home Mode

When `is_home_mode=True`, file-reference processing skips copy side effects. This is used when the invocation doesn't
need workspace-local copies from `@path` references.

### Source Functions

The preprocessing steps delegate to functions from two libraries:

- **`xprompt`**: `process_xprompt_references()`, `extract_prompt_directives()`, `is_jinja2_template()`,
  `render_toplevel_jinja2()`
- **`gemini_wrapper.file_references`**: `process_command_substitution()`, `process_file_references()`,
  `validate_file_references()`, `format_with_prettier()`, `strip_html_comments()`

## Subprocess Streaming

Providers use shared helpers in `_subprocess.py` and the `_subprocess_*` modules to stream LLM output in real time.
Plain text, JSON-line, and provider-specific parsers share the same artifact hooks for live replies and usage files.

### Mechanism

1. The provider spawns the CLI tool via `subprocess.Popen`. Providers that consume prompts from stdin set `stdin=PIPE`;
   OpenCode passes the prompt as the final `opencode run` argument.
2. The prompt is supplied using the provider's documented transport, either stdin or an argv message argument.
3. Stdout and stderr are set to **non-blocking** mode via `os.set_blocking()`.
4. A `select.select()` loop with a 0.1s timeout polls for readable data on both streams.
5. Lines are read, parsed when needed, and optionally printed to the console in real time.
6. After the process exits (`process.poll() is not None`), any remaining buffered output is drained.
7. Helpers return stdout/assistant text, stderr diagnostics, return code, and usage data when the provider reports it.

### Live Reply File

When `SASE_ARTIFACTS_DIR` is set, the streaming output is also written in real-time to
`<SASE_ARTIFACTS_DIR>/live_reply.md`. This file is used by the ACE TUI Agents tab to display the agent's reply as it
streams in, and remains available after execution completes for the metadata panel's AGENT REPLY section.

Providers that support richer streams may write companion artifacts. Codex writes reasoning summaries to
`<SASE_ARTIFACTS_DIR>/codex_thinking.jsonl`; providers with token counters write `<SASE_ARTIFACTS_DIR>/usage.json`.

### Output Suppression

When `suppress_output=True`, lines are still captured but not printed to the console. This is used for background
invocations where the caller only needs the final result.

## Postprocessing

After a provider returns (or raises an error), the orchestration layer runs postprocessing steps.

### On Success (`postprocess_success`)

1. **Audio notification**: Plays a sound via `run_bam_command("Agent reply received")` (skipped if `suppress_output`).
2. **Log to sase.md**: Appends a timestamped entry with the prompt and response to `<artifacts_dir>/sase.md` (if
   `artifacts_dir` is set).
3. **Save chat history**: Writes to `~/.sase/chats/` if `workflow` is set. See [Chat History](#chat-history).

### On Error (`postprocess_error`)

1. **Rich error display**: Prints the prompt and error via `print_prompt_and_response()` with an `_ERROR` suffix on the
   agent type label (skipped if `suppress_output`).
2. **Log to sase.md**: Same as success, but the response is the error message and the agent type gets an `_ERROR`
   suffix.
3. **Save error chat history**: Writes to `~/.sase/chats/` with an `_ERROR` agent suffix.

### sase.md Log Format

Each entry in the log file follows this format:

```markdown
## <timestamp> - <agent_type> - iteration <N> - tag <workflow_tag>

### PROMPT:

\`\`\` <prompt text> \`\`\`

### RESPONSE:

\`\`\` <response text> \`\`\`

---
```

### Prompt File Saving

Before invocation, the preprocessed prompt is saved to `<artifacts_dir>/<agent_type>_prompt.md` (or
`<agent_type>_iter_<N>_prompt.md` if an iteration number is set). This allows reviewing the exact prompt that was sent.

## Chat History

Chat histories are stored as markdown files in `~/.sase/chats/`.

### File Naming

```
<branch_or_workspace>-<workflow>-[<agent>-]<timestamp>.md
```

| Part                  | Source                                   | Example             |
| --------------------- | ---------------------------------------- | ------------------- |
| `branch_or_workspace` | Output of `branch_or_workspace_name`     | `my_feature`        |
| `workflow`            | Workflow name, normalized                | `crs`, `run`        |
| `agent`               | Agent type (omitted if same as workflow) | `editor`, `planner` |
| `timestamp`           | `YYmmdd_HHMMSS` format                   | `260214_153042`     |

Dashes and slashes in workflow names are normalized to underscores.

### File Format

```markdown
# Chat History - <workflow> (<agent>)

**Timestamp** <display_timestamp>

**MODEL** <provider>/<model>

**AGENT** <sase_agent_name>

## Previous Conversation

<previous history if resuming>

---

## Prompt

<prompt text>

## Response

<response text>
```

The `MODEL` and `AGENT` blocks are omitted when the invocation did not provide that metadata. `MODEL` can contain just a
model name, just a provider name, or both. When both provider and model are known, it is rendered as
`<provider>/<model>` unless the model already includes that prefix.

### Resume Support

The `sase run --resume` flag resumes a previous conversation by agent name. The `#fork` workflow resolves the agent name
to its artifacts directory, extracts the response path from `done.json`, and delegates to `#fork_by_chat` which loads
the chat history and prepends it to the new conversation. The `--resume` flag also accepts a history file basename or
full path for direct chat-file-based resumption via the `#fork_by_chat` workflow.

Fork expansion is recursive: if the loaded chat history itself contains `#fork` or `#fork_by_chat` references, those are
expanded inline as well. Legacy `#resume` and `#resume_by_chat` references in old transcripts are still recognized.
Cycle detection prevents infinite loops when chat histories reference each other.

## Invocation Lifecycle

The `invoke_agent()` function in `_invoke.py` orchestrates the complete lifecycle of an LLM invocation. Here is the
end-to-end flow:

```
invoke_agent(prompt, agent_type, model_tier, ...)
│
├── 1. Handle deprecated model_size → model_tier mapping
├── 2. Check SASE_MODEL_TIER_OVERRIDE / SASE_MODEL_SIZE_OVERRIDE env vars
├── 3. Build LoggingContext from parameters
│
├── 4. Preprocess prompt unless skip_preprocessing=True
│   ├── early phase: optional workflow Jinja2, xprompt expansion, directive extraction
│   └── late phase: command substitution, file refs, top-level Jinja2, formatting, comment stripping
│
├── 5. Resolve %model / temporary provider-model override
├── 6. Display decision counts (if not suppressed)
├── 7. Print prompt via Rich (if not suppressed)
├── 8. Generate or use provided timestamp
├── 9. Save prompt to artifacts directory
│
├── 10. Get provider from registry and invoke
│   ├── Build CLI command with flags
│   ├── Spawn subprocess (Popen)
│   ├── Supply prompt via provider transport
│   └── Stream stdout/stderr in real-time
│
├── 11. Run commit finalizer for SASE agent sessions
│   ├── Skip when disabled or outside an agent session
│   ├── Check main workspace and configured Git sibling repos
│   ├── Auto-commit exact SDD plan done-status closeouts
│   └── Run bounded follow-up provider invocations until enforced repos are clean or failed
│
├── 12. Postprocess
│   ├── Success path:
│   │   ├── Audio notification
│   │   ├── Log to sase.md
│   │   └── Save chat history
│   └── Error path:
│       ├── Rich error display
│       ├── Log error to sase.md
│       └── Save error chat history
│
└── 12. Return AIMessage(content=response), or raise LLMInvocationError on failure
```

### Parameters

| Parameter             | Type                        | Default    | Description                                       |
| --------------------- | --------------------------- | ---------- | ------------------------------------------------- |
| `prompt`              | `str`                       | (required) | Raw prompt to send                                |
| `agent_type`          | `str`                       | (required) | Agent type label (e.g., `"editor"`)               |
| `model_tier`          | `ModelTier`                 | `"large"`  | Model tier to use                                 |
| `model_size`          | `"big" \| "little" \| None` | `None`     | Deprecated, use `model_tier`                      |
| `iteration`           | `int \| None`               | `None`     | Iteration number for logging                      |
| `workflow_tag`        | `str \| None`               | `None`     | Workflow tag for logging                          |
| `artifacts_dir`       | `str \| None`               | `None`     | Directory for sase.md, prompt, and stream files   |
| `workflow`            | `str \| None`               | `None`     | Workflow name for chat history                    |
| `suppress_output`     | `bool`                      | `False`    | Suppress console output                           |
| `timestamp`           | `str \| None`               | `None`     | Shared timestamp (`YYmmdd_HHMMSS`)                |
| `is_home_mode`        | `bool`                      | `False`    | Skip file copying for `@` references              |
| `branch_or_workspace` | `str \| None`               | `None`     | Override the chat-history filename prefix         |
| `decision_counts`     | `dict[str, Any] \| None`    | `None`     | Planning agent decision counts                    |
| `provider_name`       | `str \| None`               | `None`     | Override provider (default from config)           |
| `skip_preprocessing`  | `bool`                      | `False`    | Use `prompt` as already-preprocessed input        |
| `directives`          | `PromptDirectives \| None`  | `None`     | Pre-extracted directives for `skip_preprocessing` |

### Return Value

On success, returns an `AIMessage` (from `langchain_core.messages`) whose `content` is the provider response. On
provider failure, `invoke_agent()` logs the error and raises `LLMInvocationError` with the formatted error text.
