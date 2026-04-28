# Research: Unified Plan Mode & Q/A Across LLM Providers

## Goal

Understand exactly what it takes to replicate Claude Code's built-in plan mode and AskUserQuestion tool so that SASE can
provide a unified plan/Q&A experience across all three providers (Claude, Gemini, Codex) without depending on any
provider's built-in plan mode implementation.

---

## Current State: How It Works Today

### The Two Hook-Intercept Points (Claude Code)

Claude Code exposes two `PreToolUse` hooks that SASE intercepts (configured in `~/.claude/settings.json`):

1. **`ExitPlanMode`** — fired when Claude finishes writing a plan and wants to transition to implementation
2. **`AskUserQuestion`** — fired when Claude wants to ask the user a question mid-execution

Both hooks are handled by `sase` CLI subcommands that block (poll for a file-based response from the TUI) and return a
JSON hook decision on stdout:

```json
{
  "decision": "allow|deny",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny",
    "permissionDecisionReason": "..."
  }
}
```

**Key insight**: The hook decision format supports both Claude Code (`hookSpecificOutput`) and Gemini CLI (top-level
`decision`/`reason`) — see `emit_hook_decision()` in `plan_approve_handler.py:47-67`.

### Plan Mode: Provider-Specific Implementations

Each provider uses its own CLI flags to enable a two-phase plan/implement flow:

| Provider   | Phase 1 (Planning)                                  | Phase 2 (Implementation)                     | Plan Capture                                                              |
| ---------- | --------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------- |
| **Claude** | `--permission-mode=plan`                            | No flag (full permissions)                   | `~/.claude/plans/*.md`                                                    |
| **Gemini** | `--approval-mode=plan`                              | `--yolo`                                     | `~/.gemini/plans/*.md` or response text                                   |
| **Codex**  | `--sandbox read-only --ask-for-approval on-request` | `--dangerously-bypass-approvals-and-sandbox` | `--output-last-message` tempfile, `~/.codex/plans/*.md`, or response text |

**All three share**:

- `SASE_AGENT_PLAN_MODE` env var as the activation signal
- `_plan_utils.py` for approval handling, feedback logging, plan persistence
- File-based IPC via `~/.sase/plan_approval/{session_id}/`
- TUI notification → `PlanApprovalModal` → response file flow
- Feedback retry loop (up to 5 rounds)

### AskUserQuestion: Currently Claude-Only

The `AskUserQuestion` hook only exists in Claude Code. Gemini and Codex have no equivalent built-in mechanism for asking
the user structured questions mid-execution. The current implementation:

1. Claude calls `AskUserQuestion` tool → triggers `PreToolUse` hook
2. Hook runs `sase user-question` → writes request file → creates TUI notification
3. `UserQuestionModal` displays questions with radio/checkbox options
4. User answers → response file written → hook emits `deny` with formatted answers
5. Claude sees the denial reason as the user's answers and proceeds

**Critical detail**: The hook returns `deny` (not `allow`) with the answers in `permissionDecisionReason`. This prevents
Claude from actually using its built-in AskUserQuestion UI and instead feeds the TUI-provided answers as the "reason"
for denial, which Claude treats as the user's response.

---

## What Claude Code Plan Mode Actually Does (Built-In Behavior)

When `--permission-mode=plan` is passed to Claude Code CLI:

1. Claude enters a restricted mode where it can only call `EnterPlanMode` and `ExitPlanMode` tools
2. It writes a plan to `~/.claude/plans/` as a markdown file
3. When it calls `ExitPlanMode`, the `PreToolUse` hook fires
4. If the hook allows: Claude transitions to implementation mode with full tool access
5. If the hook denies: Claude receives the denial reason and can revise

**What SASE adds on top**: The `sase plan-approve` hook handler intercepts `ExitPlanMode`, creates a TUI notification,
and blocks until the user approves/rejects/provides feedback from the TUI's `PlanApprovalModal`.

### Claude's Internal Plan Mode State Machine

Claude Code maintains internal state that tracks:

- Whether the agent is in planning or implementation phase
- The plan file path
- Session continuity (via `--session-id`)

**Problem with pipe mode**: When Claude Code runs in pipe mode (`-p`) and the plan hook denies with feedback, Claude
exits rather than revising. This is why the SASE Claude provider has a feedback retry loop that re-launches Phase 1 with
the feedback appended to the prompt (`claude.py:200-237`).

### Session Continuity

- **Claude**: Uses `--session-id` for both phases. Phase 2 gets a different session UUID but a `.impl_session` sidecar
  file links them for the thinking panel
- **Gemini**: No session persistence. Context must be reconstructed from accumulated response text
- **Codex**: No session persistence. Same reconstruction approach as Gemini

---

## What Would a Unified Re-Implementation Require?

### Option A: Prompt-Level Plan Mode (No Provider Built-In Features)

Skip each provider's built-in plan mode entirely. Instead, always run providers in normal (full-permission) mode and
implement plan mode purely through prompt engineering and SASE's own approval flow.

**How it would work**:

