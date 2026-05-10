---
create_time: 2026-05-10 00:57:01
status: wip
prompt: sdd/prompts/202605/refresh_docs_validation.md
---
# Plan: Fix `refresh_docs` Workflow Validation

## Problem

The `sase ace` snapshot shows the `refresh_docs` workflow failing before execution:

```text
Workflow 'refresh_docs' validation failed:
  - Step 'launch_docs_agents' has output 'launched' but is never referenced
```

The active workflow is not the retired repo-local `xprompts/refresh_docs.yml`. It is a global config workflow loaded
from `sase_athena.yml`, with the source managed by chezmoi at:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- applied copy: `~/.config/sase/sase_athena.yml`

The recent workflow design replaced a synchronous docs `agent:` step with a hidden Python step that launches two daemon
agents and prints `launched=2`. If that Python step declares `output: { launched: int }`, SASE's workflow validator
requires the output to be consumed by a later step unless it is the workflow's final output. In `refresh_docs`, the
marker-update step follows the launcher, so an unreferenced `launch_docs_agents.launched` output is invalid.

## Root Cause

The launcher step's structured output describes a side-effect handoff, but the workflow did not make that handoff part
of the dependency graph. The validator is doing the right thing for the declared schema: a non-final step output should
be referenced so typoed or stale outputs do not silently drift.

The correct workflow relationship is:

1. `count_commits` decides whether refresh work is needed.
2. `launch_docs_agents` performs the daemon-agent handoff and reports how many agents were launched.
3. `update_marker` should only run after that handoff succeeds.

Today, `update_marker` only depends on `count_commits.count >= threshold`; it should also reference
`launch_docs_agents.launched`.

## Implementation

1. Update the chezmoi-managed `refresh_docs` workflow source in
   `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.

2. Ensure `launch_docs_agents` has an explicit structured output:

   ```yaml
   output: { launched: int }
   ```

3. Change `update_marker`'s condition to consume that output:

   ```yaml
   if: "{{ count_commits.count >= threshold and launch_docs_agents.launched > 0 }}"
   ```

   This resolves validation and captures the intended semantics: update the marker only after the daemon-agent launch
   step completed and reported a positive launch count.

4. Apply the chezmoi source to keep the live config in sync:

   ```bash
   chezmoi apply --force ~/.config/sase/sase_athena.yml
   ```

5. Validate from the SASE workspace:

   ```bash
   sase xprompt explain refresh_docs
   ```

   This exercises loading and validation of the active config workflow.

6. Because chezmoi is modified, run its required check:

   ```bash
   just check
   ```

   from `~/.local/share/chezmoi`.

7. Because the SASE workspace only receives this plan artifact, do not run the full SASE `just check` unless additional
   SASE source changes become necessary.

## Acceptance Criteria

- `sase xprompt explain refresh_docs` succeeds.
- `launch_docs_agents.launched` is referenced by a later step, so the workflow validator no longer rejects the workflow.
- The refresh marker is updated only after a successful positive daemon-agent handoff.
- The chezmoi source and applied `~/.config/sase/sase_athena.yml` match for this workflow change.
