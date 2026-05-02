---
status: done
bead_id: sase-owpf
prompt: sdd/prompts/202603/sase_plan.md
---

# Plan: `/sase_plan` and `/sase_questions` Skills

## Context

Replace Claude's native plan-mode and question-asking with custom sase skills. When an agent invokes `sase plan` or
`sase questions`, the current claude instance is killed and the agent runner orchestrates follow-up: plan approval then
coder spawn, or question notification then re-spawn with answers appended. This moves control from inside claude.py to
the runner level, enabling a unified plan/question flow across all LLM providers.

---

## Phase 1: CLI Subcommands (`sase plan` and `sase questions`)

### New file: `src/sase/main/plan_command_handler.py`

Handler for `sase plan <plan_file>`:

1. Guard: verify `SASE_AGENT` and `SASE_ARTIFACTS_DIR` env vars are set
2. Validate `plan_file` exists
3. Archive plan to `~/.sase/plans/` via `save_plan_to_sase()` from `src/sase/llm_provider/_plan_utils.py:35`
4. Write `.sase_plan_pending` marker JSON to `SASE_ARTIFACTS_DIR` (flush and close before proceeding):
   ```json
   {"plan_file": "<archived_path>", "original_file": "<abs_path>", "timestamp": ...}
   ```
5. Install no-op SIGTERM handler (`signal.signal(signal.SIGTERM, signal.SIG_IGN)`) so the process survives its own
   `killpg` long enough to send the signal
6. Kill process group: `os.killpg(os.getpgrp(), signal.SIGTERM)`

### New file: `src/sase/main/questions_command_handler.py`

Handler for `sase questions '<json>'`:

1. Guard: verify `SASE_AGENT` and `SASE_ARTIFACTS_DIR` env vars are set
2. Parse and validate questions JSON (schema below)
3. Write `.sase_questions_pending` marker JSON to `SASE_ARTIFACTS_DIR` (flush and close before proceeding):
   ```json
   {"questions": [...], "timestamp": ...}
   ```
4. Install no-op SIGTERM handler (`signal.signal(signal.SIGTERM, signal.SIG_IGN)`) so the process survives its own
   `killpg` long enough to send the signal
5. Kill process group: `os.killpg(os.getpgrp(), signal.SIGTERM)`

**Question JSON schema** (matches existing TUI `user_question_modal.py` format):

```json
[
  {
    "question": "string (required) - full question text",
    "header": "string (optional) - short label for sidebar",
    "options": [{ "label": "string (required)", "description": "string (optional)" }],
    "multiSelect": false
  }
]
```

Validation: questions must be a non-empty list; each must have a `question` string; `options[].label` is required if
options are provided; `multiSelect` must be bool.

### Modify: `src/sase/main/parser.py`

Add two subcommands (alphabetical order, between `plan-approve` and `restore`):

```python
# --- plan ---
plan_parser = top_level_subparsers.add_parser(
    "plan",
    help="Submit a plan file for approval (used by /sase_plan skill)",
)
plan_parser.add_argument("plan_file", help="Path to the plan .md file")

# --- questions ---
questions_parser = top_level_subparsers.add_parser(
    "questions",
    help="Ask the user questions (used by /sase_questions skill)",
)
questions_parser.add_argument("questions_json", help="JSON string containing questions")
```

### Modify: `src/sase/main/entry.py`

Add dispatch entries (alphabetical order):

```python
if args.command == "plan":
    from .plan_command_handler import handle_plan_command
    handle_plan_command(args.plan_file)

if args.command == "questions":
    from .questions_command_handler import handle_questions_command
    handle_questions_command(args.questions_json)
```

### Modify: `src/sase/axe_run_agent_runner.py` (line ~403, after agent_name is resolved)

Set `SASE_AGENT_NAME` env var so downstream commands can identify the agent:

```python
if agent_name:
    os.environ["SASE_AGENT_NAME"] = agent_name
```

---

## Phase 2: Agent Runner Marker Detection & Follow-up Spawning

### Modify: `src/sase/axe_runner_utils.py`

**SIGTERM handler** (line 21): Add `soft` parameter. When `soft=True`, set killed flag but do NOT call `sys.exit()` --
let the current operation fail naturally (claude subprocess dies from SIGTERM, `execute_workflow()` raises
`CalledProcessError`, runner catches it).

```python
def install_sigterm_handler(description: str = "process", *, soft: bool = False) -> None:
    def _handler(_signum: int, _frame: object) -> None:
        _killed_state["killed"] = True
        print(f"\nReceived SIGTERM - {description} was killed", file=sys.stderr)
        if not soft:
            sys.exit(128 + signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handler)
```

