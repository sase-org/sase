# Tools Panel Population Path

Research date: 2026-05-15

## Question

How does the Agents tab Tools panel populate its contents?

## Short Answer

The Tools panel is a projection of normalized per-agent artifacts, not a direct live query to provider APIs. Provider
subprocess parsers and Claude hooks append JSONL records to the current phase's
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl`. When the user cycles an agent detail view to the Tools panel, the TUI resolves
the selected agent's artifacts directory, reads that file plus related sibling phase/retry artifact directories, parses
supported schema versions into `ToolCallEntry` objects, deduplicates and collapses start/result pairs, then renders a
Rich timeline.

The core path is:

```text
provider stream or hook
  -> append_*_tool_call_event(...)
  -> $SASE_ARTIFACTS_DIR/tool_calls.jsonl
  -> Agent.get_artifacts_dir()
  -> read_tool_calls_for_agent(agent)
  -> AgentToolsPanel._build_tools_timeline_text(...)
```

## UI Entry Point

The panel is available only for rows where `Agent.is_agent_entry` is true: running agent rows, workflow rows that appear
as agents, and workflow child steps whose `step_type` is `agent`
(`src/sase/ace/tui/models/agent.py:466`). Non-agent workflow entries cycle only between files/metadata. There is no
aggregator that rolls child-step tools up to a workflow parent row — each agent entry resolves its own artifact
directory.

Panel cycling lives in `src/sase/ace/tui/widgets/_agent_detail_panels.py`:

- `toggle_tools()` advances `AUTO -> TOOLS -> INFO -> AUTO` for agent entries (`_agent_detail_panels.py:78`).
- Applying `DetailPanelMode.TOOLS` hides the file panel, shows `#agent-tools-scroll`, and calls
  `tools_panel.update_display(agent)` (`_agent_detail_panels.py:141`).
- `ToolsVisibilityChanged` feeds the prompt border subtitle. `has_tools` is based on `bool(entries)`, so both "no
  artifact" (`None`) and "artifact exists but no usable rows" (`[]`) render as an empty tools indicator
  (`tools_panel.py:336`, `_agent_detail_panels.py:227`).

### Preflight probe and selection lifecycle

`AgentDetail._update_display_body` calls `tools_panel.update_display(agent, ...)` even when the visible mode is `AUTO`
or `INFO`, so the cache and `_has_tools_content` flag are warm before the user toggles to `TOOLS`
(`src/sase/ace/tui/widgets/agent_detail.py:189`). The probe is skipped only when the same agent is still selected
and the panel is in `INFO` mode (the worker would just re-confirm what it already showed). Attempt-pinned views skip
tools entirely because per-attempt tool history cannot be reconstructed from archived snapshots
(`agent_detail.py:176`).

When no agent is selected, `AgentDetail.show_empty()` calls `tools_panel.show_empty()`, which renders
`No agent selected`, clears `_has_displayed_content`, and prevents further loading-state flicker
(`tools_panel.py:306`, `agent_detail.py:261`). Editor/export actions on the panel call `get_tools_text()` to read a
plain-markdown rendering of the most recent fetch (`tools_panel.py:300`, `agent_detail.py:378`).

## Artifact Directory Resolution

The TUI starts from `agent.get_artifacts_dir()` (`src/sase/ace/tui/models/agent.py:492`), implemented in
`src/sase/ace/tui/models/agent_artifacts.py`.

Resolution order:

1. Use `agent.artifacts_dir` directly when marker/loading code provided an existing directory
   (`agent_artifacts.py:16`).
2. Derive the project name from `agent.project_file`.
3. Derive the workflow artifact bucket from the row type and workflow label, e.g. `ace-run`, `crs`, `fix-hook`,
   `workflow-<name>`, or mentor-specific buckets (`agent_artifacts.py:31`).
4. Extract a 14-digit timestamp from `agent.raw_suffix` and construct
   `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` (`agent_artifacts.py:84`).

Agent execution publishes the active phase directory with `_publish_phase_env()`:
`SASE_ARTIFACTS_DIR=<artifacts_dir>` and `SASE_AGENT_TIMESTAMP=<timestamp>`
(`src/sase/axe/run_agent_exec.py:38`). Follow-up phases such as Q&A, feedback, coder, and retry can therefore write
their own `tool_calls.jsonl` under sibling timestamp directories.

## Reader Behavior

`src/sase/ace/tui/tools/reader.py` is the authoritative read adapter.

`read_tool_calls_for_agent(agent)`:

- Returns `None` when the agent has no artifacts directory or no related `tool_calls.jsonl`.
- Returns `[]` when one or more files exist but no supported/parseable records remain.
- Discovers related artifact directories before reading (`reader.py:89`).

