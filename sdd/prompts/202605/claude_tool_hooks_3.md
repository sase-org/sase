---
plan: sdd/epics/202605/claude_tool_hooks_3.md
---
 Can you help me start using one or more hooks to gather rich data about Claude's tool calls instead of our
existing implementation, which has never worked? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 

### Additional Requirements

- Make sure you add some new PNG snapshot tests that show what the new Tools panels looks like when populated with tool
  calls.