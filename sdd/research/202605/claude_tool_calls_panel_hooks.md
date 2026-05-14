# Claude Tool Calls Panel via Hooks

Research date: 2026-05-14

## Question

Should the Agents tab retire the current "Thinking" panel and replace it with a "Tools" panel showing the tool calls an
agent made, and is Claude Code hook capture the right MVP implementation path?

## Short Answer

Yes. For the Claude-only MVP, the cleanest path is to capture tool activity with Claude Code command hooks and store a
per-agent `tool_calls.jsonl` artifact under the existing SASE artifacts directory. The TUI should read that artifact
directly instead of deriving tool history from Claude transcript JSONL.

The minimum useful hook set is:

- `PostToolUse` with matcher `*` or omitted: log successful tool calls, including `tool_name`, `tool_input`,
  `tool_response` summary, `tool_use_id`, `duration_ms`, `session_id`, `transcript_path`, and `cwd`.
- `PostToolUseFailure` with matcher `*` or omitted: log failed tool calls, including `error`, `is_interrupt`, and
  `duration_ms`.
- Optional later: `PostToolBatch` to record batch boundaries when Claude runs tools in parallel.

Do not use `PreToolUse` as the main source of truth for this panel. It sees intended tool calls before they run, but the
panel should primarily show what happened. `PreToolUse` can be added later only if the UI wants to show queued or denied
attempts.

## Why Hooks Beat Transcript Parsing For This Panel

The current thinking panel reads Claude transcript JSONL from `~/.claude/projects/...` through
`src/sase/ace/tui/thinking/session_resolver.py` and `src/sase/ace/tui/thinking/parser.py`. That was reasonable for
extended-thinking blocks because Claude does not expose those through SASE's own artifacts. Tool calls are different:
Claude Code exposes tool events through hooks with structured JSON input, including a stable `tool_use_id` and the
transcript path.

Hook capture gives SASE better ownership:

- It writes into the already-selected agent artifacts directory instead of scanning global Claude transcript history.
- It works while the agent is still running.
- It can normalize and redact at write time.
- It avoids guessing which `~/.claude/projects/<hashed-cwd>/*.jsonl` belongs to the selected agent.
- It can be implemented as a provider adapter now and generalized later to Gemini/Codex/Qwen without changing the TUI
  panel contract.

The existing transcript parser can still be a fallback or a migration aid, but it should not be the primary data path
for the Tools panel.

## Relevant Claude Hook Facts

Claude Code's current hook documentation says settings can define hooks at user, project, local project, managed, plugin,
skill, and subagent scopes. Project settings live under `.claude/settings.json`, while local project settings live under
`.claude/settings.local.json`. The docs also note that omitted, empty, or `*` matchers fire on every occurrence of the
event.

Hook commands receive JSON on stdin. Common hook input includes:

- `session_id`
- `transcript_path`
- `cwd`
- `permission_mode`
- `hook_event_name`

