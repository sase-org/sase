# Glossary

- **ChangeSpec**: Represents a single CL/PR. Stored in `.gp` files at `~/.sase/projects/<project>/`. Sections: NAME,
  DESCRIPTION, PARENT, CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS. Active specs in `<project>.gp`; terminal ones
  (Submitted, Archived, Reverted) in `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.
- **ChangeSpec COMMITS Drawer**: A line of the form `| <NAME>: <FILE_PATH>` under a ChangeSpec COMMITS entry.
- **xprompt**: Triggered with `#foo` in agent prompts. Defined in an xprompts/ directory (.md or .yml file) or in
  ~/.config/sase/sase.yml (`xprompts` field).
- **xprompt Part**: .md file → single `prompt_part` step with the file's content.
- **xprompt Workflow**: .yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
- **Retry chain (spawn-on-retry)**: When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh
  detached child agent (as if `sase run -d` had been invoked) instead of in-process retry. The failing parent transfers
  its workspace claim to the child via `transfer_workspace_claim()` and exits with `FAILED (RETRIED)`. Linkage fields
  (in `agent_meta.json` / `done.json`): `retry_of_timestamp` (backward), `retried_as_timestamp` (forward),
  `retry_chain_root_timestamp` (root), `retry_attempt` (depth). State is carried across the boundary by
  `retry_handoff.json` written to the parent's artifacts dir. Spawn lives in `src/sase/axe/run_agent_retry_spawn.py`.
