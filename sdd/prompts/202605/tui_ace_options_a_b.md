---
plan: sdd/epics/202605/tui_ace_options_a_b.md
---
 Can you help me optimize the TUI by implementing the options A (Fix the _CachedSyntaxRenderable width-vs-height cache key) and B (Move the post-load apply/finalize prep off the UI thread) that were recommended by the sdd/research/202605/ace_profile_20260515_105702_next_optimization.md file? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

