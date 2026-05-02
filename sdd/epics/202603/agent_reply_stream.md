---
status: done
bead_id: sase-0oou
prompt: sdd/prompts/202603/agent_reply_stream.md
---

# Plan: Live AGENT REPLY Section in Agents Tab

## Context

The Agents tab metadata panel currently shows AGENT DETAILS, AGENT XPROMPT (running only), AGENT PROMPT, and AGENT CHAT
(done only). There is no way to see what a running agent is outputting in real-time. The user wants an "AGENT REPLY"
section that streams the agent's live output, shown only while running (hidden once done, since AGENT CHAT will contain
the full conversation).

## Architecture

All 3 providers (Claude, Codex, Gemini) stream subprocess output through functions in `_subprocess.py`. These functions
already extract assistant text and print to stdout. The `SASE_ARTIFACTS_DIR` env var is set in the agent runner before
invocation. We'll write extracted text to `{SASE_ARTIFACTS_DIR}/live_reply.md` during streaming, and the TUI will read
this file on each refresh cycle.

## Phase 1: Backend - Write `live_reply.md` During Agent Streaming

**File: `src/sase/llm_provider/_subprocess.py`**

1. Add helper to open the live reply file:

   ```python
   def _open_live_reply_file() -> IO[str] | None:
       artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
       if not artifacts_dir:
           return None
       path = os.path.join(artifacts_dir, "live_reply.md")
       return open(path, "w", encoding="utf-8")
   ```

2. **`stream_and_parse_json_output()`** (Claude): Open live_reply file, pass to `_process_json_line()`, close in finally
   block.

3. **`stream_and_parse_codex_json_output()`** (Codex): Same pattern - open live_reply file, pass to
   `_process_codex_json_line()`, close in finally.

4. **`stream_process_output()`** (Gemini): Open live_reply file, write each stdout line to it (since Gemini outputs
   plain text, not JSON).

5. **`_process_json_line()`**: Add optional `live_reply_file` param. When assistant text is extracted, write it + flush.

6. **`_process_codex_json_line()`**: Same - add optional `live_reply_file` param, write + flush on text extraction.

## Phase 2: Frontend - Display AGENT REPLY Section in TUI

**File: `src/sase/ace/tui/models/agent.py`**

1. Add `get_live_reply_content()` method:
   ```python
   def get_live_reply_content(self) -> str | None:
       artifacts_dir = self.get_artifacts_dir()
       if artifacts_dir is None:
           return None
       path = os.path.join(artifacts_dir, "live_reply.md")
       try:
           with open(path, encoding="utf-8") as f:
               return f.read()
       except (FileNotFoundError, OSError):
           return None
   ```

**File: `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`**

1. In `update_display()`: After the AGENT PROMPT section (line ~119, the else branch for non-done agents), add AGENT
   REPLY section:
   - Only shown when `agent.status not in ("DONE", "FAILED")`
   - Separator line, "AGENT REPLY" header (same gold styling as other headers), then content rendered as Markdown Syntax
   - If no live reply content yet, show "Waiting for agent response..." in dim italic

2. In `update_display_with_hints()`: Same addition after AGENT PROMPT section for running agents - add AGENT REPLY with
   file path hints support.

### Section Ordering (for running agents)

```
AGENT DETAILS
─────────────
AGENT XPROMPT
─────────────
AGENT PROMPT
─────────────
AGENT REPLY      <-- NEW
```

### Section Ordering (for done agents)

```
AGENT DETAILS
─────────────
AGENT PROMPT
─────────────
AGENT CHAT
```

(AGENT XPROMPT and AGENT REPLY are both hidden for done agents)

## Verification

1. **Phase 1**: Launch an agent with `@` in the TUI, then check
   `~/.sase/projects/<project>/artifacts/ace-run/<timestamp>/live_reply.md` - it should contain the agent's streamed
   response text, growing as the agent runs.

2. **Phase 2**: While an agent is running, select it in the Agents tab - the metadata panel should show the AGENT REPLY
   section with live content that updates on each refresh cycle (every 10s or manual `y` key). Once the agent completes,
   AGENT REPLY should disappear and AGENT CHAT should show instead.

3. **E2E test**: Can test with `sase ace --agent` to verify the display structure includes the new section.
