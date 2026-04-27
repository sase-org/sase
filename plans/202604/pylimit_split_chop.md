---
create_time: 2026-04-27 16:42:26
status: wip
---
# Plan: Fix `sase_pylimit_split` Chop Reliability

## Context

`just pylimit` in the main `sase` checkout still reports these over-limit files:

- `src/sase/ace/tui/models/agent.py`
- `src/sase/ace/tui/widgets/agent_list.py`
- `src/sase/ace/tui/widgets/_agent_list_rendering.py`
- `tests/ace/tui/widgets/test_agent_list_grouping.py`
- `tests/test_agent_names.py`
- `tests/test_axe_lumberjack.py`

The active `run_every` lumberjack is running and has no scheduler-level errors. It last launched `sase_pylimit_split` at
`2026-04-27T15:38:11-04:00`, and the chop timestamp was updated. So the issue is not that the lumberjack is dead.

The current chezmoi config defines `sase_pylimit_split` as an **agent chop**:

```yaml
agent: "#gh:sase #sase/pylimit_split %approve"
gate: "{ tools/pylimit_files-260227 src 1000 850 700; tools/pylimit_files-260227 tests 1000 850 700; } | grep -q ."
run_every: 60m
```

That means the standalone executable script at `~/.config/sase/chops/sase_pylimit_split` is not used. There is also no
`axe.chop_script_dirs` entry for `~/.config/sase/chops`, and the script is not present in the chezmoi source tree, so it
is not persistent configuration.

The `#sase/pylimit_split` workflow does find all long files and then iterates through them, but it runs them as a single
workflow-agent process. The recent artifact log shows one such workflow spending roughly 40 minutes moving from file to
file. Some iterations committed successfully, but others left dirty changes in old workspaces or hit conflicts because
another pylimit agent had already landed a split for the same file. The main checkout is therefore still over limit even
though the chop has been launching.

The live standalone script is closer to the desired model because it builds a multi-prompt with one
`#sase/pysplit:<file>` segment per file. However, it currently has two problems:

1. It is not discoverable/configured by the lumberjack.
2. Its `set -e` process substitution can stop after the first non-zero `tools/pylimit_files-260227` call, which can skip
   `tests/` when `src/` already has violations.

## Goals

- Make the configured chop launch one background split agent per currently over-limit file.
- Keep the gate behavior: do not launch anything when `pylimit_files` finds no files.
- Ensure split agents are prompted through the normal commit path so successful splits land on the main branch instead
  of remaining dirty in temporary workspaces.
- Keep the fix in managed chezmoi config, then apply it to the live `~/.config/sase` location.
- Avoid touching stale dirty workspaces except to inspect them. They may contain user/agent work and should not be reset
  as part of this fix.

## Proposed Changes

1. Persist the standalone chop script under chezmoi:
   - Add `home/dot_config/sase/chops/sase_pylimit_split`.
   - Base it on the live `~/.config/sase/chops/sase_pylimit_split`.
   - Change the pylimit collection commands to tolerate non-zero `pylimit_files` exits:
     `tools/pylimit_files-260227 src ... || true` and `tools/pylimit_files-260227 tests ... || true`.
   - Add `#commit` to each generated segment, e.g. `#gh:sase #sase/pysplit:<file> #commit %approve`, so the agent has
     explicit commit workflow instructions after it splits the file.

2. Update `home/dot_config/sase/sase_athena.yml` so the chop uses the script path instead of the YAML workflow agent:
   - Add `axe.chop_script_dirs: ["/home/bryan/.config/sase/chops"]`.
   - Remove `agent` and `gate` from the `sase_pylimit_split` chop entry.
   - Keep `run_every: 60m`.
   - Optionally add `timeout: 5m` if the script launch path needs more than the default but should still fail fast.

3. Apply the chezmoi config:
   - Run `chezmoi apply`.
   - Confirm `~/.config/sase/chops/sase_pylimit_split` exists and is executable.
   - Confirm `sase axe chop list` still lists `sase_pylimit_split`.

4. Validate without triggering a destructive cleanup:
   - Run `just check` in the chezmoi repo because chezmoi was modified.
   - From this repo, run a non-mutating discovery/config smoke check with `sase axe chop list`.
   - Run `tools/pylimit_files-260227` in the main `sase` checkout to confirm the expected file set before/after.
   - Do not manually run the chop unless we explicitly decide it is acceptable to spawn the split agents immediately.

## Follow-up Considerations

- The current `#sase/pylimit_split` YAML workflow can remain for manual foreground use, but the lumberjack should use
  the executable script because it gives better observability and one background agent per file.
- A core improvement worth doing separately: expand `~` in `chop_script_dirs` inside `discover_chop_script()`. The
  immediate config can use an absolute path to avoid coupling this fix to a core code change.
- Existing dirty workspaces such as `sase_104` and `sase_105` explain some of the current repeated pylimit output, but
  they should be handled separately because they contain uncommitted agent work and possible conflict states.
