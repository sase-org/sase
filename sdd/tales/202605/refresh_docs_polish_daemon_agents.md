---
create_time: 2026-05-09 23:27:26
status: wip
prompt: sdd/prompts/202605/refresh_docs_polish_daemon_agents.md
---
# Plan: Refresh Docs Polish Daemon Agent

## Goal

Update the scheduled `sase_refresh_docs` path so a refresh-docs run launches two daemon agents:

1. A documentation update agent that performs the existing `#sase/docs` review/update work.
2. A follow-up polish agent that waits for the first agent, resumes its context, and reviews the resulting documentation
   changes for factual accuracy and new-user clarity.

The important behavior change is that these agents should not run as synchronous `agent:` steps inside the
`#!refresh_docs` xprompt workflow. They should be launched with the same high-level daemon path used by
`xprompts/pylimit_split.yml`: a hidden Python workflow step calls `launch_agent_from_cwd(...)` with a multi-prompt.

## Current State

- The active workflow is not `xprompts/refresh_docs.yml`; that file is intentionally retired.
- The real workflow lives in `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` under
  `workflows.refresh_docs`.
- The `refresh_docs` lumberjack in that same config has one chop per repo. The main `sase_refresh_docs` chop invokes
  `#gh:sase %g:chop #!refresh_docs` every 60 minutes when its `run_every` gate allows it.
- The current workflow:
  - counts commits since `~/.sase/projects/<project>/refresh_docs_marker`;
  - runs a synchronous `agent:` step with `#sase/docs`;
  - updates the marker after that synchronous step completes.
- The pylimit pattern already shows the desired launch model: a hidden Python step builds a wait-chained multi-prompt
  and calls `launch_agent_from_cwd(...)`, allowing the actual work to appear as normal daemon agents while preserving
  chop metadata in the inherited environment.
- The chezmoi repo already has unrelated local edits in `sase_athena.yml` changing `%t:chop` to `%g:chop`; preserve
  those edits.

## Design

### 1. Keep the chop entry as a lightweight workflow trigger

Leave the `sase_refresh_docs` chop configured as an agent chop that invokes `#!refresh_docs`. The chop should continue
to be deduped by the lumberjack agent-chop registry and should keep the existing `%g:chop` grouping.

Do not move the two real documentation agents directly into the lumberjack `agent:` string. Keeping the count/threshold
logic inside `#!refresh_docs` avoids relaunching docs agents when the marker threshold has not been met.

### 2. Add `gh_ref` as an explicit workflow input

The scheduled plugin-repo chops already pass `gh_ref=...`, and docs currently describe that input. Make the config
workflow declare it explicitly with default `sase`.

Use `gh_ref` in both daemon-agent prompts so each launched segment targets the intended repository:

- main SASE: `#gh:sase`
- sibling repos: `#gh:sase-org/<repo>`

### 3. Replace the synchronous docs agent step with a hidden daemon-launch Python step

Replace the current `run_docs` `agent:` step with a hidden Python step, for example `launch_docs_agents`, gated by the
same commit threshold condition.

The Python step should:

- import `launch_agent_from_cwd` and `build_wait_chained_multi_prompt`;
- render `project` and `gh_ref` from workflow inputs;
- build a first segment for the existing docs update work;
- build a second segment for the polish pass;
- call `launch_agent_from_cwd(multi_prompt)`;
- print a simple structured output such as `launched=2`.

The first segment should include a stable `%name:` directive, the repo VCS tag, `%g:chop`, and `#sase/docs`.

The second segment should include its own stable `%name:` directive, the same repo VCS tag, `%g:chop`, a bare `#resume`,
and explicit polish instructions:

- inspect the first agent's documentation changes;
- verify descriptions against the current system rather than assuming they are true;
- improve clarity for a new user;
- keep edits scoped to documentation unless a tiny companion correction is required;
- run appropriate docs checks if files changed.

Use `build_wait_chained_multi_prompt([docs_prompt, polish_prompt])` so the second segment starts with a bare `%wait`.
Because the first segment has an explicit name, the multi-prompt launcher will rewrite both bare `%wait` and bare
`#resume` to that first daemon agent.

### 4. Keep marker updates after successful handoff

Keep `update_marker` after the daemon-launch step and gate it on the same threshold. This changes the marker meaning
slightly: it records that a docs refresh was successfully handed off for the current HEAD, not that the daemon agents
have completed.

That tradeoff is acceptable for this scheduled chop because:

- the lumberjack registry prevents duplicate launches while the daemon agents are live;
- updating the marker avoids relaunching the same docs review every hour after the handoff succeeds;
- daemon agent failures remain visible as normal failed agents, which is consistent with the pylimit-style chop model.

Do not ask the polish agent to update the marker itself; marker management should stay in the workflow launcher logic,
not in freeform agent instructions.

### 5. Apply the same workflow behavior to all refresh-docs repo chops

Because all refresh-docs chops invoke the shared `#!refresh_docs` workflow, this implementation will give the two-agent
update-and-polish behavior to `sase_refresh_docs` and to the sibling repo refresh-docs chops. That is preferable to a
special case for only the main repo because the workflow's purpose and quality bar are the same for every target repo.

## Files To Change

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
  - declare `gh_ref`;
  - replace the synchronous `run_docs` agent step with a hidden Python daemon-launch step;
  - keep `count_commits` and `update_marker`, adjusted only as needed for the new step name/output.

Possibly add or update a lightweight test in the chezmoi repo only if there is an existing suitable test surface for
Athena workflow config. Avoid adding SASE core code unless config parsing or validation exposes a real gap.

## Validation

After editing:

1. In the SASE repo, run `just install` if needed, then at least:
   - `sase xprompt explain refresh_docs`
   - `just check`
2. In the chezmoi repo, run:
   - `just check`
3. If the live config should pick up the change immediately, run:
   - `chezmoi apply --force`

If any full check is blocked by unrelated existing chezmoi changes, record that clearly and run the narrowest useful
validation for the edited workflow config.

## Acceptance Criteria

- `#!refresh_docs` no longer contains a synchronous `agent:` docs step.
- A threshold-passing refresh-docs run launches a daemon multi-prompt with exactly two agent segments.
- The second segment waits for and resumes the first segment.
- Both segments target the configured `gh_ref`.
- The polish prompt explicitly evaluates accuracy and new-user clarity.
- Existing `%g:chop` local edits in `sase_athena.yml` remain intact.
