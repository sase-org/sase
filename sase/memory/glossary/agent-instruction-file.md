---
keyword: Agent Instruction File
aliases:
  - agents.md file
---

An agent instruction file is a `.md` file that an agent CLI reads automatically when
working in a directory that contains it. For example, the `AGENTS.md` file is the name
of the agent instruction file that is supported by codex. sase supports one agent
instruction file per supported agent CLI (ex: `CLAUDE.md` for claude, `GEMINI.md` for
antigravity, etc...). The `sase init` command, which is run automatically as a sase
post-commit hook, initializes the top-level agent instruction files using memories in
the sase/memory/ directory and ensures that all agent instruction files in the same
directory contain the same contents.
