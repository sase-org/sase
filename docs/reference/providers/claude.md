---
title: Claude Code provider
description:
  Claude Code command construction, model mapping, and provider-specific behavior.
---

# Claude Code provider

This page describes how SASE integrates Claude Code for agent invocations.

## Claude Code Integration

The `ClaudeCodeProvider` invokes the `claude` CLI tool.

### Command Construction

```
claude -p --verbose --model <alias> --output-format stream-json \
  --dangerously-skip-permissions \
  --append-system-prompt-file <root bundle> --disallowedTools ScheduleWakeup \
  --session-id <uuid> [--effort <level>] [extra_args...]
```

The prompt is written to stdin. Output is streamed as JSON events; SASE extracts
assistant text and token usage from the stream. A wait-guard continuation (see below)
replaces `--session-id <uuid>` with `--resume <uuid>` so the nudge lands in the same
Claude session.

Every cycle also passes `--settings <inline JSON>` carrying a PreToolUse guard on
`Bash|Skill`, exact-path `claudeMdExcludes` for SASE-owned root and home files, and
`autoMemoryEnabled: false`, plus `--append-subagent-system-prompt-file <helper bundle>`
when the installed CLI parses that flag (see "Native helpers" below).

The root and helper files contain their respective compiled bundles and trailing
invocation markers. They are private temporary files kept across all cycles and removed
after the call. With `claude_explicit_instructions` disabled or no delivery plan, the
root flag is `--append-system-prompt <single-turn directive>`, settings contain only the
helper guard, and the helper uses the packaged static template. A failed root file
restores the default root delivery, including native discovery; a failed helper file
uses the static template independently.

SASE also sets two Claude Code environment variables on the subprocess unless the caller
already set them: `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, and `BASH_MAX_TIMEOUT_MS`
raised to four hours (`14400000`) so long verification commands can stay in the
foreground. Commands still need an explicit larger timeout to use that ceiling.

### Single-Turn Wait Guard

A SASE provider turn is one `claude -p` process with no follow-up event loop, so a
background-task notification or a scheduled wake-up can never reach the model. SASE
guards against replies that end the turn waiting for one:

- The appended system prompt tells the model that the session is single-turn, that
  commands must run synchronously in the foreground, and that a command killed by its
  timeout should be rerun with a larger explicit timeout.
- The `ScheduleWakeup` tool is disallowed.
- The stream parser records background task IDs reported by tool results, clears them
  when a matching `<task-notification>` arrives, and notes any `ScheduleWakeup` call.

After a successful exit, a turn counts as a wait state when it requested a wake-up, or
when a background task is still outstanding and the tail of the final reply reads like a
wait ("I'll wait", "will be notified", "still running", and similar). SASE then resumes
the same session with a nudge to read the task output or rerun the command in the
foreground and finish. After `SASE_CLAUDE_MAX_WAIT_CONTINUATIONS` continuations (default
`2`) the run fails with `LLMInvocationError` instead of recording the waiting reply as a
successful answer.

### Native helpers

Claude native subagents (general-purpose and Explore) inherit the root's environment, so
without a stopgap they can act as roots: helpers have invoked `sase final` and two
submissions were even accepted for their parent's turn. Two mechanisms keep helpers in
their lane:

- **Helper bundle.** The compiled helper instructions (headed
  `# SASE Helper Instructions`) are passed through the hidden
  `--append-subagent-system-prompt-file` flag on every invocation cycle, including
  `--resume` cycles. It reaches Explore and general-purpose helpers but not the root,
  and tells helpers their parent owns the turn: never run `sase final …` or the
  root-only skills, never commit, create beads, or launch agents, and return the result
  to the parent. Live probes confirm both helper types carry `agent_id` and see the
  helper heading. The packaged static file
  `src/sase/llm_provider/templates/claude_helper_instructions.md` remains the fallback
  for a disabled flag, missing delivery plan, or helper render/materialization failure.
- **PreToolUse guard.** The inline `--settings` JSON installs a stdlib-only hook
  (`src/sase/llm_provider/_claude_helper_guard.py`, run as
  `<sys.executable> -I <guard path>`) on `Bash|Skill`. When the hook input carries a
  non-empty `agent_id` — set only for calls made inside a subagent — the guard denies
  `sase final context|defer|prepare|submit`, the turn-ending CLI forms the root-only
  skills run (`sase plan propose`, `sase monitor start`, `sase launch request`,
  `sase pipe`, `sase gate create|wait`, `sase questions`, `sase run`,
  `sase sudo request`, `sase stitch create`), and the root-only skills themselves
  (`sase_final`, `sase_gate`, `sase_git_commit`, `sase_handoff`, `sase_monitor`,
  `sase_plan`, `sase_questions`, `sase_run`, `sase_sudo`). Read-only forms such as
  `sase final status` stay allowed. A deny exits 0 with a `SASE helper guard:` reason,
  which blocks the call even under `--dangerously-skip-permissions` (verified by live
  probe); every other input, including the root's own calls without `agent_id` and
  malformed stdin, exits 0 silently.

