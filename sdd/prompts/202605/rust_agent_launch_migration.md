---
plan: sdd/epics/202605/rust_agent_launch_migration.md
---
 Is there any part of sase's code related to launching agents that is in Python now, but would benefit from being migrated over to our Rust sase-core repo? Launching agents can still be a little
slow in the TUI. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

