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
(`src/sase/ace/tui/models/agent.py:466`). Non-agent workflow entries cycle only between files/metadata.

Panel cycling lives in `src/sase/ace/tui/widgets/_agent_detail_panels.py`:

- `toggle_tools()` advances `AUTO -> TOOLS -> INFO -> AUTO` for agent entries (`_agent_detail_panels.py:78`).
- Applying `DetailPanelMode.TOOLS` hides the file panel, shows `#agent-tools-scroll`, and calls
  `tools_panel.update_display(agent)` (`_agent_detail_panels.py:141`).
- `ToolsVisibilityChanged` feeds the prompt border subtitle. `has_tools` is based on `bool(entries)`, so both "no
  artifact" (`None`) and "artifact exists but no usable rows" (`[]`) render as an empty tools indicator
  (`tools_panel.py:336`, `_agent_detail_panels.py:227`).

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
- Accepts `schema_version` 1, 2, and 3 (`reader.py:24`).
- Converts each line to a `ToolCallEntry` with display helpers for `display_tool_name`, `compact_target`, and `detail`
  (`reader.py:29`).
- Sorts by `recorded_at`, file order, line number, and `tool_use_id` (`reader.py:118`).
- Prefers Claude hook records (`source == "hook"`, schema v3) over stream records for the same `(runtime,
  tool_use_id)` because hooks carry richer fields and exact durations (`reader.py:235`).
- Collapses `ToolUse` plus `ToolResult` pairs with the same runtime, `tool_use_id`, and scope (`session_id` or artifact
  directory) into one rendered row. Orphan `ToolUse` rows remain visible as `pending` (`reader.py:259`).

Status derivation is tolerant: known status strings are used directly; failed/error maps to `failure`,
cancelled/canceled maps to `interrupted`, in-progress/running maps to `pending`, and response summaries can also imply
failure or interruption (`reader.py:196`).

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
- Manual refresh cancels any running worker, marks cached content as stale, invalidates the mtime watermark, and starts
  a new worker (`tools_panel.py:272`).

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
- Stream records use schema v2; Claude hook records use schema v3 (`_tool_call_common.py:12`).
- Inputs and responses are bounded and redacted by default. `SASE_TOOL_LOG_FULL=1` writes raw JSON-safe values for
  explicit debugging (`_tool_call_common.py:42`, `_tool_call_common.py:99`).
- Bash command summaries redact assignments whose variable names look secret-like (`TOKEN`, `KEY`, `SECRET`,
  `PASSWORD`, `PASS`, `AUTH`) (`_tool_call_common.py:33`).

Provider parser integration:

- Claude stream parser calls `append_claude_tool_call_event(event)` for every parsed stream event before normal
  assistant/result handling (`src/sase/llm_provider/_subprocess_claude.py:90`). Managed Claude runs also install
  `PreToolUse`/`PostToolUse` hooks via `claude_hooks_session()`; the hook command is `sase_claude_tool_hook`, which
  appends schema-v3 rows from hook stdin payloads (`src/sase/llm_provider/_claude_hooks.py:1`,
  `src/sase/scripts/sase_claude_tool_hook.py:1`).
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
not break an agent run (`src/sase/llm_provider/_tool_call_io.py`).

## Practical Implications

- An empty Tools indicator usually means the TUI saw `None` or `[]`, not necessarily that the panel failed. Check
  whether the selected row is an `is_agent_entry`, whether `agent.get_artifacts_dir()` resolves, and whether any related
  directory contains `tool_calls.jsonl`.
- Pending rows are expected while a provider has emitted a start event but not a result event.
- Claude can double-produce stream and hook records; the reader suppresses stream duplicates when a matching hook row
  exists.
- If follow-up phases or retries write tool artifacts in sibling timestamp directories, they appear only when metadata
  links them through the lineage fields the reader recognizes.
- The panel is provider-neutral. New runtime support should be added by writing normalized artifacts, not by adding
  runtime branches to the TUI.

## Tests Worth Reading

- `tests/ace/tui/widgets/test_tools_panel.py` covers cache/worker/display behavior.
- `tests/llm_provider/test_tool_calls_writer.py` and `tests/llm_provider/test_tool_calls_hook_collector.py` cover Claude
  stream and hook artifact writing.
- `tests/llm_provider/test_usage_parsing.py` covers Codex normalization.
- `tests/llm_provider/test_gemini_stream_parser.py` and `tests/test_llm_provider_qwen.py` cover Gemini/Qwen tool event
  normalization and subprocess parsing.

