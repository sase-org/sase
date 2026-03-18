# LLM Provider Integration

This document describes the LLM provider abstraction layer in sase. The system supports pluggable LLM backends
(currently Claude Code, Codex, and Gemini CLI) behind a shared orchestration layer that handles preprocessing,
invocation, and postprocessing.

## Table of Contents

- [Overview](#overview)
- [Provider Architecture](#provider-architecture)
- [Claude Code Integration](#claude-code-integration)
- [Gemini CLI Integration](#gemini-cli-integration)
- [Codex CLI Integration](#codex-cli-integration)
- [Configuration](#configuration)
- [Model Tier System](#model-tier-system)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)
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

### Source Layout

| File                                      | Purpose                             |
| ----------------------------------------- | ----------------------------------- |
| `src/sase/llm_provider/__init__.py`       | Public API exports                  |
| `src/sase/llm_provider/base.py`           | `LLMProvider` abstract base class   |
| `src/sase/llm_provider/claude.py`         | Claude Code provider implementation |
| `src/sase/llm_provider/gemini.py`         | Gemini CLI provider implementation  |
| `src/sase/llm_provider/registry.py`       | Provider registration and lookup    |
| `src/sase/llm_provider/config.py`         | Config file reader (`sase.yml`)     |
| `src/sase/llm_provider/types.py`          | `ModelTier`, `LoggingContext` types |
| `src/sase/llm_provider/_invoke.py`        | `invoke_agent()` orchestrator       |
| `src/sase/llm_provider/_subprocess.py`    | `stream_process_output()`           |
| `src/sase/llm_provider/codex.py`          | Codex CLI provider implementation   |
| `src/sase/llm_provider/_plan_utils.py`    | Shared plan utilities               |
| `src/sase/llm_provider/preprocessing.py`  | 6-step preprocessing pipeline       |
| `src/sase/llm_provider/postprocessing.py` | Logging, chat history, audio        |

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
    ) -> str: ...
```

| Parameter         | Type        | Description                                  |
| ----------------- | ----------- | -------------------------------------------- |
| `prompt`          | `str`       | Already-preprocessed prompt text             |
| `model_tier`      | `ModelTier` | `"large"` or `"small"`                       |
| `suppress_output` | `bool`      | If `True`, suppress real-time console output |

Returns the raw response text. Raises `subprocess.CalledProcessError` on failure.

### Registry

Providers are registered by name in a global registry (`registry.py`). Built-in providers are auto-registered on module
import:

```python
register_provider("claude", ClaudeCodeProvider)
register_provider("codex", CodexProvider)
register_provider("gemini", GeminiProvider)
```

To get a provider instance:

```python
provider = get_provider()          # Uses default from config
provider = get_provider("claude")  # Explicit provider name
```

### Selection Logic

1. If `provider_name` is passed to `invoke_agent()`, use that.
2. Otherwise, read the `llm_provider.provider` field from `~/.config/sase/sase.yml`.
3. If no config exists (or provider is empty), auto-detect: prefer `claude` if available on PATH, then `codex`, fall
   back to `"gemini"`.

## Claude Code Integration

The `ClaudeCodeProvider` invokes the `claude` CLI tool.

### Command Construction

```
claude -p --model <alias> --output-format text --dangerously-skip-permissions [extra_args...]
```

The prompt is written to stdin, and output is streamed from stdout in real-time.

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

## Gemini CLI Integration

The `GeminiProvider` invokes Google's internal Gemini CLI tool.

### Command Construction

```
gemini --yolo [extra_args...]
```

The prompt is written to stdin, and output is streamed from stdout in real-time.

### Default Model

The Gemini provider uses `gemini-3-flash-preview` as its default model. This can be overridden per-prompt using the
`%model` directive (e.g., `%model:gemini-2.5-flash`).

### Environment Variables

| Variable           | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `SASE_GEMINI_PATH` | Path to the Gemini CLI binary (default: `"gemini"`). |

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
| `large` | `gpt-5.3-codex`     |
| `small` | `codex-mini-latest` |

### Plan Mode

When `SASE_AGENT_PLAN_MODE` is set, Codex runs a two-phase plan/implement flow:

1. **Phase 1 (Planning)**: Runs with `--sandbox read-only` and `--ask-for-approval on-request`. The model generates a
   plan captured via `--output-last-message`, on-disk plan files, or streamed response text.
2. **Approval**: The plan is presented for user approval with up to 5 feedback-retry rounds.
3. **Phase 2 (Implementation)**: On approval, runs with full permissions (`--dangerously-bypass-approvals-and-sandbox`)
   using the plan content as the prompt.

### Environment Variables

| Variable                | Description                                               |
| ----------------------- | --------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`   | Extra CLI args for `large` tier (generic, preferred)      |
| `SASE_LLM_SMALL_ARGS`   | Extra CLI args for `small` tier (generic, preferred)      |
| `SASE_CODEX_LARGE_ARGS` | Extra CLI args for `large` tier (Codex-specific fallback) |
| `SASE_CODEX_SMALL_ARGS` | Extra CLI args for `small` tier (Codex-specific fallback) |
| `SASE_AGENT_PLAN_MODE`  | Enable two-phase plan/implement flow                      |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_CODEX_*_ARGS`.

### Timer Display

While waiting for a response, a `gemini_timer("Waiting for Codex")` spinner is shown (unless `suppress_output` is
`True`). In plan mode, the timer reads "Waiting for Codex (planning)" during Phase 1 and "Implementing plan" during
Phase 2.

## Configuration

The LLM provider reads its configuration from `~/.config/sase/sase.yml` under the `llm_provider` key.

### Config File

```yaml
llm_provider:
  provider: claude # or "gemini" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
```

### Config Fields

| Field                               | Type   | Default     | Description                                                                                 |
| ----------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------- |
| `llm_provider.provider`             | string | auto-detect | Which registered provider to use. Auto-detects: claude if on PATH, then codex, then gemini. |
| `llm_provider.model_tier_map.large` | string | -           | Model identifier for the `large` tier                                                       |
| `llm_provider.model_tier_map.small` | string | -           | Model identifier for the `small` tier                                                       |

## Per-Prompt Provider Switching

The `%model` directive (see [xprompt directives](xprompt.md#directives)) can switch both the model and the LLM provider
for a single prompt. Provider resolution uses two strategies:

### Explicit Provider/Model Syntax

Use `provider/model` to specify both explicitly:

```
%model:codex/o3
%model:claude/opus
%model:gemini/gemini-2.5-pro
```

### Automatic Provider Resolution

Known model names are automatically mapped to their provider:

| Model Name                                                                                                           | Provider |
| -------------------------------------------------------------------------------------------------------------------- | -------- |
| `opus`, `sonnet`, `haiku`                                                                                            | claude   |
| `gpt-5.3-codex`, `codex-mini-latest`, `o3`, `o4-mini`, `gpt-5.4`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini` | codex    |
| `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-2.0-flash`         | gemini   |

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

| Variable                | Description                                |
| ----------------------- | ------------------------------------------ |
| `SASE_CODEX_LARGE_ARGS` | Codex-specific extra args for `large` tier |
| `SASE_CODEX_SMALL_ARGS` | Codex-specific extra args for `small` tier |
| `SASE_AGENT_PLAN_MODE`  | Enable Codex two-phase plan/implement flow |

### Gemini-Specific

| Variable           | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `SASE_GEMINI_PATH` | Path to the Gemini CLI binary (default: `"gemini"`). |

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

| Field            | Type      | Default | Description                                                              |
| ---------------- | --------- | ------- | ------------------------------------------------------------------------ |
| `max_retries`    | int       | `0`     | Maximum retry attempts. `0` disables retrying.                           |
| `error_patterns` | list[str] | `[]`    | Case-insensitive substring patterns matched against error output.        |
| `wait_times`     | list[int] | `[30]`  | Per-retry wait times in seconds. Last value reused if list is too short. |
| `fallback_model` | str\|null | `null`  | Alternate model to use after exhausting all retries.                     |

### Default Configuration

Only Gemini has retry defaults:

- **max_retries**: 3
- **error_patterns**: `["An unexpected critical error occurred:"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"gemini-3-flash-preview"`

### Retry Flow

```
Error detected
│
├── Does error match error_patterns? (case-insensitive substring)
│   ├── No  → fail immediately
│   └── Yes → retry_count < max_retries?
│       ├── Yes → wait (wait_times[retry_count]) → retry
│       └── No  → fallback_model configured?
│           ├── Yes → switch model via SASE_MODEL_OVERRIDE → retry once
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

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/axe_run_agent_exec.py`

## Prompt Preprocessing Pipeline

Before any prompt reaches a provider, it passes through a 6-step preprocessing pipeline defined in `preprocessing.py`.

### Steps

| #   | Step                 | Syntax         | Description                                        |
| --- | -------------------- | -------------- | -------------------------------------------------- |
| 1   | xprompt references   | `#name`        | Expand reusable prompt snippets from xprompts      |
| 2   | Command substitution | `$(cmd)`       | Execute shell commands and inline their output     |
| 3   | File references      | `@path`        | Inline file contents (copy absolute/tilde paths)   |
| 4   | Jinja2 rendering     | `{{ var }}`    | Render Jinja2 templates after all prior expansions |
| 5   | Prettier formatting  | -              | Format with prettier for consistent markdown       |
| 6   | Comment stripping    | `<!-- ... -->` | Remove HTML/markdown comments                      |

### Order Matters

The pipeline runs in strict order. Jinja2 rendering (step 4) happens **after** xprompt, command substitution, and file
reference expansion, so templates can reference content injected by earlier steps.

### Home Mode

When `is_home_mode=True`, file reference processing skips copying files (step 3). This is used when the invocation
doesn't need side effects from `@path` references.

### Source Functions

The preprocessing steps delegate to functions from two libraries:

- **`xprompt`**: `process_xprompt_references()`, `is_jinja2_template()`, `render_toplevel_jinja2()`
- **`gemini_wrapper.file_references`**: `process_command_substitution()`, `process_file_references()`,
  `format_with_prettier()`, `strip_html_comments()`

## Subprocess Streaming

Both providers use the shared `stream_process_output()` function from `_subprocess.py` to stream LLM output in
real-time.

### Mechanism

1. The provider spawns the CLI tool via `subprocess.Popen` with `stdin=PIPE`, `stdout=PIPE`, `stderr=PIPE`.
2. The prompt is written to stdin, then stdin is closed.
3. Both stdout and stderr file descriptors are set to **non-blocking** mode via `os.set_blocking()`.
4. A `select.select()` loop with a 0.1s timeout polls for readable data on both streams.
5. Lines are read and optionally printed to the console in real-time.
6. After the process exits (`process.poll() is not None`), any remaining buffered output is drained.
7. The function returns `(stdout_content, stderr_content, return_code)`.

### Live Reply File

When `SASE_ARTIFACTS_DIR` is set, the streaming output is also written in real-time to
`<SASE_ARTIFACTS_DIR>/live_reply.md`. This file is used by the ACE TUI Agents tab to display the agent's reply as it
streams in, and remains available after execution completes for the metadata panel's AGENT REPLY section.

### Output Suppression

When `suppress_output=True`, lines are still captured but not printed to the console. This is used for background
invocations where the caller only needs the final result.

### Mid-Execution Interrupt

Both the Claude and Gemini providers support mid-execution user interrupts. A monitor thread polls for an
`interrupt_request.json` file in the agent's artifacts directory (1-second interval). When detected:

1. The current LLM subprocess is terminated
2. The user's message is read from the file
3. The provider resumes with the message injected into the conversation

**Claude Code**: Reuses the same session ID, so the user message becomes a follow-up conversation turn with full context
preserved.

**Gemini**: Reconstructs the prompt by appending the accumulated response so far and the user's message, since Gemini
has no session persistence.

Interrupt events are logged to `interrupt_log.jsonl` in the artifacts directory. The interrupt file format is:

```json
{ "message": "user text", "timestamp": 1234567890.123 }
```

The interrupt is triggered from the ACE TUI via the `m` key on the Agents tab. See
[`docs/ace.md`](ace.md#mid-execution-user-interrupt) for the user-facing workflow.

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

**Timestamp:** <display_timestamp>

## Previous Conversation

<previous history if resuming>

---

## Prompt

<prompt text>

## Response

<response text>
```

### Resume Support

The `sase run --resume` flag resumes a previous conversation by agent name. The `#resume` workflow resolves the agent
name to its artifacts directory, extracts the response path from `done.json`, and delegates to `#resume_by_chat` which
loads the chat history and prepends it to the new conversation. The `--resume` flag also accepts a history file basename
or full path for direct chat-file-based resumption via the `#resume_by_chat` workflow.

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
├── 4. Preprocess prompt (6-step pipeline)
│   ├── xprompt references (#name)
│   ├── Command substitution ($(cmd))
│   ├── File references (@path)
│   ├── Jinja2 rendering ({{ var }})
│   ├── Prettier formatting
│   └── Comment stripping
│
├── 5. Display decision counts (if not suppressed)
├── 6. Print prompt via Rich (if not suppressed)
├── 7. Generate or use provided timestamp
├── 8. Save prompt to artifacts directory
│
├── 9. Get provider from registry and invoke
│   ├── Build CLI command with flags
│   ├── Spawn subprocess (Popen)
│   ├── Write prompt to stdin
│   └── Stream stdout/stderr in real-time
│
├── 10. Postprocess
│   ├── Success path:
│   │   ├── Audio notification
│   │   ├── Log to sase.md
│   │   └── Save chat history
│   └── Error path:
│       ├── Rich error display
│       ├── Log error to sase.md
│       └── Save error chat history
│
└── 11. Return AIMessage(content=response)
```

### Parameters

| Parameter         | Type                        | Default    | Description                             |
| ----------------- | --------------------------- | ---------- | --------------------------------------- |
| `prompt`          | `str`                       | (required) | Raw prompt to send                      |
| `agent_type`      | `str`                       | (required) | Agent type label (e.g., `"editor"`)     |
| `model_tier`      | `ModelTier`                 | `"large"`  | Model tier to use                       |
| `model_size`      | `"big" \| "little" \| None` | `None`     | Deprecated, use `model_tier`            |
| `iteration`       | `int \| None`               | `None`     | Iteration number for logging            |
| `workflow_tag`    | `str \| None`               | `None`     | Workflow tag for logging                |
| `artifacts_dir`   | `str \| None`               | `None`     | Directory for sase.md and prompt files  |
| `workflow`        | `str \| None`               | `None`     | Workflow name for chat history          |
| `suppress_output` | `bool`                      | `False`    | Suppress console output                 |
| `timestamp`       | `str \| None`               | `None`     | Shared timestamp (`YYmmdd_HHMMSS`)      |
| `is_home_mode`    | `bool`                      | `False`    | Skip file copying for `@` references    |
| `decision_counts` | `dict[str, Any] \| None`    | `None`     | Planning agent decision counts          |
| `provider_name`   | `str \| None`               | `None`     | Override provider (default from config) |

### Return Value

Always returns an `AIMessage` (from `langchain_core.messages`). On error, the `content` field contains the error message
rather than a response.