For `PostToolUse`, Claude adds `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, and optional `duration_ms`.
This fires only after a successful tool call.

For `PostToolUseFailure`, Claude adds `tool_name`, `tool_input`, `tool_use_id`, `error`, optional `is_interrupt`, and
optional `duration_ms`.

For `PostToolBatch`, Claude fires once after a full batch of tool calls resolves. It includes `tool_calls`, an array of
calls with tool input, ids, and serialized model-visible results. The docs explicitly warn that `PostToolUse` fires once
per tool and can fire concurrently for parallel tool calls, while `PostToolBatch` fires once for the whole batch.

Command hook behavior matters for the logger:

- Exit `0` is success. The logger should normally exit `0` and print nothing.
- Any non-zero hook failure could pollute the Claude transcript or affect the run, so the logger must fail open.
- Async hooks exist, but the MVP should probably start synchronous with a very small timeout and cheap append-only I/O.
  If logging overhead ever shows up, move the same command hook to `"async": true`.
- Claude Code hook handlers run with Claude Code's environment. SASE already publishes `SASE_ARTIFACTS_DIR` before each
  agent phase in `src/sase/axe/run_agent_exec.py`, so the hook can write to the active phase's artifacts directory.

## Current SASE Surfaces That Fit

SASE already has a per-agent artifact root:

```text
~/.sase/projects/<project>/artifacts/ace-run/<timestamp>/
```

The run loop publishes:

- `SASE_ARTIFACTS_DIR`
- `SASE_AGENT_TIMESTAMP`
- `SASE_AGENT_ROOT_TIMESTAMP`
- `SASE_AGENT_CHAT_PATH`

This is exactly the correlation mechanism the tool logger needs. The hook should only write when `SASE_ARTIFACTS_DIR`
is set and points to a directory. If it is unset, the hook should exit `0` immediately. That makes a user-level Claude
hook safe enough to install globally because ordinary Claude Code sessions outside SASE will be ignored.

The current thinking panel is wired as a third detail panel mode:

- `DetailPanelMode.AUTO`
- `DetailPanelMode.THINKING`
- `DetailPanelMode.INFO`

It also already has:

- background worker refresh
- stale-cache display
- editor-open export of the panel text
- `]` / `[` panel cycling
- a visibility message from panel to `AgentDetail`

The Tools panel can reuse most of that UI shape. The clean local migration is to rename the semantic surface from
thinking to tools while preserving the panel-mode machinery:

- `AgentThinkingPanel` -> `AgentToolsPanel`
- `ThinkingBlock` -> `ToolCallEntry`
- `ThinkingVisibilityChanged` -> `ToolsVisibilityChanged`
- `DetailPanelMode.THINKING` -> `DetailPanelMode.TOOLS`
- footer label `thinking` -> `tools`

This is mostly presentation code, so it can stay in this repo. If SASE wants mobile, CLI, or Rust daemon projections to
show the same tool history later, the parser/projection should move behind the Rust core boundary.

## Proposed Artifact Format

Use JSONL, one normalized event per hook invocation:

```json
{
  "schema_version": 1,
  "recorded_at": "2026-05-14T12:34:56-04:00",
  "event": "PostToolUse",
  "status": "success",
  "runtime": "claude",
  "session_id": "abc123",
  "transcript_path": "/home/user/.claude/projects/.../session.jsonl",
  "cwd": "/home/user/projects/foo",
  "permission_mode": "bypassPermissions",
  "tool_use_id": "toolu_01ABC123",
  "tool_name": "Bash",
  "tool_input": {
    "command": "pytest tests/test_foo.py",
    "description": "Run focused tests",
    "timeout": 120000
  },
  "tool_response_summary": {
    "stdout_preview": "...",
    "stderr_preview": "",
    "exit_code": 0,
    "success": true
  },
  "duration_ms": 4187
}
```

For failures:

```json
{
  "schema_version": 1,
  "recorded_at": "2026-05-14T12:35:10-04:00",
  "event": "PostToolUseFailure",
  "status": "failure",
  "runtime": "claude",
  "session_id": "abc123",
  "tool_use_id": "toolu_01DEF456",
  "tool_name": "Bash",
  "tool_input": {
    "command": "pytest tests/test_missing.py"
  },
  "error": "Command exited with non-zero status code 4",
  "is_interrupt": false,
  "duration_ms": 900
}
```

Recommended file layout:

```text
<SASE_ARTIFACTS_DIR>/tool_calls.jsonl
<SASE_ARTIFACTS_DIR>/tool_calls.lock
```

Use an advisory file lock for appends because parallel tool calls can fire concurrent hooks. The hook should write one
line atomically under lock, flush, and exit. If locking or JSON parsing fails, write a small diagnostic to
`tool_calls_hook_errors.jsonl` if possible, then exit `0`.

## Input Redaction And Summarization

The panel should be useful without storing huge tool outputs or secrets.

Recommended MVP policy:

- Preserve `tool_name`, `tool_use_id`, timestamps, duration, status, `cwd`, and `transcript_path`.
- Preserve safe input fields by tool type:
  - `Read`: `file_path`, `offset`, `limit`
  - `Grep`: `pattern`, `path`, `glob`, `output_mode`
  - `Glob`: `pattern`, `path`
  - `Bash`: `command`, `description`, `timeout`, `run_in_background`
  - `Write` / `Edit` / `MultiEdit`: `file_path`, edit counts, content length, old/new string lengths, but not full file
    content by default
  - `WebFetch` / `WebSearch`: URL/query and short result metadata
  - `Task` / `Agent`: prompt length and subagent type/name, not the full prompt unless a debug flag is enabled
- Summarize `tool_response` instead of storing it wholesale:
  - `Bash`: output previews capped to a small byte limit, exit/interrupted flags if present
  - `Read`: path, line count, byte count, maybe first line preview
  - `Write` / `Edit`: success flag and file path
  - Unknown tools: JSON type and capped preview
- Add `SASE_TOOL_LOG_FULL=1` for local debugging only.

This policy avoids turning `tool_calls.jsonl` into a second full transcript store.

## UI Shape

The first Tools panel should be an operational timeline, not a decorative table.

Each row should show:

- local time
- status marker: success, failure, interrupted
- tool name
- short target: file basename, command first word, search pattern, URL host, or subagent label
- duration
- one-line detail preview

Expanding or selecting a row can show structured details in the same panel, but the MVP can start as a readable
vertical list.

Good filters for later:

- all
- file ops
- shell
- search/read
- web
- subagents
- failures

The existing `]` and `[` cycle can become `file -> tools -> collapsed`, replacing the old `file -> thinking ->
collapsed`. The old `i`/thinking label should disappear from help and footer text if still present.

## Recommended Implementation Path

1. Add a small hook command, probably `sase_tool_call_hook`, under `src/sase/scripts/`.
2. Register it for Claude `PostToolUse` and `PostToolUseFailure`.
3. Gate the hook on `SASE_ARTIFACTS_DIR`; exit `0` when absent.
4. Normalize and append JSONL under file lock.
5. Add a parser module that reads `tool_calls.jsonl`, tolerates malformed lines, sorts by recorded time and sequence,
   and returns `ToolCallEntry` objects.
6. Replace the thinking panel widget with a tools panel using the existing `AgentDetail` secondary-panel machinery.
7. Update footer/help labels, tests, and PNG snapshots.
8. Keep the transcript-based thinking parser around only if there is another consumer; otherwise remove it in a later
   cleanup after the UI migration is stable.

## Hook Registration Options

Best MVP: user-level hook installed by SASE, gated by `SASE_ARTIFACTS_DIR`.

Why:

- SASE can launch agents in arbitrary project workspaces, not just the SASE repo.
- Project `.claude/settings.json` only helps repos that already carry that file.
- Writing `.claude/settings.local.json` into every ephemeral workspace is possible, but it mutates each workspace and
  adds another setup/cleanup edge.
- `CLAUDE_CONFIG_DIR` can isolate configuration, but the docs say it moves all settings, credentials, session history,
  and plugins under that directory. That is too broad for an MVP unless SASE also manages Claude auth/session state.

The global hook can be safe if it is no-op outside SASE:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "sase_tool_call_hook",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUseFailure": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "sase_tool_call_hook",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

If SASE wants to avoid modifying user-level Claude settings, the second-best option is a SASE launch preflight that
merges a local `.claude/settings.local.json` hook into the workspace. That needs careful non-destructive merge/restore
logic and tests around user-owned local settings.

## Risks And Decisions

### Parallel tool ordering

`PostToolUse` hooks can run concurrently for parallel tool calls. Use `recorded_at`, `tool_use_id`, and a monotonic
sequence assigned under the file lock. If exact batch grouping matters, add `PostToolBatch` later.

### Hook failure must never fail the agent

This hook is telemetry/UI capture, not policy. It should exit `0` even on malformed stdin, missing artifact directory,
or append failure. A broken logger should not block Claude or change task behavior.

### Large outputs

Do not write raw `tool_response` by default. Claude's docs explicitly note that responses can be large, especially for
batch hooks. Store previews and metadata.

### Secrets

Tool inputs can contain secret-looking shell commands, file contents, URLs, and prompt bodies. The default formatter
should redact obvious env assignments and token-like values in Bash commands, avoid full Write/Edit content, and avoid
subagent prompt bodies.

### Runtime uniformity

Even though the MVP supports Claude only, the TUI model should be runtime-neutral: `runtime`, `event`, `tool_name`,
`tool_input_summary`, `tool_response_summary`, and `status`. Do not bake Claude transcript assumptions into the panel.
Gemini/Qwen/Codex can later write the same artifact from their own hook/stream adapters.

### Backend boundary

The first TUI panel can parse JSONL in Python. If tool-call history becomes a daemon API, mobile feature, archive query
field, or reusable artifact projection, the parser and model belong in `../sase-core/crates/sase_core` with a thin
Python adapter.

## Open Questions

- Should SASE expose a setup command that installs the Claude tool logger hook, similar to skills/hook setup, or should
  SASE auto-install it on first Claude run?
- Does the user-level hook need to coexist with the existing commit stop hook installer, or should SASE consolidate all
  Claude hook registration in one managed block?
- Do we want `PostToolBatch` in the MVP to avoid explaining parallel ordering, or is per-tool logging enough?
- Should failed permission/denied tool attempts appear in the panel? If yes, add `PermissionDenied` or `PreToolUse`
  capture as a separate event type after the success/failure timeline works.
- Should archived/dismissed agents preserve `tool_calls.jsonl` with their artifact bundle? They probably should.

## Bottom Line Recommendation

Build the Tools panel around a SASE-owned `tool_calls.jsonl` artifact populated by Claude `PostToolUse` and
`PostToolUseFailure` hooks. Install the hook globally or through SASE-managed Claude setup, but make it a no-op unless
`SASE_ARTIFACTS_DIR` is set. Keep the TUI data model runtime-neutral from day one, even though only Claude writes the
artifact initially.

This gives the Agents tab a more actionable panel than thinking output, avoids fragile transcript matching, and creates
a durable artifact that can be reused by archive views, mobile, and future runtime adapters.

## Sources

- Claude Code hooks reference: <https://code.claude.com/docs/en/hooks>
- Claude Code hooks guide: <https://code.claude.com/docs/en/hooks-guide>
- Claude Code settings/configuration: <https://code.claude.com/docs/en/configuration>
- Claude Code environment variables: <https://code.claude.com/docs/en/env-vars>
- Current thinking panel plan: `sdd/epics/202602/claude_thinking_panel.md`
- Current thinking parser/session resolver: `src/sase/ace/tui/thinking/parser.py`,
  `src/sase/ace/tui/thinking/session_resolver.py`
- Current thinking panel/detail wiring: `src/sase/ace/tui/widgets/thinking_panel.py`,
  `src/sase/ace/tui/widgets/agent_detail.py`, `src/sase/ace/tui/widgets/_agent_detail_panels.py`
- Current Claude provider subprocess invocation: `src/sase/llm_provider/claude.py`,
  `src/sase/llm_provider/_subprocess_claude.py`
- Current SASE agent env/artifact publication: `src/sase/axe/run_agent_exec.py`,
  `src/sase/artifacts.py`
