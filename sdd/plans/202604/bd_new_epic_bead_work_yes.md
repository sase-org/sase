---
create_time: 2026-04-29 12:56:14
status: done
---
# Instruct `bd/new_epic` to Run `sase bead work --yes`

## Context

The built-in `#bd/new_epic` xprompt in `src/sase/default_config.yml` currently tells the bead-creation agent:

```text
After committing the bead-creation work, run `sase bead work <epic_id>` (using the new plan bead's ID) to mark
the epic as ready to work.
```

The `sase bead work` CLI already supports `-y, --yes`, and the repo docs describe it as skipping the launch confirmation
prompt. The request is therefore a prompt-instruction change, not a CLI behavior change.

## Goal

When an agent is invoked with `#bd/new_epic`, it should create and commit the epic/phase beads as it does today, then
run:

```bash
sase bead work <epic_id> --yes
```

This avoids the post-commit confirmation prompt in the automated handoff path while preserving normal CLI confirmation
behavior for users who run `sase bead work <epic_id>` directly.

## Non-Goals

- Do not change the semantics of `sase bead work`.
- Do not make `--yes` the default at the parser or handler level.
- Do not alter `bd/work_phase_bead` or `bd/land_epic`.
- Do not update docs that already correctly list `-y, --yes`, unless implementation reveals a stale reference.

## Implementation Plan

1. Update the built-in `bd/new_epic` prompt text in `src/sase/default_config.yml`.
   - Replace the final instruction's command with `sase bead work <epic_id> --yes`.
   - Keep the surrounding wording that says to use the newly-created plan bead ID.
   - Make the sentence explicit that `--yes` skips the launch confirmation prompt for this automated kickoff.

2. Add focused regression coverage in `tests/test_bead_xprompt_tags.py`.
   - Extend the existing built-in xprompt loading test, or add a nearby test, to inspect
     `get_all_prompts()["bd/new_epic"]`.
   - Assert the prompt body includes `sase bead work <epic_id> --yes`.
   - Assert it still carries the `create_epic_bead` tag so the test continues to cover both discovery and instruction
     content.

3. Check whether any generated/default prompt catalog snapshots exist.
   - If no snapshot is present, no additional generated file update is needed.
   - If a snapshot or docs table embeds the old command text, update only the stale reference.

4. Verify the change.
   - Run the focused test:

     ```bash
     uv run pytest tests/test_bead_xprompt_tags.py
     ```

   - Because this repo requires the full gate after source changes, run:

     ```bash
     just check
     ```

## Risks and Mitigations

- Risk: `--yes` bypasses a launch confirmation.
  - Mitigation: The change is limited to the `bd/new_epic` agent handoff path after bead creation has been committed,
    which is the flow the user wants automated. Direct human CLI usage keeps the existing confirmation prompt.

- Risk: The prompt body changes without a test noticing.
  - Mitigation: Add a focused assertion on the loaded built-in prompt content.

- Risk: User overrides of `bd/new_epic` do not inherit this behavior.
  - Mitigation: That is expected; tag-based user overrides intentionally replace built-ins. This plan only changes the
    default built-in instruction.
