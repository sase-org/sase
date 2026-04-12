# Code Conventions and Gotchas

- **Always define short options** (e.g., `-m`, `-f`) for every argument on all `sase` CLI subcommands
- When changing keymaps, leader mode keys, or any configuration values, don't forget to update the keymap configuration
  in the `src/sase/default_config.yml` file if necessary.
- All supported agent runtimes (Claude, Gemini, Codex, etc.) have the same capabilities: they all support hooks, skills,
  and the same commit workflow. Do NOT introduce runtime-specific special cases or branching logic that assumes one
  runtime lacks a capability that others have. Treat all runtimes uniformly.
