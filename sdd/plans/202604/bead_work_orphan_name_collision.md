---
create_time: 2026-04-28 19:02:37
status: done
prompt: sdd/prompts/202604/bead_work_orphan_name_collision.md
---
# Plan: `sase bead work` collides with orphaned phase agents

## Summary

`sase bead work sase-12` produced two visible agents for phase `sase-12.1` — one named `sase-12.1`, the other
`sase-12.1.2`. The `.2` suffix is the collision-avoidance rename emitted by `_claim_explicit` in
`src/sase/agent/names/_claim.py` when a launching agent's explicit `%name:<n>` clashes with another live agent.
`sase bead work` did not launch twice; it ran exactly once and produced the correct 7-segment multi-prompt — but a stale
`sase-12.1` agent was already running, and `_claim_explicit` silently renamed it instead of refusing.

This plan adds a defensive precondition to `handle_bead_work` so the command refuses to run when any of the agent names
it would claim are already in use, and it tightens partial-launch cleanup so a future bug report cannot easily reproduce
orphan accumulation.

## Root cause (evidence)

### What we observed in `~/.sase/projects/sase/artifacts/ace-run/`

Eight `agent_meta.json` files, all referencing `sase-12.*`:

| timestamp      | pid    | name (now)   | start_time          | workflow status    |
| -------------- | ------ | ------------ | ------------------- | ------------------ |
| 20260428184710 | 705490 | sase-12.1.2  | 2026-04-28 18:47:12 | failed (SIGTERM)   |
| 20260428184725 | 709390 | sase-12.1    | 2026-04-28 18:47:27 | running            |
| 20260428184726 | 709417 | sase-12.3    | —                   | running            |
| 20260428184727 | 709522 | sase-12.4    | —                   | running            |
| 20260428184728 | 709735 | sase-12.5    | —                   | running            |
| 20260428184730 | 709832 | sase-12.2    | —                   | wait_for sase-12.1 |
| 20260428184731 | 709973 | sase-12.6    | —                   | wait_for sase-12.1 |
| 20260428184732 | 710403 | sase-12.land | —                   | wait_for 12.{2-6}  |

The seven agents from `184725` onward are exactly what `render_multi_prompt` produces for the `sase-12` DAG (Wave 0:
`sase-12.{1,3,4,5}`; Wave 1: `sase-12.{2,6}`; then `sase-12.land`). This batch is correct — each phase has the expected
`wait_for` and the names follow `<epic_id>.<N>`.

The agent at `184710` is the _orphan_. Both its `raw_xprompt.md` and its expanded `main_prompt.md` are byte-for-byte
identical to those of the new `sase-12.1` (timestamp `184725`), so it was clearly launched with the same
`%name:sase-12.1` / `%approve` / `#bd/work_phase_bead:sase-12.1` prompt that `sase bead work` emits per phase.

### Why the orphan came first, not the integration

`handle_bead_work` in `src/sase/bead/cli.py` runs in this order:

1. `proj.mark_ready_to_work(args.id)` — mutates epic row.
2. Pre-claim loop: `proj.update(bead_id, status='in_progress', assignee=...)`.
3. `launch_agent_from_cwd(query)` — spawns processes.

