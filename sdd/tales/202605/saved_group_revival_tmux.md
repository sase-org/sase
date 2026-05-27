---
create_time: 2026-05-27 15:51:43
status: done
prompt: sdd/prompts/202605/saved_group_revival_tmux.md
---
# Saved Group Revival Tmux E2E Fix Plan

## Context

The previous saved-group revival fix is present in this checkout, but the live `sase ace --tmux` flow still fails to
make a selected saved group visibly reappear.

I reproduced the failure without changing repo files:

- Launched the repo-local TUI with:
  `./.venv/bin/sase ace --tmux --no-axe --tab agents --refresh-interval 0 'project:home'`
- Pressed `R` in the Agents tab.
- Accepted the first saved group in the modal: `48 agents from @home-1`.
- Captured the tmux pane before and after pressing Enter.

The modal preview was correct: it showed `48 agents from @home-1`, including rows such as `home @home-1`,
`home @home-1.7`, and their workflow children. After pressing Enter, the app logged successful revive events for the
eight top-level workflow suffixes, but the captured pane still showed `14 Agents` and no `#home-1` group even after a
long wait.

There are two concrete technical risks to address:

1. The restored root workflow rows can be loaded from source artifacts with `parent_timestamp` equal to their own
   `raw_suffix`. `Agent.is_workflow_child` currently treats any non-null `parent_timestamp` as a child relationship, so
   these restored roots become orphan children and disappear from the visible Agents list after the real loader
   reconciles.

2. The previous authoritative dismissed-index sync is still vulnerable to a metadata short-circuit. The code checks
   whether dismissed-projection metadata matches before honoring the `added=...` authoritative path. If the previous
   projection was bundle-derived and the source signatures have not changed, revive can return early and leave stale
   dismissed rows in the artifact index.

## Plan

1. Add focused regression coverage for self-parent restored workflow roots.
   - Build real-loader fixture artifacts where top-level workflow/ace-run rows have `agent_meta.json` containing
     `parent_timestamp` equal to the artifact timestamp.
   - Assert the root row is treated as top-level after meta enrichment and appears in the filtered agent list.
   - Keep real child/follow-up rows with a different parent timestamp covered so child semantics are not weakened.

2. Normalize self-parent metadata in the Python loader boundary.
   - In filesystem and wire meta enrichment, ignore `parent_timestamp` when it equals the agent's own `raw_suffix` for
     top-level rows.
   - Preserve existing child/follow-up behavior when `parent_workflow` is set, when the loader is enriching a workflow
     child, or when `parent_timestamp` points to a different suffix.
   - Prefer this narrow loader normalization over changing `Agent.is_workflow_child` globally, because many callers
     intentionally use non-null `parent_timestamp` to identify follow-up rows.

3. Make authoritative dismissed-index sync truly authoritative.
   - When `sync_dismissed_agent_artifact_index(..., added=...)` is called with a dismissed set, bypass the projection
     metadata early return and replace the SQLite dismissed projection from the supplied set only.
   - Add a unit test where metadata matches a stale/full projection but an authoritative sync removes a suffix.
   - This closes the earlier plan's intended fast path rather than relying on signature drift.

4. Re-run focused automated tests.
   - Run the saved-group revival tests, agent loader/self-heal tests, and artifact-index lifecycle tests touched by the
     changes.
   - Run formatting for touched Python files.

5. Run the required live tmux E2E verification after the fix.
   - Use `./.venv/bin/sase ace --tmux --no-axe --tab agents --refresh-interval 0 'project:home'`.
   - Use `tmux send-keys` to press `R`, select the existing `48 agents from @home-1` saved group, and press Enter.
   - Use `tmux capture-pane -p` to verify the pane shows the revived group, including an increased agent count and
     visible `#home-1`/`home @home-1` content.
   - Capture the important before/modal/after lines for the final report.
   - Close the tmux window cleanly.

6. Run full repo verification after code changes.
   - Run `just check` from this workspace as required by repo instructions.
   - If the sibling Rust core is touched, use the workspace-matched `sase-core_10` checkout and run its focused Rust
     checks. Current evidence points to Python TUI/loader glue only, so no Rust edit is planned unless tests prove the
     boundary is wrong.