**New function**: `reset_killed()` to clear the killed flag between follow-up iterations:

```python
def reset_killed() -> None:
    _killed_state["killed"] = False
```

Only `axe_run_agent_runner.py` uses `soft=True`. All other callers keep the default behavior.

### Modify: `src/sase/axe_run_agent_runner.py` -- Follow-up Loop

The single `execute_workflow()` call (lines ~399-418) becomes a loop:

```python
current_prompt = prompt
current_role_suffix = ""
current_artifacts_dir = artifacts_dir

while True:
    reset_killed()
    os.environ["SASE_ARTIFACTS_DIR"] = current_artifacts_dir
    anon_workflow = create_anonymous_workflow(current_prompt)

    try:
        result = execute_workflow(...)
        break  # Normal completion

    except Exception:
        if not was_killed():
            raise  # Genuine error

        # Check marker files
        plan_data = _read_and_delete_marker(current_artifacts_dir, ".sase_plan_pending")
        q_data = _read_and_delete_marker(current_artifacts_dir, ".sase_questions_pending")

        if plan_data:
            plan_file = plan_data["plan_file"]
            _update_meta_suffix(current_artifacts_dir, ".plan")

            # Reuse handle_plan_approval() from _plan_utils.py:97
            # Also check was_killed() during polling for user-initiated kills
            approved_path = handle_plan_approval(plan_file, str(uuid.uuid4()))
            if not approved_path:
                # Write done.json with outcome "plan_rejected", break
                break

            # Spawn coder
            current_role_suffix = ".code"
            current_artifacts_dir = _create_followup_artifacts(
                project_name, agent_meta, ".code"
            )
            current_prompt = f"@{plan_file}\n\nThe above plan has been reviewed and approved. Implement it now."
            continue

        elif q_data:
            questions = q_data["questions"]
            current_role_suffix += ".q"
            _update_meta_suffix(current_artifacts_dir, current_role_suffix or ".q")

            # Run question flow: create notification, poll for answers
            # Reuse notify_user_question() and existing polling pattern
            response = _handle_questions_flow(questions, current_artifacts_dir)
            if response is None:
                break  # Killed during polling

            answers_section = _format_qa_for_prompt(response)
            current_artifacts_dir = _create_followup_artifacts(
                project_name, agent_meta, current_role_suffix
            )
            current_prompt = current_prompt + "\n\n" + answers_section
            continue

        else:
            raise  # Killed by user (no marker)
```

**Key helpers needed in the runner** (private functions):

- `_read_and_delete_marker(artifacts_dir, filename)` -- Read JSON, delete file, return data or None

- `_update_meta_suffix(artifacts_dir, suffix)` -- Read `agent_meta.json`, set `role_suffix` field, write back. This
  annotates the _just-killed_ agent's artifacts (e.g. marks it as `.plan` or `.code.q`).

- `_create_followup_artifacts(project_name, base_meta, suffix)` -- Create a new timestamped artifacts directory for the
  follow-up agent. Write a new `agent_meta.json` containing:
  - `role_suffix`: the suffix string (e.g. `".code"`, `".code.q"`)
  - `parent_timestamp`: the previous agent's timestamp (for TUI grouping)
  - All inherited fields from `base_meta`: `model`, `llm_provider`, `vcs_provider`, `name`, `approve`, etc.
  - Fresh `run_started_at` timestamp Return the new artifacts directory path.

- `_handle_questions_flow(questions, artifacts_dir)` -- Full question notification + answer collection:
  1. Generate `session_id = str(uuid.uuid4())`
  2. Create response directory: `~/.sase/user_question/<session_id>/`
  3. Write `question_request.json` to the response directory:
     `{"session_id": ..., "timestamp": ..., "questions": [...]}`
  4. Call `notify_user_question()` from `senders.py:108` to create TUI notification (with `action_data.response_dir`
     pointing to the response directory)
  5. Call `send_desktop_notification()` + `ring_tmux_bell()` from `plan_approve_handler.py`
  6. **If `is_auto_approve_active()`**: skip notification, auto-select first option per question (matching existing
     `user_question_handler.py` auto-approve behavior), return synthetic response
  7. Poll for `question_response.json` in the response directory with `_POLL_INTERVAL = 0.5` seconds
  8. Check `was_killed()` each iteration -- if killed during polling (user killed from TUI), return `None`
  9. When response appears, parse it and return `{"answers": [...], "global_note": "..."}`

- `_format_qa_for_prompt(response)` -- Format the response dict as `### Questions and Answers` markdown (see format
  below)

**Reusable functions** (DO NOT reimplement):

