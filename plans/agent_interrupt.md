---
status: done
---

# Plan: Mid-Execution User Interrupt for Running Agents

## Context

Users watching agents in the TUI Agents tab currently have no way to guide a running agent mid-execution. The only
options are to kill it and start over, or wait until it finishes. This feature adds the ability to send a message to a
running agent that interrupts the current LLM subprocess and resumes with the user's guidance injected into the
conversation.

The approach extends the existing file-based IPC pattern (used by plan approval and AskUserQuestion) with a monitor
thread + kill/restart mechanism.

## Design

### IPC Protocol

- **File**: `{artifacts_dir}/interrupt_request.json` (agent's existing artifacts dir)
- **Format**: `{"message": "user text", "timestamp": 1234567890.123}`
- **Flow**: TUI writes file → provider monitor thread detects it → kills LLM subprocess → provider loop restarts LLM
  with user message

### Resume Semantics

- **Claude Code**: Restart with same `--session-id`. Claude Code persists conversation state per session, so the user's
  message becomes a follow-up turn in the same conversation. No context reconstruction needed.
- **Gemini**: No session persistence. Restart with reconstructed prompt: original prompt + accumulated response so far +
  user's message. Inherently lossy but functional.

### Detection Mechanism

Each provider's `_run_subprocess()` gets an interrupt monitor thread (identical pattern to the existing plan marker
monitor in `claude.py:389-403`). The thread:

1. Polls for `interrupt_request.json` every 1s
2. When found: reads message, stores in `self._pending_interrupt_message`, calls `process.terminate()`
3. Deletes the request file

The caller of `_run_subprocess()` checks `self._pending_interrupt_message` after return. If set, it loops: clears the
flag, adjusts the prompt, and calls `_run_subprocess()` again.

## Implementation Steps

### Step 1: Claude provider interrupt-resume loop

**File**: `src/sase/llm_provider/claude.py`

- Add `_pending_interrupt_message: str | None = None` instance attribute
- In `_run_subprocess()`: add an interrupt monitor thread alongside the existing plan marker monitor. Polls for
  `{SASE_ARTIFACTS_DIR}/interrupt_request.json`, reads message into `self._pending_interrupt_message`, terminates
  process
- In `invoke()` phase 2 (lines 332-349): wrap the `_run_subprocess` call in a `while True` loop. After return, check
  `_pending_interrupt_message`. If set: clear it, set `impl_prompt = user_message`, accumulate response text, continue
  loop. Same `impl_session_uuid` and `impl_args` are reused (Claude resumes the session)
- In `invoke()` phase 1 (lines 145-248): similar interrupt handling inside the existing plan feedback retry loop. If
  interrupted, set `current_prompt = user_message` and continue the loop
- Key: check `_pending_interrupt_message` BEFORE checking `return_code != 0`, just like the existing
  `marker_path.exists()` check (line 197)

### Step 2: Gemini provider interrupt-resume loop

**File**: `src/sase/llm_provider/gemini.py`

- Same `_pending_interrupt_message` attribute
- In `_run_subprocess()`: add interrupt monitor thread (same logic as Claude's)
- In `invoke()` normal mode (lines 225-256): wrap in a `while True` loop. On interrupt: reconstruct prompt with
  accumulated response + user message, continue
- In `_invoke_plan_mode()` (lines 262-373): same treatment for both plan and implementation phases

### Step 3: TUI modal

**New file**: `src/sase/ace/tui/modals/agent_interrupt_modal.py`

Follow `agent_name_modal.py` pattern:

- `AgentInterruptModal(ModalScreen[str | None])` with a single `Input` widget
- Title: "Send Message to Agent" with agent name/CL subtitle
- Enter submits, Escape cancels
- Register in `src/sase/ace/tui/modals/__init__.py`

### Step 4: TUI action and key binding

**New file**: `src/sase/ace/tui/actions/agents/_interrupt.py`

- `AgentInterruptMixin` with `action_send_agent_message()`:
  - Guard: only for running agents (`status in ("RUNNING", "PLAN APPROVED")`), not axe-spawned
  - Get `artifacts_dir` via `agent.get_artifacts_dir()`
  - Push `AgentInterruptModal`, on dismiss write `interrupt_request.json`

**Modify**: `src/sase/ace/tui/actions/agents/__init__.py` — add mixin to chain

**Modify**: `src/sase/ace/tui/actions/marking.py` — at top of `action_toggle_mark`, dispatch to
`action_send_agent_message()` when `current_tab == "agents"`. This reuses the `m` key which is already bound but unused
on agents tab.

### Step 5: Interrupt log for observability

In both providers' interrupt-resume loops, append to `{artifacts_dir}/interrupt_log.jsonl`:

```json
{"message": "...", "timestamp": ..., "cycle": 1}
```

## Key Files

| File                                               | Change                                       |
| -------------------------------------------------- | -------------------------------------------- |
| `src/sase/llm_provider/claude.py`                  | Interrupt monitor thread + resume loop       |
| `src/sase/llm_provider/gemini.py`                  | Same pattern with context reconstruction     |
| `src/sase/ace/tui/modals/agent_interrupt_modal.py` | New modal (follows agent_name_modal pattern) |
| `src/sase/ace/tui/actions/agents/_interrupt.py`    | New mixin for interrupt action               |
| `src/sase/ace/tui/actions/agents/__init__.py`      | Wire mixin into chain                        |
| `src/sase/ace/tui/actions/marking.py`              | Dispatch `m` to interrupt on agents tab      |
| `src/sase/ace/tui/modals/__init__.py`              | Register new modal                           |

## Verification

1. Launch a long-running agent from TUI (e.g., a prompt that takes >30s)
2. Switch to Agents tab, select the running agent
3. Press `m`, type a message, press Enter
4. Verify: agent's LLM subprocess is killed and restarted with user's message
5. Verify: `interrupt_log.jsonl` is written in artifacts dir
6. Verify: agent eventually completes with the user's guidance incorporated
7. Test edge cases: interrupt during plan phase, interrupt immediately after launch, multiple rapid interrupts
