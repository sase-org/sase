# Plan: PTY-Based Interactive Mode for Claude Code Agent Execution

## Context

The sase ace TUI launches Claude Code agents as background subprocesses. When plan mode is active, the agent creates a
plan, gets user approval via the TUI, then implements it. The current "two-phase resume" approach is broken:

1. Phase 1: `claude -p --session-id {uuid}` plans, calls ExitPlanMode
2. Hook fires, TUI approves, hook allows, process exits
3. Phase 2: `claude -p --resume {uuid}` attempts implementation
4. **BUG**: The resumed session has stale plan mode system prompts. After context compaction, these persist while "plan
   approved" messages are lost. Agent gets permanently stuck calling ExitPlanMode in a loop.

**Root cause**: `--resume` reloads the session transcript containing Phase 1's plan mode system prompts, and
`--permission-mode plan` from env vars gets re-applied to Phase 2.

**Goal**: Replace the two-phase approach with a single-process PTY wrapper running Claude Code in interactive mode,
where plan mode transitions happen naturally.

## Design

### Approach: PTY-based Interactive Wrapper (no `-p`)

Spawn Claude Code in interactive mode via a pseudo-terminal. The single process stays alive across plan→implement
transitions.

**Key points:**

- Use Python's stdlib `pty` module + `subprocess.Popen` (no new dependencies)
- Initial prompt passed as CLI argument: `claude --permission-mode plan "prompt"`
- Hooks (ExitPlanMode, AskUserQuestion) work exactly as today — no changes
- New Stop hook detects turn completion via marker files
- Follow-up messages sent by writing to PTY master fd
- Response text extracted from session transcript JSONL (same files the thinking panel already reads)

### Flow

```
1. Spawn: claude --permission-mode plan --session-id <uuid> "<prompt>"  (via PTY)
2. Agent plans → ExitPlanMode hook fires → TUI approval → hook allows
3. Turn ends → Stop hook writes turn-complete marker
4. Wrapper detects marker, checks plan_approved marker
5. Wrapper writes "Proceed with implementation\r" to PTY
6. Agent implements (plan mode properly off within same process)
7. Turn ends → Stop hook writes turn-complete marker
8. Wrapper sends SIGTERM → reads transcript → returns response
```

### Why this works better

| Current (two-phase resume)                                  | Proposed (single-process PTY)                                |
| ----------------------------------------------------------- | ------------------------------------------------------------ |
| `--resume` reloads stale plan mode system prompts           | Single process — Claude Code manages state internally        |
| `--permission-mode plan` re-applied to Phase 2 via env vars | Plan mode set once at startup, turned off after ExitPlanMode |
| Context compaction loses "plan approved" context            | No session restart — no conflicting prompts                  |
| Two separate processes with file-based state handoff        | One process, clean lifecycle                                 |

---

## Phase 1: Foundation — ClaudeProcess class + Stop hook

**Goal**: Create PTY-based process wrapper and turn-completion detection. Existing code is NOT modified.

### New files

**`src/sase/llm_provider/_claude_process.py`** — PTY wrapper class:

```python
class ClaudeProcess:
    """PTY-based wrapper for Claude Code interactive mode."""

    def __init__(self, args: list[str], initial_prompt: str, *, session_uuid: str, cwd: str): ...
    def start(self) -> None:  # Spawn with PTY, prompt as CLI arg
    def wait_for_turn_complete(self, timeout: float = 600) -> TurnResult:  # Poll marker
    def send_message(self, text: str) -> None:  # Write text + \r to PTY master
    def read_response(self) -> str:  # Parse new assistant text from transcript JSONL
    def stop(self, timeout: float = 30) -> int:  # SIGTERM → wait → SIGKILL
```

Implementation details:

- PTY creation: `master_fd, slave_fd = pty.openpty()` → slave for subprocess stdin/stdout/stderr
- Spawning: `subprocess.Popen(args + [prompt], stdin=slave_fd, stdout=slave_fd, stderr=slave_fd)`
- Turn marker polling: check `~/.sase/turn_complete/{session_id}/turn_complete.json` every 0.5s
- Transcript reading: find JSONL at `~/.claude/projects/<hashed_cwd>/`, parse `assistant` events with `type: "text"`
  content blocks. Track file read position between turns to only get new content.