Related directory discovery is important. `discover_related_tool_artifact_dirs()` always reads the current artifact
directory first, then walks siblings under the same parent directory and includes only directories whose
`agent_meta.json` or `done.json` links to the same lineage (`retry_chain_root_timestamp`, `retry_of_timestamp`,
`parent_timestamp`, or the current directory name). This is how the panel can show tool calls across retry or phase
chains without hard-coding provider behavior (`reader.py:130`).

Parsing rules:

- Reads `tool_calls.jsonl` from each related directory.
- Accepts `schema_version` 1, 2, and 3 (`reader.py:24`). Lines with any other schema, lines that aren't JSON objects,
  and lines that fail `json.loads` are silently dropped (`reader.py:426`); whole-file `OSError` returns `[]`
  (`reader.py:421`). The `schema_version: 1` slot is retained only for back-compat with older artifacts — no current
  writer emits it (the `schema_version: 1` in `src/sase/llm_provider/registry.py:101` is an unrelated metadata payload,
  not a tool-call record).
- Converts each line to a `ToolCallEntry` with display helpers for `display_tool_name`, `compact_target`, and `detail`
  (`reader.py:29`).
- Sorts by `recorded_at`, file order, line number, and `tool_use_id` (`reader.py:118`). `recorded_at` strings that
  fail to parse fall back to `datetime.max`, pushing them to the end deterministically (`reader.py:534`).
- Prefers Claude hook records (`source == "hook"`, schema v3) over stream records for the same `(runtime,
  tool_use_id)` because hooks carry richer fields and exact durations (`reader.py:235`).
- Collapses `ToolUse` plus `ToolResult` pairs with the same runtime, `tool_use_id`, and scope (`session_id` or artifact
  directory) into one rendered row. Orphan `ToolUse` rows remain visible as `pending` (`reader.py:259`). The scope
  component of the pair key (`session_id or artifact_dir`) ensures cross-session id collisions can't accidentally
  collapse independent calls (`reader.py:288`).

Status derivation is tolerant: known status strings are used directly; failed/error maps to `failure`,
cancelled/canceled maps to `interrupted`, in-progress/running maps to `pending`, and response summaries can also imply
failure or interruption (`reader.py:196`). The precedence order, top to bottom: known string status, `is_interrupt`
flag, special-case events (`PostToolUseFailure` -> `failure`, `SubagentStart`/`SubagentStop` -> `subagent`,
`ToolUse` -> `pending`), then response-envelope hints (`interrupted`, `success: false`, `is_error: true`, `error`),
finally `success`.

## Panel Cache and Refresh

`AgentToolsPanel` keeps a process-global `_tools_cache` keyed by `cl_name`, `agent_type`, optional workspace number,
and `raw_suffix` (`src/sase/ace/tui/widgets/tools_panel.py:71`).

Refresh behavior:

- On display, warm cache is rendered immediately; otherwise the panel shows a loading message only if it previously had
  visible content (`tools_panel.py:237`).
- Actual artifact reads happen in a Textual worker with `thread=True`, so filesystem walking and JSONL reads stay off
  the event loop (`tools_panel.py:267`).
- Re-reads are throttled to at most once every 0.5 seconds per cache key (`tools_panel.py:23`, `tools_panel.py:254`).
- The worker caches discovered related directories, the parent directory mtime, and max mtime across all related
  `tool_calls.jsonl` files. If mtimes have not changed, it reuses prior entries (`tools_panel.py:353`).
- Manual refresh cancels any running worker, marks cached content as stale ("refreshing..." appended to the header),
  invalidates the mtime watermark, and starts a new worker (`tools_panel.py:272`).
- `on_worker_state_changed` re-renders from the freshest cache on `SUCCESS`, paints `Error fetching tool calls` on
  `ERROR`, and is a no-op on `CANCELLED` (`tools_panel.py:403`).
- Across re-renders the panel saves and restores the `VerticalScroll` Y position via
  `call_after_refresh` so the user's scrollback isn't reset every time the worker finishes
  (`tools_panel.py:323`, `tools_panel.py:415`).
- `ToolsVisibilityChanged` is only posted when the entries set actually changes (`tools_panel.py:419`); this keeps the
  prompt border subtitle stable across re-renders that don't shift visibility.

## Rendered Contents

`_build_tools_timeline_text()` renders:

- Empty states: `No tools artifact available` for `None`, `No tool calls recorded` for `[]`.
- Header: `TOOLS`, call count, failure count, interrupted count, and refresh timestamp.
- One row per normalized entry: local-time timestamp, status label, display tool name, compact target, duration, and
  optional detail preview (`tools_panel.py:132`).

Status labels:

