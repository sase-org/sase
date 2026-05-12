---
create_time: 2026-05-12 12:11:56
status: done
prompt: sdd/prompts/202605/pylimit_split_registry_collision.md
---
# Fix `sase_pylimit_split` chop: honor durable agent-name registry when naming `pysplit.<stem>` agents

## Symptom

Triggering the `sase_pylimit_split` chop manually from the AXE tab (keymap `r`) completes the chop record with status
`agent_launched`, but no per-file `pysplit.*` child agents appear on the Agents tab. Meanwhile `just pylimit` still
reports several files over the warning threshold, so this is not a "no work to do" no-op.

## Reproduction artifacts (most recent run)

- Chop run record: `~/.sase/axe/lumberjacks/run_every/chops/sase_pylimit_split/runs/20260512T115536_098652.json` →
  `status: agent_launched`, `source: manual`, `started_by: ace`.
- Outer workflow state: `~/.sase/projects/sase/artifacts/ace-run/20260512115536/workflow_state.json` → `status: failed`,
  `agents_launched: 0`, step `launch_split_agents` failed.
- Error report: `~/.sase/projects/sase/artifacts/ace-run/20260512115536/error_report.md` →
  `AgentNameLaunchCollisionError: Agent name 'pysplit.test_axe_lumberjack' is taken. Try 'pysplit.test_axe_lumberjack1'.`

The chop record's `agent_launched` only reports that the _outer_ chop agent was spawned successfully. The inner workflow
then raised before any per-file fan-out, which is why no child agents are visible.

## Root cause

This is a recurrence of the issue diagnosed in `~/.sase/plans/202605/pylimit_split_name_collision.md`. The fix proposed
there was never applied to `xprompts/pylimit_split.yml`. The current `launch_split_agents` Python step still names every
per-file agent `pysplit.<Path(path).stem>` and only de-dupes basenames **within the current file list**:

```python
seen: dict[str, int] = {}
for path in unique_files:
    stem = Path(path).stem
    count = seen.get(stem, 0)
    suffix = "" if count == 0 else f"-{count + 1}"
    seen[stem] = count + 1
    agent_name = f"pysplit.{stem}{suffix}"
```

It does not consult the durable agent-name registry at `~/.sase/agent_name_registry.json`. That registry currently
contains ~140 `pysplit.*` reservations from earlier runs (all in `state=dismissed`).
`sase.agent.names.is_name_reserved()` — and therefore the launch-time validator `validate_launch_name_requests()` at
`src/sase/agent/launch_validation.py:96` — treats _any_ entry, including `dismissed`, as reserved. As a result, every
basename that has ever been split is permanently unavailable to the next run, and a single collision aborts the whole
multi-prompt before any child agent spawns.

## Why this is an xprompt bug, not a registry/validator bug

The registry deliberately retains dismissed reservations so the auto-name suggester and history are durable across
restarts. Other workflows handle this either by letting the allocator pick a free `<base><N>` (no explicit `%name:`) or
by adding a run-scoped suffix. The pysplit workflow intentionally picks a human-readable, stable `%name:pysplit.<stem>`
so the user can tell at a glance which agent is splitting which file — that product requirement still holds. The fix
should keep the readable name when it is free and only add a numeric suffix when it is not.

The validator's own error message already advertises the right answer:
`... is taken. Try 'pysplit.test_axe_lumberjack1'.`

## Fix (xprompt-only)

Edit `xprompts/pylimit_split.yml`'s `launch_split_agents` Python step so its naming loop also avoids names already
reserved in the durable registry. Approximate shape:

```python
from sase.agent.names import is_name_reserved

claimed: set[str] = set()
per_file_prompts: list[str] = []
for path in unique_files:
    base = f"pysplit.{Path(path).stem}"
    candidate = base
    n = 1
    while candidate in claimed or is_name_reserved(candidate):
        n += 1
        candidate = f"{base}-{n}"
    claimed.add(candidate)
    per_file_prompts.append(
        f"%name:{candidate}\n#gh:sase %group:chop %approve #sase/pysplit:{path}"
    )
```

Behavior:

- First-ever split of `foo.py` → `pysplit.foo` (unchanged).
- Subsequent split when `pysplit.foo` is reserved (active or dismissed) → `pysplit.foo-2`, then `pysplit.foo-3`, ...
- Within-run basename collision (two distinct paths sharing a stem) → still resolved by the same `-N` suffix path,
  preserving the prior `pylimit_split_agent_names` tale's contract.
- Keep `-` as the suffix separator (not `.`) — a dotted suffix would interact with `%r` repeat-fanout's dotted-prefix
  reservation semantics.
- Preserve the existing `%group:chop %approve` and the rest of the per-file prompt body verbatim.

`is_name_reserved` is already exported from `sase.agent.names` (see `src/sase/agent/names/__init__.py:50, 177`) and is
implemented at `src/sase/agent/names/_registry.py:33`, so the import is stable.

## Out of scope

- Garbage-collecting dismissed entries from `~/.sase/agent_name_registry.json`. That's a registry-design question that
  affects every workflow.
- Switching to `%name:!` forced reuse. Forced reuse requires confirmation in non-TUI surfaces
  (`AgentNameReuseConfirmationRequiredError`); an auto-running chop is the worst place to demand interactive
  confirmation.
- The chezmoi chop definition in `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
  (`#gh:sase %g:chop #!sase/pylimit_split %approve`). The prior `pylimit_chop_name_collision.md` already settled the
  cwd/workspace question; current evidence again confirms the chop is reaching the workflow correctly.
- Changes to `src/sase/agent/launch_validation.py` or `src/sase/agent/names/`. The registry behavior is correct; only
  the xprompt's naming policy is too optimistic.

## Validation

1. **Static / dry-run** — exec the new naming loop in a REPL against the current registry and the
   `tools/pylimit_files-260227 src/tests 1000 850 700` output, confirming each offender resolves to a free name
   (`pysplit.test_axe_lumberjack-N`, `pysplit.axe_dashboard-N`, ...).
2. **Functional** — from the current workspace, trigger the chop manually (AXE tab, `r` on `sase_pylimit_split`) and
   confirm:
   - `workflow_state.json` for the new run shows `status=completed` and `agents_launched=N`.
   - New fan-out children appear on the Agents tab with names of the form `pysplit.<stem>` or `pysplit.<stem>-N`.
   - No `AgentNameLaunchCollisionError` in `~/.sase/projects/sase/artifacts/ace-run/<run>/error_report.md`.
3. **Repo check** — `just check` in this workspace (per the workspace memory; run `just install` first if the venv is
   stale). Changes are YAML-only, so this is mostly fmt/lint.

## Files expected to change

- `xprompts/pylimit_split.yml` — `launch_split_agents` step's naming loop only.

No changes to: chezmoi config, plugin repos, `sase-core`, `src/sase/**`, or existing tests. (If a new unit test is
added, it would live under `tests/xprompts/`; the prior plan called this optional and we are keeping that judgment.)

## Save location

This plan should be archived at `~/.sase/plans/202605/pylimit_split_registry_collision_recurrence.md` alongside the two
prior pylimit_split plans for continuity.
