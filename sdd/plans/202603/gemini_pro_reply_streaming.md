---
create_time: 2026-03-31 12:31:48
status: done
prompt: sdd/prompts/202603/gemini_pro_reply_streaming.md
---

# Fix Gemini gemini-3.1-pro-preview Agent Reply Streaming

## Problem

The AGENT REPLY section in `sase ace` is empty for Gemini `gemini-3.1-pro-preview` agents. Both the PLANNER and CODER
phase dividers render with timestamps, but no reply content appears beneath either one. This works correctly for
`gemini-3-flash-preview`.

## Root Cause

The Gemini CLI behaves differently for thinking models vs non-thinking models:

- **gemini-3-flash-preview** (non-thinking): Streams response text to stdout incrementally, line by line. The PTY-based
  capture in `stream_process_output()` writes each line to `live_reply.md` in real-time. Works fine.
- **gemini-3.1-pro-preview** (thinking model): Buffers its entire response during the thinking phase and only outputs to
  stdout when thinking completes and the session ends. This means `live_reply.md` stays empty while the agent is
  running.

This creates two distinct failures:

1. **PLANNER phase**: When `sase plan` SIGTERMs the Gemini CLI after plan approval, no output has been flushed to stdout
   yet. `live_reply.md` is 0 bytes. However, `handle_plan_marker()` already saves a synthetic response via
   `format_plan_as_response()` and stores the chat path in `agent_meta.json` as `chat_path`. But
   `enrich_agent_from_meta()` never loads this `chat_path`, so the TUI has no fallback response source for plan-killed
   agents.

2. **CODER phase** (running): The Gemini CLI hasn't finished yet, so `live_reply.md` is empty. The TUI's
   `render_agent_reply_content()` tries timestamped chunks, live reply, and response file -- all empty.

## Fix

### Phase 1: PLANNER reply -- load `chat_path` as fallback response

The planner's response is already saved. We just need to load it.

**`src/sase/ace/tui/models/agent.py`** -- Add `get_chat_response_content()` method:

- Read `agent_meta.json` from the agent's artifacts dir
- If `chat_path` exists, read that file and return its content
- This is a new fallback after `get_response_content()` returns None

**`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`** -- Update `render_agent_reply_content()`:

- After the existing `get_response_content()` fallback (line 88), add one more fallback:
  `agent.get_chat_response_content()`
- This handles plan-killed Gemini agents where `response_path` is not set but `chat_path` exists in `agent_meta.json`

### Phase 2: CODER reply -- tail the sandbox log for real-time streaming

The Gemini CLI writes a real-time session transcript to `~/.gemini/sandbox_logs/<session>/sandbox.log`. This log
contains model text responses as they're generated, even during the thinking phase. We should tail this log and pipe
model response text into `live_reply.md`.

**`src/sase/llm_provider/gemini.py`** -- Add sandbox log tailing in `_run_subprocess()`:

- After launching the subprocess, start a daemon thread that:
  1. Watches `~/.gemini/sandbox_logs/` for a new session directory (appears within seconds of launch)
  2. Tails `<session_dir>/sandbox.log` line by line
  3. Parses model response text from the log format (need to investigate exact format)
  4. Writes extracted response text to `live_reply.md` with timestamps via a shared file handle
- The thread should stop when the subprocess exits

**`src/sase/llm_provider/_subprocess.py`** -- Coordinate sandbox log writes with stdout:

- The sandbox log thread needs to write to the same `live_reply.md` and `live_reply_timestamps.jsonl` files
- Option A: Have the sandbox log thread be the sole writer (skip stdout writes for Gemini)
- Option B: Have the sandbox log thread write to `live_reply.md` during the session, then let stdout overwrite when the
  session ends (for accuracy)
- Option A is simpler and preferred -- the sandbox log has the authoritative content

### Phase 3: Alternative if sandbox log is too fragile

If the sandbox log format proves undocumented/unstable:

- For the CODER phase, show a Gemini-specific placeholder: "Gemini is thinking... Reply will appear when response
  generation begins." in dim italic style
- This is honest and avoids fragile log parsing
- Still implement Phase 1 (chat_path fallback) regardless

## Files to Change

- `src/sase/ace/tui/models/agent.py` -- Add `get_chat_response_content()` method
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` -- Add chat_path fallback in
  `render_agent_reply_content()`
- `src/sase/llm_provider/gemini.py` -- Add sandbox log tailing thread (Phase 2)
- `src/sase/llm_provider/_subprocess.py` -- Coordinate live_reply writes (Phase 2)

## Risks

- The sandbox log format is undocumented and may change between Gemini CLI versions
- Session directory discovery requires filesystem polling (brief race condition)
- Phase 1 alone fixes the PLANNER but not the CODER; Phase 2 fixes both but is more complex