| Internal status | Display |
| --- | --- |
| `success` | `ok` |
| `failure` | `fail` |
| `interrupted` | `stop` |
| `subagent` | `agent` |
| `pending` | `wait` |

Compact targets prefer `file_path`, `path`, `url`, `query`, `pattern`, `description`, then `command`, then
`subagent_type`; unknown tools fall back to visible input keys when no tool name is present (`reader.py:325`). Details
prefer explicit errors, response errors, Bash exit/output previews, response previews, and edit-length summaries
(`reader.py:353`).

## Writer Side

All provider writers share one normalized contract in `src/sase/llm_provider/_tool_call_common.py`:

- Required fields: `schema_version`, `recorded_at`, `runtime`, `source`, `event`, `status`
  (`_tool_call_common.py:16`).
- Common optional fields: `tool_name`, `tool_use_id`, `tool_input_summary`, `tool_response_summary`, `duration_ms`,
  `session_id`, `cwd` (`_tool_call_common.py:24`).
- Schema versions in use today: **v2** for stream-derived records (`source: "stream"`, the default for every provider's
  stream parser); **v3** for Claude hook records (`source: "hook"`, written only by the `sase_claude_tool_hook` CLI).
  Schema v1 is recognized but unused (`_tool_call_common.py:12`, `_tool_call_claude.py:110`).
- Inputs and responses are bounded and redacted by default. `SASE_TOOL_LOG_FULL=1` writes raw JSON-safe values for
  explicit debugging (`_tool_call_common.py:42`, `_tool_call_common.py:99`).