- Reuse `_cwd_to_claude_project_dir()` from `src/sase/ace/tui/thinking/session_resolver.py` (move or import)
- Output draining: non-blocking reads from master_fd via `select.select()` for logging/debugging

**`src/sase/main/turn_complete_handler.py`** — Stop hook handler:

```python
def handle_turn_complete_command() -> NoReturn:
    """Handle turn-complete subcommand (Stop hook).
    Only active when SASE_AGENT=1.
    Writes marker: ~/.sase/turn_complete/{session_id}/turn_complete.json
    """
```

- Reads Stop hook payload from stdin (includes `session_id`, `stop_reason`, possibly `transcript_path`)
- Only creates marker when `SASE_AGENT=1` (same gate as plan-approve/user-question)
- Marker JSON contains: `session_id`, `timestamp`, `stop_reason`

### Config changes

**`~/.local/share/chezmoi/home/dot_claude/settings.json`** — Add Stop hook:

```json
"Stop": [{
    "hooks": [{
        "type": "command",
        "command": "uv run sase turn-complete",
        "timeout": 10
    }],
    "matcher": ""
}]
```

**`src/sase/main/entry.py`** — Add `turn-complete` subcommand routing

### Existing code to reuse

- `session_resolver._cwd_to_claude_project_dir()` — convert workspace CWD to Claude projects hash dir
- `plan_approve_handler.emit_hook_decision()` — not needed for Stop hook (no decision), but pattern to follow
- `plan_approve_handler` environment gating pattern (`SASE_AGENT` check)

### Tests

- `tests/test_claude_process.py` — unit tests with mock subprocess
- `tests/test_turn_complete_handler.py` — test marker writing with sample payloads

### Verification

- `just check` passes
- Unit tests pass for new code
- Manual: run `echo '{"session_id":"test123"}' | SASE_AGENT=1 uv run sase turn-complete` and verify marker is created

---

## Phase 2: Provider Integration

**Goal**: Switch `ClaudeCodeProvider` to use `ClaudeProcess`. Remove two-phase resume code.

### Context for this phase

Phase 1 created `_claude_process.py` with `ClaudeProcess` class and `turn_complete_handler.py` with the Stop hook. The
Stop hook is configured in settings.json.

### Files to modify

**`src/sase/llm_provider/claude.py`** — Rewrite `invoke()`:

```python
def invoke(self, prompt, *, model_tier, suppress_output=False, model_override=None):
    session_uuid = str(uuid.uuid4())
    base_args = [
        "claude",
        "--model", model_alias,
        "--dangerously-skip-permissions",
        "--session-id", session_uuid,
    ]
    # Add extra args from env (includes --permission-mode plan if set)
    # Filter out -p, --output-format, --input-format, --verbose
    ...

    proc = ClaudeProcess(base_args, prompt, session_uuid=session_uuid, cwd=os.getcwd())
    proc.start()
    try:
        proc.wait_for_turn_complete()
        phase1_response = proc.read_response()

        marker = Path.home() / ".sase" / "plan_approval" / session_uuid / "plan_approved.marker"
        if marker.exists():
            marker.unlink()
            proc.send_message("Your plan has been approved. Proceed with implementation.")
            proc.wait_for_turn_complete()
            phase2_response = proc.read_response()
            return (phase1_response + "\n\n" + phase2_response).strip()

        return phase1_response.strip()
    finally:
        proc.stop()
```

Remove:

- `_run_subprocess()` method
- All Phase 2 resume code (`--resume`, marker detection, `resume_args`)
- `-p`, `--verbose`, `--output-format stream-json`, `--input-format` from args

**`tests/test_llm_provider_providers.py`** — Update/add tests for new invoke flow

### Arg filtering

The `SASE_LLM_LARGE_ARGS` env var may contain flags incompatible with interactive mode. Filter out: `-p`,
`--output-format`, `--input-format`, `--verbose`. Keep everything else (including `--permission-mode plan`).

### Verification

- `just check` passes
- Manual: launch agent from sase ace TUI WITHOUT plan mode → single turn completes
- Manual: launch agent WITH plan mode → plan appears in TUI → approve → implementation proceeds

