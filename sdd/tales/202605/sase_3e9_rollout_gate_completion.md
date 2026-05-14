---
create_time: 2026-05-14 08:35:33
status: wip
prompt: sdd/prompts/202605/sase_3e9_rollout_gate_completion.md
---
# Plan - Complete sase-3e.9 Rollout Gate Verification Fixes

## Context

Verification of `sase-3e.9` found that the epic and child beads are closed, and the merged commits implement most ACE
provider, lazy-detail, refresh-loop, and perf-gate work. However, several ACE providers bypass the new `ace_*` rollout
surface groups by calling generic daemon read surfaces directly:

- ChangeSpecs use `changespec_list`, `changespec_search`, and `changespec_detail`.
- Notifications use `notification_list`, `notification_counts`, `notification_detail`, and
  `notification_pending_actions`.
- Agent artifacts use `agent_detail`.

That means daemon reads can be used in ACE even when `ace_changespecs`, `ace_notifications`, or `ace_artifacts` remain
disabled by default, violating the Epic 9 rollout policy.

## Work

1. Route ACE ChangeSpec provider reads through `ace_changespec_*` surfaces while preserving the same daemon RPC calls,
   fallback behavior, and capabilities.
2. Route ACE notification provider reads through `ace_notification_*` surfaces while preserving
   count/list/detail/pending-action behavior and fallback.
3. Route selected-agent artifact/detail reads through an `ace_artifact_*` surface while preserving the existing daemon
   `agent_detail` RPC shape.
4. Update daemon read facade capability mappings and tests so these ACE surfaces are disabled by default and opt in
   through their specific `ace_*` gates.
5. Add focused regression tests proving the ACE providers fall back to direct loaders when their `ace_*` surface is
   disabled, and use daemon reads only when that surface is enabled.
6. Re-run focused tests plus the required repository check for source changes.
7. Close `sase-3e.9` after the fixes are verified, then run `just pyvision` if available and update the epic plan
   frontmatter `status` to `done`.
