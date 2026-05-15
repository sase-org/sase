---
create_time: 2026-05-15 09:56:45
bead_id: sase-3m
tier: epic
status: done
prompt: sdd/prompts/202605/tools_panel_gemini_qwen.md
---
# Tools Panel Support for Gemini and Qwen

## Context

The Agents tab Tools panel is already provider-neutral at the TUI layer: it reads normalized `tool_calls.jsonl`
artifacts through `sase.ace.tui.tools.reader` and refreshes the panel with a Textual thread worker from
`AgentToolsPanel.update_display()` / `refresh_tools()`. That means the remaining work is mostly in the LLM provider
stream parsers and artifact writers.

Claude currently has the richest path: SASE installs Claude `PreToolUse` / `PostToolUse` hooks for managed workspaces,
and the Claude stream parser remains as a fallback. Codex writes normalized tool rows from its NDJSON stream in
`_tool_call_codex.py` and `_subprocess_codex.py`; the TUI read path is asynchronous, but this should be explicitly
rechecked and pinned so future Codex-related changes do not reintroduce event-loop filesystem walks.

Gemini currently runs through `GeminiProvider._run_subprocess()` with PTY-backed plain text streaming, so it has no
structured tool-call extraction. Gemini CLI docs now describe headless `--output-format stream-json` events including
`tool_use` and `tool_result`.

Qwen already runs headless with `--input-format text --output-format stream-json`; its parser extracts assistant text
and usage, but does not yet normalize tool events into `tool_calls.jsonl`. Qwen docs describe stream-JSON messages and
tool-usage stats; the implementation should capture the actual event shapes used by Qwen Code for tool calls and handle
schema drift defensively.

## Phase 1: Shared Contract and Async Guardrails

Owner: Agent 1.

Goal: make the implementation target unambiguous before adding new providers.

Tasks:

- Audit `src/sase/ace/tui/widgets/tools_panel.py`, `src/sase/ace/tui/tools/reader.py`,
  `src/sase/llm_provider/_subprocess_codex.py`, and `src/sase/llm_provider/_tool_call_codex.py`.
- Confirm that all expensive Tools panel reads, sibling artifact discovery, and mtime checks happen in
  `run_worker(..., thread=True)` and not on the Textual event loop.
- Add or strengthen regression coverage if any UI-thread path is still unpinned, especially for warm-cache Codex appends
  and missing-artifact cases.
- Define the provider-normalized artifact contract for Gemini/Qwen: `schema_version`, `recorded_at`, `runtime`,
  `source`, `event`, `status`, `tool_name`, `tool_use_id`, `tool_input_summary`, `tool_response_summary`, optional
  `duration_ms`, `session_id`, `cwd`, and diagnostic behavior.
- Decide whether generic helpers are worth extracting from `_tool_call_codex.py` for start-time tracking, status
  derivation, tool-name mapping, and diagnostics. Keep this small; avoid a broad refactor unless it reduces duplication
  for both Gemini and Qwen.

Deliverables:

- Tests proving Tools panel refresh remains asynchronous and Codex does not force UI-thread artifact reads.
- A short implementation note in the final response for the next phase agents describing any shared helper choices.

Validation:

- Targeted tests for the TUI tools panel and Codex tool-call reader/writer.
- No visual snapshot updates expected unless an existing async guard test requires fixture adjustment.

## Phase 2: Gemini Stream-JSON Tool Artifacts

Owner: Agent 2.

Goal: make Gemini runs produce normalized `tool_calls.jsonl` rows without regressing live reply streaming.

Tasks:

- Replace or augment Gemini’s PTY/plain-text subprocess path with a structured headless path using Gemini CLI
  `--output-format stream-json`.
- Add a focused parser module, likely `src/sase/llm_provider/_subprocess_gemini.py`, mirroring the Qwen/Codex split:
  nonblocking JSONL reads, assistant text extraction, result/error diagnostics, live reply writes, and usage artifact
  support if Gemini exposes stats in the final `result` event.
- Add `src/sase/llm_provider/_tool_call_gemini.py` with best-effort normalization for Gemini `tool_use` and
  `tool_result` events. Map common tools to SASE display names (`Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`,
  `WebFetch`/`WebSearch` where possible), preserve unknown tool names, and use existing input/response summarizers for
  redaction and bounded previews.