- Bash command summaries redact only environment-style `NAME=value` assignments where the variable name contains
  `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `PASS`, or `AUTH` (case-insensitive). Inline `--password=...` flags or
  command-line args without an `=` are not touched (`_tool_call_common.py:33`, `_tool_call_common.py:277`).
- Per-tool input summaries are explicit: `Bash`, `Read`, `Grep`, `Glob`, `Write`, `Edit`, `MultiEdit`, `WebFetch`,
  `WebSearch`, `Task`/`Agent`. Unknown tools fall back to `{"input_keys": [...]}` listing up to 20 sorted top-level
  keys (`_tool_call_common.py:42`).
- `ToolCallDurationTracker` provides best-effort start/end durations for stream parsers when a provider does not emit
  its own `duration_ms` (`_tool_call_common.py:341`).

Provider parser integration:

- Claude stream parser calls `append_claude_tool_call_event(event)` for every parsed stream event before normal
  assistant/result handling (`src/sase/llm_provider/_subprocess_claude.py:90`). It recognizes three event shapes
  (`_tool_call_claude.py:33`):
  - `type: "assistant"` with `message.content[].tool_use` blocks -> one `ToolUse` (pending) record per block.
  - `type: "user"` with `message.content[].tool_result` blocks -> one `ToolResult` record per block, drawing structured
    output from the top-level `tool_use_result` envelope when present.
  - `type: "system"` with `subtype: "hook_response"` (or `hook_started` for subagent events) and a `hook_event` in
    `{PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop}` -> a hook-event record. For tool-related hooks
    `hook_started` is suppressed to avoid double-counting (`_tool_call_claude.py:281`).
- Managed Claude runs also install `PreToolUse`/`PostToolUse` hooks via `claude_hooks_session()`; the hook command is
  `sase_claude_tool_hook`, which appends schema-v3 rows from hook stdin payloads
  (`src/sase/llm_provider/_claude_hooks.py:1`, `src/sase/scripts/sase_claude_tool_hook.py:1`). Hooks register only when
  a workspace env var is set (`SASE_GIT_WORKSPACE_DIR`, `SASE_CD_WORKSPACE_DIR`, or `SASE_ACTIVE_PROJECT_DIR`).
  Home-mode launches skip hook installation, leaving stream as the sole source (`_claude_hooks.py:46`).
- Codex parser calls `append_codex_tool_call_event(event)` for every NDJSON event. It maps `command_execution` to
  `Bash`, `file_change` to edit/write tools, named tool items to display names, and legacy completed
  `function_call` items to `FunctionCall` rows (`src/sase/llm_provider/_subprocess_codex.py:92`,
  `src/sase/llm_provider/_tool_call_codex.py:29`).
- Gemini parser calls `append_gemini_tool_call_event(event)` for every stream-json event and normalizes `tool_use` and
  `tool_result` shapes defensively (`src/sase/llm_provider/_subprocess_gemini.py:82`,
  `src/sase/llm_provider/_tool_call_gemini.py:26`).
- Qwen parser calls `append_qwen_tool_call_event(event)` for every stream-json event and supports Claude-style nested
  content blocks plus explicit top-level tool event variants (`src/sase/llm_provider/_subprocess_qwen.py:82`,
  `src/sase/llm_provider/_tool_call_qwen.py:39`).

Each writer no-ops when `SASE_ARTIFACTS_DIR` is missing. Malformed but recognizable tool events are diagnosed to
`tool_calls_writer_errors.jsonl`; writer exceptions are swallowed after a best-effort diagnostic, so tool logging should
not break an agent run (`src/sase/llm_provider/_tool_call_io.py`). The diagnostic file is also where the hook collector
records `invalid_json` payloads and where `claude_hooks_session` records `claude_hooks_skipped` /
`claude_hooks_restore_*` reasons (`_claude_hooks.py:179`, `sase_claude_tool_hook.py:33`).

### Hook session lifecycle (Claude)

`claude_hooks_session(workspace_dir)` is a context manager that merges SASE entries into
`<workspace>/.claude/settings.local.json` for the duration of an agent run (`_claude_hooks.py:187`):

- Each managed hook entry under `hooks.PreToolUse[]` and `hooks.PostToolUse[]` carries the sentinel
  `_sase_managed: "tool-call-collector"` so cleanup can prune only SASE entries and leave any user/project hooks
  untouched (`_claude_hooks.py:33`, `_claude_hooks.py:107`).
- Writes are atomic: payload is written to a temp file in the same directory with `os.fsync` then `os.replace`
  promotes it (`_claude_hooks.py:161`). A killed agent will not corrupt the settings file.
- The session yields `False` (caller treats this as "stream-only mode") when any of these hold:
  enabled flag is off, no workspace dir resolved (home-mode), existing JSON is malformed, or the settings file is
  unwritable. Each case writes a diagnostic line and returns without mutating user state.
- On exit (including exceptions) `_restore_settings` removes SASE entries; if the file did not exist before the session
  and only SASE entries were present, the file and possibly the `.claude/` directory are removed.

### Concurrency and durability

`_append_jsonl` (`src/sase/llm_provider/_tool_call_io.py:48`) takes a `fcntl.flock` exclusive lock on
`tool_calls.jsonl.lock` for every write. This serializes stream-parser writes, hook-collector subprocess writes, and
follow-up phase writes that share the same artifact directory. The reader does not take the lock, so it can race with
in-progress writes; partially-written lines are tolerated because `_parse_tool_call_line` drops anything that fails
`json.loads`.

## Practical Implications

- An empty Tools indicator usually means the TUI saw `None` or `[]`, not necessarily that the panel failed. Check
  whether the selected row is an `is_agent_entry`, whether `agent.get_artifacts_dir()` resolves, and whether any related
  directory contains `tool_calls.jsonl`.
- Pending rows are expected while a provider has emitted a start event but not a result event.
- Claude can double-produce stream and hook records; the reader suppresses stream duplicates when a matching hook row
  exists. Home-mode Claude runs skip hook installation, so only stream (schema v2) rows will appear.
- If follow-up phases or retries write tool artifacts in sibling timestamp directories, they appear only when metadata
  links them through the lineage fields the reader recognizes (`retry_chain_root_timestamp`, `retry_of_timestamp`,
  `parent_timestamp`).
- A diagnostic-heavy run is worth checking: if rows are missing, look at
  `<artifacts_dir>/tool_calls_writer_errors.jsonl` for reasons like `invalid_json`, `unsupported hook_event_name`,
  `claude_hooks_skipped`, or `claude_hooks_restore_failed`.
- The panel is provider-neutral. New runtime support should be added by writing normalized artifacts, not by adding
  runtime branches to the TUI.

## Tests Worth Reading

- `tests/ace/tui/widgets/test_tools_panel.py` — cache/worker/display behavior, including the stale-refresh indicator
  and scroll-position preservation.
- `tests/ace/tui/tools/test_reader_core.py` — sort, pair-collapse, hook-vs-stream precedence, scope key.
- `tests/ace/tui/tools/test_reader_hooks.py` — Claude schema-v3 parsing.
- `tests/ace/tui/tools/test_reader_codex.py`, `test_reader_qwen.py`, `test_reader_cross_provider.py` — provider-specific
  and cross-provider reader behavior.
- `tests/llm_provider/test_tool_calls_writer.py` and `tests/llm_provider/test_tool_calls_hook_collector.py` cover Claude
  stream and hook artifact writing, including secret redaction and `SASE_TOOL_LOG_FULL` raw-mode.
- `tests/llm_provider/test_usage_parsing.py` covers Codex normalization.
- `tests/llm_provider/test_gemini_stream_parser.py` and `tests/test_llm_provider_qwen.py` cover Gemini/Qwen tool event
  normalization and subprocess parsing.

