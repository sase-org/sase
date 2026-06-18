---
create_time: 2026-06-17 20:47:45
status: done
---
# Plan: Nested Memory Child Reachability

## Context

Bead `sase-4u` delivered flat memory notes and nested long-term child notes rendered by `sase memory read`. Verification
found that init reachability still only follows markdown references, so a valid child note with `parent: memory/hub.md`
is reported as unreferenced unless it is also mentioned in note text.

## Plan

1. Update memory init reachability so long notes parented under a reachable long note are also considered reachable.
2. Add focused tests proving `unreferenced_memory_files_for_init` accepts child notes reachable only through `parent:`
   metadata.
3. Run source-backed verification with the workspace `.venv` on `PATH`, including `sase init --check`, targeted tests,
   and `just check`.
4. Remove this temporary plan file after the proposed plan is recorded.
5. Close bead `sase-4u` as the final implementation step, then run the requested post-close `just pyvision` check.
