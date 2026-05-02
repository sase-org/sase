---
create_time: 2026-04-13 11:10:52
status: wip
prompt: sdd/prompts/202604/split_google3_rules.md
---

# Plan to Split `google3_rules.md`

## Current State

The `~/.gemini/memory/short/google3_rules.md` file currently contains several distinct concepts grouped together:

1. Workflow restrictions (Never Create/Update CLs).
2. Coding Standards (Doc comments for public symbols).
3. Miscellaneous practices (TODO prefixes, preferring CodeSearch over `find`/`grep`).
4. Agent capability restrictions (No native plan mode, no AskUserQuestion, use sase skills instead).

## Proposed Split

To make the short-term memory more granular and easier to trigger conditionally (if needed in the future) or just easier
to maintain, we can split it into three focused files:

### 1. `google3_workflow_and_tools.md`

**Content:**

- **CL Workflow:** The directive to NEVER upload/amend a CL, but only make file changes.
- **Tool Preferences:** The directive to ALWAYS prefer the `CodeSearch` tool over shell commands like `find` and `grep`.

### 2. `google3_coding_standards.md`

**Content:**

- **Doc Comments:** The requirement that ALL public symbols have doc comments (unless exempt by a standard pattern).
- **TODO Prefixes:** The rule that all TODOs must be prefixed with "TODO(bbugyi):".

### 3. `google3_agent_skills.md`

**Content:**

- **Plan Mode:** The restriction against using native `EnterPlanMode`/`ExitPlanMode` and the instruction to use the
  `/sase_plan` skill.
- **Questions:** The restriction against using `AskUserQuestion` and the instruction to use the `/sase_questions` skill.

## Execution Steps

1. Create `~/.gemini/memory/short/google3_workflow_and_tools.md` with the relevant content.
2. Create `~/.gemini/memory/short/google3_coding_standards.md` with the relevant content.
3. Create `~/.gemini/memory/short/google3_agent_skills.md` with the relevant content.
4. Delete the old `~/.gemini/memory/short/google3_rules.md` file.
5. Update `~/.gemini/GEMINI.md` to reference the new files instead of `google3_rules.md` in the "Tier 1 (short-term)
   Memory" section.