---

## Phase 3: End-to-End Verification, Thinking Panel, and Cleanup

**Goal**: Full E2E testing, investigate thinking panel commit, fix edge cases, clean up dead code.

### Context for this phase

Phases 1-2 replaced the two-phase `claude -p` + `--resume` approach with a single-process PTY wrapper using
`ClaudeProcess`. The Stop hook detects turn completion. The provider reads response text from session transcript JSONL
files.

### Tasks

1. **E2E test plan mode**: Run real agent with plan mode, approve in TUI, verify implementation completes
2. **E2E test AskUserQuestion**: Verify questions appear in TUI and answers reach the agent
3. **Investigate commit 2125b0fb48d5** ("Fix two thinking panel bugs"):
   - The multi-JSONL merging (`parse_thinking_blocks_multi`, `resolve_agent_sessions`) was added specifically for
     two-phase sessions. With single-process PTY, there's one transcript file.
   - The multi-file logic is harmless with one file but adds unnecessary complexity.
   - **Revert**: the `parse_thinking_blocks_multi` / `resolve_agent_sessions(since=...)` changes in `thinking_panel.py`
     back to `parse_thinking_blocks` / `resolve_agent_session` (single file).
   - **Keep**: the `raw_suffix` cache key fix and the auto-shown thinking state reset (from `agent_detail.py`) — these
     are independent bug fixes.
4. **Edge cases**:
   - Agent errors during planning → proper PTY cleanup
   - Plan rejection → agent revises, calls ExitPlanMode again
   - Timeout during plan approval → process cleanup
   - Non-plan-mode agent → single turn, no follow-up
   - Very long prompts (>128KB CLI arg limit) → write to temp file, pass path
5. **Cleanup**:
   - Evaluate whether `_subprocess.py` functions (`stream_and_parse_json_output`, `stream_process_output`) are still
     used by other providers (Gemini). Keep if yes, remove if no.
   - Update `docs/llms.md` to reflect new architecture
   - Remove turn-complete markers on process exit

### Verification

- `just check` passes (fmt, lint, test)
- Full E2E: agent with plan mode → plan shown → approve → implements → completes
- Full E2E: agent without plan mode → single turn → completes
- Thinking panel shows blocks correctly during and after agent execution

---

## Critical Files Reference

| File                                                   | Role                              | Phase |
| ------------------------------------------------------ | --------------------------------- | ----- |
| `src/sase/llm_provider/_claude_process.py`             | NEW: PTY wrapper                  | 1     |
| `src/sase/main/turn_complete_handler.py`               | NEW: Stop hook handler            | 1     |
| `src/sase/main/entry.py`                               | Add turn-complete subcommand      | 1     |
| `src/sase/llm_provider/claude.py`                      | Rewrite invoke()                  | 2     |
| `src/sase/llm_provider/_subprocess.py`                 | May become unused                 | 3     |
| `src/sase/main/plan_approve_handler.py`                | **No changes** (hooks work as-is) | —     |
| `src/sase/main/user_question_handler.py`               | **No changes** (hooks work as-is) | —     |
| `src/sase/ace/tui/thinking/parser.py`                  | Revert multi-file parts           | 3     |
| `src/sase/ace/tui/thinking/session_resolver.py`        | Revert multi-file parts           | 3     |
| `src/sase/ace/tui/widgets/thinking_panel.py`           | Revert to single-file parsing     | 3     |
| `~/.local/share/chezmoi/home/dot_claude/settings.json` | Add Stop hook                     | 1     |

## Risks

1. **Message submission via PTY**: Writing `text\r` to the PTY might not reliably submit in Claude Code's TUI.
   Mitigation: test `\r` vs `\n` vs other keycodes; check if Claude Code's input widget accepts standard Enter.
2. **Turn detection timing**: Stop hook might fire before transcript is fully flushed. Mitigation: add small delay or
   poll transcript for new content after marker.
3. **Large prompts**: CLI argument length limit (~128KB). Mitigation: for large prompts, write to temp file and
   investigate if Claude Code accepts `@file` or `--prompt-file` arguments.
4. **Claude Code version changes**: Interactive mode behavior might change. Mitigation: defensive coding, clear error
   messages.
