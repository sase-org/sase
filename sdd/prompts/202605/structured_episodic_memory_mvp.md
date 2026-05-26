---
plan: sdd/epics/202605/structured_episodic_memory_mvp.md
---
 Can you help me implement an ambitious MVP for structured, deterministic episodic memory, stored in the `~/.sase/projects/<project>/episodes/` directory, that use as much of the existing sase metadata / artifacts (and new ones that you add, if necessary) as possible to link together sase chats into a coherent lesson? Use existing research to inspire your approach. Also, if a new `episodes` command is needed, it should be named `sase memory episodes`, not `sase episodes`.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

