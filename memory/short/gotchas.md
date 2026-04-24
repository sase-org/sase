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
- Jetski is **not** a built-in sase LLM provider — it ships as part of the `sase-google` plugin. Its
  `llm_skill_deploy_subpath()` hook returns `.gemini/jetski` so skills land under `~/.gemini/jetski/skills/` (not
  `~/.jetski/skills/`), sharing the `~/.gemini/` parent with Gemini CLI by design; don't "fix" it.
- Memory xprompt `keywords` support a `!` prefix for **negative keywords**: each negative keyword masks its matched
  spans out of the prompt before positive-keyword matching runs, so a memory is excluded only when every positive hit
  fell inside a masked region (e.g. `keywords: [foo, "!/foo/"]` matches `"update foo and /path/to/foo/"` via the
  standalone `foo` but not `"update /path/to/foo/"`). A negative hit that doesn't cover any positive hit is a no-op. In
  YAML, `!`-prefixed entries MUST be quoted (`"!jetski"`) — an unquoted `!foo` is parsed as a YAML tag directive and
  errors at load time.
