# Claude Tool Calls Panel via Hooks

Research date: 2026-05-14

## Question

Should the Agents tab retire the current "Thinking" panel and replace it with a "Tools" panel showing the tool calls an
agent made, and is Claude Code hook capture the right MVP implementation path?

## Short Answer

Yes, build a "Tools" panel. There are **two viable capture strategies**, and the right MVP is to pick one and move on:

- **Strategy A — command hooks**: install a `PostToolUse` / `PostToolUseFailure` command hook that writes
  `tool_calls.jsonl` into the active `SASE_ARTIFACTS_DIR`. Decoupled from `claude` CLI argument shape, survives SASE
  restarts mid-session, and gives SASE a durable artifact independent of the subprocess that produced it.
- **Strategy B — stream-JSON in-band capture**: pass `claude --include-hook-events` together with the existing
  `--output-format stream-json` and extend `src/sase/llm_provider/_subprocess_claude.py` to fold tool events into a
  SASE-written `tool_calls.jsonl`. No external hook installation. The subprocess parser already drops every event type
  except `assistant`/`error`/`result` — extending it is a few-line change.

Recommendation: **Strategy B for the MVP, with the JSONL artifact schema designed so Strategy A can drop in later
without changing the TUI panel contract.** B avoids installing or managing any state outside the SASE process tree, has
no risk of being disabled by `disableAllHooks` or managed policy, sidesteps the parallel-hook dedup/ordering surface
entirely, and parallels the path Gemini/Qwen/Codex will most likely take (each has its own stream-json mode SASE
already parses). Treat Strategy A as a fallback or a future option when SASE wants the artifact written even for
non-SASE Claude sessions, or when SASE wants to redact tool output via `updatedToolOutput` before Claude sees it.

The minimum useful event set in either strategy:

- `PostToolUse` — successful tool calls. Includes `tool_name`, `tool_input`, `tool_response` (the **structured Output
  object** for built-in tools, not a serialized string), `tool_use_id`, optional `duration_ms`, plus the common fields
  `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, and inside subagents `agent_id` and
  `agent_type`.
- `PostToolUseFailure` — failed tool calls. Adds top-level `error`, optional `is_interrupt`, optional `duration_ms`.
  Not every failure surfaces here; some tools (e.g. `Read` on a missing file) emit a `success: false` `tool_response`
  through `PostToolUse` instead.
- `SubagentStart` / `SubagentStop` — needed if the panel should group tool calls under their parent `Task`/`Agent`
  subagent. Without these, subagent tool calls still arrive via `PostToolUse` but with `agent_id` set, so grouping is
  recoverable.
- Optional: `PermissionDenied` (auto-mode classifier denials, distinct from `PreToolUse` blocks) and `PostToolBatch`
  (single event per parallel batch carrying every `tool_calls[i].tool_response` as a model-visible serialized string).

Do not use `PreToolUse` as the main source of truth. It fires before the tool runs and may not match what actually
happened (the tool can be denied, retried, or block on permission). It is useful only if the UI later wants to show
queued or in-flight calls.

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

Claude Code's current hook documentation lists ~25 hook events across three cadences: once per session (`SessionStart`,
`SessionEnd`), once per turn (`UserPromptSubmit`, `Stop`, `StopFailure`), and per tool call inside the agentic loop
(`PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `SubagentStart`,
`SubagentStop`, `TaskCreated`, `TaskCompleted`, `PermissionDenied`, plus the worktree/notification/elicitation/etc.
families).

Settings can define hooks at user, project, local project, managed, plugin, skill, and subagent scopes. Project
settings live under `.claude/settings.json`, local project settings under `.claude/settings.local.json`, user settings
under `~/.claude/settings.json`, plugin hooks under `<plugin>/hooks/hooks.json`. **The `claude` CLI also accepts
`--settings <file-or-json>`**, which loads additional settings from a path or an inline JSON string for the lifetime of
that invocation only — no on-disk mutation required. This is the most attractive install vehicle if SASE goes with
Strategy A.

Omitted, empty, or `*` matchers fire on every occurrence of the event. Matchers containing only `[A-Za-z0-9_|]` are
exact-string or `|`-separated lists; matchers with any other character are evaluated as JavaScript regex. MCP tools
appear in `PostToolUse` with the `mcp__<server>__<tool>` naming pattern, so a server-wide match needs the explicit
`.*`, e.g. `mcp__memory__.*`. `PostToolBatch` does not support matchers.

