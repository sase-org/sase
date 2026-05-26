---
create_time: 2026-05-26 18:34:22
status: wip
prompt: sdd/prompts/202605/chop_open_changespec_guard.md
---
# Plan: Guard SASE Repair Chops Against Existing Open ChangeSpecs

## Goal

Prevent the two recurring SASE repair chops from creating more duplicate repair work when there is already an open
ChangeSpec for the same repair family:

- `gh_actions_fix` should not launch another GitHub Actions fixer if any open ChangeSpec name starts with
  `sase_gha_fix_`.
- `sase_fix_just` should not run the `#!sase/fix_just` workflow if any open ChangeSpec name starts with
  `sase_fix_just_`.

“Open” should mean active lifecycle states (`WIP`, `Draft`, `Ready`, or `Mailed`). Terminal specs (`Submitted`,
`Archived`, `Reverted`) must not block future chop runs.

## Current Shape

- `gh_actions_fix` is a script chop in chezmoi at
  `/home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix`.
- `sase_fix_just` is currently a direct agent chop in
  `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`: `agent: "#gh:sase %g:chop #!sase/fix_just"`.
- Axe passes script chops a context JSON that includes `all_changespecs_file`; that serialized snapshot is the right
  source of truth for this guard because it avoids brittle CLI text parsing and uses the same ChangeSpec list visible to
  the lumberjack tick/manual run.
- A live search currently finds Draft specs in both families.
  `sase changespec search '(sase_gha_fix OR sase_fix_just) AND (%w OR %d OR %y OR %m)'` returns nine Draft ChangeSpecs,
  confirming the desired guard would no-op right now.

## Design

1. Add a small shared-style guard to the chezmoi chop scripts that:
   - Reads `context["all_changespecs_file"]`.
   - Parses the serialized ChangeSpec list as JSON dictionaries.
   - Treats `WIP`, `Draft`, `Ready`, and `Mailed` as open.
   - Matches by exact prefix with `str.startswith(prefix)`.
   - Logs the matching ChangeSpec names in bounded form and exits successfully without launching work when matches
     exist.

2. Update `gh_actions_fix` to run the guard before querying GitHub Actions:
   - Prefix: `sase_gha_fix_`.
   - If blocked, emit a clear summary/no-op reason and return `0`.
   - If the context lacks a readable ChangeSpec snapshot, fail closed by skipping launch and logging a check error
     rather than creating duplicate ChangeSpecs from stale/incomplete context.

3. Convert `sase_fix_just` from a direct agent chop to a script chop:
   - Add `/home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_sase_fix_just`.
   - The script reads the same context guard with prefix `sase_fix_just_`.
   - If no open matches exist, it runs `sase run -d "#gh:sase %g:chop #!sase/fix_just"`.
   - The script logs a compact launch/no-op summary so the AXE tab remains useful.
   - Remove the `agent:` field from the `sase_fix_just` chop entry in `sase_athena.yml` so Axe resolves it as a script
     chop while preserving the existing chop name and `run_every: 60m`.

4. Tests:
   - Extend `tests/bash/gh_actions_fix_chop_test.sh` to include `all_changespecs_file` in its fake context and cover:
     existing open `sase_gha_fix_...` blocks before GH calls/agent launch; terminal `sase_gha_fix_...` does not block.
   - Add a new bash test for the `sase_fix_just` script covering: open `sase_fix_just_...` blocks; terminal
     `sase_fix_just_...` allows `sase run -d` with the expected prompt; unreadable/missing snapshot skips safely.

5. Validation:
   - Run the affected chezmoi bash tests directly.
   - Run a YAML parse of `sase_athena.yml`.
   - Because the production edits are in the chezmoi repo rather than this SASE repo, do not run `just check` for the
     plan-only artifact here unless source changes are made in the SASE repo.

## Risks and Tradeoffs

- Using `all_changespecs_file` means the guard relies on Axe’s per-run snapshot. That is preferable to invoking
  `sase changespec search` because it is structured and avoids query-language limitations around prefix matching.
- Converting `sase_fix_just` to a script chop changes its AXE run status from native `agent_launched` to a normal script
  `success` that launches an agent internally. The script output should include the launched prompt/workflow label so
  the run remains traceable.
- There is still a small race if two separate AXE processes build snapshots simultaneously before either newly-launched
  agent creates a ChangeSpec. The existing `run_every` cadence and single daemon should make that uncommon; preventing
  cross-process races would require a lock or core-level launch claim and is outside this scoped fix.
