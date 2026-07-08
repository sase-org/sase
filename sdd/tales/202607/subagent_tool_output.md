---
create_time: 2026-07-07 21:09:18
status: done
prompt: sdd/prompts/202607/subagent_tool_output.md
---
# Plan: Capture & Surface Subagent (`Agent`/`Task`) Tool Output

## Problem

When an agent calls the `Agent`/`Task` tool to spawn a subagent, SASE records the tool call to `tool_calls.jsonl`, but
the subagent's actual output is thrown away. The user sees this most painfully in the **slow-tool-call report**
(`~/.sase/tool_call_reports/agent-*.md`), which renders:

```
## Recorded Output
No recorded output summary fields were available.

## Full Output (transcript)
Not recovered: transcript unavailable.
```

The same gap makes the in-TUI **Tools timeline** show nothing meaningful for subagent rows — no result detail, no
metadata, no preview. A subagent can run for minutes and burn tens of thousands of tokens, and none of its work product
is visible after the fact.

We want subagent tool calls to surface **useful, reliable, and beautifully-formatted output**: the subagent's final
message plus the rich run metadata the runtime already hands us.

## Root Cause

For a subagent tool call, two artifact records are written and later merged:

1. A `ToolUse` (start) record from the assistant event: `tool_name = "Agent"`,
   `tool_input_summary = {subagent_type, description, prompt_length}`.
2. A `ToolResult` (end) record from the user event. Its `tool_name` is `None` (the runtime's `tool_result` block does
   not echo the tool name), and its structured envelope (`toolUseResult`) is summarized by the **shared**
   `summarize_tool_response` helper.

The subagent result envelope actually contains everything we want:

| Field                                                 | Meaning                                                                                   |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `content: [{type:"text", text: "…"}]`                 | **The subagent's full final message** (list of text blocks)                               |
| `agentType`                                           | e.g. `Explore`                                                                            |
| `resolvedModel`                                       | e.g. `claude-opus-4-8`                                                                    |
| `status`                                              | e.g. `completed`                                                                          |
| `totalDurationMs`, `totalTokens`, `totalToolUseCount` | run cost/effort                                                                           |
| `usage`                                               | token breakdown (input / output / cache)                                                  |
| `toolStats`                                           | `readCount`, `searchCount`, `bashCount`, `editFileCount`, `linesAdded`, `linesRemoved`, … |
| `prompt`                                              | the full subagent prompt                                                                  |

But `_summarize_structured_response` (the default branch used when `tool_name` is `None`) only extracts `content` when
it is a **plain string**. For subagents `content` is a **list of blocks**, so it is silently dropped and the summary
collapses to just `{"response_keys": [...]}`. Because that summary is non-empty, the list-aware
`_summarize_tool_result_content` fallback never runs either.

Downstream, the report's transcript-recovery path can't rescue this: stream-json `ToolResult` records carry **no
`transcript_path`**, and reconstructing the parent transcript path from `session_id` + cwd is fragile and breaks across
SASE's ephemeral workspace clones.

**Conclusion:** the reliable fix is to capture the subagent output _into the artifact at record time_, in the shared
summarizer, so the data travels with the run and every consumer (report + TUI) benefits.

## Goals

1. Capture the subagent's final message and run metadata into `tool_response_summary` at record time.
2. Make the slow-tool report render a clean, scannable **Subagent** section plus the **full final message** — no more
   "No recorded output" / "transcript unavailable" dead ends for subagents.
3. Make the in-TUI Tools timeline show a useful compact detail line and expanded metadata + preview for subagent rows.
4. Keep it **runtime-uniform** (works through the shared summarizer, activates on envelope shape, no per-runtime
   branching) and **self-contained** (no dependency on external/rotating transcripts).

## Non-Goals

- Ingesting the separate per-subagent transcript file (`.../subagents/agent-*.jsonl`). It is location-dependent,
  per-runtime, and not needed — the final message + metadata are already in the result envelope the parent receives.
- Changing how non-subagent tools are summarized or reported.
- Moving tool-call summarization into the Rust core. Tool-call artifact summarization currently lives entirely in Python
  (`src/sase/llm_provider/_tool_call_common.py`) with no `sase_core` counterpart or binding; this change stays within
  that established Python layer. (Boundary noted as a deliberate scoping decision, not an oversight.)

## Design

### Layer 1 — Capture (foundational)

**Where:** `src/sase/llm_provider/_tool_call_common.py` (the shared `summarize_tool_response` /
`_summarize_structured_response`). Because Claude, Codex, and Qwen normalizers all route their result summaries through
this helper, the fix is automatically uniform.

**What:** Detect a subagent-result envelope by _shape_ — a mapping that carries an `agentType`/`agentId` identity
together with a `content` value that is a list of text blocks (or a string). When detected, emit a normalized,
well-named summary instead of the generic `response_keys` blob:

- `content_preview` — standard 512-char preview of the final message. This single field immediately lights up the
  _existing_ report "Recorded Output" logic and the _existing_ timeline preview keys (`content_preview` is already
  recognized by both), so even before any report/TUI changes land, the output stops being "unavailable."
