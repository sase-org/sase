---
create_time: 2026-03-29 17:08:56
status: done
prompt: sdd/prompts/202603/reply_timestamps.md
---

# Plan: Reply Timestamps in Agent Metadata Panel

## Goal

Add per-turn timestamps to the AGENT REPLY (running) and AGENT CHAT (done) sections of the agent metadata panel on the
Agents tab, so users can see _when_ each piece of the agent's reply was generated.

## Design

### Sidecar Timestamp File

Introduce a new file `live_reply_timestamps.jsonl` alongside the existing `live_reply.md` in each agent's artifacts
directory. Each line records when a new assistant turn began:

```json
{"byte_offset": 0, "timestamp": "2026-03-29T18:45:23.456789+00:00"}
{"byte_offset": 1547, "timestamp": "2026-03-29T18:47:01.123456+00:00"}
```

- **byte_offset**: Position in `live_reply.md` where this turn's content starts (measured _before_ writing the `\n\n`
  separator for turns after the first).
- **timestamp**: ISO 8601 UTC timestamp captured at write time.

This sidecar approach keeps `live_reply.md` as plain markdown (no format change), preserves backward compatibility with
older agents that lack the JSONL file, and mirrors the existing `codex_thinking.jsonl` pattern.

### Writer Changes (`src/sase/llm_provider/_subprocess.py`)

All three streaming codepaths write to `live_reply.md`. Each needs a small addition to also write timestamp entries:

1. **`stream_and_parse_json_output` / `_process_json_line`** (Claude Code): Each `assistant` event is a distinct turn.
   Record a timestamp entry when the first text block of each assistant turn is written to the live reply file.

2. **`stream_and_parse_codex_json_output` / `_process_codex_json_line`** (Codex): Each `agent_message` is a distinct
   turn. Same treatment.

3. **`stream_process_output`** (Gemini / generic): Continuous line-by-line streaming without discrete turn boundaries.
   Record a single timestamp at the very first line of output. This gives at least a start-of-reply marker.

Implementation: Open a second file handle (`live_reply_timestamps.jsonl`) alongside `live_reply_file`. Pass it through
to the `_process_*` helpers. Write a JSONL entry each time a new turn begins (tracking byte position via a counter or
`file.tell()`).

### Model Changes (`src/sase/ace/tui/models/agent.py`)

Add a method to load the timestamped reply content:

```python
def get_timestamped_reply_chunks(self) -> list[tuple[str, str]] | None:
    """Load live reply split into timestamped chunks.

    Returns:
        List of (iso_timestamp, content_text) tuples, or None if timestamps
        unavailable. Falls back to None so callers can use the un-timestamped
        path.
    """
```

Logic:

1. Read `live_reply_timestamps.jsonl` from artifacts dir.
2. Read `live_reply.md` from artifacts dir.
3. Split the markdown content at the recorded byte offsets.
4. Return `[(timestamp, chunk), ...]`.
5. Return `None` if either file is missing (backward compat with old agents).

For DONE agents: `live_reply.md` persists in the artifacts directory after completion, so the same method works. If the
JSONL file doesn't exist (older agent), fall back to showing response_content without timestamps (current behavior
preserved).

### Display Changes (`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`)

When timestamps are available, render the reply as timestamped sections instead of a single Syntax block. Each section
gets a timestamp divider:

```
─── 18:45:23 ──────────────────────────────────────

[markdown content for turn 1, syntax-highlighted]

─── 18:47:01 ──────────────────────────────────────

[markdown content for turn 2, syntax-highlighted]
```

Visual design:

- Dividers use `─` characters with `HH:MM:SS` in local time, styled `dim #D7D7FF` (same color family as the Timestamps
  field in AGENT DETAILS)
- First divider appears right after the section header (AGENT REPLY / AGENT CHAT)
- Each chunk rendered as its own `Syntax("markdown", theme="monokai")` block
- If only one timestamp exists (plain streaming), show a single divider — still useful to see when the reply started

Fallback: When no timestamps JSONL exists (old agents), render exactly as today (single Syntax block, no dividers).

Both `update_display` and `update_display_with_hints` need the same treatment to keep the hint-mode rendering
consistent.

### Affected Code

| File                                                      | Change                                                              |
| --------------------------------------------------------- | ------------------------------------------------------------------- |
| `src/sase/llm_provider/_subprocess.py`                    | Open + write `live_reply_timestamps.jsonl` in all 3 streaming paths |
| `src/sase/ace/tui/models/agent.py`                        | Add `get_timestamped_reply_chunks()` method                         |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` | Render timestamped sections in both display methods                 |

### Edge Cases

- **Single turn**: Show one timestamp divider. Still useful (shows when reply started).
- **Empty reply**: No timestamps written. Display says "Waiting for agent response..." as now.
- **Old agents without JSONL**: `get_timestamped_reply_chunks()` returns `None`, display falls back to current
  un-timestamped rendering.
- **DONE agents**: `live_reply.md` persists in artifacts dir, so timestamps work the same way. If `live_reply.md` is
  missing but `response_path` exists, fall back to response_content without timestamps.
- **Plain streaming (Gemini)**: Only one timestamp (at first output). Shows a single divider.
