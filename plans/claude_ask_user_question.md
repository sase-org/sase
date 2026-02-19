---
bead_id: sase-5qu
---

# Answer AskUserQuestion from SASE Ace TUI

## Context

When Claude Code calls `AskUserQuestion`, the user currently must switch to the CLI terminal to answer. This plan adds
the ability to answer these questions from the `sase ace` TUI via the existing notification system, mirroring the plan
approval flow (commits e3363df, f9fb5e8).

**Mechanism**: A PreToolUse hook intercepts `AskUserQuestion`, creates a TUI notification, and blocks until the user
answers from the modal. The hook emits structured `hookSpecificOutput` JSON on stdout (via `_emit_hook_decision()`) to
deny the tool and pass the user's answers in `permissionDecisionReason`. Claude reads this denial reason and proceeds
with the answers.

---

## Phase 1: Backend — CLI Handler + Hook Registration

### 1.1 Create `sase user-question` CLI subcommand

**New file**: `src/sase/main/user_question_handler.py` (modeled on `plan_approve_handler.py`)

```
handle_user_question_command():
  1. Read JSON from stdin (contains tool_input with questions array, session_id)
  2. If SASE_AGENT not set: send desktop notification + ring bell + exit 0 (let CLI handle it)
  3. If SASE_AGENT=1:
     a. Write request file: ~/.sase/user_question/{session_id}/question_request.json
        Contents: the full tool_input (questions array with options, multiSelect, etc.)
     b. Call notify_user_question() to create TUI notification
     c. Send desktop notification + ring tmux bell
     d. Poll for response file: ~/.sase/user_question/{session_id}/question_response.json
        (0.5s interval, 10-minute timeout)
     e. On response: format answers as structured text, call `_emit_hook_decision("deny", formatted_answers)`, exit 2
     f. On timeout: call `_emit_hook_decision("deny", "User question timed out")`, exit 2
```

**`_emit_hook_decision` helper**: Import the shared `_emit_hook_decision()` from `sase.main.plan_approve_handler` (see
`src/sase/main/plan_approve_handler.py:22-31`), or extract it into a common module (e.g., `sase.main._hook_utils`) that
both handlers import. The helper is only ~6 lines, so duplicating locally is also acceptable.

**`permissionDecisionReason` format** (what Claude sees as the denial reason):

```
USER ANSWERS PROVIDED VIA SASE TUI

Question: "Which database should we use?"
Selected: "PostgreSQL"

Question: "Which features?"
Selected: "Auth", "Logging"
Custom feedback: "Use JWT for auth"

Global note: "Also add error handling"

The user answered via the SASE TUI. Proceed with these selections.
```

### 1.2 Add notification sender

**File**: `src/sase/notifications/senders.py` — add `notify_user_question()`

```python
def notify_user_question(
    questions: list[dict],
    response_dir: str,
    session_id: str,
) -> None:
```

- `sender="question"`
- `action="UserQuestion"`
- `action_data={"response_dir": ..., "session_id": ...}`
- `notes` = first question text (truncated)
- `files` = [] (no files to attach; question data is in action_data)

### 1.3 Register CLI subcommand

- **`src/sase/main/parser.py`**: Add `user-question` subparser (like `plan-approve`, line 276)
- **`src/sase/main/entry.py`**: Add handler dispatch (like `plan-approve`, line 63)

### 1.4 Update hook registration

**File**: `~/.claude/settings.json` — replace the AskUserQuestion hook:

```json
{
  "matcher": "AskUserQuestion",
  "hooks": [
    {
      "type": "command",
      "command": "uv run sase user-question",
      "timeout": 600
    }
  ]
}
```

The old `plan_hook` bash script no longer handles AskUserQuestion (it only fires for ExitPlanMode now, which is already
handled by `sase plan-approve`). Since both matchers now use dedicated `sase` commands, the `plan_hook` bash script's
AskUserQuestion case is dead code — but we can leave it for now.

**Note on hook timeouts**: The current `~/.claude/settings.json` has `"timeout": 10` for both ExitPlanMode and
AskUserQuestion hooks. Both should be updated to `600` (10 minutes) since they block while polling for TUI responses.
The ExitPlanMode hook should already point at `sase plan-approve` with `"timeout": 600`; verify this when updating the
AskUserQuestion hook.

### 1.5 Store question data in request file

The request file `question_request.json` should contain:

```json
{
  "session_id": "abc123",
  "timestamp": 1708300000,
  "questions": [
    {
      "question": "Which option?",
      "header": "Choice",
      "multiSelect": false,
      "options": [
        { "label": "Option A", "description": "First choice" },
        { "label": "Option B", "description": "Second choice" }
      ]
    }
  ]
}
```

---

## Phase 2: TUI — UserQuestionModal + Notification Wiring

### 2.1 Create UserQuestionModal

**New file**: `src/sase/ace/tui/modals/user_question_modal.py`

**Data types**:

```python
@dataclass
class QuestionAnswer:
    question: str
    selected: list[str]        # Selected option labels
    custom_feedback: str | None = None  # "Other" text

@dataclass
class UserQuestionResult:
    answers: list[QuestionAnswer]
    global_note: str | None = None  # Custom prompt for Claude
```

