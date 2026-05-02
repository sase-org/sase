---
create_time: 2026-04-13 11:13:07
status: wip
prompt: sdd/prompts/202604/split_google3_rules_2.md
---

# Plan: Split `google3_rules.md` into smaller short-term memory files

## Goal

To organize `google3_rules.md` by breaking it down into distinct, focused, topical files. This modularization will help
maintainability and keep short-term memory organized.

## Analysis of Current File

The `google3_rules.md` file currently contains four distinct categories of rules:

1.  **CLs**: Strict instructions _never_ to create or update Changelists.
2.  **Coding Standards**: Rules around doc comments for public symbols (e.g., Dart).
3.  **Miscellaneous**: Includes TODO formatting (`TODO(bbugyi)`) and instructions to prefer CodeSearch over
    `find`/`grep`.
4.  **Disabled Native Features (Agent capabilities)**: Instructions to avoid `EnterPlanMode` and `AskUserQuestion`
    native tools in favor of `/sase_plan` and `/sase_questions` skills.

## Proposed Splits

Based on the analysis, I recommend splitting `google3_rules.md` into the following separate files within
`~/.gemini/memory/short/`:

1.  **`google3_cls.md`**
    - **Content**: The "Never Create/Update CLs!" section.
    - **Rationale**: This is a critical workflow constraint specific to interaction with the Google3 repository and
      version control.

2.  **`google3_coding_style.md`**
    - **Content**: The "Coding Standards" section (doc comments) and the "TODO" prefix rule from the Miscellaneous
      section.
    - **Rationale**: Groups all code-level formatting and style constraints into one place.

3.  **`google3_tools.md`**
    - **Content**: The instructions to use the CodeSearch tool instead of bash commands (`find`, `grep`).
    - **Rationale**: Focuses entirely on Google3-specific tool selection and search best practices.

4.  **`sase_agent_skills.md`**
    - **Content**: The "Plan Mode and Questions" section (replacing native features with `/sase_plan` and
      `/sase_questions` skills).
    - **Rationale**: This relates more directly to the agent's operating constraints and SASE skills rather than Google3
      specifically. Keeping this separate makes it clearer that these are agent configuration overrides.

## Implementation Steps

1. Create the new files (`google3_cls.md`, `google3_coding_style.md`, `google3_tools.md`, `sase_agent_skills.md`) in
   `~/.gemini/memory/short/`.
2. Extract the relevant text from `~/.gemini/memory/short/google3_rules.md` into these new files.
3. Update `~/.gemini/GEMINI.md` to update the short-term memory import statements, replacing `google3_rules.md` with the
   new list of files.
4. Delete the original `google3_rules.md`.
