---
keyword: Agent Instruction File
aliases:
  - agents.md file
---

An agent instruction file is a `.md` file that an agent CLI reads automatically when
working in a directory that contains it. `AGENTS.md` is the canonical name, kept beside
a byte-identical `CLAUDE.md` copy for older Claude Code versions; Antigravity (agy),
Qwen Code, and OpenCode all read `AGENTS.md` through native discovery.
`sase memory init` renders the project files from the notes in `sase/memory/`. A
SASE-launched agent does not read these files: it gets a per-invocation
[[glossary:instruction-bundle]] built from the same notes instead.
