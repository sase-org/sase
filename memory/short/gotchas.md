# Code Conventions and Gotchas

- **Always define short options** (e.g., `-m`, `-f`) for every argument on all `sase` CLI subcommands
- When changing keymaps, leader mode keys, or any configuration values, don't forget to update the keymap configuration
  in the `src/sase/default_config.yml` file if necessary.
- All supported agent runtimes (Claude, Gemini, Codex, etc.) have the same capabilities: they all support hooks, skills,
  and the same commit workflow. Do NOT introduce runtime-specific special cases or branching logic that assumes one
  runtime lacks a capability that others have. Treat all runtimes uniformly.
- By default, the coder agent does NOT inherit the planner's chat transcript (the plan file is the hand-off artifact).
  Set `SASE_CODER_INHERIT_PLANNER_CHAT=1` to restore the old behavior and prepend `#resume:<planner_name>` to the coder
  prompt.
- Jetski skills deploy to `~/.gemini/jetski/skills/` (not `~/.jetski/skills/`) by design — Jetski shares the
  `~/.gemini/` parent with Gemini CLI. The `_SKILL_DEPLOY_SUBPATH` override in `init_skills_handler.py` encodes this;
  don't "fix" it.
- Memory xprompt `keywords` support a `!` prefix for **negative keywords**: a match on any negative keyword excludes the
  memory from `### DYNAMIC MEMORY` even if positive keywords also matched (e.g. `keywords: [skill, "!jetski"]`). In
  YAML, `!`-prefixed entries MUST be quoted (`"!jetski"`) — an unquoted `!foo` is parsed as a YAML tag directive and
  errors at load time.