- `handle_plan_approval()` from `src/sase/llm_provider/_plan_utils.py:97` -- plan notification + polling
- `notify_user_question()` from `src/sase/notifications/senders.py:108` -- question notification
- `notify_plan_approval()` from `src/sase/notifications/senders.py:139` -- plan notification
- `is_auto_approve_active()` from `src/sase/main/plan_approve_handler.py:23`
- `send_desktop_notification()`, `ring_tmux_bell()`, `get_tmux_prefix()` from `plan_approve_handler.py`
- `save_plan_to_sase()`, `write_plan_path_artifact()` from `src/sase/llm_provider/_plan_utils.py`

**`done.json` outcomes** -- written at loop exit to `current_artifacts_dir/done.json` with standard fields (`cl_name`,
`project_file`, `timestamp`, `model`, `llm_provider`, etc. inherited from existing done marker logic):

| Scenario                                 | `outcome` field   | Notes                                                                        |
| ---------------------------------------- | ----------------- | ---------------------------------------------------------------------------- |
| Normal completion (no kill)              | `"completed"`     | Standard path -- agent finished on its own                                   |
| Plan rejected                            | `"plan_rejected"` | Workflow dies, no retry                                                      |
| Killed during polling (plan or question) | `"killed"`        | User killed from TUI while waiting for answer                                |
| Killed by user (no marker)               | N/A               | Re-raise exception; let existing error handling write `"failed"` done marker |

**Plan rejection**: No retry loop -- the workflow is killed and dismissed.

**Auto-approve**: Check `is_auto_approve_active()`. If true, skip plan notification and immediately spawn coder. For
questions, auto-select first option per question (matching the existing behavior in `user_question_handler.py:95-108`).

**Q&A prompt format**:

```markdown
### Questions and Answers

**Q: What approach should we use?** A: Selected 'Option B'

**Q: Include tests?** A: Selected 'Yes' Custom note: "Focus on integration tests"

**Global note from user:** Keep it simple
```

### Modify: TUI agent display (minimal)

In the agent model/loading code, read `role_suffix` from `agent_meta.json` and display it as a dim purple annotation
after the agent name in the Agents tab. The exact TUI files will need investigation by the Phase 2 coder but likely
involve:

- `src/sase/ace/tui/widgets/agent_list.py` -- display suffix
- Agent data loading code -- read `role_suffix` field from `agent_meta.json`

---

## Phase 3: Skills, Hooks, CLAUDE.md & Provider Cleanup

### New file: `~/.local/share/chezmoi/home/dot_claude/skills/sase_plan/SKILL.md`

````markdown
---
name: sase_plan
description: Create an implementation plan. Use instead of plan mode (which is disabled). Only available inside sase.
---

# /sase_plan - Create an Implementation Plan

Use this skill when you need to plan before implementing. This replaces Claude's native plan mode, which is disabled.

**IMPORTANT**: Only available when running inside sase (via `sase ace` TUI or `sase run`).

## How It Works

When you use this skill, the current claude instance will be **terminated** and a NEW "coder" agent will be spawned with
ONLY your plan file as context. The coder will not have your conversation history, exploration notes, or any other
context -- only the plan file.

## Instructions

1. **Explore and understand** the problem thoroughly.

2. **Write a self-contained plan** to `sase_plan_<name>.md` (descriptive underscore name). The plan MUST include:
   - All relevant file paths (absolute)
   - Key code snippets the implementer needs
   - Architectural context and design decisions
   - Step-by-step implementation instructions
   - Edge cases and gotchas

3. **Submit the plan**:
   ```bash
   .venv/bin/sase plan sase_plan_<name>.md
   ```
````

## Critical Rules

- Plan must be COMPLETELY self-contained (no "as discussed above")
- Include actual code snippets, not just descriptions
- Write the plan file to the current working directory
- Always use `.venv/bin/sase plan`, never bare `sase plan`

````

### New file: `~/.local/share/chezmoi/home/dot_claude/skills/sase_questions/SKILL.md`

```markdown
---
name: sase_questions
description: Ask the user questions. Use instead of AskUserQuestion (which is disabled). Only available inside sase.
---

# /sase_questions - Ask the User Questions

Use this skill when you need user input. This replaces Claude's native AskUserQuestion.

**IMPORTANT**: Only available when running inside sase (via `sase ace` TUI or `sase run`).

## How It Works

When you use this skill, the current claude instance will be **terminated**. The questions
are presented to the user in the sase TUI. After answering, a NEW agent is spawned with the
original prompt plus a "Questions and Answers" section appended.

## Usage

```bash
.venv/bin/sase questions '<json>'
````