The bead JSONL records `"updated_at": "2026-04-28T22:47:23Z"` (18:47:23 EDT) for sase-12 and every phase. The orphan's
`start_time` is **18:47:12**, eleven seconds _before_ the pre-claims fired. If `handle_bead_work` had launched the
orphan, the bead rows would have already been touched by the time the agent process started. They were not, so the
orphan came from a different source entirely (a manual `sase run "%name:sase-12.1 #bd/work_phase_bead:sase-12.1"`-style
invocation, a SIGINT'd previous attempt that left a partial launch behind, or a different test path).

### Why the rename happened silently

`_claim_explicit(name, claiming_dir)` in `src/sase/agent/names/_claim.py` is the explicit-claim path: when a new agent
is launched with an explicit `%name:foo` and another visible agent already carries `name == foo`, it allocates
`<foo>.<n>` via `dedup_name` and rewrites the **older** agent's `agent_meta.json` and `done.json`. Wait references in
other agents' on-disk markers are rewritten via `rewrite_dismissed_references`. All I/O errors are swallowed
("best-effort: name reservation must never block agent launch"). The launching agent always wins.

This is the right policy for interactive use — the user typed `%name:foo`, they meant it, and they expect the existing
instance to step aside. It is the wrong policy for the programmatic `sase bead work` flow, because the user did not type
the name; the integration generated it from the bead id and has no opinion about overriding a stranger that happens to
share the same id.

## Goals

1. `sase bead work <epic>` must refuse to run when any of the agent names it would claim (`<epic>.<N>` for every open
   phase, plus `<epic>.land`) is already held by a visible, non-dismissed agent. The error must name every offending
   agent so the user can dismiss/kill them deliberately before retrying.
2. The `--dry-run` path must surface the same precondition (with a warning, not a hard error, since dry-run mutates
   nothing).
3. If `launch_agent_from_cwd` fails partway through the multi-prompt, `_rollback_work_launch` must terminate the agents
   that were already spawned. This closes the orphan-on-partial-launch source even if it was not the cause of the
   observed incident, so a future SIGINT or transient failure cannot leak a phase agent that the next retry will collide
   with.

Non-goals:

- Changing `_claim_explicit` semantics for non-bead launches. Manual `%name:<n>` keeps its current "rename the older
  one" behavior — the TUI revive flow and `dedup_agent_names_1` plan depend on it.
- Auto-killing the orphan from inside `handle_bead_work`. That has too much blast radius (the orphan may belong to a
  different epic instance the user is intentionally running). Refuse and let the user decide.

## Design

### Precondition check in `handle_bead_work`

Add a helper next to `_print_work_plan_summary` in `src/sase/bead/cli.py`:

```python
def _find_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return {agent_name: artifact_dir} for every plan name already in use."""
    from sase.agent.names import get_active_agent_names
    # Resolve a richer mapping that also tells us where the colliding
    # agent lives, so we can print actionable advice.
    ...
```

`get_active_agent_names()` already scans `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`, skipping
dismissed-suffix dirs and dead non-done agents. We need the _artifact dir_ per name as well, not just the set, so the
error message can point the user at the offending agent. Two options:

- **Add a sibling helper** `get_active_agent_name_map()` that returns a `dict[str, str]` (name → artifact dir). Internal
  callers that want a set keep using the existing API; the new helper is dedicated to collision diagnostics.
- **Inline the scan** inside `_find_name_collisions`. Simpler for a single caller but duplicates the dismissed-suffix
  bookkeeping.

Pick the sibling helper — the bookkeeping (dismissed suffixes, done.json fallback for `name`/`workflow_name`) already
lives in `src/sase/agent/names/_auto.py` and a second copy will rot.

The check runs after `build_epic_work_plan` and before `_print_work_plan_summary`, with `--dry-run` short-circuiting to
a warn:

```python
plan = build_epic_work_plan(proj._conn, args.id)
collisions = _find_name_collisions(plan)
if collisions:
    if dry_run:
        print("Warning: agent-name collisions would block live launch:", file=sys.stderr)
        for name, path in sorted(collisions.items()):
            print(f"  {name} (already running at {path})", file=sys.stderr)
    else:
        print(
            "Error: refusing to launch — these agent names are already in use:",
            file=sys.stderr,
        )
        for name, path in sorted(collisions.items()):
            print(f"  {name} (running at {path})", file=sys.stderr)
        print(
            "\nDismiss or kill those agents in the TUI (or `sase run --kill ...`) "
            "before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)
```

The set of names to check is derived from the plan, not re-derived from the bead DAG, so it stays in lockstep with what
`render_multi_prompt` actually emits:

```python
def _expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names
```

### Partial-launch cleanup

`launch_agent_from_cwd` currently raises through any partial-launch state. The fix has two layers:

1. **`launch_multi_prompt_agents` returns `(results, error)` on partial failure** — change the signature to either
   return `results` plus an optional exception, or wrap the spawn loop in a `try/except` that re-raises with a custom
   `MultiPromptPartialLaunchError(results, cause)`. The custom-exception form is less invasive: every existing caller
   already lets exceptions bubble, so we just bolt on a richer payload.

2. **`_rollback_work_launch` accepts launched agents and terminates them.** Extend the helper:

   ```python
   def _rollback_work_launch(
       proj: BeadProject,
       epic_id: str,
       claimed: list[tuple[str, str]],
       launched_pids: list[int] = (),
   ) -> None:
       for pid in launched_pids:
           try:
               os.kill(pid, signal.SIGTERM)
           except (ProcessLookupError, PermissionError):
               pass
       ...
   ```

   In `handle_bead_work`'s `except Exception as e:` for the launch, pull `launched_pids` out of the exception payload
   (or `getattr(e, 'results', [])`) and pass them through.

This addresses the _systemic_ orphan source. The user's incident likely was not caused by a partial launch — but every
future partial launch would otherwise be a foot-gun once the precondition check is in place (rollback un-marks the epic
ready flag, the user retries, and the half-spawned agents collide).

### What the user sees

Before:

```
$ sase bead work sase-12
Epic sase-12 — TUI Performance v2: 6 phase agent(s) in 2 wave(s) plus 1 land agent (sase-12.land).
  Wave 0: sase-12.1 → sase-12.1, sase-12.3 → sase-12.3, ...
  Land waits on: sase-12.2, sase-12.6, sase-12.3, sase-12.4, sase-12.5
Launch these agents? [y/N] y
✓ Launched 7 agents for epic sase-12 ...
# (silently renames any existing sase-12.1 agent to sase-12.1.2)
```

After:

```
$ sase bead work sase-12
Error: refusing to launch — these agent names are already in use:
  sase-12.1 (running at /home/.../artifacts/ace-run/20260428184710)

Dismiss or kill those agents in the TUI (or `sase run --kill ...`)
before retrying.
$ echo $?
1
```

## Test plan

In `tests/test_bead/test_cli_work.py`:

- `test_work_refuses_when_phase_name_collision`: seed an epic, write a fake `agent_meta.json` (with
  `"name": "<phase_id>"`) to a tmp artifacts directory, point the names scan at it, assert `handle_bead_work` exits with
  code 1 and the error names the colliding phase. Use `monkeypatch` on `pathlib.Path.home` (already the pattern in the
  names tests) so the scan reads the fake projects dir.
- `test_work_refuses_when_land_name_collision`: same, but the colliding name is `<epic>.land` to confirm the land agent
  is included in the precondition.
- `test_work_dry_run_warns_on_collision`: collision is logged to stderr but the command exits 0 and does not mutate
  state.
- `test_work_passes_when_no_collisions`: existing happy path stays green.
- `test_rollback_kills_partially_launched_agents`: monkeypatch `launch_agent_from_cwd` to spawn one fake
  `subprocess.Popen` (e.g. `sleep 30`) and then raise; assert the fake process is no longer alive after
  `handle_bead_work` returns with exit 1.

In `tests/test_agent/test_names_auto.py` (or wherever `get_active_agent_names` is covered):

- `test_get_active_agent_name_map_returns_artifact_dirs`: covers the new sibling helper.

## Risks and trade-offs

- **False-positive collisions.** A user who _intentionally_ re-runs a phase agent (e.g. revived after a kill) and then
  runs `sase bead work` will now see a hard error. This is the right default — silently renaming a deliberate revive to
  `<name>.2` is the bug we're trying to prevent — but the error message should be clear about the remedy (dismiss/kill
  before retrying).

- **Race window between precondition and launch.** Another agent could claim the name between the scan and the spawn.
  The check is best-effort; in the rare race, `_claim_explicit` falls back to the current rename behavior. We are not
  adding a global lock for this.

- **Pre-existing rollback behavior.** Today the rollback path leaks any successfully-spawned agents on partial failure.
  Changing this is technically out of scope for the immediate symptom but is the root-cause fix for the _general_ class
  of "stale phase agent collides with a fresh epic launch" — and the precondition check needs the rollback to behave
  correctly to be safe (otherwise the second retry always fails the new check until the user manually cleans up).

## Implementation order

1. Add `get_active_agent_name_map()` in `src/sase/agent/names/_auto.py` and re-export from
   `src/sase/agent/names/__init__.py`. Tests for it.
2. Wire `_find_name_collisions` + precondition into `handle_bead_work` (and dry-run warning). Tests for
   `test_cli_work.py` collision cases.
3. Extend `launch_multi_prompt_agents` to surface partial-launch results in a custom exception. Update
   `_rollback_work_launch` to terminate them. Test that rollback kills the leaked process.
4. Update the `bd/work_phase_bead` doc / `docs/beads.md` if it mentions relaunch semantics — the new failure mode needs
   to be documented.
