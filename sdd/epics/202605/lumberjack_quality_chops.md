---
create_time: 2026-05-09 23:55:37
status: wip
prompt: sdd/prompts/202605/lumberjack_quality_chops.md
bead_id: sase-2n
tier: epic
---
# Plan: Add Commit-Threshold Bug and Improvement Lumberjack Chops

## Goal

Add two scheduled Athena lumberjack chops:

- A bug-audit chop that reviews commits since its last successful launch and fixes any bugs it finds.
- An improvement-audit chop that reviews commits since its last successful launch and only changes code when the change
  is a clear, objective win.

Both chops should mirror the active `refresh_docs` workflow's early-abort behavior: do not launch the actual work agent
until at least 50 commits have landed since the relevant marker. Both agent prompts must embed the `#pr` xprompt so any
resulting edits go through the standard PR workflow.

## Current Shape

The active implementation lives in the chezmoi Athena config:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- `workflows.refresh_docs` counts commits since `~/.sase/projects/<project>/refresh_docs_marker`.
- If the marker SHA exists, it counts `marker..HEAD`; if the SHA is gone but a marker timestamp exists, it counts
  commits after the timestamp; if no usable marker exists, it forces a run.
- The workflow updates the marker after launching its daemon agents, so the threshold is tied to the last time the
  chop's agents ran.
- The `refresh_docs` lumberjack schedules repo-specific agent chops that invoke `#!refresh_docs(...)`.

This work should follow that pattern rather than adding Python product code unless a validation gap requires it.

## Design

Introduce two new standalone config workflows in `sase_athena.yml`:

- `audit_recent_bugs`
- `audit_recent_improvements`

Each workflow should accept:

- `project`, default `sase`
- `gh_ref`, default `sase`
- `threshold`, default `50`

Each workflow should:

1. Count commits since `~/.sase/projects/<project>/<workflow_marker>`, using the same SHA and timestamp fallback
   semantics as `refresh_docs`.
2. Abort early when `count < threshold`.
3. When `count >= threshold`, launch one daemon agent via `launch_agent_from_cwd`.
4. Include the commit range in the prompt, ideally both the base SHA/timestamp context and the current HEAD, so the
   agent knows exactly what to inspect.
5. Embed `#pr(...)` in the launched prompt, not merely mention it in prose.
6. Update the workflow-specific marker to current `HEAD` and commit timestamp after launching the agent.

Use distinct marker files so the two chops do not suppress each other:

- `recent_bug_audit_marker`
- `recent_improvement_audit_marker`

Add scheduled chops under a new lumberjack such as `code_quality` or under the existing low-frequency scheduled group.
Prefer a new `code_quality` lumberjack to keep intent visible:

- `sase_recent_bug_audit`
- `sase_recent_improvement_audit`

Both should use `run_every: 60m` or another conservative cadence, relying on the workflow's 50-commit threshold for the
real launch gate. Their prompt wrappers should keep the current repo targeting convention:

- `#gh:sase %g:chop #!audit_recent_bugs`
- `#gh:sase %g:chop #!audit_recent_improvements`

The improvement prompt must be stricter than the bug prompt:

- Only make changes for clear, objective wins.
- Do not perform style churn, speculative refactors, preference changes, or broad rewrites.
- If no objectively valuable change is found, leave the worktree untouched and report that outcome.

## Phase 1: Config Workflow Implementation

Agent responsibility: edit only `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.

Tasks:

- Add `audit_recent_bugs` and `audit_recent_improvements` under top-level `workflows`.
- Reuse the `refresh_docs` marker counting structure closely enough that SHA fallback, timestamp fallback, first-run
  behavior, and marker updates stay consistent.
- Name launched agents using stable prefixes that include project and short HEAD, for example `audit_bugs.sase.<head>`
  and `audit_improvements.sase.<head>`.
- For the bug agent prompt:
  - Include `#gh:<gh_ref> %g:chop #pr(<pr-name>)`.
  - Tell the agent to inspect every commit in the since-last-run range for bugs and fix confirmed issues.
  - Tell it to avoid unrelated improvements.
