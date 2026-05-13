---
create_time: 2026-05-13 19:23:43
status: done
---
# Plan: Rerun `sase-3e.3.1` With Forced Name Reuse

## Context

The failed agent `sase-3e.3.1` is recorded in the SASE agent index with artifacts at:

`/home/bryan/.sase/projects/sase/artifacts/ace-run/20260513190057`

Its authoritative submitted prompt is:

```text
#gh:sase
%name:sase-3e.3.1
%group:sase-3e
%approve
#bd/work_phase_bead:sase-3e.3.1
```

The failure recorded in `done.json` was:

```text
RuntimeError: SASE_AGENT_DEFERRED_WORKSPACE=1 but extracted wait metadata is empty; refusing to continue in the placeholder workspace
```

The requested rerun prompt should preserve the original prompt exactly except for forced agent-name reuse:

```text
#gh:sase
%name:!sase-3e.3.1
%group:sase-3e
%approve
#bd/work_phase_bead:sase-3e.3.1
```

## Plan

1. Submit this plan with `sase plan` before taking any rerun action.
2. Re-check that `sase-3e.3.1` is not currently live/running immediately before launch. If it is live, stop and report
   instead of overwriting a running owner.
3. Apply the same forced-reuse handshake used by the TUI/bead launcher:
   - parse the `%name:!sase-3e.3.1` directive,
   - wipe the prior stale owner for `sase-3e.3.1`,
   - rewrite the launch prompt back to `%name:sase-3e.3.1` for the launcher after the wipe.
4. Launch the rerun as a detached SASE agent from the current repo workspace so it appears in the Agents tab.
5. Verify the new `sase-3e.3.1` entry is present via `sase agents status -a -j`, and report its status, PID, workspace,
   and artifacts directory.

## Non-Goals

- Do not modify SASE memory files.
- Do not edit source code or tests.
- Do not rerun the whole `sase-3e.3` workflow or launch sibling phase agents.
