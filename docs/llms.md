# LLM Provider Integration

This document describes the LLM provider abstraction layer in sase. The system supports
pluggable LLM backends (Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code,
OpenCode, Meta's Muse Code, and xAI's Grok Build are bundled; additional providers can
ship as external plugins) behind a shared orchestration layer that handles
preprocessing, invocation, and postprocessing.

> This page documents how SASE _integrates_ each provider. To install and authenticate a
> provider CLI in the first place, see
> [Installing & Authenticating Agent Providers](agent_providers.md).

## Table of Contents

- [Overview](#overview)
- [Provider Architecture](#provider-architecture)
- [Commit Finalization](#commit-finalization)
- [Claude Code Integration](#claude-code-integration)
- [Antigravity (`agy`) Integration](#antigravity-agy-integration)
- [Codex CLI Integration](#codex-cli-integration)
- [Qwen Code Integration](#qwen-code-integration)
- [OpenCode Integration](#opencode-integration)
- [Muse Code Integration](#muse-code-integration)
- [Grok Build Integration](#grok-build-integration)
- [External Provider Plugins](#external-provider-plugins)
- [Configuration](#configuration)
- [Per-Prompt Provider Switching](#per-prompt-provider-switching)
- [Reasoning Effort](#reasoning-effort)
- [Model Tier System](#model-tier-system)
- [Role Aliases for Delegated Work](#role-aliases-for-delegated-work)
- [Temporary Model Overrides](#temporary-model-overrides)
- [Temporary Provider Disables](#temporary-provider-disables)
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
- **Runtime-uniform commit enforcement**: SASE agent sessions use a shared commit
  finalizer instead of provider-specific native stop hooks.

### Source Layout

| File                                              | Purpose                                                                                  |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `src/sase/llm_provider/__init__.py`               | Public API exports                                                                       |
| `src/sase/llm_provider/base.py`                   | `LLMProvider` abstract base class                                                        |
| `src/sase/llm_provider/_hookspec.py`              | Pluggy hook specifications (`LLMHookSpec`)                                               |
| `src/sase/llm_provider/_plugin_manager.py`        | Plugin manager wrapping pluggy (`LLMPluginManager`)                                      |
| `src/sase/llm_provider/claude.py`                 | Claude Code provider implementation                                                      |
| `src/sase/llm_provider/codex.py`                  | Codex CLI provider implementation                                                        |
| `src/sase/llm_provider/fakey.py`                  | Bundled deterministic testing provider                                                   |
| `src/sase/llm_provider/agy.py`                    | Antigravity CLI (`agy`) provider implementation                                          |
| `src/sase/llm_provider/qwen.py`                   | Qwen Code provider implementation                                                        |
| `src/sase/llm_provider/opencode.py`               | OpenCode provider implementation                                                         |
| `src/sase/llm_provider/muse.py`                   | Meta Muse Code provider implementation                                                   |
| `src/sase/llm_provider/_subprocess_muse.py`       | Muse `exec --json` JSONL stream parser                                                   |
| `src/sase/llm_provider/_tool_call_muse.py`        | Muse tool-call record extraction from the event stream                                   |
| `src/sase/llm_provider/_muse_session_usage.py`    | Muse token-usage recovery from the on-disk session log                                   |
| `src/sase/llm_provider/grok.py`                   | xAI Grok Build provider implementation                                                   |
| `src/sase/llm_provider/_subprocess_claude.py`     | Provider-neutral Anthropic-Messages stream reader shared by Claude and Grok              |
| `src/sase/llm_provider/_tool_call_grok.py`        | Grok tool-call normalization (native names → canonical display names)                    |
| `src/sase/llm_provider/registry.py`               | Provider registration and lookup                                                         |
| `src/sase/llm_provider/_registry_metadata.py`     | Provider metadata normalization and cache fingerprints                                   |
| `src/sase/llm_provider/_registry_plugins.py`      | Plugin discovery/construction via `sase_llm` entry points                                |
| `src/sase/llm_provider/model_alias_defaults.yml`  | Single bundled source of truth for shipped implicit-alias targets/fallbacks/descriptions |
| `src/sase/llm_provider/model_alias_policy.py`     | Model-alias name constants and the validating loader for `model_alias_defaults.yml`      |
| `src/sase/llm_provider/model_alias_config.py`     | Model-alias config parsing and presentation metadata                                     |
| `src/sase/llm_provider/model_alias_resolution.py` | Alias/target/effort resolution logic                                                     |
| `src/sase/llm_provider/alias_view.py`             | ACE Launch Control alias-view construction (`build_alias_views()`)                       |
| `src/sase/llm_provider/config.py`                 | Config file reader (`sase.yml`)                                                          |
| `src/sase/llm_provider/temporary_override.py`     | Primary/worker temporary override state and resolution                                   |
| `src/sase/llm_provider/provider_disable.py`       | Rust-backed temporary provider-disable facade                                            |
| `src/sase/llm_provider/provider_disable_peek.py`  | Lock-free display peek for active provider disables                                      |
| `src/sase/llm_provider/commit_finalizer.py`       | Provider-neutral dirty-workspace finalizer                                               |
| `src/sase/llm_provider/types.py`                  | `ModelTier`, `InvokeResult`, `LoggingContext` types                                      |
| `src/sase/llm_provider/_invoke.py`                | `invoke_agent()` orchestrator                                                            |
| `src/sase/llm_provider/_subprocess.py`            | Provider stream-parser compatibility exports                                             |
| `src/sase/llm_provider/_plan_utils.py`            | Shared plan utilities                                                                    |
| `src/sase/llm_provider/preprocessing.py`          | Shared prompt preprocessing pipeline                                                     |
| `src/sase/llm_provider/postprocessing.py`         | Logging, chat history, audio                                                             |
| `src/sase/llm_provider/retry_config.py`           | `ProviderRetryConfig` (per-provider retry defaults)                                      |

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

Returns `InvokeResult(content=..., usage=...)`. Providers raise
`subprocess.CalledProcessError` for failed CLI exits or a provider-specific exception
for launch/configuration failures.

### Registry

Providers are discovered via `importlib.metadata.entry_points(group="sase_llm")`. The
built-in providers are packaged the same way as external provider plugins; their entry
points live in `pyproject.toml`:

```toml
[project.entry-points."sase_llm"]
claude = "sase.llm_provider.claude:ClaudeCodeProvider"
codex  = "sase.llm_provider.codex:CodexProvider"
fakey = "sase.llm_provider.fakey:FakeyProvider"
agy = "sase.llm_provider.agy:AgyProvider"
grok = "sase.llm_provider.grok:GrokProvider"
muse = "sase.llm_provider.muse:MuseProvider"
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
2. If the prompt has a `%model` directive, resolve explicit `provider/model` syntax
   first, then known model names from installed plugin metadata.
3. If no explicit provider/model was supplied, use an active temporary override from
   `~/.sase/llm_override.json`.
4. Otherwise, read the `llm_provider.provider` field from `~/.config/sase/sase.yml`.
5. If no config exists (or provider is empty), auto-detect by walking registered plugins
   in ascending `llm_autodetect_priority()` order and picking the first whose
   `llm_autodetect_cli_name()` is on `PATH`. Built-in priorities: `claude=0`,
   `codex=10`, `qwen=15`, `opencode=18`, `agy=30`. External plugins slot in by declaring
   their own priority. `agy` autodetects via the `agy` CLI name in the late-fallback
   slot. A provider that declares no priority never participates in autodetection:
   `muse` and `grok` deliberately omit one, because `muse` and `grok` are both generic
   executable names and autodetect only checks `PATH` presence. Muse is reachable only
   by explicit selection (see [Muse Code Integration](#muse-code-integration)). Grok
   never participates in autodetection either, but it is reached automatically by the
   shipped `@xsmall`/`@small`/`@medium` load-balanced pools, or as the last candidate in
   `@xlarge`'s ordered fallback, whenever the `grok` CLI is installed (see
   [Grok Build Integration](#grok-build-integration)).

## Commit Finalization

After a provider returns successfully, `invoke_agent()` runs the provider-neutral commit
finalizer before success postprocessing when the process is a SASE agent session
(`SASE_AGENT_TIMESTAMP` is set). The finalizer checks the active project workspace
through the active VCS provider and checks configured linked repositories as Git
worktrees at their resolved `workspace_dir`. If it finds dirty enforced work, it sends
the same provider a bounded follow-up prompt that lists the dirty files and instructs
the agent to use the appropriate commit skill, such as `/sase_git_commit`. Dirty linked
repo clones are enforced like the main workspace. A narrow generated SDD plan closeout,
where the only enforced change is one markdown file's frontmatter `status: wip` becoming
`status: done`, is committed directly with a `SASE_TYPE=sdd` commit instead of consuming
a provider follow-up pass.

The finalizer skips when the call is outside a SASE agent session, when
`commit.finalizer.enabled` is false, or when `SASE_DISABLE_COMMIT_STOP_HOOK=1` is set.
When an artifacts directory is available, each follow-up pass writes
`commit_finalizer_pass_<N>_prompt.md` and `commit_finalizer_pass_<N>_response.md`; the
final outcome is written to `commit_finalizer_result.json`. If the workspace remains
dirty after `commit.finalizer.max_passes`, the invocation is converted into an
`LLMInvocationError` rather than being logged as a successful clean run.

The older provider-native commit hook scripts are no longer shipped; SASE-launched agent
sessions rely on the shared finalizer path.

## Claude Code Integration

The `ClaudeCodeProvider` invokes the `claude` CLI tool.

### Command Construction

```
claude -p --verbose --model <alias> --output-format stream-json --dangerously-skip-permissions --session-id <uuid> [extra_args...]
```

The prompt is written to stdin. Output is streamed as JSON events; SASE extracts
assistant text and token usage from the stream.

### Model Mapping

| Tier    | Claude CLI Alias |
| ------- | ---------------- |
| `large` | `opus`           |
| `small` | `sonnet`         |

`opus` and `sonnet` are floating Claude CLI aliases that Claude resolves to its current
model (Opus 5 today), so SASE intentionally does not pin them to point version IDs.

### Environment Variables

| Variable                 | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`    | Extra CLI args for `large` tier (generic, preferred)       |
| `SASE_LLM_SMALL_ARGS`    | Extra CLI args for `small` tier (generic, preferred)       |
| `SASE_CLAUDE_LARGE_ARGS` | Extra CLI args for `large` tier (Claude-specific fallback) |
| `SASE_CLAUDE_SMALL_ARGS` | Extra CLI args for `small` tier (Claude-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence. Values are split on whitespace
and appended to the command.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Claude")` spinner is shown
(unless `suppress_output` is `True`).

### Claude Tool-Call Hooks

To record what tools an agent actually invoked (file reads, edits, bash commands, etc.),
`ClaudeCodeProvider.invoke()` asks Claude Code to call back into SASE every time a tool
runs. It does this by writing a pair of `PreToolUse` and `PostToolUse` hook entries into
the workspace's `.claude/settings.local.json` for the duration of the agent run. Each
entry matches all tools (`"matcher": "*"`) and invokes the `sase_claude_tool_hook`
console script, which reads the Claude-supplied JSON payload from stdin and appends one
normalized record (schema version 3) to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl`:

- The `PreToolUse` hook writes a pending entry capturing the tool name and a redacted
  version of its input.
- The `PostToolUse` hook writes the matching result entry: success/failure/interrupted
  status, the call's duration, and a length-bounded preview of the response.

The ACE Tools panel reads this same `tool_calls.jsonl` to render the per-agent timeline
— see [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel).

Installation and cleanup are wrapped in a `claude_hooks_session()` context manager that
is careful not to corrupt user-managed Claude settings:

- Writes to `.claude/settings.local.json` go through `tmp + os.replace` so a killed
  agent cannot leave a half-written file behind.
- Each SASE-installed hook command carries a `_sase_managed` sentinel value. On exit,
  cleanup removes only entries carrying that sentinel; any pre-existing user or project
  hooks (including hooks for unrelated events such as `Notification`) are left
  untouched.
- "Home-mode" launches — agents started outside a tracked workspace, identified by the
  absence of `SASE_GIT_WORKSPACE_DIR` and `SASE_ACTIVE_PROJECT_DIR` — skip the settings
  mutation entirely. They emit a `claude_hooks_skipped` diagnostic to
  `tool_calls_writer_errors.jsonl` so the operator can see why the hook records are
  missing, and rely on the stream-derived fallback writer (below) to populate the
  timeline.
- If `.claude/settings.local.json` exists but is malformed JSON, it is left alone, the
  run logs a diagnostic, and the fallback writer takes over.
- If SASE created the file (it did not pre-exist) and only SASE entries remain at exit,
  both the file and an empty `.claude` directory are removed so the workspace is left
  clean.

The collector script itself is intentionally non-blocking: malformed JSON, non-object
payloads, exceptions inside the collector, a missing `SASE_ARTIFACTS_DIR`, and
unrecognized hook event names all produce a best-effort diagnostic (or a silent no-op
when stdin is empty) and exit 0. This guarantees that a SASE-side bug can never make
Claude surface the hook as a tool-call failure to the agent.

The hook-based writer coexists with a stream-derived fallback writer in the LLM provider
layer, which parses tool calls out of the Claude streaming response. Both writers append
to the same artifact, and the Tools-panel reader accepts schema versions 1, 2, and 3.
When hook and stream records describe the same `tool_use_id`, the reader keeps the
hook-derived record and suppresses the duplicate stream-derived row; otherwise, older
stream-only artifacts remain readable.

The normalized tool-call artifact is still Python/TUI-owned glue rather than a shared
`sase-core` contract. Move it into `../sase-core` only if another frontend or
integration needs to produce or consume exactly the same schema through the Rust
boundary.

Source: `src/sase/llm_provider/claude.py`, `src/sase/llm_provider/_claude_hooks.py`,
`src/sase/llm_provider/_tool_calls.py`, `src/sase/scripts/sase_claude_tool_hook.py`,
`src/sase/ace/tui/tools/reader.py`

## Antigravity (`agy`) Integration

The `AgyProvider` invokes Google's Antigravity CLI (`agy`), the replacement for the
retired consumer Gemini CLI. It is a plain-stdout provider: the current Antigravity CLI
does not document a machine-readable JSON/stream output mode, so SASE streams plain
stdout instead of parsing a structured event stream.

### Command Construction

```
agy --print-timeout <duration> --model <model> --dangerously-skip-permissions --add-dir <workspace> --print <prompt>
```

The prompt is passed as the value of `--print` (not on stdin) as a single argv element,
so prompts containing quotes, newlines, or shell metacharacters are never
shell-interpolated. `--print-timeout` defaults to `24h` (Antigravity's own `5m` default
is too short for long agentic runs) and is a Go duration string.

SASE pins Antigravity to the agent workspace in two ways: it launches the subprocess
with `cwd=<workspace>` and passes `--add-dir <workspace>` to the CLI. The workspace is
resolved from `SASE_ACTIVE_PROJECT_DIR`, then provider project and workspace env vars,
and finally the current working directory.

Because the current Antigravity CLI does not document a stable stdin or prompt-file
contract for print mode, SASE cannot fall back to streaming the prompt when that single
argv element becomes too large for the OS. `AgyProvider` therefore rejects prompts above
a conservative 120 KiB UTF-8 guard before spawning `agy`, with an error that names the
upstream argv transport limitation and asks the user to reduce the prompt or use a
stdin-capable provider.

Before invoking `agy --print`, SASE wraps the user prompt with a compact print-mode
directive. It tells the model that tool approval has already been granted by
`--dangerously-skip-permissions`, commands must run synchronously, background tasks
should not be used because print mode has no event loop for later notifications, and the
final answer must be written directly to stdout.

### Print-Mode No-Progress Recovery

Antigravity's `run_command` tool can dispatch long-running commands as background tasks.
In an interactive Antigravity session, the UI can deliver the later completion
notification and the model can continue. In `agy --print`, SASE starts a single
non-interactive process and reads stdout; there is no follow-up event loop. Some models
therefore end the print turn with prose such as "I will wait to be notified" or "please
approve the command" even though the subprocess exits `0`.

`AgyProvider` treats those replies as no-progress, not success. When the supported
trajectory extractor is available, SASE first checks the structural diff: zero tool-use
steps or a final pending/backgrounded `run_command` step triggers recovery. When
trajectory data is unavailable, a conservative text heuristic catches
planning-only/waiting replies. SASE then restarts `agy --print` with accumulated context
and a provider-local continuation nudge that asks the model to run tools synchronously
and output the final answer. If the reply still makes no progress after the bounded
continuation budget, `invoke()` raises `LLMInvocationError` so the run fails loudly
instead of writing a false-success answer.

### Model Mapping

`agy` stable model slugs are used verbatim, matching `agy models` output. The tier
defaults are:

| Tier    | Model                   | Short alias |
| ------- | ----------------------- | ----------- |
| `large` | `gemini-3.7-flash-high` | `flash37h`  |
| `small` | `gemini-3.7-flash-low`  | `flash37l`  |

All other `agy models` slugs remain reachable through the model picker, configured
aliases, and provider/model directives such as `%m:agy/gemini-3.6-flash-high`. When the
Antigravity CLI is available, the shipped `@xsmall` pool can select
`gemini-3.7-flash-medium` automatically, and `@small` can select
`gemini-3.7-flash-high`.

### Environment Variables

| Variable                                 | Description                                                        |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `SASE_AGY_PATH`                          | Path to the Antigravity CLI binary (default: `"agy"`).             |
| `SASE_AGY_PRINT_TIMEOUT`                 | Override the `agy --print-timeout` Go duration (default: `"24h"`). |
| `SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS` | Override the no-progress continuation cap (default: `2`).          |
| `SASE_AGY_LARGE_ARGS`                    | Extra args for the `large` tier (after `SASE_LLM_LARGE_ARGS`).     |
| `SASE_AGY_SMALL_ARGS`                    | Extra args for the `small` tier (after `SASE_LLM_SMALL_ARGS`).     |

### Skill Deployment

`sase skill init -p agy` writes generated SASE skills to
`~/.gemini/antigravity-cli/skills/`, the documented Antigravity global skill path. The
leading `.gemini` here is an Antigravity-owned path, not a Gemini CLI path.

### Structured Artifacts Parity Gap

The Antigravity CLI exposes no stable machine-readable stdout contract: there is no
documented `--output-format stream-json` or JSON event mode. Because SASE will not
scrape Antigravity's human TUI rendering to synthesize artifacts, the `agy` provider
preserves these invariants:

- **Tool-call timeline** — SASE never invents rows from stdout display glyphs or prose.
  For explicitly supported Antigravity versions, a guarded best-effort extractor may
  decode new rows from Antigravity's local trajectory DB and append
  `source="trajectory"` records to `tool_calls.jsonl`; otherwise the ACE
  [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel) shows nothing for `agy` runs.
- **Usage accounting** — `InvokeResult.usage` is `None` and no `usage.json` is written;
  `agy` print mode exposes no stable token counters.
- **Thinking extraction** — no thinking artifact is produced.

The plain-stdout path still writes `live_reply.md` (and `live_reply_timestamps.jsonl`)
like every other provider, so the final reply, chat history, and resume support work
normally. These structured features are fast-follow work gated on a future Antigravity
machine-readable output/log/conversation contract.

### Timer Display

While waiting for a response, a `Waiting for Antigravity` spinner is shown (unless
`suppress_output` is `True`).

## Codex CLI Integration

The `CodexProvider` invokes the OpenAI `codex` CLI tool.

### Command Construction

Normal mode:

```
codex exec --model <model> --dangerously-bypass-approvals-and-sandbox --json --color never --skip-git-repo-check - [extra_args...]
```

The prompt is written to stdin. Output is streamed as NDJSON events, with assistant text
extracted from `item.completed` events.

### Model Mapping

| Tier    | Codex Model         |
| ------- | ------------------- |
| `large` | `gpt-5.6-sol`       |
| `small` | `codex-mini-latest` |

### Plan Handling

The Codex provider does not enable Codex CLI's native plan mode. SASE planning flows are
implemented at the orchestration layer through workflows, xprompts, and the `sase_plan`
skill, so provider behavior stays consistent across runtimes.

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

By default, SASE launches Codex with a per-invocation shadow `CODEX_HOME` under
`~/.cache/sase/codex_home/`. The shadow home copies `config.toml` and symlinks other
Codex home entries back to the real Codex home so Codex can read auth, hooks, skills,
logs, and caches while any config rewrites stay disposable. The shadow directory is
removed after each Codex subprocess exits. Set `SASE_CODEX_DISABLE_SHADOW_HOME=1` to
pass through the inherited environment directly for debugging or emergency
compatibility.

### Codex Tool-Call Capture

SASE captures Codex tool calls from the `codex exec --json` NDJSON stream; it does not
install Codex hooks or mutate user Codex configuration for telemetry. When
`SASE_ARTIFACTS_DIR` is present, the stream parser appends normalized Codex records to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for the ACE
[Agents Tab Tools Panel](ace.md#agents-tab-tools-panel).

Current fixture coverage is based on Codex CLI `0.130.0`. For stream items that expose
both start and completion events (`command_execution`, `file_change`, and named tool
items), SASE writes `ToolUse` and `ToolResult` rows with `runtime: "codex"` and
`source: "stream"`. The Tools-panel reader collapses those pairs into one row,
preserving pending rows while a command is still running and showing result previews,
failure/interruption status, and duration when the stream exposes enough data to compute
it.

Older Codex stream shapes that only expose a completed `function_call` item remain
readable as legacy `FunctionCall` rows. Those records can show the tool name and compact
input target, but they do not invent response summaries, durations, or failure details
that Codex did not emit.

Codex tool-call summaries use the same bounded and redacted artifact helpers as the
other providers. Textual command output (`stdout`, `stderr`, and combined `output`) uses
a tail-oriented soft character budget: when truncation is needed, the summary marks how
much was omitted from the beginning and retains at least the final 50 complete logical
lines. Exceptionally wide trailing lines can therefore make a summary larger than the
nominal budget. Command input, paths, errors, read/web content, and subagent final
messages remain head-oriented. Set `SASE_TOOL_LOG_FULL=1` only for explicit debugging
sessions when raw tool input or output is needed in the local artifact.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Codex")` spinner is shown
(unless `suppress_output` is `True`).

## Qwen Code Integration

The `QwenProvider` invokes the `qwen` CLI tool.

### Command Construction

```
qwen --input-format text --output-format stream-json --yolo --model <model> [extra_args...]
```

The prompt is written to stdin using Qwen's text input mode. Output is streamed as JSON
events; SASE extracts assistant text from `assistant` events and falls back to the final
`result` text when no assistant text is emitted.

### Model Mapping

| Tier    | Qwen Model          |
| ------- | ------------------- |
| `large` | `qwen3.6-plus`      |
| `small` | `qwen3-coder-flash` |

### Authentication

Configure Qwen Code through its supported auth and settings flow before using it from
SASE. Qwen OAuth free tier access ended on 2026-04-15; use API keys, Alibaba Cloud
Coding Plan, OpenRouter, Fireworks, or another Qwen-supported provider instead of
relying on the discontinued OAuth free tier.

### Environment Variables

| Variable               | Description                                              |
| ---------------------- | -------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`  | Extra CLI args for `large` tier (generic, preferred)     |
| `SASE_LLM_SMALL_ARGS`  | Extra CLI args for `small` tier (generic, preferred)     |
| `SASE_QWEN_PATH`       | Path to the Qwen Code CLI binary (default: `qwen`)       |
| `SASE_QWEN_LARGE_ARGS` | Extra CLI args for `large` tier (Qwen-specific fallback) |
| `SASE_QWEN_SMALL_ARGS` | Extra CLI args for `small` tier (Qwen-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_QWEN_*_ARGS`.

Qwen Code config is left in Qwen's normal locations (`~/.qwen/settings.json` and project
`.qwen/settings.json`). SASE does not create a shadow Qwen home in the first
implementation because local Qwen was unavailable during this phase, so no normal
headless-run config mutation could be verified.

### Qwen Tool-Call Capture

SASE captures Qwen tool calls from the `qwen --output-format stream-json` event stream;
it does not install Qwen hooks. When `SASE_ARTIFACTS_DIR` is present, the stream parser
normalizes Qwen's nested `tool_use` and `tool_result` blocks into records appended to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for the ACE
[Agents Tab Tools Panel](ace.md#agents-tab-tools-panel) with `runtime: "qwen"` and
`source: "stream"`. Malformed or unsupported tool-shaped events emit a diagnostic
instead of producing a malformed record. The Tools-panel reader collapses each
start/result pair into a single row.

### Commit Finalization

SASE-launched Qwen runs use the shared provider-neutral commit finalizer described
above; active SASE settings do not need repo-local or global Qwen commit-hook
configuration.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Qwen")` spinner is shown
(unless `suppress_output` is `True`).

## OpenCode Integration

The `OpenCodeProvider` invokes the `opencode` CLI tool.

### Command Construction

```
opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> [extra_args...] <prompt>
```

The prompt is passed as OpenCode's `run [message..]` argument without shell
interpolation. Output is streamed as JSONL events; SASE extracts assistant text from
`text` events, captures errors from `error` events, and accumulates token counters from
`step_finish` events when OpenCode reports them.

### Model Mapping

OpenCode model IDs normally include an upstream provider prefix. Use
`%model:opencode/<provider/model>` to route a single SASE prompt to a concrete OpenCode
model.

| Tier    | OpenCode Model                |
| ------- | ----------------------------- |
| `large` | `anthropic/claude-sonnet-4-5` |
| `small` | `openai/gpt-5-mini`           |

### Authentication and Config

Configure OpenCode through its normal auth and settings flow before using it from SASE.
OpenCode stores auth under its XDG data directory and reads config from its XDG config
directory plus project `.opencode` config. Use `opencode models` to inspect the models
available in your configured OpenCode environment.

SASE deploys OpenCode skills under `~/.config/opencode/skills/`, which OpenCode scans as
part of its config directory. SASE does not create a shadow OpenCode data/config home in
this first implementation because OpenCode's normal headless run writes session/database
state under its XDG data directory while reading auth/config from the standard
locations.

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

While waiting for a response, a `provider_timer("Waiting for OpenCode")` spinner is
shown (unless `suppress_output` is `True`).

## Muse Code Integration

The `MuseProvider` invokes Meta's Muse Code CLI (`muse`).

### Selection

Muse is **explicit-only**. It publishes `llm_autodetect_cli_name` but deliberately no
`llm_autodetect_priority`, so it never appears in autodetect candidates: `muse` is a
generic executable name, and SASE's autodetect only checks whether a binary of that name
is on `PATH`. Reach Muse with `llm_provider.provider: muse`, `%model:muse/<model>`, or
by pointing `SASE_MUSE_PATH` at the binary. `provider_cli_available()` still uses the
CLI name, so `sase doctor` and the `sase agent-cli` inventory see Muse normally.

Muse's provider short name is `mus`, which enables `foo.mus` agent naming.

### Command Construction

```
MUSE_NO_AUTO_UPDATE=1 muse exec --json --workspace <cwd> --model <model> [--reasoning-effort <level>] \
  --trust-workspace --disable-approval --disable-sandbox \
  --user-input-auto-resolve --no-foreign-personal-context \
  --session-id <uuid> --prompt-file <tempfile> [extra_args...]
```

Decisions inside that command:

- **`--prompt-file`, not stdin and not a positional argument.** `muse exec` reserves
  stdin for `--api-key-stdin`, and SASE prompts routinely exceed comfortable argv
  limits. The prompt is written to a `0o600` file under SASE's managed temp root and
  removed as soon as the cycle ends.
- **`MUSE_NO_AUTO_UPDATE=1`.** The Muse launcher otherwise checks for and swaps in a new
  binary hourly; a multi-hour agent run must not have its binary replaced mid-flight.
  Update Muse through [`sase agent-cli update muse`](agent_providers.md#muse-code)
  instead.
- **`--session-id` is generated by SASE**, not left to Muse, because it is the handle
  that locates the session log SASE reads token usage from.
- **Sandbox off by default.** Under Muse's sandbox, `.git`, `.muse`, and `.agents` are
  read-only inside the workspace root, which breaks any in-run `sase stitch create` an
  agent performs through the `sase_git_commit` skill. Disabling it matches what SASE
  already does for Codex and OpenCode. Approvals must go regardless — a headless run
  cannot answer them.
- **No `-w/--worktree` and no `--subagent-worktree-isolation`.** SASE's workspace is the
  workspace, and subagent isolation is a documented no-op.

Set `SASE_MUSE_SANDBOX=on` for a hardened opt-in: SASE keeps Muse's sandbox and passes
`--sandbox-network enabled` instead of `--disable-sandbox`. This is containment SASE has
with no other provider and is genuinely useful for read-only research agents, but
**in-run commits fail under it** because the sandbox makes `.git` read-only.

### Model Mapping

| Tier    | Muse Model       |
| ------- | ---------------- |
| `large` | `muse-spark-1.2` |
| `small` | `muse-spark-1.2` |

| Model                        | Context | In / Cached / Out (per 1M) | Notes                                                                                                                                         |
| ---------------------------- | ------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `muse-spark-1.2`             | 1M      | $1.25 / $0.15 / $4.25      | Coding-optimized, purpose-built for agentic workflows.                                                                                        |
| `muse-spark-1.2-contributor` | 1M      | $0.10 / $0.002 / $0.20     | Same model and capabilities. **Meta uses its inputs and outputs to train and improve Meta's AI models.** Rate limited; select countries only. |
| `muse-spark-1.1`             | 1M      | $1.25 / $0.15 / $4.25      | Agentic and multimodal (text, images, video, documents).                                                                                      |

**Both tiers map to `muse-spark-1.2` on purpose.** `small` is what `@small` and
`@xsmall` reach for automatically, so mapping it to the Contributor model would silently
ship a user's proprietary source into Meta's training corpus. SASE does not make that
decision on anyone's behalf. The Contributor model stays fully available — it is a known
model name, it has the short alias `spark12c`, and
`%model:muse/muse-spark-1.2-contributor` works — but reaching it requires typing its
name, and a [model advisory](#model-advisories) makes sure the trade is visible when you
do.

### Reasoning Effort

Muse accepts `none|minimal|low|medium|high|xhigh|ultra` and rejects `max` by name, so
SASE's canonical `max` maps onto Muse's `ultra`. Muse is the first provider to cover all
seven canonical levels. Muse's own internal default is `high`, so a run with no resolved
effort shows blank in SASE while Muse actually used `high`; the recorded model identity
(below) closes the equivalent gap for the model.

### The Event Stream

`muse exec --json` writes pure JSONL to stdout; human diagnostics go to stderr. Every
line is an envelope carrying `schema_version`, `payload_type`, `payload_schema_version`,
and `payload`. SASE's parser rules, in priority order:

1. **`run.terminal.completed` → `payload.text` is the authoritative reply.**
   `payload.terminal` is the outcome and `payload.reason` the detail; SASE parses those
   fields and never pattern-matches reply text.
2. **`run.output.delta` is for live display only.** It is marked `ephemeral` and repeats
   text the terminal event later carries in full. SASE streams it into `live_reply.md`
   and the timestamps file but never appends it to the returned content, so replies do
   not double.
3. **A failed, rejected, or cancelled task is not a failed run.** Muse emits
   `task.lifecycle.rejected` (`reason: "skip_if_running"`) and
   `task.lifecycle.cancelled` (`reason: "main run completed"`) on runs that exit `0`.
   Success is gated on `run.terminal.*` plus the exit code; task-level failures are
   recorded as diagnostics only.
4. **Unknown payload types and higher schema versions do not raise.** Parse failures
   surface the observed versions as a stdout-decode diagnostic rather than returning an
   empty success, and repeated schema diagnostics are capped.
5. **Exit code 2 is a `muse exec` usage error**, not a run failure, and the raised
   `CalledProcessError` diagnostics say so, so a bad flag does not read as a model
   failure.

Every flag and payload-type string lives in one module-level constant block in
`_subprocess_muse.py`, so a beta rename is a one-line fix.

### Muse Tool-Call Capture

SASE builds tool-call records purely from the stdout stream; it does not wire Muse's
hook system and does not read Muse state off disk for this. When `SASE_ARTIFACTS_DIR` is
present, normalized records are appended to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl` with
`runtime: "muse"` and `source: "stream"` for the ACE
[Agents Tab Tools Panel](ace.md#agents-tab-tools-panel). Fixture coverage is keyed to
Muse release `0.1.0-R708.1`.

| Event                                             | Carries                                                                   | Use                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `task.lifecycle.proposed`                         | `task_kind: "tool.<name>"`, `task_id`                                     | Opens a pending call — only for `task_kind` values under `tool.` |
| `task.lifecycle.scheduled` / `side_effect_intent` | `idempotency_key: "tool:<call_id>"`, `operation`, `policy_decision`       | Binds `task_id` → `call_id`                                      |
| `task.lifecycle.output`                           | `event.chunk`                                                             | Streamed tool output                                             |
| `tool.result`                                     | `call_id`, `correlation_facts.{tool_name,outcome}`, optional `edit_facts` | Closes the call with its outcome and result                      |

**Tool arguments are never in the stream.** SASE derives each record's target honestly
and in this order: `edit_facts.path` when present; for `bash`, the `command` and
`description` fields of the result JSON; otherwise a truncated preview of the result
text. It does not invent arguments Muse did not emit. Non-tool tasks
(`model.meta.response`, `reminder.agent.plugin:*`) never become tool records, and calls
still pending at stream end are finalized like every other provider's.

### Token Usage and Model Identity

Muse's stdout stream carries **no token counts at all**; the numbers live in the on-disk
session log. Because SASE passes `--session-id`, that location is deterministic:

```
$XDG_DATA_HOME/muse/sessions/YYYY/MM/DD/<session-id>/session.jsonl
```

(`XDG_DATA_HOME` defaults to `~/.local/share`; the date components are globbed rather
than computed from today's date so a run spanning midnight still resolves.) After the
subprocess exits, SASE sums `usage` across `runtime.session` events whose
`payload.event.kind` is `model_completed`, mapping `input_tokens`, `output_tokens`,
`cache_read_tokens` (falling back to the older `cached_tokens`), and
`cache_write_tokens` onto SASE's counters. `goal_usage_attribution` events repeat the
same numbers for the same call and are deliberately ignored — counting both would double
every run's totals. A missing or unreadable session log is not an error: it degrades to
zeroed usage plus a diagnostic.

SASE does not shell out to `muse export` for this. It costs a subprocess, `--redacted`
strips the `call_id`s, and unredacted output contains verbatim encrypted reasoning SASE
has no reason to retain.

`run.model.configured` carries the model Muse actually configured. SASE records its
`model_id`, `provider_id`, and the session id into `run_metadata.json`, which closes the
observability gap where a run with no explicitly resolved model shows blank in SASE
while Muse used its own default.

### Interrupts and Retries

Muse has no headless resume (`muse resume` is interactive-only), so interrupt handling
reuses the accumulated-context restart that Qwen, OpenCode, and Codex use: SASE
reconstructs a continuation prompt and relaunches. The session log is kept for manual
recovery. Muse ships no `llm_default_retry_config`; it already retries its own model
stream internally, and a nonzero exit falls into SASE's generic retry path.

### Skills and Instruction File

SASE deploys Muse skills under `~/.config/muse/skills/<skill>/SKILL.md`, rendered with
`provider_name: "Muse Code"`. Without that deploy path Muse picks up SASE's
Claude-rendered skill copies from `~/.claude/skills/` and reads them as if it were
Claude Code. Muse reads `AGENTS.md` natively, so there is no `MUSE.md` provider shim.

### Environment Variables

| Variable               | Description                                                         |
| ---------------------- | ------------------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`  | Extra CLI args for `large` tier (generic, preferred)                |
| `SASE_LLM_SMALL_ARGS`  | Extra CLI args for `small` tier (generic, preferred)                |
| `SASE_MUSE_PATH`       | Path to the Muse Code CLI binary (default: `muse` on `PATH`)        |
| `SASE_MUSE_LARGE_ARGS` | Extra CLI args for `large` tier (Muse-specific fallback)            |
| `SASE_MUSE_SMALL_ARGS` | Extra CLI args for `small` tier (Muse-specific fallback)            |
| `SASE_MUSE_SANDBOX`    | Set to `on` to keep Muse's sandbox with `--sandbox-network enabled` |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_MUSE_*_ARGS`.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Muse Code")` spinner is
shown (unless `suppress_output` is `True`).

## Grok Build Integration

The `GrokProvider` invokes xAI's Grok Build CLI (`grok`).

### Selection

Grok publishes `llm_autodetect_cli_name` but deliberately no `llm_autodetect_priority`,
so it never appears in autodetect candidates: `grok` is a generic executable name shared
with a stale community CLI (`grok-dev`, which also uses `~/.grok/`) and with Homebrew's
deprecated, unrelated `grok` regex tool. Reach Grok with `llm_provider.provider: grok`,
`%model:grok/grok-4.6`, by pointing `SASE_GROK_PATH` at the binary, or automatically
whenever the `grok` CLI is installed: through the shipped `@xsmall`/`@small`/`@medium`
load-balanced pools, or as the last candidate in `@xlarge`'s ordered fallback (behind
Claude and Codex). When a `grok` on `PATH` does not identify itself as Grok Build,
`sase doctor` reports a distinct wrong-binary advisory instead of silently launching it.

Grok's provider short name is `grk`, which enables `foo.grk` agent naming.

### Command Construction

```
grok --prompt-file /dev/stdin --output-format streaming-messages-json \
  --permission-mode bypassPermissions --model <model> --cwd <cwd> \
  --session-id <uuid> --no-plan --no-ask-user --no-auto-update --no-leader \
  [--effort <level>] [extra_args...]
```

The prompt is written to `process.stdin`, exactly as Claude's provider does, so there is
no temp file to leak or clean up on interrupt and no argv exposure of prompt text.
Decisions inside that command:

- **`--permission-mode bypassPermissions`, not the undocumented `--yolo`.** No sandbox
  profile is set, matching what SASE already does for Codex, OpenCode, and Muse.
- **`--no-auto-update` is not optional.** Without it Grok may replace its own ~166 MB
  binary mid-run; update it through
  [`sase agent-cli update grok`](agent_providers.md#grok-build) instead.
- **`--no-plan` and `--no-ask-user`.** `/sase_plan` owns planning handoffs and
  `/sase_questions` owns asking, so Grok's native planning and asking are disabled. Both
  flags are undocumented in `grok --help`, so a parse-probe test pins them.
- **`--no-leader` is passed explicitly**, even though leader mode is off by default,
  because it is opt-in via a user's own `[cli] use_leader = true` and SASE runs many
  agents concurrently against one shared backend socket — explicit beats inherited.
- **`--session-id` is generated by SASE**, matching Claude's convention.
- **Subagents stay enabled.** Subagent usage can set Grok's internal
  `usage_is_incomplete` flag, which degrades usage telemetry only — SASE treats token
  counts as telemetry, not as text or tool-call fidelity, so `--no-subagents` is not
  passed.

### Model Mapping

| Tier    | Grok Model |
| ------- | ---------- |
| `large` | `grok-4.6` |
| `small` | `grok-4.6` |

**Both tiers map to `grok-4.6` on purpose**: it is the only model in the authenticated
catalog. Inventing a distinct `small` mapping to a model that may not exist would make
ordinary `@small`/`@xsmall` routing fail; this is revisited if the catalog grows.

### Reasoning Effort

`grok-4.6` accepts only `--effort low|medium|high|xhigh`; `none`, `minimal`, and `max`
are rejected by the CLI with a nonzero exit. SASE declares exactly the four supported
levels, so an explicit `%effort:max`/`none`/`minimal` raises a clean
`LLMInvocationError` instead of a Grok process crash, and a config-derived default at
one of those levels is logged and skipped. See [Reasoning Effort](#reasoning-effort)
below — the shipped `@xlarge` ordered fallback carries `@max` on every candidate, but
`max` is not an explicit directive. When `@xlarge` selects Grok (or Codex, which
likewise has no `max` level), the alias-borne `max` is best-effort: it is logged and
skipped, and the CLI runs at its own default effort instead of erroring.

### The Event Stream

Grok shares Claude's generalized Anthropic-Messages stream reader
(`stream_and_parse_messages_json_output` in `_subprocess_claude.py`), parameterized with
`runtime="grok"`, the Grok tool-call writer, and a thinking sink — Claude's own behavior
is unchanged by this generalization. A no-tool turn emits `system`/`init`, one
`assistant` message whose `message.content[]` holds `thinking` and `text` blocks, and a
terminal `result`; a tool-using turn adds `assistant` messages with `tool_use` blocks
and `user` messages with `tool_result` blocks. `result.usage` carries the same four keys
`initial_usage_totals()` accumulates, plus a nested `server_tool_use` SASE's accumulator
ignores harmlessly.

Grok's failure frames carry detail in **`errors[]` only** — no top-level `error`,
`message`, or `result` field. The shared error-detail extraction folds `errors[]` in
when those are absent:

```python
detail = event.get("error") or event.get("message") or event.get("result", "")
if not detail:
    errors = event.get("errors")
    if isinstance(errors, list):
        detail = "\n".join(str(item) for item in errors if item)
```

This is safe by construction for Claude, which never emits `errors[]` and whose
`append_error_events` returns early on a success exit, so a success-path `result.result`
is never mistaken for an error.

Grok's `thinking` content blocks are routed into the same `codex_thinking.jsonl` sidecar
Codex writes reasoning summaries to (the filename is kept as-is because ACE's
`read_codex_thinking` reads that exact path), so Grok's reasoning renders in the ACE
thinking pane instead of being silently discarded the way non-`text` Claude blocks are.

### Grok Tool-Call Capture

SASE captures Grok tool calls from the `streaming-messages-json` event stream; it does
not install Grok hooks. When `SASE_ARTIFACTS_DIR` is present, normalized records are
appended to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl` with `runtime: "grok"` and
`source: "stream"` for the ACE [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel).
Grok's native tool names are mapped onto SASE's canonical display names so the shared
summarizers in `_tool_call_common.py` produce rich previews instead of falling through
to a generic `{"input_keys": [...]}` row:

| Grok tool              | Canonical display name |
| ---------------------- | ---------------------- |
| `run_terminal_command` | `Bash`                 |
| `read_file`            | `Read`                 |
| `write`                | `Write`                |
| `search_replace`       | `Edit`                 |
| `grep`                 | `Grep`                 |
| `list_dir`             | `Glob`                 |
| `web_fetch`            | `WebFetch`             |
| `web_search`           | `WebSearch`            |
| `spawn_subagent`       | `Task`                 |
| `todo_write`           | `TodoWrite`            |

An unmapped tool name survives under its own name rather than being dropped.

**Result envelope decoding.** Grok's `tool_result` blocks carry `content` as a
**JSON-encoded string**, not text, decoding to a bespoke tagged shape (for example
`{"type": "Bash", "output": [...], "output_for_prompt": "exit: 0\n...", "exit_code": 0, ...}`
for a shell command, or `{"type": "SearchReplace", "EditsApplied": {...}}` for an edit).
SASE decodes it and prefers `output_for_prompt` / `tool_output_for_prompt` for previews
— the human-readable projection Grok itself uses — maps `exit_code` through so `Bash`
rows show exit status, and `absolute_path` through so edit rows show the file. `output`
is a byte array, not a string, and is never previewed raw. A `content` string that is
not valid JSON degrades to the existing plain-text preview path rather than raising.
Grok's `user` messages carry no top-level `tool_use_result` envelope, so the decoded
`content` is the only structured source; Grok's tool-call ids are
`call-<uuid>-<n>`-shaped, which pair correctly through the existing id-based logic.

### Token Usage

Grok's `result.usage` carries the same four keys Claude's does (`input_tokens`,
`output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`), so token
accounting reuses the same accumulator. Usage is **best-effort**: Grok's
`streaming-messages-json` output is a projection of its native usage ledger that drops
the internal "usage incomplete" marker, so subagent turns and interrupted turns can
under-count or zero out. Text and tool records are unaffected. `total_cost_usd` and a
per-model `modelUsage` ledger are populated on the OAuth subscription path.

### Interrupts and Retries

Interrupt handling reuses Claude's interrupt/continue loop: `start_interrupt_monitor`
watches for an interrupt, and a continuation prompt carrying accumulated work is
relaunched on the same session mechanics as Claude. `GrokProvider` declares
`llm_default_retry_config()` with xAI-specific `error_patterns` (`"xAI API error"`,
`"xAI rate limit"`, `"xAI server error"`, `"xAI upstream request failed"`) kept
deliberately narrow so they cannot collide with Codex's ownership of generic `429` /
`Too Many Requests` wording; see
[Provider-Supplied Retry Defaults](#provider-supplied-retry-defaults).

### Skills and Instruction File

`skill_deploy_subpaths()` defaults to `f".{provider}"` with no hook override, so Grok
skills deploy to `~/.grok/skills/<skill>/SKILL.md`, rendered with
`provider_name: "Grok"`, `provider_tool_name: "Grok Build"`, and
`provider_native_ask_tool: "ask_user_question"`. Grok's `[compat.claude]` cells default
to on, so a Grok run also sees `~/.claude/skills/`; this is benign because a native
`~/.grok/skills/<name>` shadows a same-named Claude-compat skill entirely, and
`sase init skills` deploys every SASE skill to every registered provider's subpath, so
SASE skills are always shadowed by their correctly-rendered Grok copies.

Grok reads `AGENTS.md` natively, so there is no `GROK.md` provider shim. Grok also loads
SASE's generated `CLAUDE.md` as project instructions — `[compat.claude] agents = false`
does not suppress this — so a Grok run injects the same ~2,930-token instruction content
twice. This is accepted for now rather than suppressing `CLAUDE.md` generation under a
Grok provider, which would break any human running `claude` in the same tree.

### Environment Variables

| Variable               | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`  | Extra CLI args for `large` tier (generic, preferred)          |
| `SASE_LLM_SMALL_ARGS`  | Extra CLI args for `small` tier (generic, preferred)          |
| `SASE_GROK_PATH`       | Path to the Grok Build CLI binary (default: `grok` on `PATH`) |
| `SASE_GROK_LARGE_ARGS` | Extra CLI args for `large` tier (Grok-specific fallback)      |
| `SASE_GROK_SMALL_ARGS` | Extra CLI args for `small` tier (Grok-specific fallback)      |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_GROK_*_ARGS`.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Grok")` spinner is shown
(unless `suppress_output` is `True`).

## External Provider Plugins

Additional LLM providers are shipped as external packages that declare
`[project.entry-points."sase_llm"]` in their own `pyproject.toml`. Plugins carry all
their own metadata (model names, skill deploy path, CLI status color, auto-detect
priority, retry defaults) via pluggy `@hookimpl` methods — sase core has no
plugin-specific branching.

External provider packages own their CLI invocation details, model metadata, skill
deployment path, auto-detect priority, and retry defaults. Install the provider package
in the same environment as sase to make its `sase_llm` entry point available.

## Configuration

The LLM provider reads its configuration from `~/.config/sase/sase.yml` under the
`llm_provider` key.

### Config File

```yaml
llm_provider:
  provider: claude # or "codex", "qwen", "opencode", "agy", "muse", "grok", "fakey" (default: auto-detect)
  default_effort: xhigh # default reasoning effort when a prompt sets none (default: unset)
  model_tier_map:
    large: opus
    small: sonnet
  default_model: "@large" # used when a launch has no %model directive (default: @large)
  epic_lander_model: "@large" # epic land agents below bead.big_epic_phase_threshold (default: @large)
  big_epic_lander_model: codex/gpt-5.6-sol # epic land agents at/above the threshold (default: @xlarge)
  model_alias_history_limit: 10 # runs shown per alias in Launch Control history (minimum: 1)
  # Override examples; shipped size-alias targets are generated below.
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low # custom xsmall pool
      small: claude/haiku | codex/gpt-4.1-mini # custom small pool
      medium: claude/sonnet@xhigh | codex/gpt-5.5@xhigh
      large: codex/gpt-5.6-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max # custom maximum-effort target
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
        bucket: research
    buckets:
      research:
        description: Aliases used by research agents.
```

### Config Fields

| Field                                    | Type   | Default     | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`                  | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; real built-ins default to claude → codex → qwen → opencode → agy, with fakey last as a testing-only fallback. `muse` and `grok` declare no priority and are never auto-detected; select them explicitly.                                                                                                                                                                                                                                                          |
| `llm_provider.default_effort`            | string | unset       | Default [reasoning-effort](#reasoning-effort) level applied when a prompt sets no `%effort`/`@effort` and the selected alias carries no effort. One of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; unset/invalid imposes no effort.                                                                                                                                                                                                                                                                                           |
| `llm_provider.model_tier_map.large`      | string | -           | Model identifier for the `large` tier                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `llm_provider.model_tier_map.small`      | string | -           | Model identifier for the `small` tier                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `llm_provider.default_model`             | string | `@large`    | Model expression used for a launch with no explicit `%model` directive. See [Implicit role aliases](#implicit-role-aliases).                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `llm_provider.epic_lander_model`         | string | `@large`    | Model expression used by epic land agents whose epic has fewer authored phases than `bead.big_epic_phase_threshold`.                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `llm_provider.big_epic_lander_model`     | string | `@xlarge`   | Model expression used by epic land agents whose epic has `bead.big_epic_phase_threshold` or more authored phases.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `llm_provider.model_alias_history_limit` | int    | `10`        | Maximum prior runs returned per alias for the Launch Control agent-history panel. Must be at least `1`; malformed runtime values defensively fall back to `10`.                                                                                                                                                                                                                                                                                                                                                                               |
| `llm_provider.model_aliases.builtin`     | dict   | -           | Builtin size-alias overrides only (`xsmall`, `small`, `medium`, `large`, `xlarge`). Values use the single-target grammar below, a `\|` round-robin pool, or a `\|\|` ordered fallback. Retired names — `default`, `epic_lander`, `big_epic_lander`, `<size>_worker`, `smart`, `smarter`, `smartest`, `cheap`, `cheaper`, `cheapest`, `coder`, `<provider>_coder`, `epic_creator`, `phase_worker`, and `<size>_phase_worker` — are no longer builtin overrides; `sase doctor -C config.model_aliases` reports them and names each replacement. |
| `llm_provider.model_aliases.custom`      | dict   | -           | User-defined aliases for `%model:@<alias>` / `%m:@<alias>`. Each value is an object with required `model` and `description` fields; `model` accepts the same single-target and selector grammar. Descriptions are shown in completions and Launch Control.                                                                                                                                                                                                                                                                                    |
| `llm_provider.model_aliases.buckets`     | dict   | -           | Optional display-only ACE Launch Control bucket descriptions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

## Per-Prompt Provider Switching

The `%model` directive (see [xprompt directives](xprompt.md#directives)) can switch both
the model and the LLM provider for a single prompt. Provider resolution uses configured
aliases first, then concrete provider/model syntax and known model metadata.

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
      medium: codex/gpt-5.6-sol@xhigh
```

Then prompts can use the alias with a leading `@`:

```
%model:@fast
%{%m:@fast | %m:gpt-5.6-sol}
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
directive surface syntax: alias keys and xprompt values stay bare. A bare
configured/implicit alias raises with a migration hint, and `@` in front of a non-alias
raises.

An alias value can instead use one of two selector operators. `A | B` is an
availability-filtered round-robin pool: each real LLM invocation advances the
machine-global cursor in `~/.sase/llm_lb.json` exactly once, under a machine-wide lock,
immediately before the provider is called — never during metadata preparation, a
display/marker preview, or a doctor/dry-run check, which only peek. Any alias that
merely delegates to a pool-owning alias (directly or through further aliasing) shares
that pool-owning alias's cursor rather than keeping one of their own. `A || B` is an
ordered fallback chain: the first registered provider whose CLI is installed and not
temporarily disabled always wins, and resolution never reads or changes the round-robin
cursor, including during a real launch. Fallback is based on the cached CLI-installation
probe (including `SASE_<PROVIDER>_PATH`) plus a captured active-disable snapshot, not a
later model or runtime failure; SASE does not relaunch with the next candidate after
such a failure. If every provider is unavailable, both modes preserve a candidate for
the ordinary provider lookup to report: fallback preserves its first member, while the
pool preserves its current rotation choice.

Both selectors accept two or more members using the same single-target grammar,
including candidate-specific trailing reasoning effort. Whitespace is trimmed and empty
members are invalid. `|` and `||` cannot be mixed in one value, and a member may follow
an ordinary alias chain but cannot reach another pool or fallback. Selector expressions
are config-only: `%model` values, launch-scoped alias overrides, and temporary overrides
remain single targets. The ACE Launch Control's persistent Edit path authors selectors
directly — hand-typed in the custom input or assembled with a guided pool/fallback
builder — while its temporary Override path refuses a typed pool or fallback outright,
pointing at Edit, rather than silently accepting and corrupting it. An override on the
alias that owns a selector bypasses that expression for the override's lifetime. The ACE
Launch Control shows every member's availability, an aggregate
`pool <available>/<total>` chip for round-robin pools, and a `→` on the current
selection. A temporary alias override labels the member list suspended only while its
provider is available. If its provider is temporarily disabled, the stored override is
paused, the live selector target is shown instead, and the override resumes
automatically after the provider disable is cleared or expires while the override itself
is still active.

To verify pool fairness from real launches, count recorded `llm_provider`/`model` pairs
for agents whose metadata has a matching `model_alias` value for the alias being audited
— a no-`%model` launch's `model_alias` records whichever alias
`llm_provider.default_model` currently references, `@large` under the shipped default. A
healthy two-member round-robin pool should keep the member counts within one launch of
each other, ignoring periods where provider availability caused a member to be skipped.

When the same name appears in both maps, `model_aliases.custom` wins.
`sase doctor -C config.model_aliases` warns about legacy flat keys in `model_aliases`,
removed top-level `custom_model_aliases`, custom names under `model_aliases.builtin`,
builtin names under `model_aliases.custom`, collisions between the two maps, missing
custom descriptions/models, dangling `@alias` references, empty or mixed selectors, and
nested selectors. Unavailable selector providers are reported as informational notes;
for an ordered fallback the note also identifies the current winner. In ACE, Launch
Control shows descriptions from config; a user alias without one shows the
`llm_provider.model_aliases.custom.<name>.description` path to fix.

The same alias vocabulary appears in the `%model:` / `%m:` completion menu in ACE and in
editors through the xprompt LSP: alias rows sit beneath the concrete model names with
their kind, resolved `PROVIDER(model)` target, and provenance, and typing `@` right
after the colon narrows the menu to aliases only. Concrete model rows and provider-scope
rows for temporarily disabled providers are omitted, while aliases remain and show their
current fallback target. Provider rows such as `claude/` sit at the bottom of the broad
menu; accepting one opens that provider's scoped model list and inserts qualified values
such as `claude/opus`. See [xprompt directive syntax](xprompt.md#syntax) for the row
anatomy. The completion menu is read-only; the ACE Launch Control (`,m`) remains the
authoritative place to edit alias targets and to set or clear temporary overrides.

There are no built-in Launch Control buckets: the compact five-size-alias contract ships
no automatic grouping. The ACE Launch Control instead shows the three scalar
[launch model settings](#implicit-role-aliases) (`launch model`, `epic lander`,
`big epic lander`) as their own rows, alongside the five size aliases and any custom
aliases. Optional `model_aliases.buckets.<name>` metadata still creates a display-only
bucket for custom aliases: a collapsed bucket summarizes its effective-model mix and
active overrides, opening it exposes independently editable aliases, and a custom alias
tagged with `bucket: <name>` coalesces into that bucket.

A bare `%model` token that is _not_ a configured alias, an explicit `provider/model`
target, or a known provider model silently falls back to the default provider rather
than erroring. To catch this drift — for example a removed `model_aliases` entry that
quietly reroutes a `#m_<provider>_*` preset to the default provider — `sase doctor`
(`-C config.model_xprompts`) scans configured model presets and warns with
`<xprompt> -> <token> does not resolve to a provider; it will fall back to the default provider`.
The check is provider-neutral and read-only.

#### Implicit role aliases

On top of any aliases you configure, SASE always exposes a fixed set of **implicit role
aliases** that resolve even when you have not defined them: `@xsmall`, `@small`,
`@medium`, `@large`, and `@xlarge`. Each is a direct selector — a concrete model, an
`A | B` round-robin pool, or an `A || B` ordered fallback — with no further alias
indirection. Three related scalar config fields, `llm_provider.default_model`,
`llm_provider.epic_lander_model`, and `llm_provider.big_epic_lander_model`, are not
aliases themselves, but ship with the same kind of automatic, shipped-default target and
accept the same model-expression grammar; this section covers both. The current shipped
size-alias defaults are generated from `src/sase/llm_provider/model_alias_defaults.yml`:

<!-- BEGIN GENERATED: model-alias-defaults -->

| Alias     | Description                                                                 | Shipped default                                                                                       |
| --------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `@xsmall` | Extra-small launch alias for the smallest direct tasks and tale follow-ups. | `claude/sonnet@medium \| codex/gpt-5.5@medium \| grok/grok-4.6@medium \| agy/gemini-3.7-flash-medium` |
| `@small`  | Small launch alias for straightforward task and phase work.                 | `claude/sonnet@high \| codex/gpt-5.5@high \| grok/grok-4.6@high \| agy/gemini-3.7-flash-high`         |
| `@medium` | Medium launch alias for ordinary implementation work.                       | `codex/gpt-5.5@xhigh \| claude/sonnet@xhigh \| grok/grok-4.6@xhigh`                                   |
| `@large`  | Large launch alias for planning-heavy work and default launches.            | `claude/opus@xhigh \| codex/gpt-5.6-sol@xhigh`                                                        |
| `@xlarge` | Extra-large launch alias for maximum-effort work.                           | `claude/opus@max \|\| codex/gpt-5.6-sol@max \|\| grok/grok-4.6@max`                                   |

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
  big_epic_lander_model: codex/gpt-5.6-sol # large epic land agents only
  model_alias_history_limit: 10
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low
      small: claude/haiku | codex/gpt-4.1-mini
      medium: codex/o3@xhigh | claude/sonnet@xhigh
      large: codex/gpt-5.6-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max
```

Source: `src/sase/llm_provider/model_alias_defaults.yml` (shipped size-alias defaults —
the single edit point), `src/sase/llm_provider/model_launch_settings.py` (the three
scalar launch-model settings), `src/sase/llm_provider/model_alias_policy.py`

#### Launch-scoped alias overrides

A prompt can override the five size aliases (or a custom alias) for its SASE-created
launch lineage with keyword arguments on `%model(...)`:

```text
%model(opus, medium=codex/gpt-5.6-sol)
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
`%id(suffix, family=parent)` attachment inherits it only when the attached prompt
supplies no alias keywords. Ordinary nested launches do not inherit it. This is a
propagation rule, not a change to `sase.yml` or `~/.sase/llm_override.json`.

Launch-scoped values have the highest alias-resolution precedence. They beat
machine-wide per-alias temporary overrides and configured/implicit aliases at every hop;
a launch-scoped keyword matching the alias `default_model` references also beats the
machine-wide temporary override on the `launch model` setting. An explicit concrete
model for the current agent remains concrete, while an explicit alias is resolved
through this launch map. See
[Launch-Scoped Model Alias Overrides](xprompt.md#launch-scoped-model-alias-overrides)
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
%model:muse/muse-spark-1.2
%model:grok/grok-4.6
%model:fakey/fakey-large
```

In ACE and xprompt-aware editors, `%model:` completion includes provider rows such as
`claude/`, `codex/`, and `opencode/` after concrete models and aliases. Typing or
accepting a visible provider prefix scopes the menu to that provider, so `%m:claude/`
offers `claude/opus`, `claude/sonnet`, and the rest of Claude's model catalog while
`%m:opencode/anthropic/` continues narrowing inside OpenCode's slash-bearing model
names.

### Automatic Provider Resolution

Known model names are automatically mapped to their provider:

| Model Name                                                                                                                                                                                                                                                                                                                                              | Provider |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `opus`, `sonnet`, `haiku`, `claude-haiku-4-5`, `claude-fable-5`                                                                                                                                                                                                                                                                                         | claude   |
| `gpt-5.6-sol`, `gpt-5.5`, `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `codex-mini-latest`, `o3`, `o4-mini`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`                                                                                                                                                                                   | codex    |
| `gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `gemini-3.7-flash-low`, `gemini-3.6-flash-high`, `gemini-3.6-flash-medium`, `gemini-3.6-flash-low`, `gemini-3.5-flash-high`, `gemini-3.5-flash-medium`, `gemini-3.5-flash-low`, `gemini-3.1-pro-high`, `gemini-3.1-pro-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium` | agy      |
| `qwen3.6-plus`, `qwen3-coder-plus`, `qwen3-coder-flash`, `qwen3-max`, `qwen-plus`, `qwen-max`                                                                                                                                                                                                                                                           | qwen     |
| `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`, `openai/gpt-5`, `openai/gpt-5-mini`, `google/gemini-3-flash-preview`, `qwen/qwen3-coder-plus`                                                                                                                                                                                               | opencode |
| `muse-spark-1.2`, `muse-spark-1.2-contributor`, `muse-spark-1.1`                                                                                                                                                                                                                                                                                        | muse     |
| `grok-4.6`                                                                                                                                                                                                                                                                                                                                              | grok     |
| `fakey-large`, `fakey-small`                                                                                                                                                                                                                                                                                                                            | fakey    |

Each installed plugin contributes its own model names via the `llm_known_model_names()`
hook.

`fakey` is deliberately hidden from the ACE model picker and the `%model` completion
menu (a provider opts in via the `llm_hidden_from_model_pickers()` hook) since it exists
only for testing. Routing, resolution, autodetect, and short aliases are unaffected —
`%model:fakey-large` and the explicit `fakey/fakey-large` syntax above still work, and
typing either by hand (or via the picker's `Custom...` entry) still selects it.

For unrecognized model names, the prompt falls back to the default provider and a
warning is logged at invocation time.

Source: `src/sase/llm_provider/registry.py`, `src/sase/llm_provider/_invoke.py`

### Model Short Aliases

Providers also declare compact display shorthands for long model ids via the
`llm_model_short_aliases()` hook. These shorthands appear in
[provider/model agent-name suffixes](ace.md#providermodel-suffixes) on the Agents tab
and act as filter terms in the coder model picker. They are display-only: `%model`
resolution uses known model names and
[configured model aliases](#configured-model-aliases), not these shorthands. For
example, `%model:fable` does _not_ select `claude-fable-5` — it falls back to the
default provider (with a warning) unless you define `fable` as a configured model alias
yourself.

| Provider | Shorthands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| claude   | `claude-haiku-4-5` → `haiku45`, `claude-fable-5` → `fable`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| codex    | `codex-mini-latest` → `mini`, `gpt-5.6-sol` → `gpt56sol`, `gpt-5.5` → `gpt55`, `gpt-5.4` → `gpt54`, `gpt-5.3-codex` → `gpt53`, `gpt-5.3-codex-spark` → `gpt53spark`, `gpt-4.1` → `gpt41`, `gpt-4.1-mini` → `gpt41m`, `gpt-4o-mini` → `gpt4om`                                                                                                                                                                                                                                                                                              |
| agy      | `gemini-3.7-flash-high` → `flash37h`, `gemini-3.7-flash-medium` → `flash37m`, `gemini-3.7-flash-low` → `flash37l`, `gemini-3.6-flash-high` → `flash36h`, `gemini-3.6-flash-medium` → `flash36m`, `gemini-3.6-flash-low` → `flash36l`, `gemini-3.5-flash-high` → `flash35h`, `gemini-3.5-flash-medium` → `flash35m`, `gemini-3.5-flash-low` → `flash35l`, `gemini-3.1-pro-high` → `pro31h`, `gemini-3.1-pro-low` → `pro31l`, `claude-sonnet-4-6` → `sonnet46`, `claude-opus-4-6-thinking` → `opus46t`, `gpt-oss-120b-medium` → `gptoss120m` |
| qwen     | `qwen3.6-plus` → `qwen36p`, `qwen3-coder-plus` → `qwen3cp`, `qwen3-coder-flash` → `qwen3cf`                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| opencode | `anthropic/claude-sonnet-4-5` → `sonnet45`, `anthropic/claude-opus-4-5` → `opus45`, `openai/gpt-5` → `gpt5`, `openai/gpt-5-mini` → `gpt5m`, `google/gemini-3-flash-preview` → `flash3`, `qwen/qwen3-coder-plus` → `qwen3cp`                                                                                                                                                                                                                                                                                                                |
| muse     | `muse-spark-1.2` → `spark12`, `muse-spark-1.2-contributor` → `spark12c`, `muse-spark-1.1` → `spark11`                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| fakey    | `fakey-large` → `fakeyl`, `fakey-small` → `fakeys`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

Source: `llm_model_short_aliases()` in each provider module under
`src/sase/llm_provider/`

### Model Advisories

A provider can flag individual models with an advisory through the
[`llm_model_advisories()`](plugins.md#llm-provider-install-metadata-and-advisories) hook
— a discounted tier that trains on its inputs, a preview model with no stability
guarantee, and so on. Each advisory is
`{"severity": "warn"|"info", "label": <short>, "detail": <sentence>}`. Providers that
omit the hook contribute nothing, so the map is empty on an install with no
advisory-flagged models.

Advisories render at every point a user meets the model, all reading from the registry
so no render site hardcodes a model id:

| Surface                                    | Rendering                                                      |
| ------------------------------------------ | -------------------------------------------------------------- |
| [ACE model picker](ace.md#custom-approval) | `⚠ <label>` suffix on the row, with `detail` as secondary text |
| `%model` completion detail                 | `— ⚠ <label>` appended to the completion description           |
| [Resolved model label](#model-tier-system) | An inline `⚠` marker for the run's whole life                  |
| `sase doctor -C llm.model_advisory`        | A **warning** naming each configured route that lands on one   |

`⚠` (orange) marks `severity: "warn"`; `ⓘ` (blue) marks `severity: "info"`.

The doctor check resolves the configured default and every configured model alias and
warns — it never fails — when one routes SASE traffic to an advisory-flagged model.
Opting in globally is the user's call; doing it without being told is not. For the same
reason, no bundled provider's tier map points at an advisory-flagged model, and a test
asserts that so a future cost optimization cannot quietly reintroduce the problem.

The only bundled advisory today is Muse's `muse-spark-1.2-contributor` (see
[Muse Code Integration](#muse-code-integration)).

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
   [Effort Directive](xprompt.md#effort-directive) for the directive syntax and
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

The ACE Launch Control shows the launch-effective default in its header
(`default effort: @ <level>`), or says `provider default` when none is configured. An
active temporary value carries an override countdown plus an annotation for the
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

| Provider            | Mechanism                             | Supported levels                  | Rejected           |
| ------------------- | ------------------------------------- | --------------------------------- | ------------------ |
| Claude              | `--effort <level>`                    | low, medium, high, xhigh, max     | none, minimal      |
| Codex               | `-c model_reasoning_effort="<level>"` | minimal, low, medium, high, xhigh | none, max          |
| OpenCode            | `--variant <level>`                   | all (validated by OpenCode/model) | —                  |
| Antigravity (`agy`) | none today                            | —                                 | all                |
| Qwen                | none today                            | —                                 | all                |
| Muse Code           | `--reasoning-effort <level>`          | all seven (`max` sent as `ultra`) | —                  |
| Grok Build          | `--effort <level>`                    | low, medium, high, xhigh          | none, minimal, max |
| Fakey               | `--effort <level>`                    | all                               | —                  |

For `agy` and `qwen` (no reasoning-effort mechanism today), every level is
"unsupported": an explicit effort raises, while a config-default effort is skipped with
a warning. The effort args are appended alongside the existing
[`SASE_LLM_*_ARGS` / `SASE_<P>_LARGE_ARGS`](#environment-variables) escape hatches,
which remain available.

Source: `src/sase/xprompt/effort.py` (vocabulary + `split_model_effort`),
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
  big_epic_lander_model: codex/gpt-5.6-sol # threshold-selected epic landers run on Codex
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low
      small: claude/haiku | codex/gpt-4.1-mini
      medium: codex/gpt-5.5@xhigh | claude/sonnet@xhigh
      large: codex/gpt-5.6-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max # xlarge phase/epic maximum-effort target
```

Xsmall phases/tasks/tale-follow-ups use the `@xsmall` pool, small ones the `@small`
pool, medium ones `@medium`, large ones `@large`, and xlarge ones `@xlarge`. Sizeless
standalone tasks fall back to `@small`; sizeless tale follow-ups fall back to `@medium`.
Normal epic landers use `llm_provider.epic_lander_model`, and threshold-selected epic
landers use `llm_provider.big_epic_lander_model`, independent of the size aliases and of
`llm_provider.default_model`. See [Implicit role aliases](#implicit-role-aliases) for
the current shipped defaults. Explicit `%model` directives, approval-picker model
choices, direct alias overrides, and per-bead/land model metadata always win over role
defaults.

> The previous `llm_provider.worker_models` map, the `~/.sase/llm_worker_override.json`
> worker temporary override, and the later
> `@default`/`@epic_lander`/`@big_epic_lander`/`@<size>_worker`/capability-alias
> generation were all removed (epics sase-5d and sase-mf). See the
> [migration note](#launch-scoped-alias-overrides) above.

## Temporary Model Overrides

In addition to prompt-level [launch-scoped overrides](#launch-scoped-alias-overrides)
and the tier-based global override, sase supports **concrete** provider/model overrides
that act as temporary, time-bound machine-wide overrides of a model alias or
launch-model setting. The ACE `,m` chord opens the
[**Launch Control**](ace.md#launch-control) for setting, changing, and clearing these
overrides — for the `launch model`, `epic lander`, and `big epic lander` settings, or
any size/custom alias.

The panel also shows a two-line description for the highlighted alias, launch-model
setting, or bucket. Builtin aliases have fixed descriptions, custom aliases read
`llm_provider.model_aliases.custom.<name>.description`, selector aliases list each
member, its current availability, and the current selection, and each of the three
scalar launch-model-setting rows shows its configured/shipped target, resolved
provider/model, and provenance. The title shows the launch-effective default effort and
current effective `max_running_agents` cap; active temporary values include their
remaining time and configured provenance. Non-pool aliases that explicitly carry an
effort explain its provenance on the second description line.

Overrides are independent **per-alias** for the five size aliases and any custom alias,
and independent **per-setting** for the three scalar launch-model settings (namespaced
`setting:default_model`, `setting:epic_lander_model`, and
`setting:big_epic_lander_model` keys in the override store). An override takes effect
wherever that alias or setting is resolved. For example, an override on `@medium`
affects only that size alias, and an override on the `epic lander` setting affects only
below-threshold epic land agents. An active override on `@xlarge` suspends its ordered
fallback for a single concrete target, just as overrides on `@xsmall`, `@small`, and
`@medium` suspend their independent load-balanced rotations for the override's duration.
The three launch-model settings do not reference a shared alias, so an override on the
`launch model` setting (`llm_provider.default_model`) does not move phase/task/tale
routing — which resolves through the size aliases directly — or epic-land routing —
which resolves through `epic_lander_model`/`big_epic_lander_model`; override the size
alias, or the specific launch-model setting, to move one of those lanes. Machine-wide
temporary overrides do not change:

- Already-running agents — they keep whatever provider/model they were launched with.
- Explicit concrete `%model` prompt targets — they still take precedence. A
  `%model(...)` alias keyword is a separate, higher-precedence launch-scoped override.
- An explicit `provider_name=` argument to `invoke_agent()` — it still wins.

Temporary provider disables can pause, but do not delete, these overrides. If an active
alias override resolves to a disabled provider, SASE ignores that override for live
routing and falls through to the alias's configured or implicit target. If the disable
is cleared or expires before the alias override expires, the stored override resumes
automatically.

An override may carry a canonical reasoning-effort suffix, such as
`codex/gpt-5.6-sol@medium` or `@large@medium`. The write resolves and snapshots the
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

The ACE Launch Control's `p=Providers` flow can temporarily disable a registered
provider for new routing without editing `sase.yml` or unregistering the plugin.
Provider-disable state is machine-wide runtime state in
`~/.sase/llm_provider_disables.json`, owned by the Rust core and exposed through
`src/sase/llm_provider/provider_disable.py`. The lock-free `provider_disable_peek.py`
reader is reserved for high-frequency display and completion paths; launches and writes
use the authoritative Rust-backed facade.

Provider disables are an availability layer:

| Request                  | Disabled provider present? | Result                                             |
| ------------------------ | -------------------------- | -------------------------------------------------- |
| round-robin alias        | one member                 | next available member; cursor advances from winner |
| ordered fallback         | preferred member           | next available candidate                           |
| temporary alias override | override target            | override pauses; underlying alias resolves         |
| direct provider/model    | target provider            | actionable failure; no silent provider change      |
| every selector member    | all                        | member zero retained for diagnostic; launch fails  |
| running provider process | disabled after start       | process continues; future resolution changes       |

Each top-level routing operation captures active disables once and passes that snapshot
through alias resolution, autodetection, model-picker rows, completion overlays, and the
final provider dispatch gate. Round-robin pools skip disabled members without rewriting
membership or fingerprints; re-enabling a provider lets it participate in later
rotations naturally. Ordered fallbacks choose the first installed, non-disabled member
and return to a higher-priority provider on the next resolution after it is re-enabled.
When every selector member is disabled or otherwise unavailable, SASE preserves the
diagnostic candidate rather than silently rerouting to a default provider.

Direct intent remains direct. `%model:claude/opus`, a known bare model owned by Claude,
an explicit `provider_name="claude"`, or `SASE_LLM_EXEC_PROVIDER=claude` fails before
provider construction while Claude is disabled; the error names the provider and expiry
or says `until cleared`. This proves the request was not silently changed to another
provider.

The state file is a versioned envelope with one independent record per provider:

```json
{
  "version": 1,
  "disables": {
    "claude": {
      "provider": "claude",
      "created_at": 1777470000.0,
      "expires_at": 1777473600.0,
      "source": "ace"
    }
  }
}
```

`expires_at: null` means until cleared. Finite expiries are exclusive:
`now >= expires_at` removes the record. Authoritative reads self-clean expired or
malformed per-provider records and delete the file when no active disables remain. A
malformed envelope/version fails closed to no active disables and is removed.

Public provider-disable helpers:

| Function                                                         | Purpose                                                    |
| ---------------------------------------------------------------- | ---------------------------------------------------------- |
| `get_active_provider_disables(now=None)`                         | Read every active disable, keyed by provider.              |
| `get_active_provider_disable(provider, now=None)`                | Read one active provider disable, or `None`.               |
| `disable_provider(provider, duration_seconds, source, now=None)` | Disable one provider for a duration or until cleared.      |
| `disable_provider_until(provider, expires_at, source, now=None)` | Disable one provider until an exact Unix timestamp.        |
| `enable_provider(provider)`                                      | Clear one provider disable; returns whether it existed.    |
| `peek_active_provider_disables(now=None)`                        | Read-only, lock-free display snapshot for TUI/completions. |

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

A legacy **v1** file (a single flat override object with top-level `provider` / `model`
/ ... keys) is migrated on read into `overrides.default`, so an override set by an older
build keeps working after upgrade. Existing v2 entries without `effort` remain valid and
are read as `effort: null`.

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

- Launch Control (`,m`), highlight `launch model`, `o`, pick `codex/o3`, duration `1h` →
  `~/.sase/llm_override.json` gains a `setting:default_model` entry; new launches with
  no `%model` default to CODEX(o3) for the next hour.
- Launch Control, highlight `medium`, `o`, pick `opencode/anthropic/claude-sonnet-4-5`,
  `Until cleared` → medium phases and tasks without an explicit model inherit that
  target until cleared.
- Launch Control, highlight `launch model`, `o`, pick `sonnet`, duration `30m` → known
  bare model; provider resolves to claude via plugin metadata.
- Launch Control, highlight an alias, `x` → that alias's override is cleared; when the
  last override is removed the state file is deleted and defaults revert to permanent
  config / autodetect.

## Environment Variables

Complete reference of environment variables used by the LLM provider layer.

### Generic (Provider-Agnostic)

| Variable                   | Description                                                                         |
| -------------------------- | ----------------------------------------------------------------------------------- |
| `SASE_LLM_EXEC_PROVIDER`   | Execute through this provider while retaining the requested provider/model metadata |
| `SASE_LLM_LARGE_ARGS`      | Extra CLI args for `large` tier invocations                                         |
| `SASE_LLM_SMALL_ARGS`      | Extra CLI args for `small` tier invocations                                         |
| `SASE_MODEL_TIER_OVERRIDE` | Force all invocations to a specific model tier                                      |
| `SASE_MODEL_SIZE_OVERRIDE` | Legacy alias for `SASE_MODEL_TIER_OVERRIDE`                                         |

`SASE_LLM_EXEC_PROVIDER` must name a registered provider. It changes subprocess dispatch
and execution-provider retry policy only; agent, step, and chat metadata continue to
show the provider and model the user requested. Run artifacts record the dispatched
provider separately as `exec_llm_provider`.

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

### Antigravity (`agy`)-Specific

| Variable                 | Description                                                        |
| ------------------------ | ------------------------------------------------------------------ |
| `SASE_AGY_PATH`          | Path to the Antigravity CLI binary (default: `"agy"`).             |
| `SASE_AGY_PRINT_TIMEOUT` | Override the `agy --print-timeout` Go duration (default: `"24h"`). |
| `SASE_AGY_LARGE_ARGS`    | Antigravity-specific extra args for `large` tier                   |
| `SASE_AGY_SMALL_ARGS`    | Antigravity-specific extra args for `small` tier                   |

### OpenCode-Specific

| Variable                   | Description                                   |
| -------------------------- | --------------------------------------------- |
| `SASE_OPENCODE_PATH`       | Path to the OpenCode CLI binary               |
| `SASE_OPENCODE_LARGE_ARGS` | OpenCode-specific extra args for `large` tier |
| `SASE_OPENCODE_SMALL_ARGS` | OpenCode-specific extra args for `small` tier |

### Muse Code-Specific

| Variable               | Description                                                         |
| ---------------------- | ------------------------------------------------------------------- |
| `SASE_MUSE_PATH`       | Path to the Muse Code CLI binary (default: `muse` on `PATH`)        |
| `SASE_MUSE_LARGE_ARGS` | Muse-specific extra args for `large` tier                           |
| `SASE_MUSE_SMALL_ARGS` | Muse-specific extra args for `small` tier                           |
| `SASE_MUSE_SANDBOX`    | Set to `on` to keep Muse's sandbox with `--sandbox-network enabled` |

SASE always launches Muse with `MUSE_NO_AUTO_UPDATE=1` so the launcher cannot swap the
binary mid-run; `sase agent-cli update muse` sets `MUSE_SYNC_UPDATE=1` instead. The two
must never be set together.

### Grok-Specific

| Variable               | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `SASE_GROK_PATH`       | Path to the Grok Build CLI binary (default: `grok` on `PATH`) |
| `SASE_GROK_LARGE_ARGS` | Grok-specific extra args for `large` tier                     |
| `SASE_GROK_SMALL_ARGS` | Grok-specific extra args for `small` tier                     |

SASE always launches Grok with `--no-auto-update` so it cannot swap its own binary
mid-run; `sase agent-cli update grok` runs Grok Build's own `update` subcommand instead.

External provider plugins document their own environment variables in their respective
repos.

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

The `ace` command wires `--model-tier` / `--model-size` into the `model_tier_override`
parameter of `AceApp`. The `--vcs-provider` flag is wired to the `SASE_VCS_PROVIDER`
environment variable for downstream resolution.

## Retry and Fallback

The LLM provider layer supports per-provider retry and fallback configuration. When an
agent encounters a retryable error, it can automatically wait and retry, then optionally
fall back to an alternate model.

### Configuration

Retry behavior is configured per provider under `llm_provider.retry` in `sase.yml`:

```yaml
llm_provider:
  retry:
    claude:
      max_retries: 3
      error_patterns:
        - "API Error: 500"
      wait_times: [60, 300, 1800]
      fallback_model: "sonnet"
```

### Config Fields

| Field                 | Type          | Default | Description                                                                                                                                                                                   |
| --------------------- | ------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_retries`         | int           | `0`     | Maximum retry attempts. `0` disables retrying.                                                                                                                                                |
| `error_patterns`      | list[str]     | `[]`    | Case-insensitive substring patterns matched against error output.                                                                                                                             |
| `wait_times`          | list[int]     | `[30]`  | Per-retry wait times in seconds. Last value reused if list is too short.                                                                                                                      |
| `fallback_model`      | `str \| null` | `null`  | Alternate model to use after exhausting all retries.                                                                                                                                          |
| `continuation_prompt` | `str \| null` | `null`  | Text prepended to `state.current_prompt` on every retry (used to nudge the agent).                                                                                                            |
| `preserve_workspace`  | bool          | `false` | Preserve on-disk edits across legacy in-process retry attempts.                                                                                                                               |
| `spawn_new_agent`     | bool          | `false` | Opt in to spawn-on-retry: a retryable error spawns a fresh detached child agent (as if `sase run` had been invoked) instead of in-process retry. See [Spawn-on-Retry](#spawn-on-retry) below. |

### Default Configuration

Retry defaults can come from two places: configured policy under `llm_provider.retry`
and provider-supplied defaults from the `llm_default_retry_config()` hook. The bundled
`default_config.yml` already provides configured policy for Claude and Codex; user
config can replace or extend it through the normal config merge.

**Claude:**

- **max_retries**: 3
- **error_patterns**:
  `["API Error: 500", "API Error: 529", "Internal server error", "overloaded_error"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"sonnet"`

**Codex:**

- **max_retries**: 3
- **error_patterns**:
  `["exceeded retry limit", "429 Too Many Requests", "Too Many Requests", "rate limit", "failed to connect to websocket", "Selected model is at capacity"]`
  — the Codex CLI's own give-up message, terminal rate-limit and model-capacity
  statuses, and the transient websocket transport error. A bare `403 Forbidden` is
  deliberately excluded so a persistent auth failure is not retried forever.
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min) — rate limits need a real
  cool-down

### Provider-Supplied Retry Defaults

Providers can also declare retry defaults through the `llm_default_retry_config()` hook.
Claude, Codex, and Grok declare a recovery entry that is merged with their configured
policy.

Claude:

- **error patterns**: `"Prompt is too long"`,
  `"socket connection was closed unexpectedly"`, and `"API Error"`
- **max_retries**: 3
- **wait_times**: `[0]` — used only when no config layer supplies `wait_times`; the
  bundled Claude policy supplies `[60, 300, 1800]`, so that is the out-of-the-box
  backoff
- **continuation_prompt**: A short nudge that tells the coder to inspect `git status` /
  `git diff` before resuming, since prior edits are preserved on disk after a
  context-limit, socket-close, or API-error retry
- **preserve_workspace**: `true`

Codex:

- **error patterns**: `"exceeded retry limit"`, `"429 Too Many Requests"`,
  `"Too Many Requests"`, `"rate limit"`, and `"failed to connect to websocket"`, and
  `"Selected model is at capacity"` — the transient transport, rate-limit, and
  model-capacity failure modes where the Codex CLI exhausts its own internal reconnects
  or exits non-zero
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` — the bundled Codex policy supplies the same backoff
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude
- **preserve_workspace**: `true`

Grok:

- **error patterns**: `"xAI API error"`, `"xAI rate limit"`, `"xAI server error"`, and
  `"xAI upstream request failed"` — kept narrow and xAI-specific so they cannot collide
  with Codex's ownership of generic `429` / `Too Many Requests` wording
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude and
  Codex
- **preserve_workspace**: `true`

Fakey:

- **error pattern**: `"FAKEY-RETRYABLE"`, the canonical marker emitted by retryable
  fakey scenarios
- **max_retries**: 3
- **wait_times**: `[0]`, keeping deterministic test retries fast
- **continuation_prompt**: The same resume nudge as Claude and Codex
- **preserve_workspace**: `true`

These defaults make `@flaky` and other retryable fakey scenarios exercise the retry
pipeline without user config. A commented `llm_provider.retry.fakey` example in the
default config shows how to override them.

Configured `llm_provider.retry.<provider>` values are merged on top of provider-supplied
defaults: explicit falsy values (`max_retries: 0` to opt out entirely,
`continuation_prompt: ""` to disable the nudge) override the built-in via key-presence
checks. `error_patterns` is a de-duplicated union of built-in and configured lists.

On every retry attempt the `continuation_prompt` (if non-empty) is idempotently
prepended to `state.current_prompt` before the next invocation — the prepend is gated on
a `startswith` check so repeated retries don't stack duplicate nudges. Workspaces are
preserved across Claude's built-in context-limit, socket-close, and API-error retries
(no workspace wipe), so on-disk edits remain available to the restarted session.

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

Wait periods are interruptible — if the agent is killed during a wait, it stops
immediately.

### TUI Display

The ACE Agents tab reflects retry state (see
[Retry/Fallback Display](ace.md#retryfallback-display)):

- **RETRYING (Ns)** — Waiting before the next attempt (bold orange, with countdown)
- **↻N** — Retry count annotation on running agents
- **▸Model** — Fallback model annotation (e.g., `↻3▸flash`)

### Metadata Tracking

If any retries occurred or a fallback model was used, retry metadata is written to
`done.json` in the agent's artifacts directory after execution completes (runs that
succeed on the first attempt omit these fields):

```json
{
  "retry_count": 2,
  "retry_errors": ["An unexpected critical error occurred: ..."],
  "used_fallback": false
}
```

When `used_fallback` is `true`, the metadata also includes the `fallback_model` that
served the final attempt.

Source: `src/sase/llm_provider/retry_config.py`,
`src/sase/axe/run_agent_exec_finalize.py`

### Spawn-on-Retry

When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh
detached child agent (as if `sase run` had been invoked) instead of running the next
attempt in-process. The failing parent transfers its workspace claim to the child via
`transfer_workspace_claim()` and exits with status `FAILED (RETRIED)`. This trades the
small cost of a fresh process for two benefits:

- The workspace is preserved by design — the child skips `prepare_workspace()` and
  inherits the parent's in-progress edits via the transferred workspace claim. (Legacy
  in-process retry runs `prepare_workspace()` between attempts and wipes uncommitted
  file edits unless `preserve_workspace=True`.)
- A retry boundary becomes a real process boundary, which is more robust against memory
  leaks, lingering child processes, and stale interpreter state.

**Linkage fields** (written to both `agent_meta.json` and `done.json` so retry chains
are queryable from either side):

| Field                        | Meaning                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `retry_of_timestamp`         | Backward link: the parent agent's run timestamp.                                  |
| `retried_as_timestamp`       | Forward link: the child agent's run timestamp (written on the parent at handoff). |
| `retry_chain_root_timestamp` | The root agent's timestamp — stable across the entire chain.                      |
| `retry_attempt`              | Depth in the chain (1-based).                                                     |

State is carried across the boundary by a `retry_handoff.json` file written to the
parent's artifacts directory; the child reads it before launch.

**Fallback behavior**: spawn-on-retry is opt-in (default `false`). If spawning fails
(e.g. workspace transfer fails), the legacy in-process retry runs as a fallback so the
user is never worse off.

Source: `src/sase/axe/run_agent_retry_spawn.py`, `src/sase/llm_provider/retry_config.py`

## Legacy Thinking Metadata

Older parser helpers can still read provider thinking/reasoning artifacts when a caller
uses them directly. For Claude extended-thinking events whose `thinking` text is empty
but whose payload contains an opaque `signature`, those helpers produce an
encrypted-thinking placeholder instead of hiding the block. When Claude also reports
`message.usage.output_tokens`, the placeholder includes an approximate output-token
count so the caller can tell that reasoning occurred even though the raw thought text is
not available. The Agents tab now uses the Tools panel for provider tool activity
instead of exposing these thinking helpers as a panel.

## Token Usage Tracking

The LLM provider layer tracks token usage for providers that emit parseable usage
events. Claude and Qwen usage is read from their stream-json result events. OpenCode
usage is accumulated from `step_finish` token counters. Muse emits no token counts on
stdout at all, so its usage is recovered after the process exits from the
[session log SASE named](#token-usage-and-model-identity) via `--session-id`. Codex
currently captures assistant text and reasoning summaries but does not emit
`usage.json`. Grok's `result.usage` uses the same four keys as Claude's, but is
best-effort: subagent turns and interrupted turns can under-count or zero out because
the `streaming-messages-json` projection drops Grok's internal "usage incomplete" marker
— see [Token Usage](#token-usage).

When usage is available, input tokens, output tokens, cache-creation tokens, and
cache-read tokens are persisted as a `usage.json` artifact in the agent run directory.

### Artifact Format

```json
{
  "input_tokens": 12345,
  "output_tokens": 6789,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 3456
}
```

When telemetry is enabled, token counts are recorded as local debugging counters
(`sase_llm_input_tokens_total`, `sase_llm_output_tokens_total`,
`sase_llm_cache_read_tokens_total`). See [docs/telemetry.md](telemetry.md) for the full
telemetry reference.

Source: `src/sase/llm_provider/_subprocess.py`, `src/sase/llm_provider/types.py`

## Prompt Preprocessing Pipeline

Before any prompt reaches a provider, it passes through the shared preprocessing
pipeline defined in `preprocessing.py`. The pipeline has an early phase used for xprompt
expansion and directive extraction, then a late phase used for command, file, template,
and formatting work.

### Steps

| Phase | Step                       | Syntax                                     | Description                                              |
| ----- | -------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| Early | Optional workflow Jinja2   | `{{ var }}`                                | Render workflow-supplied template context before xprompt |
| Early | xprompt references         | `#name`                                    | Expand reusable prompt snippets or workflows             |
| Early | Prompt directives          | `%model`, `%m`, other `%...` directives    | Extract directives after xprompt expansion               |
| Late  | Disabled/fenced protection | `%xprompts_enabled:false`, fenced code     | Protect regions that should not be rewritten             |
| Late  | Command substitution       | `$(cmd)`                                   | Execute shell commands and inline their output           |
| Late  | Artifact references        | `@kind:payload`                            | Resolve known artifact kinds into launch-ready locators  |
| Late  | File references            | `@path`                                    | Process, validate, or skip file references               |
| Late  | Top-level Jinja2           | `{{ var }}`                                | Render remaining top-level Jinja2 templates              |
| Late  | Prettier formatting        | -                                          | Format with prettier for consistent markdown             |
| Late  | Comment stripping          | `<!-- ... -->`                             | Remove HTML/markdown comments                            |
| Late  | Restore protected regions  | fenced code / disabled-region placeholders | Restore protected content after rewrites                 |

### Order Matters

The pipeline runs in strict order. Prompt directives are extracted after xprompt
expansion, so directives embedded in xprompts are honored. Late-phase command
substitution and reference processing run with fenced blocks protected, so examples
inside code fences are not executed or rewritten. Canonical artifact references are
expanded before ordinary file references: document and artifact-file references become
`@path` tokens, as do published bead and agent pages. A stitch becomes
`stitch <full-sha> in <repo> (checkout: <path>)`; a Patch becomes a project-qualified
label with a `sase patch show` hint. Unknown `@kind:` references remain unchanged as
prose. The retired `#ref/<kind>` renderer syntax is not accepted. Inline-code references
also remain literal.

During the same pass, SASE stages prompt references for later archive publication. File
references are recorded in the workspace-local `.sase/artifacts/prompt-artifacts.jsonl`
manifest. Home-directory `@path` references are copied to the readable working-copy tree
`.sase/artifacts/home/`, external bytes are pooled by digest under
`.sase/artifacts/pool/`, and clean tracked files in known repositories are recorded as
VCS-backed rows instead of copied. The committing agent's prompt archive then links
those rows from the agents sidecar.

### Home Mode

When `is_home_mode=True`, file-reference processing skips copy side effects. This is
used when the invocation doesn't need workspace-local copies from `@path` references.

### Source Functions

The preprocessing steps delegate to functions from two libraries:

- **`xprompt`**: `process_xprompt_references()`, `extract_prompt_directives()`,
  `is_jinja2_template()`, `render_toplevel_jinja2()`
- **`artifact_refs`**: `process_artifact_references()`, `validate_artifact_references()`
- **`file_references`**: `process_command_substitution()`, `process_file_references()`,
  `validate_file_references()`, `format_with_prettier()`, `strip_html_comments()`

## Subprocess Streaming

Providers use shared helpers in `_subprocess.py` and the `_subprocess_*` modules to
stream LLM output in real time. Plain text, JSON-line, and provider-specific parsers
share the same artifact hooks for live replies and usage files.

### Mechanism

1. The provider spawns the CLI tool via `subprocess.Popen`. Providers that consume
   prompts from stdin set `stdin=PIPE`; OpenCode passes the prompt as the final
   `opencode run` argument, and Muse passes a `0o600` `--prompt-file` under SASE's
   managed temp root.
2. The prompt is supplied using the provider's documented transport, either stdin or an
   argv message argument.
3. Stdout and stderr are set to **non-blocking** mode via `os.set_blocking()`.
4. A `select.select()` loop with a 0.1s timeout polls for readable data on both streams.
5. Lines are read, parsed when needed, and optionally printed to the console in real
   time.
6. After the process exits (`process.poll() is not None`), any remaining buffered output
   is drained.
7. Helpers return stdout/assistant text, stderr diagnostics, return code, and usage data
   when the provider reports it.

### Live Reply File

When `SASE_ARTIFACTS_DIR` is set, the streaming output is also written in real-time to
`<SASE_ARTIFACTS_DIR>/live_reply.md`. This file is used by the ACE TUI Agents tab to
display the agent's reply as it streams in, and remains available after execution
completes for the metadata panel's AGENT REPLY section.

Providers that support richer streams may write sidecar artifacts. Codex and Grok both
write reasoning content to `<SASE_ARTIFACTS_DIR>/codex_thinking.jsonl` (the filename is
shared rather than renamed per provider, since ACE's `read_codex_thinking` reads that
exact path); providers with token counters write `<SASE_ARTIFACTS_DIR>/usage.json`; Muse
records the model it actually configured and its session id in
`<SASE_ARTIFACTS_DIR>/run_metadata.json`.

### Output Suppression

When `suppress_output=True`, lines are still captured but not printed to the console.
This is used for background invocations where the caller only needs the final result.

## Postprocessing

After a provider returns (or raises an error), the orchestration layer runs
postprocessing steps.

### On Success (`postprocess_success`)

1. **Audio notification**: Plays a sound via `run_bam_command("Agent reply received")`
   (skipped if `suppress_output`).
2. **Log to sase.md**: Appends a timestamped entry with the prompt and response to
   `<artifacts_dir>/sase.md` (if `artifacts_dir` is set).
3. **Save chat history**: Writes to `~/.sase/chats/` if `workflow` is set. See
   [Chat History](#chat-history).

### On Error (`postprocess_error`)

1. **Rich error display**: Prints the prompt and error via `print_prompt_and_response()`
   with an `_ERROR` suffix on the agent type label (skipped if `suppress_output`).
2. **Log to sase.md**: Same as success, but the response is the error message and the
   agent type gets an `_ERROR` suffix.
3. **Save error chat history**: Writes to `~/.sase/chats/` with an `_ERROR` agent
   suffix.

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

Before invocation, the preprocessed prompt is saved to
`<artifacts_dir>/<agent_type>_prompt.md` (or `<agent_type>_iter_<N>_prompt.md` if an
iteration number is set). This allows reviewing the exact prompt that was sent.

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

The `MODEL` and `AGENT` blocks are omitted when the invocation did not provide that
metadata. `MODEL` can contain just a model name, just a provider name, or both. When
both provider and model are known, it is rendered as `<provider>/<model>` unless the
model already includes that prefix.

### Resume Support

Resume uses the `#fork` and `#fork_by_chat` workflows through normal detached `sase run`
launches. `#fork` resolves an agent name to its artifacts directory, extracts the
response path from `done.json`, and delegates to `#fork_by_chat`, which loads the chat
history and prepends it to the new conversation. Use `#fork_by_chat(<path-or-basename>)`
for direct chat-file-based resumption.

Fork expansion is recursive: if the loaded chat history itself contains `#fork` or
`#fork_by_chat` references, those are expanded inline as well. Legacy `#resume` and
`#resume_by_chat` references in old transcripts are still recognized. Cycle detection
prevents infinite loops when chat histories reference each other.

## Invocation Lifecycle

The `invoke_agent()` function in `_invoke.py` orchestrates the complete lifecycle of an
LLM invocation. Here is the end-to-end flow:

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
│   ├── Check main workspace and configured Git linked repos
│   ├── Enforce dirty linked repo clones
│   ├── Auto-commit exact tracked SDD done-status closeouts
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

On success, returns an `AIMessage` (from `langchain_core.messages`) whose `content` is
the provider response. On provider failure, `invoke_agent()` logs the error and raises
`LLMInvocationError` with the formatted error text.
