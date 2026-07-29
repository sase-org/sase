# LLM Provider Integration

This document describes the LLM provider abstraction layer in sase. The system supports pluggable LLM backends (Claude
Code, Codex, Antigravity CLI (`agy`), Qwen Code, and OpenCode are bundled; additional providers can ship as external
plugins) behind a shared orchestration layer that handles preprocessing, invocation, and postprocessing.

> This page documents how SASE _integrates_ each provider. To install and authenticate a provider CLI in the first
> place, see [Installing & Authenticating Agent Providers](agent_providers.md).

## Table of Contents

- [Overview](#overview)
- [Provider Architecture](#provider-architecture)
- [Commit Finalization](#commit-finalization)
- [Claude Code Integration](#claude-code-integration)
- [Antigravity (`agy`) Integration](#antigravity-agy-integration)
- [Codex CLI Integration](#codex-cli-integration)
- [Qwen Code Integration](#qwen-code-integration)
- [OpenCode Integration](#opencode-integration)
- [External Provider Plugins](#external-provider-plugins)
- [Configuration](#configuration)
- [Per-Prompt Provider Switching](#per-prompt-provider-switching)
- [Reasoning Effort](#reasoning-effort)
- [Model Tier System](#model-tier-system)
- [Role Aliases for Delegated Work](#role-aliases-for-delegated-work)
- [Temporary Model Overrides](#temporary-model-overrides)
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

| File                                          | Purpose                                                |
| --------------------------------------------- | ------------------------------------------------------ |
| `src/sase/llm_provider/__init__.py`           | Public API exports                                     |
| `src/sase/llm_provider/base.py`               | `LLMProvider` abstract base class                      |
| `src/sase/llm_provider/_hookspec.py`          | Pluggy hook specifications (`LLMHookSpec`)             |
| `src/sase/llm_provider/_plugin_manager.py`    | Plugin manager wrapping pluggy (`LLMPluginManager`)    |
| `src/sase/llm_provider/claude.py`             | Claude Code provider implementation                    |
| `src/sase/llm_provider/codex.py`              | Codex CLI provider implementation                      |
| `src/sase/llm_provider/fakey.py`              | Bundled deterministic testing provider                 |
| `src/sase/llm_provider/agy.py`                | Antigravity CLI (`agy`) provider implementation        |
| `src/sase/llm_provider/qwen.py`               | Qwen Code provider implementation                      |
| `src/sase/llm_provider/opencode.py`           | OpenCode provider implementation                       |
| `src/sase/llm_provider/registry.py`           | Provider registration and lookup                       |
| `src/sase/llm_provider/config.py`             | Config file reader (`sase.yml`)                        |
| `src/sase/llm_provider/temporary_override.py` | Primary/worker temporary override state and resolution |
| `src/sase/llm_provider/commit_finalizer.py`   | Provider-neutral dirty-workspace finalizer             |
| `src/sase/llm_provider/types.py`              | `ModelTier`, `InvokeResult`, `LoggingContext` types    |
| `src/sase/llm_provider/_invoke.py`            | `invoke_agent()` orchestrator                          |
| `src/sase/llm_provider/_subprocess.py`        | Provider stream-parser compatibility exports           |
| `src/sase/llm_provider/_plan_utils.py`        | Shared plan utilities                                  |
| `src/sase/llm_provider/preprocessing.py`      | Shared prompt preprocessing pipeline                   |
| `src/sase/llm_provider/postprocessing.py`     | Logging, chat history, audio                           |
| `src/sase/llm_provider/retry_config.py`       | `ProviderRetryConfig` (per-provider retry defaults)    |

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
fakey = "sase.llm_provider.fakey:FakeyProvider"
agy = "sase.llm_provider.agy:AgyProvider"
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
   priorities: `claude=0`, `codex=10`, `qwen=15`, `opencode=18`, `agy=30`. External plugins slot in by declaring their
   own priority. `agy` autodetects via the `agy` CLI name in the late-fallback slot.

## Commit Finalization

After a provider returns successfully, `invoke_agent()` runs the provider-neutral commit finalizer before success
postprocessing when the process is a SASE agent session (`SASE_AGENT_TIMESTAMP` is set). The finalizer checks the active
project workspace through the active VCS provider and checks configured linked repositories as Git worktrees at their
resolved `workspace_dir`. If it finds dirty enforced work, it sends the same provider a bounded follow-up prompt that
lists the dirty files and instructs the agent to use the appropriate commit skill, such as `/sase_git_commit`. Dirty
linked repo clones are enforced like the main workspace. A narrow generated SDD plan closeout, where the only enforced
change is one markdown file's frontmatter `status: wip` becoming `status: done`, is committed directly with a
`SASE_TYPE=sdd` commit instead of consuming a provider follow-up pass.

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

`opus` and `sonnet` are floating Claude CLI aliases that resolve to the provider's current model (Opus 5 today), so sase
intentionally does not pin them to a point version.

### Environment Variables

| Variable                 | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`    | Extra CLI args for `large` tier (generic, preferred)       |
| `SASE_LLM_SMALL_ARGS`    | Extra CLI args for `small` tier (generic, preferred)       |
| `SASE_CLAUDE_LARGE_ARGS` | Extra CLI args for `large` tier (Claude-specific fallback) |
| `SASE_CLAUDE_SMALL_ARGS` | Extra CLI args for `small` tier (Claude-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence. Values are split on whitespace and appended to the command.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Claude")` spinner is shown (unless `suppress_output` is
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
- "Home-mode" launches — agents started outside a tracked workspace, identified by the absence of
  `SASE_GIT_WORKSPACE_DIR` and `SASE_ACTIVE_PROJECT_DIR` — skip the settings mutation entirely. They emit a
  `claude_hooks_skipped` diagnostic to `tool_calls_writer_errors.jsonl` so the operator can see why the hook records are
  missing, and rely on the stream-derived fallback writer (below) to populate the timeline.
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

## Antigravity (`agy`) Integration

The `AgyProvider` invokes Google's Antigravity CLI (`agy`), the replacement for the retired consumer Gemini CLI. It is a
plain-stdout provider: Antigravity CLI 1.0.10 does not document a machine-readable JSON/stream output mode, so SASE
streams plain stdout instead of parsing a structured event stream.

### Command Construction

```
agy --print-timeout <duration> --model <model> --dangerously-skip-permissions --add-dir <workspace> --print <prompt>
```

The prompt is passed as the value of `--print` (not on stdin) as a single argv element, so prompts containing quotes,
newlines, or shell metacharacters are never shell-interpolated. `--print-timeout` defaults to `24h` (Antigravity's own
`5m` default is too short for long agentic runs) and is a Go duration string.

SASE pins Antigravity to the agent workspace in two ways: it launches the subprocess with `cwd=<workspace>` and passes
`--add-dir <workspace>` to the CLI. The workspace is resolved from `SASE_ACTIVE_PROJECT_DIR`, then provider project and
workspace env vars, and finally the current working directory.

Because the current Antigravity CLI does not document a stable stdin or prompt-file contract for print mode, SASE cannot
fall back to streaming the prompt when that single argv element becomes too large for the OS. `AgyProvider` therefore
rejects prompts above a conservative 120 KiB UTF-8 guard before spawning `agy`, with an error that names the upstream
argv transport limitation and asks the user to reduce the prompt or use a stdin-capable provider.

Before invoking `agy --print`, SASE wraps the user prompt with a compact print-mode directive. It tells the model that
tool approval has already been granted by `--dangerously-skip-permissions`, commands must run synchronously, background
tasks should not be used because print mode has no event loop for later notifications, and the final answer must be
written directly to stdout.

### Print-Mode No-Progress Recovery

Antigravity's `run_command` tool can dispatch long-running commands as background tasks. In an interactive Antigravity
session, the UI can deliver the later completion notification and the model can continue. In `agy --print`, SASE starts
a single non-interactive process and reads stdout; there is no follow-up event loop. Some models therefore end the print
turn with prose such as "I will wait to be notified" or "please approve the command" even though the subprocess exits
`0`.

`AgyProvider` treats those replies as no-progress, not success. When the supported trajectory extractor is available,
SASE first checks the structural diff: zero tool-use steps or a final pending/backgrounded `run_command` step triggers
recovery. When trajectory data is unavailable, a conservative text heuristic catches planning-only/waiting replies. SASE
then restarts `agy --print` with accumulated context and a provider-local continuation nudge that asks the model to run
tools synchronously and output the final answer. If the reply still makes no progress after the bounded continuation
budget, `invoke()` raises `LLMInvocationError` so the run fails loudly instead of writing a false-success answer.

### Model Mapping

`agy` model display names are used verbatim — they contain spaces and parentheses (e.g. `Gemini 3.5 Flash (High)`). The
tier defaults are:

| Tier    | Model                     | Short alias |
| ------- | ------------------------- | ----------- |
| `large` | `Gemini 3.5 Flash (High)` | `flash35h`  |
| `small` | `Gemini 3.5 Flash (Low)`  | `flash35l`  |

All other `agy models` names remain reachable through the model picker, configured aliases, and quoted paren-form
provider/model directives such as `%m("agy/Gemini 3.5 Flash (High)")`. Use the quoted form for names with spaces or
parentheses; colon syntax cannot express those names verbatim.

### Environment Variables

| Variable                                 | Description                                                        |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `SASE_AGY_PATH`                          | Path to the Antigravity CLI binary (default: `"agy"`).             |
| `SASE_AGY_PRINT_TIMEOUT`                 | Override the `agy --print-timeout` Go duration (default: `"24h"`). |
| `SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS` | Override the no-progress continuation cap (default: `2`).          |
| `SASE_AGY_LARGE_ARGS`                    | Extra args for the `large` tier (after `SASE_LLM_LARGE_ARGS`).     |
| `SASE_AGY_SMALL_ARGS`                    | Extra args for the `small` tier (after `SASE_LLM_SMALL_ARGS`).     |

### Skill Deployment

`sase skill init -p agy` writes generated SASE skills to `~/.gemini/antigravity-cli/skills/`, the documented Antigravity
global skill path. The leading `.gemini` here is an Antigravity-owned path, not a Gemini CLI path.

### Structured Artifacts Parity Gap

Antigravity CLI 1.0.10 exposes no stable machine-readable stdout contract: there is no documented
`--output-format stream-json` or JSON event mode. Because SASE will not scrape Antigravity's human TUI rendering to
synthesize artifacts, the `agy` provider preserves these invariants:

- **Tool-call timeline** — SASE never invents rows from stdout display glyphs or prose. For explicitly supported
  Antigravity versions, a guarded best-effort extractor may decode new rows from Antigravity's local trajectory DB and
  append `source="trajectory"` records to `tool_calls.jsonl`; otherwise the ACE
  [Agents Tab Tools Panel](ace.md#agents-tab-tools-panel) shows nothing for `agy` runs.
- **Usage accounting** — `InvokeResult.usage` is `None` and no `usage.json` is written; `agy` print mode exposes no
  stable token counters.
- **Thinking extraction** — no thinking artifact is produced.

The plain-stdout path still writes `live_reply.md` (and `live_reply_timestamps.jsonl`) like every other provider, so the
final reply, chat history, and resume support work normally. These structured features are fast-follow work gated on a
future Antigravity machine-readable output/log/conversation contract.

### Timer Display

While waiting for a response, a `Waiting for Antigravity` spinner is shown (unless `suppress_output` is `True`).

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
| `large` | `gpt-5.6-sol`       |
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

Codex tool-call summaries use the same bounded and redacted artifact helpers as the other providers. Textual command
output (`stdout`, `stderr`, and combined `output`) uses a tail-oriented soft character budget: when truncation is
needed, the summary marks how much was omitted from the beginning and retains at least the final 50 complete logical
lines. Exceptionally wide trailing lines can therefore make a summary larger than the nominal budget. Command input,
paths, errors, read/web content, and subagent final messages remain head-oriented. Set `SASE_TOOL_LOG_FULL=1` only for
explicit debugging sessions when raw tool input or output is needed in the local artifact.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Codex")` spinner is shown (unless `suppress_output` is
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

While waiting for a response, a `provider_timer("Waiting for Qwen")` spinner is shown (unless `suppress_output` is
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

While waiting for a response, a `provider_timer("Waiting for OpenCode")` spinner is shown (unless `suppress_output` is
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
  provider: claude # or "qwen", "opencode", "agy", "fakey" (default: auto-detect)
  default_effort: xhigh # default reasoning effort when a prompt sets none (default: unset)
  model_tier_map:
    large: opus
    small: sonnet
  model_aliases:
    builtin:
      default: opus # model used when a prompt has no %model directive
      claude_coder: codex/gpt-5.6-sol # coder follow-ups from Claude-authored plans
      codex_coder: claude/opus # coder follow-ups from Codex-authored plans
      big_epic_lander: codex/gpt-5.6-sol # threshold-selected epic landers
      cheap: claude/opus@medium | codex/gpt-5.5 # small-phase pool
      cheaper: claude/sonnet | codex/gpt-5.3-codex-spark # xsmall-phase pool
      cheapest: claude/haiku || codex/gpt-5.3-codex-spark # explicit-use fallback
      xsmall_phase_worker: "@cheaper"
      small_phase_worker: "@cheap"
      medium_phase_worker: "@default@high"
      large_phase_worker: "@smart"
      xlarge_phase_worker: "@smartest"
      smartest: claude/claude-fable-5 || codex/gpt-5.6-sol # ordered fallback
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
    buckets:
      coders:
        description: Coder defaults and provider-specific follow-ups.
      phase_worker:
        description: Size-specific phase-agent roles.
```

### Config Fields

| Field                                | Type   | Default     | Description                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------ | ------ | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`              | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; real built-ins default to claude → codex → qwen → opencode → agy, with fakey last as a testing-only fallback.                                                                                                                                                                                                                |
| `llm_provider.default_effort`        | string | unset       | Default [reasoning-effort](#reasoning-effort) level applied when a prompt sets no `%effort`/`@effort`. One of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; unset/invalid imposes no effort.                                                                                                                                                                                               |
| `llm_provider.model_tier_map.large`  | string | -           | Model identifier for the `large` tier                                                                                                                                                                                                                                                                                                                                                                    |
| `llm_provider.model_tier_map.small`  | string | -           | Model identifier for the `small` tier                                                                                                                                                                                                                                                                                                                                                                    |
| `llm_provider.model_aliases.builtin` | dict   | -           | Builtin alias overrides only (`default`, `coder`, `<provider>_coder`, `epic_lander`, `big_epic_lander`, `<size>_phase_worker`, `smartest`, `smart`, `cheap`, `cheaper`, `cheapest`). Values use the single-target grammar below, a `\|` round-robin pool, or a `\|\|` ordered fallback. The retired `epic_creator` and `phase_worker` names are no longer builtin overrides; `sase doctor` reports them. |
| `llm_provider.model_aliases.custom`  | dict   | -           | User-defined aliases for `%model:@<alias>` / `%m:@<alias>`. Each value is an object with required `model` and `description` fields; `model` accepts the same single-target and selector grammar. Descriptions are shown in completions and the Models panel.                                                                                                                                             |
| `llm_provider.model_aliases.buckets` | dict   | -           | Optional display-only ACE Models-panel bucket descriptions.                                                                                                                                                                                                                                                                                                                                              |

## Per-Prompt Provider Switching

The `%model` directive (see [xprompt directives](xprompt.md#directives)) can switch both the model and the LLM provider
for a single prompt. Provider resolution uses configured aliases first, then concrete provider/model syntax and known
model metadata.

### Configured Model Aliases

Use `llm_provider.model_aliases.custom` to define launch-time aliases for reusable prompts. Each custom alias must carry
a short description:

```yaml
llm_provider:
  model_aliases:
    custom:
      fast:
        model: claude/sonnet
        description: Quick follow-up agents.
```

Use `llm_provider.model_aliases.builtin` only to override the implicit role aliases (see below):

```yaml
llm_provider:
  model_aliases:
    builtin:
      default: opus
      coder: "@default"
```

Then prompts can use the alias with a leading `@`:

```
%model:@fast
%{%m:@default | %m:gpt-5.6-sol}
```

Alias values may point at another alias (for example `@default` or `@coder`), a bare known model such as `opus`, an
explicit provider/model string such as `claude/opus`, or a nested provider-local path such as
`opencode/anthropic/claude-sonnet-4-5`. An alias reference may carry a trailing effort such as `@default@high`, which
overrides the referenced alias's effort; an effort on the outer reference still wins. Alias-to-alias chains are followed
with cycle and depth protection; a cyclic or unresolved reference falls back to the raw input rather than crashing a
launch. The `@` marker is only directive surface syntax: alias keys and xprompt values stay bare. A bare
configured/implicit alias raises with a migration hint, and `@` in front of a non-alias raises.

An alias value can instead use one of two selector operators. `A | B` is an availability-filtered round-robin pool: real
launches advance machine-global state in `~/.sase/llm_lb.json`, while display, completion, doctor, dry-run, and preview
callers only peek. `A || B` is an ordered fallback chain: the first member whose registered provider CLI is installed
always wins, and resolution never reads or changes the round-robin cursor, including during a real launch. Fallback is
based only on the cached CLI-installation probe (including `SASE_<PROVIDER>_PATH`), not a later model or runtime
failure; SASE does not relaunch with the next candidate after such a failure. If every provider is unavailable, both
modes preserve a candidate for the ordinary provider lookup to report: fallback preserves its first member, while the
pool preserves its current rotation choice.

Both selectors accept two or more members using the same single-target grammar, including candidate-specific trailing
reasoning effort. Whitespace is trimmed and empty members are invalid. `|` and `||` cannot be mixed in one value, and a
member may follow an ordinary alias chain but cannot reach another pool or fallback. Selector expressions are
config-only: `%model` values, launch-scoped alias overrides, and temporary overrides remain single targets. An override
on the alias that owns a selector bypasses that expression for the override's lifetime. The ACE Models panel shows every
member's availability, an aggregate `pool <available>/<total>` chip for round-robin pools, and a `→` on the current
selection; an active temporary override labels the member list suspended because it bypasses selection.

When the same name appears in both maps, `model_aliases.custom` wins. `sase doctor -C config.model_aliases` warns about
legacy flat keys in `model_aliases`, removed top-level `custom_model_aliases`, custom names under
`model_aliases.builtin`, builtin names under `model_aliases.custom`, collisions between the two maps, missing custom
descriptions/models, dangling `@alias` references, empty or mixed selectors, and nested selectors. Unavailable selector
providers are reported as informational notes; for an ordered fallback the note also identifies the current winner. In
ACE, the Models panel shows descriptions from config; a user alias without one shows the
`llm_provider.model_aliases.custom.<name>.description` path to fix.

The same alias vocabulary appears in the `%model:` / `%m:` completion menu in ACE and in editors through the xprompt
LSP: alias rows sit beneath the concrete model names with their kind, resolved `PROVIDER(model)` target, and provenance,
and typing `@` right after the colon narrows the menu to aliases only. See [xprompt directive syntax](xprompt.md#syntax)
for the row anatomy. The completion menu is read-only; the ACE Models panel (`,m`) remains the authoritative place to
edit alias targets and to set or clear temporary overrides.

The ACE Models panel supplies two built-in buckets without changing resolution, completion, launch routing, or config
paths. `coders` folds together `@coder` and all registered `@<provider>_coder` aliases; `phase_worker` folds together
the five `@<size>_phase_worker` aliases. A collapsed bucket summarizes its effective-model mix and active overrides;
opening it exposes independently editable aliases. Optional `model_aliases.buckets.<bucket>.description` metadata
replaces either built-in description, and a custom alias tagged with `bucket: coders` or `bucket: phase_worker`
coalesces into that display bucket.

A bare `%model` token that is _not_ a configured alias, an explicit `provider/model` target, or a known provider model
silently falls back to the default provider rather than erroring. To catch this drift — for example a removed
`model_aliases` entry that quietly reroutes a `#m_<provider>_*` preset to the default provider — `sase doctor`
(`-C config.model_xprompts`) scans configured model presets and warns with
`<xprompt> -> <token> does not resolve to a provider; it will fall back to the default provider`. The check is
provider-neutral and read-only.

#### Implicit role aliases

On top of any aliases you configure, SASE always exposes a fixed set of **implicit role aliases** that resolve even when
you have not defined them. Most fall back through other aliases to `@default`; `@smartest` and `@cheapest` own ordered
provider fallbacks, while `@cheap` and `@cheaper` own independent built-in pools:

| Alias                  | Role                                                                                                    | Fallback when not configured                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `@default`             | Model used when a prompt has no `%model` directive.                                                     | Configured `model_aliases.builtin.default`, else the provider's requested-tier default. |
| `@coder`               | Coder follow-up launched from an accepted plan.                                                         | `@default`                                                                              |
| `@<provider>_coder`    | Coder follow-up for a plan authored by `<provider>` (`@claude_coder`, `@codex_coder`, `@agy_coder`, …). | `@coder`                                                                                |
| `@epic_lander`         | Epic land agent with no explicit land model.                                                            | `@default`                                                                              |
| `@big_epic_lander`     | Epic land agent selected when the authored phase count meets the configured threshold.                  | `@smartest`                                                                             |
| `@xsmall_phase_worker` | Extra-small bead phase agent with no explicit per-bead model.                                           | `@cheaper`                                                                              |
| `@small_phase_worker`  | Small bead phase agent with no explicit per-bead model.                                                 | `@cheap`                                                                                |
| `@medium_phase_worker` | Medium bead phase agent with no explicit per-bead model.                                                | `@default@high`                                                                         |
| `@large_phase_worker`  | Large bead phase agent with no explicit per-bead model.                                                 | `@smart`                                                                                |
| `@xlarge_phase_worker` | Extra-large bead phase agent with no explicit per-bead model.                                           | `@smartest`                                                                             |
| `@smart`               | High-capability model selected automatically for large phases.                                          | `@default`                                                                              |
| `@smartest`            | Highest-capability model selected automatically for xlarge phases and threshold-sized epic landers.     | `claude/claude-fable-5 \|\| codex/gpt-5.6-sol`                                          |
| `@cheap`               | Load-balanced pool selected automatically for small phase agents.                                       | `claude/opus@medium \| codex/gpt-5.5`                                                   |
| `@cheaper`             | Lower-cost load-balanced pool selected automatically for extra-small phase agents.                      | `claude/sonnet \| codex/gpt-5.3-codex-spark`                                            |
| `@cheapest`            | Lowest-cost provider fallback available for explicit use.                                               | `claude/haiku \|\| codex/gpt-5.3-codex-spark`                                           |

Override any role by configuring an alias of the same name. A common setup routes coder follow-ups to a second provider
while normal epic landers track `@default`. Threshold-selected epic landers deliberately diverge through
`@big_epic_lander` → `@smartest`, so an `epic_lander` override affects only below-threshold epics; configure
`big_epic_lander` directly to replace the large-epic policy. Phase sizes likewise diverge: xsmall uses `@cheaper`, small
uses `@cheap`, medium uses `@default@high`, large uses `@smart`, and xlarge uses `@smartest`. The implicit `@smartest`
value prefers Claude Fable 5 whenever the Claude CLI is installed and otherwise selects Codex GPT-5.6 SOL; a configured
or temporary override bypasses that fallback. The standalone `@cheapest` fallback has no automatic consumer and is
available for explicit launches:

```yaml
llm_provider:
  model_aliases:
    builtin:
      default: opus
      claude_coder: codex/gpt-5.6-sol # Claude-authored plans hand coding to Codex
      codex_coder: claude/opus # Codex-authored plans hand coding to Claude
      big_epic_lander: codex/gpt-5.6-sol # large epic land agents only
      cheap: claude/opus@medium | codex/gpt-5.5
      cheaper: claude/sonnet | codex/gpt-5.3-codex-spark
      cheapest: claude/haiku || codex/gpt-5.3-codex-spark
      medium_phase_worker: "@default@high"
      xsmall_phase_worker: "@cheaper"
      small_phase_worker: "@cheap"
      large_phase_worker: "@smart"
      xlarge_phase_worker: "@smartest"
      smartest: claude/claude-fable-5 || codex/gpt-5.6-sol
```

#### Launch-scoped alias overrides

A prompt can override these aliases for its SASE-created launch lineage with keyword arguments on `%model(...)`:

```text
%model(opus, coder=codex/gpt-5.6-sol)
%model(medium_phase_worker=claude/sonnet)
```

The positional value, when present, selects the current agent's model. Without one, the current agent starts from the
normal default and resolves that alias chain through the map. Thus `default=...` changes it directly, while an unrelated
role keyword normally affects only a later delegated launch. Keyword keys are bare known alias names, and values may be
concrete model targets or `@other_alias` references. The map is stored in agent metadata and inherited by SASE-created
plan/coder follow-ups. An explicit `%id(suffix, family=parent)` attachment inherits it only when the attached prompt
supplies no alias keywords. Ordinary nested launches do not inherit it. This is a propagation rule, not a change to
`sase.yml` or `~/.sase/llm_override.json`.

Launch-scoped values have the highest alias-resolution precedence. They beat machine-wide per-alias temporary overrides
and configured/implicit aliases at every hop; a launch-scoped `default` also beats the machine-wide temporary default.
An explicit concrete model for the current agent remains concrete, while an explicit alias is resolved through this
launch map. See [Launch-Scoped Model Alias Overrides](xprompt.md#launch-scoped-model-alias-overrides) for syntax and
validation rules.

> **Migration note:** the previously reserved `@worker` and `@other` aliases were removed (epic sase-5d). Route
> delegated work through `@coder`, a size-specific phase alias, or an explicit model instead of `@worker`, and use
> `@default` instead of `@other`. `@phase_worker` is no longer builtin; move a stale builtin override to
> `medium_phase_worker` or define it deliberately under `model_aliases.custom`. `@epic_creator` is retired outright —
> SASE no longer launches an epic-creator role, so delete the entry rather than repointing it. `sase doctor` flags stale
> config and names the replacement for each retired alias.

### Explicit Provider/Model Syntax

Use `provider/model` to specify both explicitly:

```
%model:codex/o3
%model:claude/opus
%model("agy/Gemini 3.5 Flash (High)")
%model:qwen/qwen3.6-plus
%model:opencode/anthropic/claude-sonnet-4-5
%model:fakey/fakey-large
```

### Automatic Provider Resolution

Known model names are automatically mapped to their provider:

| Model Name                                                                                                                                                                                                               | Provider |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| `opus`, `sonnet`, `haiku`, `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5`                                                                                                                      | claude   |
| `gpt-5.6-sol`, `gpt-5.5`, `gpt-5.3-codex`, `codex-mini-latest`, `o3`, `o4-mini`, `gpt-5.4`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`                                                                           | codex    |
| `Gemini 3.5 Flash (High)`, `Gemini 3.5 Flash (Medium)`, `Gemini 3.5 Flash (Low)`, `Gemini 3.1 Pro (High)`, `Gemini 3.1 Pro (Low)`, `Claude Sonnet 4.6 (Thinking)`, `Claude Opus 4.6 (Thinking)`, `GPT-OSS 120B (Medium)` | agy      |
| `qwen3.6-plus`, `qwen3-coder-plus`, `qwen3-coder-flash`, `qwen3-max`, `qwen-plus`, `qwen-max`                                                                                                                            | qwen     |
| `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`, `openai/gpt-5`, `openai/gpt-5-mini`, `google/gemini-3-flash-preview`, `qwen/qwen3-coder-plus`                                                                | opencode |
| `fakey-large`, `fakey-small`                                                                                                                                                                                             | fakey    |

Each installed plugin contributes its own model names via the `llm_known_model_names()` hook.

For unrecognized model names, the prompt falls back to the default provider and a warning is logged at invocation time.

Source: `src/sase/llm_provider/registry.py`, `src/sase/llm_provider/_invoke.py`

### Model Short Aliases

Providers also declare compact display shorthands for long model ids via the `llm_model_short_aliases()` hook. These
shorthands appear in [provider/model agent-name suffixes](ace.md#providermodel-suffixes) on the Agents tab and act as
filter terms in the coder model picker. They are display-only: `%model` resolution uses known model names and
[configured model aliases](#configured-model-aliases), not these shorthands. For example, `%model:fable` does _not_
select `claude-fable-5` — it falls back to the default provider (with a warning) unless you define `fable` as a
configured model alias yourself.

| Provider | Shorthands                                                                                                                                                                                                                                                                                                                     |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| claude   | `claude-opus-5` → `opus5`, `claude-sonnet-5` → `sonnet5`, `claude-haiku-4-5` → `haiku45`, `claude-fable-5` → `fable`                                                                                                                                                                                                           |
| codex    | `codex-mini-latest` → `mini`, `gpt-5.6-sol` → `gpt56sol`, `gpt-5.5` → `gpt55`, `gpt-5.4` → `gpt54`, `gpt-5.3-codex` → `gpt53`, `gpt-4.1` → `gpt41`, `gpt-4.1-mini` → `gpt41m`, `gpt-4o-mini` → `gpt4om`                                                                                                                        |
| agy      | `Gemini 3.5 Flash (High)` → `flash35h`, `Gemini 3.5 Flash (Medium)` → `flash35m`, `Gemini 3.5 Flash (Low)` → `flash35l`, `Gemini 3.1 Pro (High)` → `pro31h`, `Gemini 3.1 Pro (Low)` → `pro31l`, `Claude Sonnet 4.6 (Thinking)` → `sonnet46t`, `Claude Opus 4.6 (Thinking)` → `opus46t`, `GPT-OSS 120B (Medium)` → `gptoss120m` |
| qwen     | `qwen3.6-plus` → `qwen36p`, `qwen3-coder-plus` → `qwen3cp`, `qwen3-coder-flash` → `qwen3cf`                                                                                                                                                                                                                                    |
| opencode | `anthropic/claude-sonnet-4-5` → `sonnet45`, `anthropic/claude-opus-4-5` → `opus45`, `openai/gpt-5` → `gpt5`, `openai/gpt-5-mini` → `gpt5m`, `google/gemini-3-flash-preview` → `flash3`, `qwen/qwen3-coder-plus` → `qwen3cp`                                                                                                    |
| fakey    | `fakey-large` → `fakeyl`, `fakey-small` → `fakeys`                                                                                                                                                                                                                                                                             |

Source: `llm_model_short_aliases()` in each provider module under `src/sase/llm_provider/`

## Reasoning Effort

A prompt can request a reasoning-effort level for its agent, and a config default can apply one to every launch. The
public surface spells it `effort`; the threaded/stored field is named `reasoning_effort` everywhere internally.

### Requesting an Effort

There are five ways an effort reaches a launch, in precedence order:

1. An explicit per-prompt `%effort:<level>` directive, or the `@<level>` suffix on a `%model`/alias reference
   (`%model:opus@xhigh`, `%model:@default@medium`). See [Effort Directive](xprompt.md#effort-directive) for the
   directive syntax and per-branch fan-out (`%{%m:opus@xhigh | %m:sonnet@low}`).
2. A trailing effort on the selected alias target, temporary model override, or pool member (for example
   `claude/opus@medium`). An outer alias-reference suffix wins over effort carried by the alias target.
3. An active machine-wide temporary default-effort override from `~/.sase/llm_effort_override.json`.
4. The `llm_provider.default_effort` config value, applied when none of the higher-precedence sources sets effort.
5. Nothing — the provider runs at its own built-in default.

The canonical effort vocabulary, ordered least → most, is `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
Spelling is validated globally; _which_ levels a given provider honors is decided per provider (below).

The ACE Models panel shows the launch-effective default in its header (`default effort: @ <level>`), or says
`provider default` when none is configured. An active temporary value carries an override countdown plus an annotation
for the underlying configured value. Alias-borne effort appears only on rows that explicitly pin or inherit a suffix,
beside the provider/model badge; the description strip compares it with the current effective default. For pools, each
member keeps its own suffix in the member list and the row badge reflects the next selected member.

Press `Ctrl+E` in the Models panel for the global default-effort workflow. `e` opens a permanent Edit and `o` opens a
temporary Override; when an override is active, `x` clears it. Both paths use the canonical single-key ladder (`1`
`none` through `7` `max`). Edit additionally offers `0` Provider default and writes the empty sentinel to the user-base
`sase.yml` after a source-preserving preview. With `use_chezmoi`, the preview names and writes the chezmoi source,
applies its home target, and offers the standard tracked commit/pull/push flow when that source is dirty in Git.

Temporary Override reuses the full alias duration UI: `15m`, `30m`, `1h`, `2h`, `4h`, Until cleared, combined custom
durations, and `t` for an exact configured-timezone end. The versioned `~/.sase/llm_effort_override.json` record
contains `effort`, `created_at`, optional `expires_at`, and `source`. Writes are atomically replaced under a bounded
advisory lock; malformed and expired state self-cleans, with `now >= expires_at` considered expired. A permanent edit
does not displace an active temporary override, and neither kind of change mutates already-running agents.

### Explicit vs. Default Semantics

The distinction between an explicitly requested effort and a config-default effort governs what happens on a provider
that cannot honor the requested level:

- **Explicit** (`%effort`/`@effort`): an unsupported level raises an error — SASE never silently launches at a different
  effort than you asked for.
- **Config-derived** (an alias-target suffix, temporary default override, or `llm_provider.default_effort`):
  best-effort. Unsupported levels are logged and skipped so shared configuration never breaks an `agy`/`qwen` run.

### Provider Support Matrix

| Provider            | Mechanism                             | Supported levels                  | Rejected      |
| ------------------- | ------------------------------------- | --------------------------------- | ------------- |
| Claude              | `--effort <level>`                    | low, medium, high, xhigh, max     | none, minimal |
| Codex               | `-c model_reasoning_effort="<level>"` | minimal, low, medium, high, xhigh | none, max     |
| OpenCode            | `--variant <level>`                   | all (validated by OpenCode/model) | —             |
| Antigravity (`agy`) | none today                            | —                                 | all           |
| Qwen                | none today                            | —                                 | all           |
| Fakey               | `--effort <level>`                    | all                               | —             |

For `agy` and `qwen` (no reasoning-effort mechanism today), every level is "unsupported": an explicit effort raises,
while a config-default effort is skipped with a warning. The effort args are appended alongside the existing
[`SASE_LLM_*_ARGS` / `SASE_<P>_LARGE_ARGS`](#environment-variables) escape hatches, which remain available.

Source: `src/sase/xprompt/effort.py` (vocabulary + `split_model_effort`), `src/sase/llm_provider/config.py`
(`resolve_effective_effort`, the temporary-effort facade, and the public `default_reasoning_effort` config reader),
`src/sase/llm_provider/_effort_args.py` (per-provider translation).

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

## Role Aliases for Delegated Work

Delegated launches do not use a separate "worker lane". Instead, each delegated role resolves through an
[implicit role alias](#implicit-role-aliases):

- **Coder follow-ups** from an accepted plan use `@<provider>_coder` for the planner's provider (for example
  `@claude_coder`), falling back to `@coder` and then `@default`.
- **`sase bead work` phase agents** without an explicit per-bead model use the alias matching their normalized size:
  `@xsmall_phase_worker`, `@small_phase_worker`, `@medium_phase_worker`, `@large_phase_worker`, or
  `@xlarge_phase_worker`. Their defaults are respectively `@cheaper`, `@cheap`, `@default@high`, `@smart`, and
  `@smartest`. `xsmall`, `small`, and `medium` phases implement directly; only `large` and `xlarge` phases receive
  `#plan`. An explicit per-bead model is accepted at every size and always wins without changing the size-based planning
  policy.
- **Epic land agents** without an explicit land model use `@epic_lander`, or `@big_epic_lander` when their authored
  phase count meets `bead.big_epic_phase_threshold` (default `5`). Normal landers fall back to `@default`; the
  threshold-selected alias falls back independently to provider-aware `@smartest`.

Validated Epic approvals create beads and launch `sase bead work` directly; there is no epic-creator model lane.

Planning agents stay on `@default` unless their prompt explicitly asks for a different model. To send delegated work to
a second provider, configure the matching role alias under `llm_provider.model_aliases.builtin`:

```yaml
llm_provider:
  provider: claude
  model_aliases:
    builtin:
      default: opus
      claude_coder: codex/gpt-5.6-sol # Claude-authored plans hand coding to Codex
      codex_coder: claude/opus # Codex-authored plans hand coding to Claude
      cheap: claude/opus@medium | codex/gpt-5.5
      cheaper: claude/sonnet | codex/gpt-5.3-codex-spark
      cheapest: claude/haiku || codex/gpt-5.3-codex-spark
      medium_phase_worker: codex/gpt-5.6-sol@high # explicitly route medium phases to Codex
      smartest: claude/claude-fable-5 || codex/gpt-5.6-sol # xlarge phase/epic fallback
      big_epic_lander: codex/gpt-5.6-sol # threshold-selected epic landers run on Codex
```

Normal epic landers fall back to `@default`; xsmall phases use the `@cheaper` pool, small phases the `@cheap` pool,
medium phases `@default@high`, large phases `@smart`, and xlarge phases and threshold-selected epic landers `@smartest`.
Explicit `%model` directives, approval-picker model choices, direct alias overrides, and per-bead/land model metadata
always win over role defaults.

> The previous `llm_provider.worker_models` map and the `~/.sase/llm_worker_override.json` worker temporary override
> were removed in epic sase-5d. See the [migration note](#implicit-role-aliases) above.

## Temporary Model Overrides

In addition to prompt-level [launch-scoped overrides](#launch-scoped-alias-overrides) and the tier-based global
override, sase supports **concrete** provider/model overrides that act as temporary, time-bound machine-wide overrides
of a model alias. The ACE `,m` chord opens the [**Models** panel](ace.md#models-panel) for setting, changing, and
clearing these overrides — for the `default` alias or any role/user alias.

The panel also shows a two-line description for the highlighted alias or bucket. Builtin aliases have fixed
descriptions, custom aliases read `llm_provider.model_aliases.custom.<name>.description`, selector aliases list each
member, its current availability, and the current selection, and the built-in `coders` and `phase_worker` buckets report
their aggregate effective-model-and-effort mix and active override count. The title shows the launch-effective default
effort and current effective `max_running_agents` cap; active temporary values include their remaining time and
configured provenance. Non-pool aliases that explicitly carry an effort explain its provenance on the second description
line.

Overrides are **per-alias** and independent. An override takes effect wherever that alias is resolved, including a
`default` override at every direct or nested `@default` hop. For example, an override on `@medium_phase_worker` affects
only that size alias. Active overrides on selector-owning aliases such as `@smartest`, `@cheap`, `@cheaper`, and
`@cheapest` suspend their ordered fallback or independent rotation for the override's duration. Those selectors pin
concrete targets rather than referencing `@default`, so a `default` override does not move them or their dependent size
lanes; override the selector-owning or size alias itself to move one of those lanes. Machine-wide temporary overrides do
not change:

- Already-running agents — they keep whatever provider/model they were launched with.
- Explicit concrete `%model` prompt targets — they still take precedence. A `%model(...)` alias keyword is a separate,
  higher-precedence launch-scoped override.
- An explicit `provider_name=` argument to `invoke_agent()` — it still wins.

An override may carry a canonical reasoning-effort suffix, such as `codex/gpt-5.6-sol@medium` or `@coder@medium`. The
write resolves and snapshots the clean provider/model plus `medium`, while preserving the original `raw_model`. That
effort survives state reloads and shapes the next matching launch. An explicit outer reference such as `@coder@xhigh`
still wins over the stored override effort.

`SASE_MODEL_TIER_OVERRIDE` / `SASE_MODEL_SIZE_OVERRIDE` still force the tier for tier-based launches. A concrete
temporary override supplies a provider and model directly, so it is used only when no explicit model/provider was
requested.

### Resolution Order (default provider/model)

When no positional `%model` target and no explicit `provider_name` are present, the default is resolved as:

1. A launch-scoped `default` alias override from `%model(default=...)`, when present.
2. **Active machine-wide `default` temporary override** at `~/.sase/llm_override.json` (if not expired).
3. The configured `@default` alias, otherwise the configured/autodetected provider's requested-tier model.

For every alias, including `default`, `resolve_model_alias()` consults the launch-scoped map first, then that alias's
active machine-wide override, then its configured/implicit value. The implicit `default` value is the configured or
autodetected provider's requested-tier model. This order applies at every nested alias hop. A launch-scoped generic
`coder` value also applies at a provider-specific `<provider>_coder` hop unless the launch map supplies that
more-specific key.

A concrete temporary override sets both the default provider and a concrete `model_override` for the next launch — so
the agent metadata (running marker, plan review badge, agent rows) reflects the actual model that will run, not just the
configured default.

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

A legacy **v1** file (a single flat override object with top-level `provider` / `model` / ... keys) is migrated on read
into `overrides.default`, so an override set by an older build keeps working after upgrade. Existing v2 entries without
`effort` remain valid and are read as `effort: null`.

Writes are atomic (temp file + `os.replace`). Reads are best-effort self-cleaning: expired or unparseable entries are
pruned and the file is deleted once no override remains, so a forgotten override never lingers past its `expires_at`,
even with no TUI running.

Relative and exact-expiry writes use the same provider/model resolution and atomic v2 serialization path. Exact-expiry
writes persist the caller's Unix timestamp unchanged and reject non-finite or no-longer-future targets. The state schema
is unchanged; an exact target is represented by the same `expires_at` field.

### Model Resolution

The user-supplied `raw_model` is normalized through the same rules as `%model`:

- `provider/model` selects the provider explicitly (e.g. `codex/o3` or `opencode/anthropic/claude-sonnet-4-5`).
- A bare known model name infers its provider from plugin metadata (e.g. `sonnet` → claude).
- An unknown bare model is accepted and runs on the current default provider, matching `%model` behavior.
- A known trailing effort is split into the entry's `effort` field. Unknown trailing `@token` text remains part of the
  model identifier, and `@alias@effort` resolves the alias eagerly while retaining the raw reference for display.

### Duration Parsing

Durations accept compact unit suffixes: `15m`, `1h`, `1h30m`, `90m`, `2h15m30s`. Bare integers are interpreted as
minutes (`45` → 45 minutes). The case-insensitive sentinel `until cleared` (or `until_cleared`) means "no expiry —
persists until the user clears it from the TUI or another sase process clears the state file."

### Public API

The override primitives live in `src/sase/llm_provider/temporary_override.py`. The alias-keyed functions are the primary
API; the `*_temporary_override` wrappers are back-compat shims that operate on the `default` alias:

| Function                                                | Purpose                                                                        |
| ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `get_active_alias_overrides(now=None)`                  | Read every active override, keyed by alias (auto-prunes expired/malformed).    |
| `get_active_alias_override(alias, now=None)`            | Read the active override for one alias, or `None`.                             |
| `set_alias_override(alias, raw, dur, source=)`          | Set/replace one alias's relative/no-expiry override.                           |
| `set_alias_override_until(alias, raw, expiry, source=)` | Set/replace one alias's override with an exact future Unix expiry.             |
| `clear_alias_override(alias)`                           | Remove one alias's override; returns whether an entry was present.             |
| `get_active_temporary_override(now=None)`               | Back-compat wrapper: the active `default` override.                            |
| `set_temporary_override(raw, dur, source=)`             | Back-compat wrapper: set the `default` override.                               |
| `clear_temporary_override()`                            | Back-compat wrapper: clear the `default` override.                             |
| `parse_override_duration(value)`                        | Parse a user-facing duration string into seconds (or `None`).                  |
| `resolve_effective_default_provider_model()`            | Resolve the default launch target: active override, else the `@default` alias. |

### Examples

- Models panel (`,m`), highlight `default`, `o`, pick `codex/o3`, duration `1h` → `~/.sase/llm_override.json` gains a
  `default` entry; new launches default to CODEX(o3) for the next hour.
- Models panel, open `phase_worker`, highlight `medium_phase_worker`, `o`, pick `opencode/anthropic/claude-sonnet-4-5`,
  `Until cleared` → medium phases without an explicit model inherit that target until cleared.
- Models panel, highlight `default`, `o`, pick `sonnet`, duration `30m` → known bare model; provider resolves to claude
  via plugin metadata.
- Models panel, highlight an alias, `x` → that alias's override is cleared; when the last override is removed the state
  file is deleted and defaults revert to permanent config / autodetect.

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

`SASE_LLM_EXEC_PROVIDER` must name a registered provider. It changes subprocess dispatch and execution-provider retry
policy only; agent, step, and chat metadata continue to show the provider and model the user requested. Run artifacts
record the dispatched provider separately as `exec_llm_provider`.

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

Retry defaults can come from two places: configured policy under `llm_provider.retry` and provider-supplied defaults
from the `llm_default_retry_config()` hook. The bundled `default_config.yml` already provides configured policy for
Claude and Codex; user config can replace or extend it through the normal config merge.

**Claude:**

- **max_retries**: 3
- **error_patterns**: `["API Error: 500", "API Error: 529", "Internal server error", "overloaded_error"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"sonnet"`

**Codex:**

- **max_retries**: 3
- **error_patterns**:
  `["exceeded retry limit", "429 Too Many Requests", "Too Many Requests", "rate limit", "failed to connect to websocket", "Selected model is at capacity"]`
  — the Codex CLI's own give-up message, terminal rate-limit and model-capacity statuses, and the transient websocket
  transport error. A bare `403 Forbidden` is deliberately excluded so a persistent auth failure is not retried forever.
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min) — rate limits need a real cool-down

### Provider-Supplied Retry Defaults

Providers can also declare retry defaults through the `llm_default_retry_config()` hook. Both Claude and Codex declare a
recovery entry that is merged with their configured policy.

Claude:

- **error patterns**: `"Prompt is too long"`, `"socket connection was closed unexpectedly"`, and `"API Error"`
- **max_retries**: 3
- **wait_times**: `[0]` — used only when no config layer supplies `wait_times`; the bundled Claude policy supplies
  `[60, 300, 1800]`, so that is the out-of-the-box backoff
- **continuation_prompt**: A short nudge that tells the coder to inspect `git status` / `git diff` before resuming,
  since prior edits are preserved on disk after a context-limit, socket-close, or API-error retry
- **preserve_workspace**: `true`

Codex:

- **error patterns**: `"exceeded retry limit"`, `"429 Too Many Requests"`, `"Too Many Requests"`, `"rate limit"`, and
  `"failed to connect to websocket"`, and `"Selected model is at capacity"` — the transient transport, rate-limit, and
  model-capacity failure modes where the Codex CLI exhausts its own internal reconnects or exits non-zero
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` — the bundled Codex policy supplies the same backoff
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude
- **preserve_workspace**: `true`

Fakey:

- **error pattern**: `"FAKEY-RETRYABLE"`, the canonical marker emitted by retryable fakey scenarios
- **max_retries**: 3
- **wait_times**: `[0]`, keeping deterministic test retries fast
- **continuation_prompt**: The same resume nudge as Claude and Codex
- **preserve_workspace**: `true`

These defaults make `@flaky` and other retryable fakey scenarios exercise the retry pipeline without user config. A
commented `llm_provider.retry.fakey` example in the default config shows how to override them.

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

If any retries occurred or a fallback model was used, retry metadata is written to `done.json` in the agent's artifacts
directory after execution completes (runs that succeed on the first attempt omit these fields):

```json
{
  "retry_count": 2,
  "retry_errors": ["An unexpected critical error occurred: ..."],
  "used_fallback": false
}
```

When `used_fallback` is `true`, the metadata also includes the `fallback_model` that served the final attempt.

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/axe/run_agent_exec_finalize.py`

### Spawn-on-Retry

When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh detached child agent (as if `sase run`
had been invoked) instead of running the next attempt in-process. The failing parent transfers its workspace claim to
the child via `transfer_workspace_claim()` and exits with status `FAILED (RETRIED)`. This trades the small cost of a
fresh process for two benefits:

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

When telemetry is enabled, token counts are recorded as local debugging counters (`sase_llm_input_tokens_total`,
`sase_llm_output_tokens_total`, `sase_llm_cache_read_tokens_total`). See [docs/telemetry.md](telemetry.md) for the full
telemetry reference.

Source: `src/sase/llm_provider/_subprocess.py`, `src/sase/llm_provider/types.py`

## Prompt Preprocessing Pipeline

Before any prompt reaches a provider, it passes through the shared preprocessing pipeline defined in `preprocessing.py`.
The pipeline has an early phase used for xprompt expansion and directive extraction, then a late phase used for command,
file, template, and formatting work.

### Steps

| Phase | Step                       | Syntax                                     | Description                                              |
| ----- | -------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| Early | Optional workflow Jinja2   | `{{ var }}`                                | Render workflow-supplied template context before xprompt |
| Early | xprompt references         | `#name`                                    | Expand reusable prompt snippets or workflows             |
| Early | Prompt directives          | `%model`, `%m`, other `%...` directives    | Extract directives after xprompt expansion               |
| Late  | Disabled/fenced protection | `%xprompts_enabled:false`, fenced code     | Protect regions that should not be rewritten             |
| Late  | Command substitution       | `$(cmd)`                                   | Execute shell commands and inline their output           |
| Late  | File references            | `@path`                                    | Process, validate, or skip file references               |
| Late  | Top-level Jinja2           | `{{ var }}`                                | Render remaining top-level Jinja2 templates              |
| Late  | Prettier formatting        | -                                          | Format with prettier for consistent markdown             |
| Late  | Comment stripping          | `<!-- ... -->`                             | Remove HTML/markdown comments                            |
| Late  | Restore protected regions  | fenced code / disabled-region placeholders | Restore protected content after rewrites                 |

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
- **`file_references`**: `process_command_substitution()`, `process_file_references()`, `validate_file_references()`,
  `format_with_prettier()`, `strip_html_comments()`

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

Providers that support richer streams may write sidecar artifacts. Codex writes reasoning summaries to
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

Resume uses the `#fork` and `#fork_by_chat` workflows through normal detached `sase run` launches. `#fork` resolves an
agent name to its artifacts directory, extracts the response path from `done.json`, and delegates to `#fork_by_chat`,
which loads the chat history and prepends it to the new conversation. Use `#fork_by_chat(<path-or-basename>)` for direct
chat-file-based resumption.

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

On success, returns an `AIMessage` (from `langchain_core.messages`) whose `content` is the provider response. On
provider failure, `invoke_agent()` logs the error and raises `LLMInvocationError` with the formatted error text.