## JSON Schema

```json
[
  {
    "question": "Full question text (required)",
    "header": "Short sidebar label (optional)",
    "options": [{ "label": "Option label (required)", "description": "Details (optional)" }],
    "multiSelect": false
  }
]
```

## Examples

Single question with options:

```bash
.venv/bin/sase questions '[{"question": "Which database should we use?", "options": [{"label": "PostgreSQL", "description": "Relational, mature"}, {"label": "SQLite", "description": "Embedded, simple"}]}]'
```

Multiple questions:

```bash
.venv/bin/sase questions '[{"question": "Approach?", "header": "Approach", "options": [{"label": "A"}, {"label": "B"}]}, {"question": "Include tests?", "options": [{"label": "Yes"}, {"label": "No"}]}]'
```

## Notes

- Users can always provide a custom "Other..." response
- Users can add a global note across all questions
- Always use `.venv/bin/sase questions`, never bare `sase questions`
- JSON must be a single shell argument (wrap in single quotes)

````

### Modify: `~/.local/share/chezmoi/home/dot_claude/settings.json`

Update PreToolUse hooks to deny with messages pointing to the proper skills. Use exit 0 with
deny JSON (Claude Code ignores stdout on exit 2):

```json
{
  "matcher": "EnterPlanMode",
  "hooks": [{
    "type": "command",
    "command": "printf '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Plan mode is disabled. Use the /sase_plan skill instead.\"}}'",
    "timeout": 5
  }]
},
{
  "matcher": "ExitPlanMode",
  "hooks": [{
    "type": "command",
    "command": "printf '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Plan mode is disabled. Use the /sase_plan skill instead.\"}}'",
    "timeout": 5
  }]
},
{
  "matcher": "AskUserQuestion",
  "hooks": [{
    "type": "command",
    "command": "printf '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"AskUserQuestion is disabled. Use the /sase_questions skill instead.\"}}'",
    "timeout": 5
  }]
}
````

### Modify: `AGENTS.md` (append new section)

```markdown
## Plan Mode and Questions (sase Agents Only)

When running inside sase (`SASE_AGENT` is set):

- You do NOT have access to plan mode (`EnterPlanMode`/`ExitPlanMode`). Use the `/sase_plan` skill instead.
- You do NOT have access to `AskUserQuestion`. Use the `/sase_questions` skill instead.
- The `sase plan` and `sase questions` CLI commands are implementation details used by these skills -- do not reference
  them directly.
