---
create_time: 2026-05-13 19:28:08
status: done
prompt: sdd/prompts/202605/retry_agent_skill.md
---
# Plan: Teach `/sase_agents_status` How to Retry Agents

## Goal

Update the generated `/sase_agents_status` skill so future agents can reliably retry a prior SASE agent from terminal
context, without depending on TUI-only muscle memory or mutating generated installed skill files by hand.

## Context Learned

- The installed Codex skill at `/home/bryan/.codex/skills/sase_agents_status/SKILL.md` is generated and should not be
  hand-edited.
- The source of truth is `src/sase/xprompts/skills/sase_agents_status.md`; generated skill deployment is handled by
  `sase init-skills --force` followed by `chezmoi apply`.
- `sase agents show -n <name>` displays the artifact directory and raw prompt when `raw_xprompt.md` exists.
- `sase agents status -a -j` can find recent DONE/FAILED agents, while `sase agents status -j` is only for live agents.
- Normal CLI launch is `sase run -d '<prompt>'`.
- Direct forced name reuse with `%name:!foo` is a TUI-confirmed path; non-TUI launch validation rejects forced reuse
  because confirmation is required.
- The TUI retry-edit path allocates a fresh retry name with `allocate_retry_name(base)` and rewrites/prepends the prompt
  name directive to `%name:<base>.<N>`.
- The same prompt-name rewrite helper is used by mobile retry flow. It prefers `raw_xprompt.md` and falls back to stored
  context, then launches a detached retry.

## Implementation

1. Edit `src/sase/xprompts/skills/sase_agents_status.md`, not the installed generated copy directly.
2. Add a focused `## Retrying an agent` section after the existing CLI quick-reference, because retrying is an action
   based on status/show output rather than artifact inspection.
3. Document the conservative terminal workflow:
   - Locate the source agent with `sase agents status -a -j` or `sase agents show -n <name>`.
   - Read `<artifacts_dir>/raw_xprompt.md` as the retry prompt source when present.
   - Allocate the next retry name using the public helper `sase.agent.names.allocate_retry_name("<name>")`.
   - Rewrite or prepend the top-level name directive using `sase.agent.retry_prompt.rewrite_retry_prompt_name`.
   - Launch with `sase run -d "$rewritten_prompt"` from the intended workspace/project context.
   - Confirm with `sase agents status -a -j` or `sase agents show -n <retry-name>`.
4. Explicitly warn future agents not to use `%name:!<name>` from non-TUI surfaces for ordinary retry, because forced
   reuse wipes the prior owner and requires the TUI confirmation path.
5. Mention when forced reuse is appropriate: only for a user-approved intentional rerun under the exact same name, and
   only through code paths that call `wipe_names_for_forced_reuse` and rewrite the directive back to `%name:<name>`
   before spawning.
6. Keep wording short enough for a skill file and avoid adding brittle private operational recipes beyond the existing
   helper APIs.
7. Regenerate/deploy generated skills with `sase init-skills --force` and `chezmoi apply`, if available in this session.
   If deployment is blocked, report that the source was updated and the live installed skill may still need
   regeneration.
8. Verify the source and generated installed skill contain the new retry section. Because this is a documentation/skill
   source change outside runtime code, do not run the full `just check` unless repo tooling or generation changes
   tracked Python/package files.

## Risks and Mitigations

- Risk: future agents might erase prior artifacts while trying to retry. Mitigation: make fresh retry-name allocation
  the default and frame forced reuse as exceptional.
- Risk: agents might retry from the wrong project context. Mitigation: instruct them to use the source agent's
  project/artifact data and launch from the intended workspace.
- Risk: installed skill drift. Mitigation: update the source of truth and run the documented generation/deployment path.