A cached no-API capability probe decides whether the installed CLI parses the hidden
flag: `claude -p --append-subagent-system-prompt-file <nonexistent>` reporting "file not
found" means supported, "unknown option" means unsupported, and anything else is
unknown. The result is cached by executable path plus mtime and size. When the probe
does not report support, the adapter omits only the template flag, logs one warning, and
keeps the guard. `sase doctor -D -C providers.claude_helper_channel` runs the probe
uncached and reports OK, or ERROR with next steps. Live probes also show that forked
(nested) helpers carry `agent_id`, so the guard covers them as well.

### Model Mapping

<!-- BEGIN GENERATED: model-tiers-claude -->

| Tier    | Model    |
| ------- | -------- |
| `large` | `opus`   |
| `small` | `sonnet` |

<!-- END GENERATED: model-tiers-claude -->

The tier values above are floating Claude CLI aliases that Claude resolves to its
current model, so SASE intentionally does not pin them to point version IDs.

### Environment Variables

| Variable                             | Description                                                                                                        |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `SASE_LLM_LARGE_ARGS`                | Extra CLI args for `large` tier (generic, preferred)                                                               |
| `SASE_LLM_SMALL_ARGS`                | Extra CLI args for `small` tier (generic, preferred)                                                               |
| `SASE_CLAUDE_LARGE_ARGS`             | Extra CLI args for `large` tier (Claude-specific fallback)                                                         |
| `SASE_CLAUDE_SMALL_ARGS`             | Extra CLI args for `small` tier (Claude-specific fallback)                                                         |
| `SASE_CLAUDE_MAX_WAIT_CONTINUATIONS` | Wait-guard continuation cap (default: `2`)                                                                         |
| `BASH_MAX_TIMEOUT_MS`                | Bash-tool timeout ceiling (default: `14400000` = 4 h); also sets the exported `SASE_PROVIDER_SYNC_CEILING_SECONDS` |

The generic `SASE_LLM_*_ARGS` variables take precedence. Values are split on whitespace
and appended to the command.

### Timer Display

While waiting for a response, a `provider_timer("Waiting for Claude")` spinner is shown
(unless `suppress_output` is `True`).

### Claude Tool Calls

To record what tools an agent actually invoked (file reads, edits, bash commands, etc.),
`ClaudeCodeProvider` parses Claude Code's `stream-json` output as it arrives and appends
one normalized record per tool call to `$SASE_ARTIFACTS_DIR/tool_calls.jsonl`:

- An `assistant` event carrying `message.content[].tool_use` blocks emits one `pending`
  `ToolUse` (start) record per block: the tool name and a bounded, redacted summary of
  its input. Set `SASE_TOOL_LOG_FULL=1` to record the raw input instead.
- A `user` event carrying `message.content[].tool_result` blocks emits the matching
  `ToolResult` (end) record: a `success`, `failure`, or `interrupted` status and a
  length-bounded preview of the response, drawing structured output from the top-level
  `tool_use_result` envelope when present.

sase's TUI LLM Calls panel reads this same `tool_calls.jsonl` to render the per-agent
timeline — see
[Agents Tab LLM Calls Panel](../tui/agents-deck-panels.md#agents-tab-llm-calls-panel).
The reader pairs a `ToolUse` with its `ToolResult` by `tool_use_id` and collapses them
into one row.

Stream parsing is the only writer for new runs. SASE does **not** install Claude Code
hooks and does **not** write to the workspace's `.claude/settings.local.json`; earlier
releases did, through the `sase_claude_tool_hook` console script, and new runs never
request Claude's `--include-hook-events`.

The `schema_version` field on each row names _which writer produced it_, not how recent
it is — the numbers are two lineages, not a sequence, so a higher number is not a newer
format:

| `schema_version` | Written by                         | Still written? |
| ---------------- | ---------------------------------- | -------------- |
| `1`, `2`         | The stream parser (`2` is current) | Yes — `2`      |
| `3`              | The retired Claude tool-call hook  | No             |

The reader accepts all three, so old artifacts stay viewable. In a historical file that
mixed both writers, a schema-3 hook row wins over a stream row describing the same
`tool_use_id`, so an old timeline does not double-count one call.

The writer is intentionally non-blocking and best-effort: a malformed event, an
exception inside normalization, or a missing `SASE_ARTIFACTS_DIR` produces a diagnostic
line in `$SASE_ARTIFACTS_DIR/tool_calls_writer_errors.jsonl` (or a silent no-op) rather
than failing the run. A SASE-side bug can never surface to the agent as a tool-call
failure.

The normalized tool-call artifact is still Python/TUI-owned glue rather than a shared
`sase-core` contract. Move it into `../sase-core` only if another frontend or
integration needs to produce or consume exactly the same schema through the Rust
boundary.

Source: `src/sase/llm_provider/claude.py`, `src/sase/llm_provider/_tool_calls.py`,
`src/sase/llm_provider/_tool_call_claude.py`,
`src/sase/llm_provider/_tool_call_common.py`, `src/sase/ace/tui/llm_calls/reader.py`

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model names and tier defaults.
