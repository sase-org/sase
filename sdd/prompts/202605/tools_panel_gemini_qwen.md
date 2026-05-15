---
plan: sdd/epics/202605/tools_panel_gemini_qwen.md
---
 We recently added a new Tools panel to the "Agents" tab of the `sase ace` TUI. It is currently only supported
by the Claude and Codex LLM providers. Can you help me add support for the Tools panel to Gemini and Qwen too? Make sure
we use asynchronous calls so we do not block the UI thread (I know Claude does this already--if Codex doesn't you should
fix that).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

