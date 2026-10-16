---
title: Codex CLI provider
description:
  Codex command construction, model mapping, planning, and provider-specific behavior.
---

# Codex CLI provider

This page describes how SASE integrates Codex CLI for agent invocations.

## Codex CLI Integration

The `CodexProvider` invokes the OpenAI `codex` CLI tool.

### Command Construction {#command-construction-2}

Normal mode:

```
codex exec --model <model> --dangerously-bypass-approvals-and-sandbox --json --color never --skip-git-repo-check - [extra_args...]
```

The prompt is written to stdin. Output is streamed as NDJSON events, with assistant text
extracted from `item.completed` events.

### Codex instruction delivery

When bundle preparation succeeds with `codex_explicit_instructions` enabled (the
default), SASE adds `-c developer_instructions=<bundle>` to the command. The value
contains the compiled root instructions and delivery marker, including the single-turn
directive. The delivered text has a 32 KiB limit; an oversized bundle falls back to the
single-turn directive instead of being truncated.

For a SASE-managed project, explicit delivery also adds `-c project_doc_max_bytes=0`.
This disables native project-document loading for the invocation, including nested
project instructions; it is not a path-by-path exclusion. Unmanaged projects retain
native project discovery. Native helpers inherit the root's `developer_instructions`;
there is no separate helper bundle or guard, so the instruction to return results to the
parent remains essential.

During explicit delivery, SASE collects each thread ID returned by the Codex adapter,
including fresh threads started after interrupts or handoff recovery, and writes them to
the invocation manifest when the provider call ends. Fallback calls do not record thread
IDs through this path. Use `sase instructions verify -a AGENT` to compare observed loads
with that manifest; verification can also match sessions by bundle markers or
timestamps.

Without an active explicit bundle, the command uses the single-turn directive and does
not override the CLI's project-document loading setting. Shadow-home suppression follows
the active delivery result: fallback runs restore the SASE-owned global instruction
copies, the `~/AGENTS.md` fallback, and native memories. Disabling
`codex_explicit_instructions` restores those shadow-home paths as well. This distinction
matters when diagnosing a render failure or an oversized bundle.

### Model Mapping {#model-mapping-2}

<!-- BEGIN GENERATED: model-tiers-codex -->

| Tier    | Model               |
| ------- | ------------------- |
| `large` | `gpt-6.1-sol`       |
| `small` | `codex-mini-latest` |

<!-- END GENERATED: model-tiers-codex -->

### Plan Handling

The Codex provider does not enable Codex CLI's native plan mode. SASE planning flows are
implemented at the orchestration layer through workflows, macros, and the `sase_plan`
skill, so provider behavior stays consistent across runtimes.

### Environment Variables {#environment-variables-2}

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
`~/.cache/sase/codex_home/`. The shadow home copies `config.toml` and symlinks an
allow-list of entries for authentication, hooks, skills, plugins, sessions, and caches
back to the real Codex home. SQLite state is not shared. With an active explicit
delivery, native `memories` and SASE-owned global instruction files are omitted; foreign
global `AGENTS.md` / `AGENTS.override.md` files remain available. With the flag
disabled, `memories` is shared and `~/AGENTS.md` is linked when no Codex-global file
wins. Config rewrites remain disposable. The shadow directory is removed after each
Codex subprocess exits. Set `SASE_CODEX_DISABLE_SHADOW_HOME=1` to pass through the
inherited environment directly for debugging or emergency compatibility.

### Codex Tool-Call Capture

SASE captures Codex tool calls from the `codex exec --json` NDJSON stream; it does not
install Codex hooks or mutate user Codex configuration for telemetry. When
`SASE_ARTIFACTS_DIR` is present, the stream parser appends normalized Codex records to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for sase's TUI
[Agents Tab LLM Calls Panel](../tui/agents-deck-panels.md#agents-tab-llm-calls-panel).

Current fixture coverage is based on Codex CLI `0.130.0`. For stream items that expose
both start and completion events (`command_execution`, `file_change`, and named tool
items), SASE writes `ToolUse` and `ToolResult` rows with `runtime: "codex"` and
`source: "stream"`. The LLM Calls reader collapses those pairs into one row, preserving
pending rows while a command is still running and showing result previews,
failure/interruption status, and duration when the stream exposes enough data to compute
it.

Older Codex stream shapes that only expose a completed `function_call` item remain
readable as `FunctionCall` rows. Those records can show the tool name and compact input
target, but they do not invent response summaries, durations, or failure details that
Codex did not emit.

Codex tool-call summaries use the same bounded and redacted artifact helpers as the
other providers. Textual command output (`stdout`, `stderr`, and combined `output`) uses
a tail-oriented soft character budget: when truncation is needed, the summary marks how
much was omitted from the beginning and retains at least the final 50 complete logical
lines. Exceptionally wide trailing lines can therefore make a summary larger than the
nominal budget. Command input, paths, errors, read/web content, and subagent final
messages remain head-oriented. Set `SASE_TOOL_LOG_FULL=1` only for explicit debugging
sessions when raw tool input or output is needed in the local artifact.

### Turn Integrity Check

Codex can exit `0` after a turn that completed without a usable answer. The stream
parser watches for that case: if Codex reports the task complete, never emitted a
non-empty final agent message, and a command execution was either killed at teardown
(`exit_code` `-1`) or started without ever reporting a result, SASE raises an
`LLMInvocationError` that starts with `Codex turn integrity failure` and names up to
three of the affected commands. That prefix is one of Codex's provider-supplied retry
patterns (see
[Provider-Supplied Retry Defaults](retry-and-fallback.md#provider-supplied-retry-defaults)),
so the turn is retried with the resume nudge instead of being recorded as an empty
success.

### Timer Display {#timer-display-2}

While waiting for a response, a `provider_timer("Waiting for Codex")` spinner is shown
(unless `suppress_output` is `True`).

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model names and tier defaults.