```

### Modify: `src/sase/llm_provider/claude.py` -- Remove plan mode logic

**Remove from `invoke()`**:

- The plan feedback retry loop (lines 125-249)
- The phase 2 implementation spawn (lines 251-347)
- `--permission-mode=plan` flag (line 150-151)
- `plan_marker_path` parameter to `_run_subprocess()`
- `_find_plan_file()` function (lines 32-49)
- `_log_interrupt()` function (lines 52-69)
- Unused imports: `shutil`, `_plan_utils` functions (`append_plan_feedback_log`, `read_plan_feedback`,
  `save_plan_to_sase`, `write_plan_path_artifact`)

**Simplified `invoke()`**: Single claude invocation with interrupt loop (keep interrupt monitoring for TUI interrupt
feature). No plan markers, no phase 2. On non-zero return code, raise `CalledProcessError` (the runner handles markers).

**Remove `plan_marker_path` from `_run_subprocess()`**: Delete the marker monitoring thread (lines 383-397). Keep the
interrupt monitoring thread.

**Remove from `axe_run_agent_runner.py`**:

- `os.environ["SASE_AGENT_PLAN_MODE"] = "1"` (line 407) -- no longer needed
- Keep `directives.plan` in agent_meta for backward compat, but stop setting the env var

### Remove orphaned hook handlers and infrastructure

The old hooks called `uv run sase plan-approve` and `uv run sase user-question`. With hooks changed to simple deny
commands, these handlers are dead code.

**Remove from `src/sase/main/parser.py`**:

- `plan-approve` subcommand definition
- `user-question` subcommand definition

**Remove from `src/sase/main/entry.py`**:

- `plan-approve` dispatch entry (`handle_plan_approve_command`)
- `user-question` dispatch entry (`handle_user_question_command`)

**Remove `src/sase/main/user_question_handler.py`** entirely -- all functionality moves to the runner's
`_handle_questions_flow` helper.

**Trim `src/sase/main/plan_approve_handler.py`** -- Keep the utility functions that are still reused by the runner:

- `is_auto_approve_active()` (used by runner for auto-approve checks)
- `send_desktop_notification()` (used by runner for notifications)
- `ring_tmux_bell()` / `get_tmux_prefix()` (used by runner for notifications)
- `emit_hook_decision()` (may still be useful)

Remove `handle_plan_approve_command()` and `_find_plan_file()` (the main hook handler logic).

**Remove `~/.local/share/chezmoi/home/dot_claude/hooks/executable_plan_hook`** -- This notification hook was used by
Claude Code's native plan mode. No longer needed since plan notifications are now triggered by the runner.

---

## Key Design Decisions

1. **Kill mechanism -- process group kill, not targeted runner signaling**: The requirement says to "signal the agent
   runner rather than killing claude directly." We chose `os.killpg(os.getpgrp(), SIGTERM)` instead, which kills the
   entire process group. The runner survives via a `soft=True` SIGTERM handler that sets a flag without exiting. This is
   simpler and more reliable than a targeted signaling approach (which would require IPC -- sockets, pipes, or shared
   files -- to communicate between the CLI command and the runner). The trade-off: every process in the group receives
   SIGTERM, so the CLI command itself must install `SIG_IGN` before calling `killpg` to avoid dying before the signal is
   fully dispatched. The `SASE_AGENT_NAME` env var is still set for TUI display and logging purposes, even though the
   kill mechanism doesn't need it.

2. **Follow-up in same process**: The runner loops and calls `execute_workflow()` again rather than spawning a new
   subprocess. Simpler, reuses same workspace.

3. **Questions accumulate**: `current_prompt += Q&A section` so chained questions (`.code.q` -> `.code.q.q`) carry all
   previous answers forward.

4. **Skills are globally registered**: The requirement says skills should "not be registered or available when claude is
   run directly outside of sase." Claude Code does not support conditional skill registration based on environment
   variables -- skills in `~/.claude/skills/` are always visible. We accept this trade-off: the skills are globally
   registered but the SKILL.md descriptions state they're sase-only, the AGENTS.md instructions tell the agent not to
   use them outside sase, and the CLI commands guard with `SASE_AGENT` env var (erroring immediately if not set). In
   practice, a user running claude directly will never trigger the skill, and if they do, the CLI command fails
   gracefully with a clear error.

5. **Plan rejection = workflow death**: No retry loop. The entire workflow is dismissed.

6. **Orphaned handler cleanup**: The old `plan-approve` and `user-question` subcommands were designed as Claude Code
   hook handlers (called via `uv run sase plan-approve` etc.). With hooks changed to simple deny-and-redirect commands,
   and all plan/question orchestration moved to the runner, these handlers become dead code. Removing them prevents
   confusion about which code path is authoritative.

---

## Verification

### Phase 1

```bash
# Set env vars manually to test CLI commands
export SASE_AGENT=1
export SASE_ARTIFACTS_DIR=/tmp/test_artifacts && mkdir -p $SASE_ARTIFACTS_DIR
echo "# Test plan" > /tmp/test_plan.md

# Test plan command (will SIGTERM itself -- run in subshell)
(.venv/bin/sase plan /tmp/test_plan.md) || true
cat $SASE_ARTIFACTS_DIR/.sase_plan_pending  # Should show marker JSON
ls ~/.sase/plans/  # Should show archived plan

# Test questions command
(.venv/bin/sase questions '[{"question":"Test?","options":[{"label":"Yes"},{"label":"No"}]}]') || true
cat $SASE_ARTIFACTS_DIR/.sase_questions_pending  # Should show marker JSON

# Test validation errors
.venv/bin/sase plan /nonexistent  # Should fail with "not found"
.venv/bin/sase questions 'not json'  # Should fail with "Invalid JSON"
unset SASE_AGENT
.venv/bin/sase plan foo.md  # Should fail with "only available inside sase"
```

### Phase 2

- Launch an agent via `sase ace` TUI with a prompt that includes `/sase_plan`
- Verify: agent explores, writes plan, calls `sase plan`, gets killed
- Verify: plan notification appears in TUI
- Verify: approve -> coder agent spawns with plan as prompt
- Verify: reject -> workflow dies with "plan_rejected" outcome
- Repeat for `/sase_questions`: verify notification, answer, re-spawn with Q&A

### Phase 3

- Run `just lint` and `just test` to verify no regressions
- Verify hooks deny native plan mode: launch claude, try `EnterPlanMode` -> denied, try `ExitPlanMode` -> denied
- Verify hooks deny native questions: try `AskUserQuestion` -> denied
- Verify `claude.py` simplified invoke works for normal (non-plan) agent runs
- Verify `sase plan-approve` and `sase user-question` subcommands are removed (should error with unknown command)
- Verify `executable_plan_hook` is removed from chezmoi