1. When `%plan` directive is detected, inject a plan-mode system prompt into the LLM prompt:

   ```
   IMPORTANT: You are in PLANNING MODE. Do NOT make any code changes.
   Instead, write a detailed implementation plan. When your plan is complete,
   output it in a clearly delimited section. Do NOT implement anything yet.
   ```

2. Capture the response text as the plan
3. Present it via the existing `PlanApprovalModal` flow
4. On approval, send a new prompt with the plan content:
   ```
   The above plan has been reviewed and approved. Implement it now.
   ```

**Pros**:

- Completely provider-agnostic — no CLI flag differences
- No dependency on provider hook systems
- Simpler code — one implementation instead of three
- Works even with providers that don't have built-in plan mode

**Cons**:

- Less reliable than built-in plan mode — the LLM might ignore instructions and edit files anyway
- No sandbox enforcement during planning phase (providers run with full permissions)
- Requires careful prompt engineering per model family
- Plan text must be parsed from unstructured response (vs. dedicated plan file)

**Mitigation for sandbox concern**: For Claude, could still use `--permission-mode=plan` as a safety net alongside the
prompt injection. For others, accept the risk or add a read-only filesystem wrapper.

### Option B: MCP Tool for Plan Submission

Define a custom MCP tool that agents call to "submit" their plan for approval.

**How it would work**:

1. Register an MCP server that exposes a `submit_plan` tool and `ask_user_question` tool
2. Add these tools to each provider's available tool set
3. System prompt instructs the agent to call `submit_plan` when done planning
4. MCP server receives the plan, triggers TUI notification, blocks until approval
5. Returns approval/rejection/feedback as the tool response

**Pros**:

- Structured interface — plan text comes as a tool parameter, not scraped from output
- Works across all providers that support MCP (Claude, Gemini, Codex all do)
- Clean separation — the tool contract is explicit
- Q&A can use the same pattern (`ask_user_question` MCP tool)

**Cons**:

- Requires running an MCP server alongside each agent
- Adds complexity to the agent spawning pipeline
- MCP support maturity varies across providers
- Agents might not reliably call the tool without strong prompting

### Option C: Skill-Based Plan Mode

Use SASE's xprompt workflow system to implement plan mode as a multi-step workflow.

**How it would work**:

```yaml
# xprompts/plan.yml
steps:
  - name: generate_plan
    agent: |
      You are in planning mode. Analyze the request and produce a detailed
      implementation plan. Do NOT implement anything.

      Request: {{ prompt }}
    output:
      plan: text
    hitl: true # Human-in-the-loop: user reviews plan in TUI

  - name: implement
    agent: |
      The following plan has been approved. Implement it now.

      {{ steps.generate_plan.plan }}
    condition: "{{ steps.generate_plan.status == 'completed' }}"
```

**Pros**:

- Uses existing SASE infrastructure (workflows, HITL)
- Naturally provider-agnostic (workflows work with any provider)
- Built-in feedback loop via HITL modal (approve/reject/edit)
- Plan is a structured output field, not scraped from text

**Cons**:

- Loses the agent's internal session/context between plan and implement phases
- The planning agent and implementing agent are separate invocations
- May not preserve the nuance of "continue from where you left off"
- Workflow overhead for what should be a simple two-phase flow

### Option D: Hybrid — Prompt Injection + Provider Safety Nets

Combine Option A's prompt-level approach with whatever provider-specific safety features are available.

**How it would work**:

1. Always inject plan-mode instructions into the prompt (provider-agnostic)
2. Where available, also use provider CLI flags as a safety net:
   - Claude: `--permission-mode=plan` (prevents actual edits)
   - Gemini: `--approval-mode=plan` (triggers built-in approval)
   - Codex: `--sandbox read-only` (filesystem protection)
3. Plan capture: check provider plan directories first, fall back to response text parsing
4. Approval flow: unified `handle_plan_approval()` (already exists)
5. Feedback loop: unified retry mechanism (already exists in `_plan_utils.py`)

**This is essentially what exists today**, but with the prompt injection added to make the planning instruction explicit
rather than relying solely on provider built-in behavior.

---

## What About AskUserQuestion?

### Current Mechanism (Claude-Only)

Claude Code has a built-in `AskUserQuestion` tool that:

- Accepts a `questions` array with structured question objects
- Each question has `question` text, `options` array (label + description), `multiSelect` flag
- Claude calls this tool when it needs user input during execution

### Making Q/A Provider-Agnostic

**Option 1: MCP `ask_user_question` Tool**

The cleanest approach for unified Q/A. All three providers support MCP tool use.

```json
{
  "name": "ask_user_question",
  "description": "Ask the user one or more questions. Blocks until the user responds.",
  "parameters": {
    "questions": [
      {
        "question": "string",
        "options": [{ "label": "string", "description": "string" }],
        "multiSelect": "boolean"
      }
    ]
  }
}
```

The MCP server would:

1. Write `question_request.json` (same format as today)
2. Create TUI notification
3. Block until `question_response.json` appears
4. Return formatted answers as the tool response

**Pros**: Structured, works across all MCP-capable providers, clean tool contract **Cons**: Requires MCP server
infrastructure

**Option 2: Prompt-Injected Q/A Convention**

