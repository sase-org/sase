---
plan: sdd/epics/202605/bead_event_log_migration.md
---
 Can you help me implement some big changes to the way we store bead data by implementing the solution recommended in the @sdd/research/202605/sase_tui_agents_tab_mvp_research.md file? This migration should be complete; it is fine to leave legacy support for issues.jsonl, but the new canonical event log should be the new source of truth for beads. Make sure to migrate existing beads over to the new file structure.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

