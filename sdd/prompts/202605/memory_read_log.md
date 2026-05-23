---
plan: sdd/epics/202605/memory_read_log.md
---
 Can you help me create a new `sase memory read` command that, when given a file path that is relative to the memory/ directory as an argument, outputs the contents of the corresponding file (with the frontmatter removed)? This command should also log when the command was run, by what agent, and for what reason (this means the agent will need to give the reason as a command line argument).

The goal is to give the user an idea of which long-term memory files (memory/short/ files should never be read with this command and we should validate this, but I do plan on adding support for a different memory/ subdirectory in the future) are actually used and read. So we also want to add a new `sase memory log` command that displays those stats and supports a drill down view for more context on a particular agent read.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

