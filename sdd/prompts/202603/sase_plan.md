---
plan: sdd/epics/202603/sase_plan.md
---
Can you help me create new `/sase_plan` and `/sase_questions` Claude Code skills that will replace claude's native
plan-mode and question-asking? The goal of this change is to eventually standardize on a single, unified plan-mode
process for all LLM provider types, but we will start with just claude.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### Changes Required to CLAUDE.md and Claude LLM Provider

- We should completely disable claude's ability to use its native plan-mode or ask questions. Use **both** approaches:
  - **Hook-based denial**: The existing `ExitPlanMode` and `AskUserQuestion` PreToolUse hooks in the chezmoi repo should
    remain, but should be updated to return `{"decision": "deny"}` with a message pointing to the proper skill that
    should be used instead (i.e. `/sase_plan` or `/sase_questions`).
  - **CLAUDE.md instructions**: Give CLAUDE.md clear instructions on two things: (1) It does NOT have access to plan
    mode; it should use the `/sase_plan` skill instead. (2) It does NOT have access to ask questions the normal way and
    should instead use the `/sase_questions` skill instead.
- **Important**: Claude should only know about the `/sase_plan` and `/sase_questions` skills, NOT the underlying
  `sase plan` and `sase questions` CLI subcommands. Those subcommands are implementation details used by the skills
  themselves.

### Availability

- The `/sase_plan` and `/sase_questions` skills should **only** be available when running inside sase (e.g. via the
  `sase ace` TUI or `sase run`). They should not be registered or available when claude is run directly outside of sase.

### A New `claude` Instance for ALL the Things

- When a plan is proposed via the `sase plan` command, the current `claude` instance will be killed. If the plan is
  approved by the user, a new "coder" agent will be created in the same workflow (see below bullet). If the plan is
  **rejected**, the workflow should be killed and dismissed entirely (no retry loop).
- We will also kill the current agent when `sase questions` is used by an agent to ask the user one or more questions
  and then create a new agent with the same prompt but with a "Questions and Answers" H3 section added to the bottom.
  These will also be in the same workflow (and will be shown as steps in the "Agents" tab).
- These new agents will be dynamically created within the current agent workflow (this creates a multi-agent workflow,
  so it should be displayed as such in the "Agents" tab of the `sase ace` TUI) and each workflow step should have the
  same number as the original agent but should be given a suffix name that indicates what role it played:
  - `.plan` for planner agents (e.g. `1/1.plan`)
  - `.code` for coder/implementation agents (e.g. `1/1.code`)
  - `.q` for agents that asked questions (appended to the current suffix)
  - Questions asked in sequence keep appending `.q` (e.g. `1/1.code.q` → `1/1.code.q.q`)
  - Example full lifecycle: `1/1.plan` → `1/1.code` → `1/1.code.q` (coder asked a question) → `1/1.code.q.q` (asked
    another question in sequence) — that's at least 4 agent instances.

### Kill and Signal Mechanism

- **Agent runner signaling**: When `sase plan` or `sase questions` needs to kill the current claude instance, it should
  signal the agent runner (`axe_run_agent_runner.py`) rather than killing claude directly. The agent's name should
  always be injected as a `SASE_AGENT_NAME` environment variable when running the `claude` command, so `sase plan` /
  `sase questions` can identify which agent to signal.
- **Marker files**: To distinguish "killed for plan" vs "killed for questions" vs "actually done" vs "crashed", the
  `sase plan` and `sase questions` commands should write marker files before signaling the runner:
  - `sase plan` writes a `.sase_plan_pending` marker file
  - `sase questions` writes a `.sase_questions_pending` marker file
  - The agent runner reads these markers to determine the appropriate next action.

### `/sase_plan` Skill Requirements

- The skill should instruct claude to, after it understands the problem, has made sufficient exploration, and finished
  the plan, write the plan to a relative file named `sase_plan_<name>.md` where `<name>` is a good name (separated by
  underscores) selected by the agent.
- **Important**: The skill should make it clear to the planner agent that the coder agent will receive ONLY the plan
  file as context — no exploration notes, no conversation history, nothing else carries over. The plan must therefore be
  completely self-contained: it should include all relevant file paths, code snippets, architectural context, and
  step-by-step instructions needed to implement the changes without any additional exploration.
- Finally, the skill should instruct claude to run the `sase plan sase_plan_<name>.md` shell command, which will kill
  the agent (see "Kill and Signal Mechanism" section).

### `/sase_questions` Skill Requirements

- The `/sase_questions` skill should instruct claude on how to ask the user questions via the `sase questions` CLI
  command. Claude should use this skill whenever it needs input from the user.
- Questions are passed as a JSON argument: `sase questions '<json>'`
- We MUST support all of the same functionality that claude's native question/answer system does (e.g. multiple
  questions, recommended answers, custom answers, etc. — see how we display these in the notification popup in the TUI;
  I want to keep this exactly the same as the current experience).
- The skill should document the exact JSON schema that claude must use when formatting questions.

### The NEW `sase plan` Subcommand

- You will need to create a new `sase plan` subcommand that will be used by the `/sase_plan` skill.
- The `sase plan` command will be responsible for:
  - Writing a `.sase_plan_pending` marker file.
  - Signaling the agent runner to kill the current agent (identified via `SASE_AGENT_NAME`).
  - Moving the plan file to `~/.sase/plans/` for archival.
  - Triggering the plan notification in the same way that claude code's hooks currently do for plans.
- **Auto-approve behavior**: If auto-approve is enabled, the notification should be skipped entirely and the runner
  should immediately spawn the coder agent.

### The NEW `sase questions` Subcommand

- You will also need to create a new `sase questions` subcommand that will allow claude to ask the user questions from
  the command-line.
- The `sase questions` command accepts structured question data as a JSON argument.
- We MUST support all of the same functionality that claude's native question/answer system does (e.g. multiple
  questions, recommended answers, custom answers, etc. — see how we display these in the notification popup in the TUI;
  I want to keep this exactly the same as the current experience).
- The `sase questions` command will be responsible for:
  - Writing a `.sase_questions_pending` marker file.
  - Signaling the agent runner to kill the current agent (identified via `SASE_AGENT_NAME`).
  - Triggering the question notification in the same way that claude code's hooks currently do for questions.
