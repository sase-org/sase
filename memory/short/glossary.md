# Glossary

- **ChangeSpec**: Represents a single CL/PR. Stored in `.gp` files at `~/.sase/projects/<project>/`. Sections: NAME,
  DESCRIPTION, PARENT, CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS. Active specs in `<project>.gp`; terminal ones
  (Submitted, Archived, Reverted) in `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.
- **ChangeSpec COMMITS Drawer**: A line of the form `| <NAME>: <FILE_PATH>` under a ChangeSpec COMMITS entry.
- **xprompt**: Triggered with `#foo` in agent prompts. Defined in an xprompts/ directory (.md or .yml file) or in
  ~/.config/sase/sase.yml (`xprompts` field).
- **xprompt Part**: .md file → single `prompt_part` step with the file's content.
- **xprompt Workflow**: .yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
- **Multi-agent xprompt**: An xprompt whose body contains `---` segment separators (outside fenced blocks). When
  referenced as the sole content of a user-prompt segment (e.g. `sase run "#three_phase(login)"`), each body segment is
  dispatched as its own agent via `launch_multi_prompt_agents`; all spawned agents share the same input arguments.
  Detection and expansion live in `src/sase/agent/multi_agent_xprompt.py` and run after `parse_multi_prompt` at each
  dispatch site (`launcher.py`, `_query.py`, TUI `_agent_launch.py`). Inline references inside another xprompt's body
  are NOT re-split (handled by the agent runner's normal xprompt expansion).
- **Epic work automation**: `sase bead work <epic_id>` flips the epic plan's `is_ready_to_work` flag, builds a Kahn-wave
  schedule from the epic's open phase children, pre-claims each phase bead (`status=in_progress`,
  `assignee=<phase_bead_id>` — i.e. `<epic_id>.<N>`), and hands a single `---`-separated multi-prompt to
  `launch_agent_from_cwd()`. The per-phase agents reference `bd/work_phase_bead` and a final land agent (named
  `<epic_id>`) references `bd/land_epic` (both resolved by `XPromptTag` so users can override). `--dry-run` prints the
  plan without mutating; `--yes` skips the confirm prompt; on launch failure the handler rolls back pre-claims and the
  ready flag best-effort. See `src/sase/bead/work.py` and `handle_bead_work` in `src/sase/bead/cli.py`.
- **Retry chain (spawn-on-retry)**: When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh
  detached child agent (as if `sase run -d` had been invoked) instead of in-process retry. The failing parent transfers
  its workspace claim to the child via `transfer_workspace_claim()` and exits with `FAILED (RETRIED)`. Linkage fields
  (in `agent_meta.json` / `done.json`): `retry_of_timestamp` (backward), `retried_as_timestamp` (forward),
  `retry_chain_root_timestamp` (root), `retry_attempt` (depth). State is carried across the boundary by
  `retry_handoff.json` written to the parent's artifacts dir. Spawn lives in `src/sase/axe/run_agent_retry_spawn.py`.