- For the improvement agent prompt:
  - Include `#gh:<gh_ref> %g:chop #pr(<pr-name>)`.
  - Tell the agent to inspect every commit in the since-last-run range for improvements.
  - Explicitly require clear, objective wins and no speculative changes.
- Update separate marker files only when the threshold condition is met and the launch step ran.

Acceptance:

- `sase xprompt explain audit_recent_bugs` resolves.
- `sase xprompt explain audit_recent_improvements` resolves.
- The rendered prompts include `#pr`.
- The threshold defaults are 50.

## Phase 2: Lumberjack Wiring

Agent responsibility: edit only `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.

Tasks:

- Add a `code_quality` lumberjack or equivalent clearly named scheduled group.
- Add the two new chops for the `sase` repo.
- Use descriptions that distinguish bug fixing from objective improvements.
- Keep the existing refresh-docs chops unchanged.
- Ensure chop names, workflow names, and marker names are all distinct.

Acceptance:

- The merged axe config includes the new lumberjack and both chop names.
- The chop agent strings invoke the new workflows with `#!`.
- No existing chop names are changed.

## Phase 3: Focused Static and Workflow Validation

Agent responsibility: validate the config change without changing product code unless the validation exposes a real
defect.

Tasks:

- Run YAML parsing against `sase_athena.yml`.
- Run `sase xprompt explain audit_recent_bugs`.
- Run `sase xprompt explain audit_recent_improvements`.
- If available, run a command or small inspection that loads the merged axe config and verifies:
  - the new workflows are visible;
  - the new lumberjack/chops are present;
  - both chops carry their intended `run_every`.
- Check current git status in the chezmoi repo and avoid disturbing unrelated user edits.

Acceptance:

- Both workflows load and explain cleanly.
- The config parser sees both chops.
- No unrelated files are modified.

## Phase 4: Extensive End-to-End Testing With Sonnet

Agent responsibility: run an end-to-end verification pass using a fast model such as Sonnet. This phase should focus on
actual behavior rather than only static parsing.

Tasks:

- Use a temporary test repository or disposable workspace with enough synthetic commits to cross the 50-commit
  threshold.
- Configure marker files in a temporary `HOME`/SASE project area so the test does not mutate real markers.
- Launch or dry-run the workflows in a way that exercises:
  - first-run behavior;
  - below-threshold abort;
  - exactly-at-threshold launch;
  - stale SHA plus timestamp fallback;
  - independent bug and improvement marker files.
- Use Sonnet for the spawned validation agent or mocked launch target where the real product path requires a model
  choice.
- Confirm the launched prompt for each workflow contains:
  - the expected commit range;
  - `#pr`;
  - bug-only language for the bug audit;
  - objective-win-only language for the improvement audit.
- Confirm marker updates happen after launch and prevent immediate relaunch below the next 50-commit window.

Acceptance:

- There is evidence from artifacts/logs/stdout that both workflows exercise the threshold gate correctly.
- There is evidence that the generated agent prompts include `#pr` and the right review scope.
- Real user marker files under `~/.sase/projects/sase/` are not changed by the test.

## Phase 5: Apply and Repository Checks

Agent responsibility: final integration and system application.

Tasks:

- Run `just check` in `~/.local/share/chezmoi`.
- Because this changes chezmoi-managed config, run `chezmoi apply --force` after checks pass.
- If any SASE repo files were changed in later phases, run `just install` and `just check` in
  `/home/bryan/projects/github/sase-org/sase_103`; otherwise skip the SASE repo check.
- Summarize changed files, commands run, and any residual risk.

Acceptance:

- Chezmoi check passes.
- Applied config contains the new workflows and chops.
- Final status shows only intentional changes.

## Risks and Decisions

- The marker is updated immediately after launching the agent, matching `refresh_docs`. If the spawned agent fails
  quickly, the next run will still wait for another 50 commits. This is intentional because the user asked to match the
  refresh-docs behavior.
- Duplicating the marker-counting Python is acceptable for a config-only change. If this grows beyond these two
  workflows, extract a shared workflow step or product helper in a later cleanup.
- The improvement agent must be conservative by prompt design. It should be allowed to return no changes, and that
  should count as a good run.