- `content_full` — the **complete** final message, bounded by a new, generous cap (`_SUBAGENT_OUTPUT_LIMIT`, ~64 KiB,
  matching the report's existing recovered-output cap). This is the self-contained source the report uses for the full
  message. Truncation reuses the existing `...[truncated N chars]` marker convention so the report's truncation note
  keeps working.
- Normalized metadata: `agent_type`, `agent_status`, `resolved_model`, `total_duration_ms`, `total_tokens`,
  `total_tool_use_count`, and a bounded `tool_stats` sub-object (reads, searches, bash, edits, lines added/removed)
  drawn from `toolStats`.
- Keep `response_keys` for debuggability/parity.

Notes:

- Detection is shape-based, so runtimes whose subagent envelope matches benefit for free; runtimes with a different
  shape are unaffected (no metadata emitted, no regression).
- Secret handling is unchanged and consistent: the final message is model-authored prose, the same risk class as the
  file-content `content_preview` we already store for `Read`; Bash-command redaction is untouched. `content_full` reuses
  the same (non-redacting) preview/truncation path, just with a larger cap.
- Also make the list-of-blocks case a first-class extraction in the default response summarizer so a subagent result
  with no structured envelope (only a `tool_result` block whose `content` is a list of text blocks) still yields
  `content_preview`/`content_full` as a safety net.

### Layer 2 — Report (primary user-visible win)

**Where:** `src/sase/ace/tui/tools/report.py`.

For entries identified as subagent calls (post-merge the entry reliably has `tool_name in {"Agent", "Task"}`, and/or
`agent_type` present in the response summary):

- **New `## Subagent` section** — a compact, scannable metadata block rendered only when subagent metadata is present.
  Example shape:

  ```
  ## Subagent

  - **Type**: Explore | **Model**: claude-opus-4-8 | **Status**: completed
  - **Duration**: 1m 54s | **Tokens**: 72,178 | **Tool uses**: 22
  - **Tool stats**: 18 reads · 3 searches · 1 bash · 0 edits (+0 / -0 lines)
  ```

  Formatting reuses existing helpers (`format_long_duration`, thousands-separated integers) for consistency with the
  rest of the report.

- **`## Full Output` section** — prefer the captured `content_full` (labeled as the subagent's final message) and fall
  back to transcript recovery only when it is absent. This turns the current "transcript unavailable" dead end into the
  actual subagent report, reliably.

- Avoid duplication: for subagent entries, suppress the generic "Recorded Output" echo of `content_preview` (the full
  message already appears once under Full Output), and let the Subagent section carry the metadata. Non-subagent reports
  keep today's exact behavior.

### Layer 3 — In-TUI Tools timeline (the "beautiful everywhere" polish)

**Where:** `src/sase/ace/tui/tools/_entry.py` (compact detail) and `src/sase/ace/tui/widgets/_tools_panel_details.py`
(expanded block + markdown export).

- **Compact one-line detail** (`_tool_call_detail`): for `Agent`/`Task`, synthesize a genuinely useful summary instead
  of the current empty/`response_keys` line — e.g.
  `Explore · 22 tools · 72k tok · 1m 54s — <first line of final message>`.
- **Expanded detail**: add a "subagent" metadata line (type · model · status · duration · tokens · tool stats). The
  final-message preview lights up automatically because `content_preview` is already in the panel's recognized preview
  keys; verify it reads well and adjust label ("final message") for subagent rows.

## Files to Change

- `src/sase/llm_provider/_tool_call_common.py` — subagent-result detection + normalized summary,
  `_SUBAGENT_OUTPUT_LIMIT`, list-of-blocks extraction. (Core.)
- `src/sase/ace/tui/tools/report.py` — `## Subagent` section, full-message-preferred Full Output, de-duplication for
  subagent entries.
- `src/sase/ace/tui/tools/_entry.py` — compact `Agent`/`Task` detail line.
- `src/sase/ace/tui/widgets/_tools_panel_details.py` — expanded subagent metadata line + preview label.

## Testing

- `tests/llm_provider/test_tool_calls_writer.py` — add a user event carrying a subagent `toolUseResult` envelope; assert
  the normalized fields, `content_preview`, and a `content_full` that is captured and correctly capped/truncated. Assert
  non-subagent responses are unchanged.
- `tests/ace/tui/tools/test_report.py` — add a subagent entry; assert the `## Subagent` section, its metadata, and the
  full final message under Full Output; assert a non-subagent report is byte-for-byte unchanged from today.
- `tests/ace/tui/widgets/test_tools_panel_timeline.py` — assert the compact detail and expanded subagent
  metadata/preview for an `Agent` entry.
- Consider a PNG visual snapshot only if the expanded subagent row's rendering warrants pinning; otherwise rely on the
  text-level timeline assertions. (Flagged, not required.)
- Run `just check` before completion (respecting the known pre-existing `llm_provider` / sandbox test caveats).

## Rollout / Compatibility

- Purely additive to the artifact schema (new optional keys inside `tool_response_summary`); no `schema_version` bump
  and no reader changes needed — the parser already passes `tool_response_summary` through verbatim, so new fields
  survive the round-trip.
- Old artifacts without the new fields degrade gracefully: the report simply omits the Subagent section and Full Output
  falls back to today's transcript-recovery message. New runs get the full experience.

## Open Question (single, low-stakes)

- `content_full` cap: default is ~64 KiB. This bounds `tool_calls.jsonl` growth while capturing essentially every real
  subagent message. If artifact size ever becomes a concern, a follow-up could spill oversized messages to a sidecar
  file; not needed for v1.
