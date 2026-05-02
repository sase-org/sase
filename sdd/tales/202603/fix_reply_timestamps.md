---
create_time: 2026-03-31 11:31:07
status: done
prompt: sdd/prompts/202603/fix_reply_timestamps.md
---

# Fix AGENT REPLY Per-Chunk Timestamps for All Model Runtimes

## Problem

In the `sase ace` TUI, the AGENT REPLY section shows timestamp dividers per chunk of agent reply text. However,
timestamps are not being recorded at proper granularity for all runtimes, causing all chunks to appear under a single
timestamp (e.g. `─── 11:18:11 ───`) even though they clearly arrived at different times.

The root cause is in `src/sase/llm_provider/_subprocess.py`, where three streaming functions record timestamps to
`live_reply_timestamps.jsonl` at different (and sometimes insufficient) granularity:

| Runtime | Function                   | Current behavior                    | Issue                                        |
| ------- | -------------------------- | ----------------------------------- | -------------------------------------------- |
| Gemini  | `stream_process_output`    | ONE timestamp on first output line  | All subsequent output gets no new timestamps |
| Claude  | `_process_json_line`       | One timestamp per `assistant` event | Multi-text-block turns share one timestamp   |
| Codex   | `_process_codex_json_line` | One timestamp per `agent_message`   | Already correct                              |

## Phase 1: Fix Gemini — paragraph-boundary timestamps in `stream_process_output`

**File**: `src/sase/llm_provider/_subprocess.py`

The main offender. Since Gemini streams raw text (not structured JSON), we need a heuristic for chunk boundaries. The
agent output shows paragraphs separated by blank lines — each paragraph is a separate agent thought/action.

**Change**: Replace the `first_output_written` boolean with `prev_line_blank = True` (initialized True so the first line
triggers a timestamp). Record a new timestamp whenever a non-blank line follows a blank line. Apply this to both the
main select loop and the drain loop.

## Phase 2: Fix Claude — per-content-block timestamps in `_process_json_line`

**File**: `src/sase/llm_provider/_subprocess.py`

Remove the `recorded_turn_ts` flag so each text content block within an `assistant` event gets its own timestamp. This
handles the edge case where a single turn contains multiple text blocks.

## Phase 3: Add tests

**File**: `tests/test_subprocess_timestamps.py` (new)

Unit tests exercising the timestamp-recording helpers directly (using `_process_json_line`, `_process_codex_json_line`,
and a simulated `stream_process_output` via temp files):

1. **Gemini**: Verify timestamps recorded at paragraph boundaries (blank-line detection)
2. **Claude**: Verify a timestamp per text content block within a single assistant event
3. **Codex**: Confirm existing correct behavior (one timestamp per `agent_message`)

## Phase 4: Run `just check`