**Modal layout** (single-question view with navigation for multiple questions):

```
┌─────────────────────────────────────────────────────┐
│          User Question  [1/2]                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Which database should we use?                      │
│                                                     │
│  > (●) PostgreSQL - Relational, mature, extensible  │
│    ( ) MongoDB - Document-oriented, flexible schema │
│    ( ) SQLite - Lightweight, embedded               │
│    ( ) Other...                                     │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [Enter text for 'Other'...]                        │
├─────────────────────────────────────────────────────┤
│  n/p: next/prev question  Enter: submit all         │
│  o: Other text  g: global note  q: cancel           │
└─────────────────────────────────────────────────────┘
```

**Behavior**:

- **Single-select**: OptionList with radio-button style (highlight = select). Pressing `Enter` on an option selects it
  AND advances to next question (or submits if last).
- **Multi-select**: OptionList with checkbox style. `Space` toggles selection. `Enter` confirms selections and advances.
- **"Other" option**: Always appended to options list. Selecting it reveals a text input for custom feedback.
- **`n`/`p`**: Navigate between questions (for multi-question forms). Answers are preserved when navigating.
- **`g`**: Opens a text input for a global note/custom prompt to Claude.
- **`Enter`** on the last question (or when all questions answered): Submits all answers.
- **`q`/`Escape`**: Cancel (no response written, hook times out).

**Keybindings**:

```python
BINDINGS = [
    ("escape", "cancel", "Cancel"),
    ("q", "cancel", "Cancel"),
    ("n", "next_question", "Next"),
    ("p", "prev_question", "Previous"),
    ("g", "global_note", "Global note"),
    ("space", "toggle_option", "Toggle"),  # multi-select only
    ("ctrl+d", "scroll_down", "Scroll down"),
    ("ctrl+u", "scroll_up", "Scroll up"),
]
```

### 2.2 Add TCSS styles

**File**: `src/sase/ace/tui/styles.tcss` — add `#user-question-*` styles (mirror plan-approval patterns)

### 2.3 Wire notification dispatch

**File**: `src/sase/ace/tui/actions/agents/_notification_actions.py` — add `handle_user_question()`:

```python
def handle_user_question(app, notification) -> bool:
    # 1. Read question_request.json from response_dir
    # 2. Parse questions from request data
    # 3. Push UserQuestionModal
    # 4. On dismiss callback: write question_response.json
    #    Response format:
    #    {
    #      "answers": [
    #        {"question": "...", "selected": ["Option A"], "custom_feedback": null},
    #        ...
    #      ],
    #      "global_note": "optional custom prompt"
    #    }
```

**File**: `src/sase/ace/tui/actions/agents/_notifications.py` — add dispatch case:

```python
elif result.action == "UserQuestion":
    handle_user_question(self, result)
```

### 2.4 Add badge and exports

**File**: `src/sase/ace/tui/modals/notification_modal.py` — add to `_ACTION_BADGES`:

```python
"UserQuestion": "[question]",
```

**File**: `src/sase/ace/tui/modals/__init__.py` — export `UserQuestionModal`, `UserQuestionResult`

---

## Files Modified (Summary)

| File                                                       | Change                        |
| ---------------------------------------------------------- | ----------------------------- |
| `src/sase/main/user_question_handler.py`                   | **NEW** — CLI handler         |
| `src/sase/main/parser.py`                                  | Add `user-question` subparser |
| `src/sase/main/entry.py`                                   | Add handler dispatch          |
| `src/sase/notifications/senders.py`                        | Add `notify_user_question()`  |
| `src/sase/ace/tui/modals/user_question_modal.py`           | **NEW** — TUI modal           |
| `src/sase/ace/tui/modals/__init__.py`                      | Export new modal              |
| `src/sase/ace/tui/modals/notification_modal.py`            | Add badge                     |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | Add handler                   |
| `src/sase/ace/tui/actions/agents/_notifications.py`        | Add dispatch                  |
| `src/sase/ace/tui/styles.tcss`                             | Add modal styles              |
| `~/.claude/settings.json`                                  | Update hook command + timeout |

## Verification

### Phase 1 testing

1. Run
   `echo '{"session_id":"test","tool_input":{"questions":[{"question":"Pick one","header":"Test","multiSelect":false,"options":[{"label":"A","description":"Option A"},{"label":"B","description":"Option B"}]}]}}' | SASE_AGENT=1 uv run sase user-question`
2. Verify notification appears in `~/.sase/notifications/notifications.jsonl`
3. Verify request file created at `~/.sase/user_question/test/question_request.json`
4. Manually write a response file and verify the handler picks it up, emits `_emit_hook_decision("deny", ...)` on
   stdout, and exits 2

### Phase 2 testing

1. Launch `sase ace`, trigger a test notification
2. Open notification modal (`N`), select the question notification
3. Verify UserQuestionModal displays with correct options
4. Select answers, provide custom feedback, submit
5. Verify response file is written correctly
6. End-to-end: run a Claude Code agent from the TUI that calls AskUserQuestion, answer from TUI, verify Claude proceeds
   with the answers