### Common input fields

Hook commands receive JSON on stdin (HTTP hooks receive the same JSON as the POST body). Common fields:

- `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`
- `effort.level` (`low`/`medium`/`high`/`xhigh`/`max`) when inside a tool-use context
- `agent_id`, `agent_type` when the hook fires inside a subagent

### Event-specific shapes worth noting

- `PostToolUse`: adds `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, optional `duration_ms`. The
  `tool_response` is the **tool's structured Output object** (e.g. `Write` returns `{filePath, success}`, `Bash`
  returns `{stdout, stderr, interrupted, isImage}`). It is *not* the same shape as the `tool_result` content block the
  model sees.
- `PostToolUseFailure`: same identifying fields but with top-level `error: string`, optional `is_interrupt`, optional
  `duration_ms`. Fires only when the tool actually throws/fails; "tool returned an error but completed" still arrives
  as `PostToolUse` with `success: false` in `tool_response`.
- `PostToolBatch`: no matcher, fires once after a full parallel batch. Carries `tool_calls`, an array where each
  element's `tool_response` is the **serialized model-visible string/blocks**, not the structured Output object. The
  docs explicitly note this divergence from `PostToolUse`.
- `SubagentStart`/`SubagentStop`: matcher is the agent type (e.g. `Explore`, `Plan`, a custom name). `SubagentStop`
  fires per subagent (rather than `Stop`).
- `PermissionDenied`: only fires in auto-mode classifier denials, not for `PreToolUse` blocks or manual denies.

### Command-hook execution semantics

- **Exit codes**: `0` = success (stdout parsed for JSON output if any). `2` = blocking error for blockable events
  (`PostToolUse` and `PostToolUseFailure` are *not* blockable: exit 2 there just shows stderr to Claude). Any other
  non-zero is a non-blocking error that surfaces a `<hook> hook error` line in the transcript. For a telemetry-only
  logger, exit `0` unconditionally and write nothing to stdout.
- **Exec form vs shell form**: when `args` is set, `command` is resolved as an executable and spawned directly with no
  shell — faster startup and no shell quoting hazards. SASE's hook script should use exec form.
- **Async**: `"async": true` runs the hook in the background without blocking Claude's loop. Async hooks cannot block
  (decision/permission fields are ignored), which is exactly what we want for telemetry. Caveat: each firing spawns a
  fresh process — there is no dedup across firings of the same async hook, and output is only delivered on the next
  conversation turn.
- **Deduplication of identical handlers**: when the same command-string + args appears in multiple settings layers,
  Claude dedups it. We do not need to worry about a user-level hook *and* a `--settings` hook firing twice.
- **Parallelism**: all matching hooks for an event run in parallel. Hook handlers cannot rely on each other's ordering.
- **Hook output cap**: `additionalContext`/`systemMessage` strings are capped at 10,000 chars. Not relevant for our
  logger because it should never emit context to Claude, but worth flagging if a future iteration injects summaries.
- **`disableAllHooks`** in any user/project/local settings file disables all non-managed hooks. **`allowManagedHooksOnly`**
  in enterprise managed policy disables user/project/local/plugin hooks entirely. Strategy A breaks in both cases;
  Strategy B does not.
- Claude Code hook handlers run with Claude Code's environment. SASE already publishes `SASE_ARTIFACTS_DIR` before each
  agent phase in `src/sase/axe/run_agent_exec.py:_publish_phase_env`, so a command hook can write to the active phase's
  artifacts directory.

### CLI flags that change the picture

- `claude --include-hook-events` (with `--output-format=stream-json`) emits every hook lifecycle event into the output
  stream. This is the foundation of Strategy B.
- `claude --settings <file-or-json>` loads ad-hoc settings for one invocation — clean per-process hook registration
  with no global mutation.
- `claude --bare` skips hooks entirely. SASE does not pass `--bare`, but any future SASE flag that adds it would
  silently disable Strategy A.

## What SASE Has Today (Code-Level Inventory)

A code search confirms several relevant facts the hook design has to live with:

- **No Claude hook installer exists.** SASE never writes `~/.claude/settings.json`, `.claude/settings.json`, or
  `.claude/settings.local.json`. The existing `src/sase/scripts/sase_commit_stop_hook.py` is *invoked by* Claude's
  native hook system based on whatever configuration the user already has on disk — it does not install itself.
  Whichever Claude hook approach we adopt for the Tools panel is greenfield install surface for SASE.
- **Runtime detection inside the hook script** uses env vars: `CLAUDE_PROJECT_DIR`, `GEMINI_PROJECT_DIR`,
  `QWEN_PROJECT_DIR`, `CODEX_PROJECT_DIR` (see `sase_commit_stop_hook.py:_resolve_project_dir`). Any new SASE-owned
  Claude hook can follow the same pattern, plus the SASE-published `SASE_ARTIFACTS_DIR`.
- **JSONL append with `fcntl` lock** is already an in-repo pattern at `sase_commit_stop_hook.py:28-33`. Strategy A's
  logger should reuse it verbatim. Note this is Unix-only; the codebase already assumes Unix elsewhere.
- **Claude subprocess invocation** lives at `src/sase/llm_provider/claude.py:_run_subprocess` (~line 246) and emits
  `["claude", "-p", "--verbose", "--model", model_alias, "--output-format", "stream-json",
  "--dangerously-skip-permissions", "--session-id", session_uuid, ...extra_args]`. There is no `--settings` or
  `--include-hook-events` flag today. Adding either is a localized one-line change.
- **The stream-JSON parser** at `src/sase/llm_provider/_subprocess_claude.py:_process_json_line` currently dispatches
  on `event.get("type") in ("assistant", "error", "result")` and silently drops everything else. With
  `--include-hook-events`, lifecycle events arrive in the same stream and would be dropped at the same call site.
  Strategy B extends this dispatcher.
- **Zero tool-call observability today.** Search across the repo finds no matches for `tool_use_id`, `PostToolUse`,
  `PreToolUse`, or `tool_calls`. There is no fixture file to model new tests on directly, but the
  `tests/test_commit_stop_hook.py` pattern (JSON stdin → JSONL append) maps cleanly.
- **Thinking-panel migration footprint** is concentrated in `src/sase/ace/tui/thinking/parser.py`,
  `src/sase/ace/tui/thinking/session_resolver.py`, `src/sase/ace/tui/widgets/thinking_panel.py`, and the
  `DetailPanelMode` enum at `src/sase/ace/tui/widgets/_agent_detail_panels.py:21-26`. Rename to a tools surface, keep
  the existing panel-mode machinery.
- **All four supported runtimes are uniform.** Gemini, Codex, Qwen, and Claude each invoke a stream-json mode and each
  log interrupts to `SASE_ARTIFACTS_DIR/interrupt_log.jsonl`. There is no runtime-only branching, and the `AGENTS.md`
  rule ("Uniform Agent Runtimes") explicitly forbids it. The panel contract has to be runtime-neutral; only the
  capture adapter is runtime-specific.

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

There is one subtlety: `SASE_ARTIFACTS_DIR` and `SASE_AGENT_TIMESTAMP` are republished **per phase** in
`run_agent_exec._publish_phase_env`, not per agent. Followup phases (Q&A, feedback, coder) mint fresh timestamped
directories. The panel will therefore see a `tool_calls.jsonl` per phase. The Tools panel data adapter must aggregate
across phases keyed on `SASE_AGENT_ROOT_TIMESTAMP` to render the full timeline for one logical agent row. The thinking
panel already has analogous logic in `session_resolver.py`; the same pattern applies.

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

### Strategy B (recommended for MVP)

1. Add `--include-hook-events` to the Claude argv in `src/sase/llm_provider/claude.py` (around line 181).
2. Extend `src/sase/llm_provider/_subprocess_claude.py:_process_json_line` to recognize `hook_event_name`-bearing events
   (`PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`) and forward them to a new
   `tool_calls_writer` module.
3. The writer normalizes each event to the artifact schema below, then appends one JSON line to
   `<SASE_ARTIFACTS_DIR>/tool_calls.jsonl` under `fcntl.flock` (reusing the
   `src/sase/scripts/sase_commit_stop_hook.py:28-33` pattern). Failures should be swallowed and surfaced via a small
   `tool_calls_writer_errors.jsonl` rather than propagated up.
4. Add a parser module that reads `tool_calls.jsonl` across the agent's phase directories (aggregated by
   `SASE_AGENT_ROOT_TIMESTAMP`), tolerates malformed lines, sorts by `recorded_at` then `tool_use_id`, and returns
   `ToolCallEntry` objects.
5. Replace the thinking panel widget with a tools panel using the existing `AgentDetail` secondary-panel machinery
   (`DetailPanelMode.THINKING` → `DetailPanelMode.TOOLS`).
6. Update footer/help labels, tests, and PNG snapshots. Model new tests on `tests/test_commit_stop_hook.py` (JSONL
   append) and `tests/test_axe_run_agent_exec.py` (phase env publication).
7. Keep the transcript-based thinking parser around only if there is another consumer; otherwise remove it in a later
   cleanup after the UI migration is stable.

### Strategy A (fallback, when out-of-process capture is required)

1. Add a small hook command, probably `sase_tool_call_hook`, under `src/sase/scripts/`. Exec form
   (`{"command": "sase_tool_call_hook", "args": [], "async": true, "timeout": 5}`).
2. Gate the hook on `SASE_ARTIFACTS_DIR`; exit `0` when absent.
3. Register the hook via `claude --settings '<inline-json>'` from `_run_subprocess` for events `PostToolUse`,
   `PostToolUseFailure`, and (if subagent grouping is needed) `SubagentStart` / `SubagentStop`.
4. Reuse steps 3–7 from Strategy B for the writer, reader, and panel. The artifact schema is identical.

## Hook Registration Options

If we adopt **Strategy A**, there are now four realistic install vehicles, not two. Ranked:

1. **`claude --settings '<inline-json>'`** (recommended for Strategy A). Pass an ad-hoc settings JSON string on the
   command line from `src/sase/llm_provider/claude.py:_run_subprocess`. No filesystem mutation, no setup/cleanup, no
   risk of leftover state if SASE crashes, and the hook is invisible to ordinary `claude` invocations the user makes
   outside SASE. The same flag also accepts a path if the JSON gets too large to inline.
2. **User-level hook in `~/.claude/settings.json`**, gated by `SASE_ARTIFACTS_DIR` (the previous-research default).
   Works, but mutates a user-owned config file and shows up in `/hooks` for every Claude session forever. Disabled by
   `disableAllHooks` and by enterprise `allowManagedHooksOnly`.
3. **SASE Claude plugin shipping `hooks/hooks.json`.** Users opt in by enabling the plugin. Cleanest UX/discoverability
   story (`/hooks` shows source `Plugin`), but requires SASE to ship + version a Claude Code plugin, which is a bigger
   investment than the panel itself.
4. **Per-workspace `.claude/settings.local.json` merge.** Mutates each ephemeral `sase_<N>` workspace, needs
   non-destructive merge/restore logic around user-owned local settings, and breaks if the workspace was not cloned by
   SASE. Avoid.

**Strategy B** does not need any of this: the only knob is appending `--include-hook-events` to the existing
`["claude", "-p", "--verbose", "--output-format", "stream-json", ...]` argv at
`src/sase/llm_provider/claude.py:_run_subprocess`.

If we pick option 2, the global hook can be safe because it is no-op outside SASE:

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

If we want the hook command to be self-contained (option 1, exec form, no shell):

```json
{
  "type": "command",
  "command": "sase_tool_call_hook",
  "args": [],
  "timeout": 5,
  "async": true
}
```

`async: true` is recommended once the logger is stable so a slow write never adds to Claude's per-tool latency.

## Risks And Decisions

### Parallel tool ordering

`PostToolUse` hooks can run concurrently for parallel tool calls (the docs explicitly note this). Under Strategy A, the
writer must use `recorded_at`, `tool_use_id`, and a monotonic sequence assigned under the file lock. Under Strategy B,
events arrive serialized on the single stdout pipe Claude writes, so the parser sees them in arrival order with no
inter-process race. If exact batch grouping matters, add `PostToolBatch` later.

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

### Phase vs. agent aggregation

`SASE_ARTIFACTS_DIR` is per-phase (see `run_agent_exec._publish_phase_env`). One logical agent row can have several
phase directories, each with its own `tool_calls.jsonl`. The reader must aggregate by `SASE_AGENT_ROOT_TIMESTAMP`.
The thinking panel's `session_resolver.py` already solves the equivalent problem; reuse the same shape.

### `disableAllHooks` and managed policy

Strategy A is silently disabled if any settings layer sets `"disableAllHooks": true`, and entirely disabled by
enterprise `"allowManagedHooksOnly": true`. We need a UX answer for "tool panel is empty because hooks are off" —
either detect at SASE launch (parse the user's merged settings) and surface a one-time warning, or fall back to
Strategy B automatically. Strategy B has no equivalent failure mode.

### `tool_response` shape divergence

`PostToolUse.tool_response` is the tool's structured Output object; `PostToolBatch.tool_calls[i].tool_response` is the
serialized string/blocks the model actually sees. They are different shapes. The normalizer must branch on the source
event before extracting previews — e.g. `Bash` Output has `stdout`/`stderr`/`interrupted`/`isImage`, while the
serialized form is a single string.

### MCP tools

MCP tool calls arrive in `PostToolUse` with names like `mcp__memory__create_entities`. The panel's display label
should strip `mcp__` and split server/tool for readability, and the redaction policy should default to **input keys
only** for unknown MCP tools (we cannot enumerate every server's schema).

### `updatedToolOutput` is out of scope for MVP

`PostToolUse` hooks can rewrite the tool result Claude sees. Tempting for redaction (e.g. scrubbing secrets from Bash
stdout), but with Strategy B we cannot use it, and even under Strategy A the failure mode is bad — a malformed
replacement object can make Claude proceed on false assumptions. Defer until there is a concrete redaction policy
worth that risk.

## Open Questions

- **Strategy A vs Strategy B for the MVP.** Strategy B (extend stream-json with `--include-hook-events`) is the
  recommendation above, but Strategy A buys the ability to capture tool calls from Claude sessions SASE did not spawn,
  and is the only path that supports `updatedToolOutput`-based redaction later. Worth confirming we never want either.
- **Do we land an installer command anyway?** Even with Strategy B, SASE may want `sase claude install-hooks` so that
  the commit stop hook (which today relies on user-maintained settings) is also a one-line install. Decoupled from this
  panel, but the design is adjacent.
- **Should the artifact be one `tool_calls.jsonl` per phase or one per agent?** Per-phase matches `SASE_ARTIFACTS_DIR`'s
  existing semantics and avoids cross-phase locking. Per-agent simplifies the reader. Per-phase + aggregation in the
  adapter is the safer default.
- **Subagent grouping.** Show `Task`/`Agent` subagent calls inline in the parent's timeline (using `agent_id`) or
  indent under a collapsible subagent row? The latter is more useful but more UI work.
- **Failed-permission visibility.** Should `PermissionDenied` (auto-mode denial) and `PreToolUse`-blocked attempts
  appear in the panel? They are useful for debugging auto-mode rules but noisy in the default view.
- **Archival.** Should archived/dismissed agents preserve `tool_calls.jsonl` with their artifact bundle? Almost
  certainly yes — the panel becomes a primary debugging surface for failed runs.
- **Strategy parity for Gemini/Qwen/Codex.** Each runtime has its own stream-json mode. Extending Strategy B uniformly
  is straightforward; Strategy A requires per-runtime hook plumbing, which Gemini/Codex/Qwen may or may not support
  identically. Audit before any cross-runtime work.

## Bottom Line Recommendation

Build the Tools panel around a SASE-owned per-phase `tool_calls.jsonl` artifact with a runtime-neutral schema. For the
Claude MVP, **populate it via Strategy B**: pass `--include-hook-events` to Claude's existing `stream-json` invocation
and extend `src/sase/llm_provider/_subprocess_claude.py:_process_json_line` to fold `PostToolUse` /
`PostToolUseFailure` / `SubagentStart` / `SubagentStop` events into the artifact alongside the existing `assistant` /
`error` / `result` dispatch. No hook installer, no global Claude settings mutation, no exposure to `disableAllHooks` or
managed policy, and runtime parity with Gemini/Qwen/Codex follows naturally.

Keep Strategy A (`claude --settings '<inline-json>'` registering a `sase_tool_call_hook` command) as a documented
fallback for a future iteration that needs (a) capture from Claude sessions SASE did not spawn, or (b)
`updatedToolOutput`-based redaction. The JSONL schema, panel UI, and reader/adapter are identical under both
strategies, so the switch cost is small.

This gives the Agents tab a more actionable panel than thinking output, avoids fragile transcript matching, and creates
a durable artifact that can be reused by archive views, mobile, and future runtime adapters.

## Sources

External Claude docs (verified 2026-05-14):

- Claude Code hooks reference: <https://code.claude.com/docs/en/hooks>
- Claude Code hooks guide: <https://code.claude.com/docs/en/hooks-guide>
- Claude Code settings/configuration: <https://code.claude.com/docs/en/configuration>
- Claude Code environment variables: <https://code.claude.com/docs/en/env-vars>
- Claude Code CLI reference: `claude --help` (flags `--settings`, `--include-hook-events`, `--bare`,
  `--append-system-prompt`, `--exclude-dynamic-system-prompt-sections`, `--output-format`)

In-repo code references (file + symbol):

- Current Claude provider subprocess invocation: `src/sase/llm_provider/claude.py` (`_run_subprocess` ~line 246) and
  the argv built around line 181 with `--output-format stream-json`.
- Stream-JSON parser to extend for Strategy B: `src/sase/llm_provider/_subprocess_claude.py`
  (`_process_json_line`, `stream_and_parse_json_output`).
- Existing fcntl-locked JSONL append pattern: `src/sase/scripts/sase_commit_stop_hook.py:28-33`.
- Runtime detection pattern (env-var-based, identical for all four runtimes):
  `sase_commit_stop_hook.py:_resolve_project_dir`.
- Per-phase env publication: `src/sase/axe/run_agent_exec.py:_publish_phase_env` (`SASE_ARTIFACTS_DIR`,
  `SASE_AGENT_TIMESTAMP`, `SASE_AGENT_ROOT_TIMESTAMP`).
- Artifact directory shape: `src/sase/artifacts.py`.
- Thinking-panel migration footprint: `src/sase/ace/tui/thinking/parser.py`,
  `src/sase/ace/tui/thinking/session_resolver.py`, `src/sase/ace/tui/widgets/thinking_panel.py`,
  `src/sase/ace/tui/widgets/agent_detail.py`, `src/sase/ace/tui/widgets/_agent_detail_panels.py`
  (`DetailPanelMode` enum at lines 21-26).
- Current thinking panel plan: `sdd/epics/202602/claude_thinking_panel.md`.
- Test patterns to model the new tool-call tests on: `tests/test_commit_stop_hook.py`,
  `tests/test_axe_run_agent_exec.py`, `tests/test_llm_provider_claude_thinking.py`.
- Runtime uniformity rule: `memory/short/gotchas.md` ("Uniform Agent Runtimes").
- Rust core backend boundary rule (for the parser if it ever leaves Python): `memory/short/rust_core_backend_boundary.md`.

## Addendum (2026-05-14): Strategy B is insufficient alone

After implementing Strategy B as originally written, live captures showed `tool_calls.jsonl` never being
populated for normal Claude runs. Two root causes converged:

1. The on-the-wire field name is `hook_event` (not `hook_event_name`), and hook events arrive wrapped as
   `type: "system"`, `subtype: "hook_response"` — not the bare hook-input shape the writer was originally
   built to consume.
2. More importantly, `--include-hook-events` only surfaces lifecycle events for hooks the user has actually
   registered. Most users have no `PostToolUse` hook installed, so the flag emits no tool-call events at
   all for real runs.

Resolution: the capture layer now reads inline `assistant.content[].tool_use` blocks paired with
`user.content[].tool_result` blocks (plus the top-level `tool_use_result` envelope) as the canonical source
of every tool call. Hook events surfaced via `--include-hook-events` are kept as supplemental enrichment
(durations, subagent boundaries, permission denials), not as the primary data source. The artifact schema
was bumped to v2 with new `ToolUse` (start) and `ToolResult` (end) event names that the reader collapses
into a single timeline entry per `tool_use_id`. See `sdd/tales/202605/tools_panel_missing_calls.md` for the
full diagnosis and plan.