Add instructions to the system prompt:

```
When you need to ask the user a question, output it in a structured format:
---QUESTION---
question: Which approach should I use?
options:
  - label: Option A
    description: First approach
  - label: Option B
    description: Second approach
---END QUESTION---
Then STOP and wait for the response.
```

**Pros**: No infrastructure needed **Cons**: Unreliable parsing, agents might not stop and wait, no structured options
UI

**Option 3: Keep Claude's AskUserQuestion + Add Equivalent for Others**

- Claude: Continue intercepting `AskUserQuestion` via `PreToolUse` hook
- Gemini: Use Gemini's built-in approval/question mechanism (if one exists) or fall back to MCP
- Codex: Same approach

This is the least unified option but may be the most pragmatic if MCP infrastructure is too heavy.

---

## Recommendation

For plan mode: **Option D (Hybrid)** is the path of least resistance since it's mostly what exists today. The main
missing piece is the prompt injection layer that makes planning instructions explicit rather than relying entirely on
provider flags.

For Q/A: **Option 1 (MCP tool)** is the right long-term answer. It gives all three providers the same structured Q/A
interface and reuses the existing TUI modal and notification infrastructure.

### Concrete Next Steps

1. **Extract prompt injection templates** — create plan-mode system prompt templates that work well with each model
   family (Claude, Gemini, GPT). These go in the preprocessing pipeline.

2. **Refactor provider plan mode** — move the shared two-phase logic (plan → approve → implement) out of individual
   providers and into a shared orchestration layer. The provider-specific code should only handle CLI flag differences.

3. **Build MCP server for Q/A** — implement `ask_user_question` as an MCP tool that uses the existing file-based IPC and
   TUI notification infrastructure.

4. **Optionally: MCP `submit_plan` tool** — if prompt-level plan mode proves unreliable, add a structured plan
   submission tool via MCP as well.

---

## Key Files Reference

### Plan Mode

| File                                             | Purpose                                                     |
| ------------------------------------------------ | ----------------------------------------------------------- |
| `src/sase/llm_provider/claude.py`                | Claude plan mode (ExitPlanMode hook + feedback retry)       |
| `src/sase/llm_provider/gemini.py`                | Gemini plan mode (--approval-mode=plan + external approval) |
| `src/sase/llm_provider/codex.py`                 | Codex plan mode (--sandbox read-only + feedback retry)      |
| `src/sase/llm_provider/_plan_utils.py`           | Shared utilities (approval, feedback, persistence)          |
| `src/sase/main/plan_approve_handler.py`          | CLI handler for ExitPlanMode hook                           |
| `src/sase/ace/tui/modals/plan_approval_modal.py` | TUI modal (a=approve, r=reject, f=feedback, e=edit)         |
| `src/sase/xprompt/directives.py`                 | `%plan` directive parsing                                   |
| `src/sase/axe_run_agent_runner.py`               | Sets `SASE_AGENT_PLAN_MODE` env var                         |

### AskUserQuestion

| File                                                       | Purpose                              |
| ---------------------------------------------------------- | ------------------------------------ |
| `src/sase/main/user_question_handler.py`                   | CLI handler for AskUserQuestion hook |
| `src/sase/ace/tui/modals/user_question_modal.py`           | TUI modal for answering questions    |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | Notification dispatch                |
| `plans/claude_ask_user_question.md`                        | Original design document             |

### Hook Configuration

| File                                | Purpose                                             |
| ----------------------------------- | --------------------------------------------------- |
| `~/.claude/settings.json` (chezmoi) | PreToolUse hooks for ExitPlanMode + AskUserQuestion |
| `.claude/settings.json` (project)   | Project-level hooks (Stop only)                     |
| `.gemini/settings.json` (project)   | Gemini hooks (SessionEnd only)                      |

### Shared Infrastructure

| File                                     | Purpose                                                    |
| ---------------------------------------- | ---------------------------------------------------------- |
| `src/sase/llm_provider/base.py`          | `LLMProvider` abstract base class                          |
| `src/sase/llm_provider/_invoke.py`       | `invoke_agent()` orchestration                             |
| `src/sase/llm_provider/preprocessing.py` | Prompt preprocessing pipeline                              |
| `src/sase/notifications/senders.py`      | Notification creation (plan approval, user question, etc.) |
| `src/sase/llm_provider/registry.py`      | Provider registration and lookup                           |

---

## Appendix: IPC Protocol Summary

All agent-TUI communication uses the same pattern:

```
Agent/Hook Handler                 TUI
     |                              |
     |-- write request.json ------->|
     |-- create notification ------>|
     |                              |-- open modal
     |                              |-- user interacts
     |<---- write response.json ----|
     |-- read response              |
     |-- emit hook decision         |
     |-- cleanup files              |
```

**Directories**:

- Plan approval: `~/.sase/plan_approval/{session_id}/`
- User questions: `~/.sase/user_question/{session_id}/`
- Agent interrupts: `{artifacts_dir}/interrupt_request.json`

**Response actions**:

- Plan: `approve` | `reject` (with optional `feedback`)
- Question: `answers` array with `selected` options and optional `custom_feedback`
