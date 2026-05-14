---
create_time: 2026-05-14 04:48:35
status: done
prompt: sdd/prompts/202605/verify_epic7_scheduler_integration.md
---
# Verify and Finish Epic 7 Scheduler Integration

## Context

The `sase-3e.7` epic has all child beads closed and Python-side scheduler rollout commits on `sase_100` master.
Verification found that the corresponding Rust daemon scheduler work exists only on sibling `../sase-core` feature
branches, so the current local core master does not yet provide the scheduler RPC, projection, health, and metrics
surfaces claimed by the Phase 7B/7H handoffs.

## Plan

1. Port the missing scheduler projection, local daemon RPC, health, metrics, and contract changes from the bead-tagged
   `../sase-core` feature branches onto current `../sase-core` master, preserving the current master workflow write
   refactor.
2. Rebuild/install the local Python extension from `../sase-core` into this workspace and run focused Rust
   scheduler/gateway tests plus the Python Epic 7 scheduler rollout tests.
3. Update `sdd/epics/202605/epic7_daemon_scheduler_phases.md` frontmatter to `status: done` once verification passes.
4. Close the epic bead `sase-3e.7` with `sase bead close`.