- Update `src/sase/llm_provider/_tool_calls.py` exports and `GeminiProvider._run_subprocess()` to call the new parser.
- Preserve interrupt behavior and prompt reconstruction across cycles.
- Write diagnostics to `tool_calls_writer_errors.jsonl` for malformed tool events instead of raising from the parser.
- Keep writes synchronous inside the provider subprocess parser; this does not block the TUI. Do not add TUI-side
  synchronous reads.

Deliverables:

- Gemini provider emits `tool_calls.jsonl` during tool use.
- Existing Gemini live reply behavior remains available through `live_reply.md`.
- Unit tests and subprocess fixture tests cover text, result, error, `tool_use`, `tool_result`, malformed lines, and
  missing `SASE_ARTIFACTS_DIR`.

Validation:

- Targeted Gemini parser/provider tests.
- TUI reader test showing Gemini `ToolUse` + `ToolResult` pairs collapse into one Tools panel row.

## Phase 3: Qwen Stream-JSON Tool Artifacts

Owner: Agent 3.

Goal: add Qwen tool-call artifact writing using the existing stream-JSON subprocess path.

Tasks:

- Capture or synthesize representative Qwen stream events for tool starts/results. Prefer real fixture JSONL if the CLI
  is available; otherwise use official-doc-compatible synthetic fixtures and document that they are synthetic.
- Add `src/sase/llm_provider/_tool_call_qwen.py` with a defensive normalizer for Qwen tool events. Support the observed
  event shapes first, and tolerate alternates such as nested `message.content` tool blocks, explicit tool-call event
  types, or result events with tool summary stats.
- Wire `_process_qwen_json_line()` to call the Qwen tool writer before normal text/result handling, just as Claude and
  Codex do.
- Preserve existing Qwen assistant/result text extraction and usage accumulation.
- Keep malformed/unsupported tool events as diagnostics, not parser failures.
- Avoid introducing runtime-specific TUI logic. Qwen should produce the same normalized artifact rows consumed by the
  existing reader.

Deliverables:

- Qwen provider emits `tool_calls.jsonl` during tool use.
- Existing Qwen tests still pass, including command construction, usage extraction, and fake CLI artifact writing.
- Fixture documentation explains real vs synthetic Qwen stream shapes.

Validation:

- Targeted Qwen parser/provider tests.
- TUI reader test showing Qwen rows collapse and display with correct status, target, and detail.

## Phase 4: Cross-Provider Integration and Polish

Owner: Agent 4.

Goal: verify Gemini, Qwen, Claude, and Codex all flow through one Tools panel contract.

Tasks:

- Add a cross-provider test matrix for normalized `tool_calls.jsonl` rows: Claude hook/stream, Codex stream, Gemini
  stream, and Qwen stream.
- Add or update visual/snapshot coverage only if Gemini/Qwen expose a display edge case not covered by existing tool
  panel snapshots.
- Run targeted tests first, then the repository check required by project memory after source changes: `just install` if
  needed, then `just check`.
- Review `tool_calls_writer_errors.jsonl` behavior so unsupported provider events are discoverable without breaking
  agent runs.
- Confirm no memory files are modified.

Deliverables:

- One provider-neutral Tools panel behavior across Claude, Codex, Gemini, and Qwen.
- Test coverage that future agents can use as a contract for additional providers.
- Final summary listing any unsupported provider event shapes left as diagnostics.

Validation:

- `just check` after all code changes.
- Optional manual smoke runs with fake CLIs or real CLIs when credentials and binaries are available.

## Risks and Open Questions

- Gemini’s structured output support is newer than the current PTY path; the Gemini phase should keep the command
  construction conservative and test it through a fake CLI before relying on a real binary.
- Qwen stream-JSON tool event shape may vary by CLI version and flags. The Qwen phase should prefer real captured
  fixtures when possible and make unsupported shapes diagnostic-only.
- If either provider emits only aggregate tool stats and not per-tool events for some versions, the implementation
  should not invent fake detailed rows. It should write diagnostics or no rows until a per-tool event is observed.
- The TUI is already provider-neutral; adding provider branches in the Tools panel would be a regression.
