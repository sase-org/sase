---
create_time: 2026-06-25 22:22:30
status: done
prompt: sdd/prompts/202606/plan_agent_pencil_consistency.md
---
# Plan Agent Pencil Consistency Plan

## Problem

The Agents tab can show a root Plan workflow row without a pencil badge even while the selected detail panel shows
`Deltas:` from the active coder child. The most visible report is in `by status` grouping, where the row can remain
stale after the deferred live-hint worker computes new badge state.

The two rejected proposals identify complementary pieces of the bug:

- `06r.cld` correctly identifies the semantic mismatch: the detail panel uses `_resolve_agent_diff_source()` and can
  redirect a root Plan workflow to its active coder child, while the row badge uses the plan row's own persisted
  `diff_has_real_edits` / `diff_path` fields.
- `06r.cdx` correctly identifies the refresh gap in grouped status mode: `_try_patch_agent_row()` currently rejects
  every `GroupingMode.BY_STATUS` patch, so non-structural badge-only changes do not paint until a later full rebuild.

Neither plan is sufficient alone. The row must first compute the same redirected live hint as the detail panel, and then
the grouped row must be eligible for a safe in-place repaint.

## Design

Keep all live VCS work in the existing deferred, coalesced background path. Do not add filesystem, VCS, or diff reads to
row rendering or Textual event-loop handlers.

1. Share the diff-source rule used by details and badges.
   - In `src/sase/ace/tui/widgets/file_panel/_diff.py`, expose a small public helper around
     `_resolve_agent_diff_source()`, such as `resolve_agent_diff_source(agent)` and/or `diff_source_redirected(agent)`.
   - The helper must stay cheap: it only inspects in-memory plan/follow-up relationships and statuses.
   - Keep `get_agent_diff()`, `_compute_diff_cache_key()`, and `live_agent_file_change_hint()` using the same source
     resolution.

2. Make live-hint classification work for redirected Plan rows.
   - Update `classify_live_file_change_hint()` so a row-level `agent.diff_path` does not immediately suppress live
     classification when the resolved diff source is a different active coder child.
   - Preserve the existing behavior for ordinary agents with a persisted `diff_path`: no live VCS probe, and the
     persisted classification remains authoritative.
   - Update `_live_hint_candidates()` to include redirected root Plan rows whose own diff path exists but whose resolved
     active child has no persisted diff path. Ordinary rows with `diff_path` should still be skipped.
   - Keep candidate computation visible-row scoped and offload the actual VCS probe through the existing
     `asyncio.to_thread()` batch.

3. Make the row badge use redirected live hints.
   - In `agent_file_change_hint()`, when the row redirects to another diff source, ignore the root plan row's own
     bookkeeping-only `diff_has_real_edits` value and render from `agent.live_file_change_hint`.
   - Treat `None` as no badge until the deferred scan fills the value in.
   - Leave the current precedence unchanged for non-redirected rows: `diff_has_real_edits`, then
     `live_file_change_hint`, then `bool(diff_path)`.

4. Permit safe `by status` row patches for non-structural changes.
   - In `_try_patch_agent_row()`, stop treating `GroupingMode.BY_STATUS` as an unconditional row-patch veto.
   - Before mutating the widget row, compare the old visible row and new agent under the same status grouping keys.
     Allow the patch only when the status bucket, name-root/prefix grouping, panel identity, and local row identity
     remain unchanged.
   - Continue returning `False` for status-bucket moves or other structural grouping changes so existing callers can
     rebuild the affected panel/list.
   - For live-hint applies, this means badge-only changes patch in place; for structural changes, the current
     conservative fallback remains intact.

## Tests

Add focused regression coverage rather than a broad new harness:

- `tests/test_agent_loader_live_file_change_hint.py`
  - redirected root Plan row with a bookkeeping-only `diff_path` and an active coder child with real live edits returns
    a true live hint;
  - the same shape with child clean/bookkeeping-only edits returns false;
  - ordinary agents with `diff_path` still do not call the live VCS path.
- `tests/ace/tui/test_agents_live_hint_refresh.py`
  - `_live_hint_candidates()` includes redirected Plan rows with their own `diff_path`;
  - it still excludes ordinary persisted-diff rows and redirected rows whose resolved child is terminal or has its own
    persisted diff.
- `tests/ace/tui/widgets/test_agent_display_list_rendering.py` or
  `tests/ace/tui/widgets/test_agent_render_key_badges.py`
  - `agent_file_change_hint()` / row rendering shows a pencil for redirected Plan rows when
    `live_file_change_hint=True`, even if the plan row's own `diff_has_real_edits=False`;
  - non-redirected persisted classifications still win over stale live hints.
- `tests/ace/tui/test_agent_display_diff.py`
  - a `GroupingMode.BY_STATUS` row patch for a badge-only live-hint change patches in place without a full rebuild;
  - a status-bucket change in `BY_STATUS` still refuses the row patch and follows the existing rebuild fallback.

## Validation

Run the narrow suites first:

```bash
pytest tests/test_agent_loader_live_file_change_hint.py
pytest tests/ace/tui/widgets/file_panel/test_diff_cache.py
pytest tests/ace/tui/test_agents_live_hint_refresh.py
pytest tests/ace/tui/test_agent_display_diff.py
pytest tests/ace/tui/widgets/test_agent_display_list_rendering.py
pytest tests/ace/tui/widgets/test_agent_render_key_badges.py
```

Then run the repository check required after code edits:

```bash
just check
```

## Boundaries

This is a Python TUI presentation fix. It should not change Rust core APIs, wire formats, persisted metadata, or the VCS
provider interface.

Linked-repository-only edits remain out of scope. The detail panel can show linked repo deltas through linked delta
groups, while the current live badge path classifies the resolved primary workspace diff. If linked-only pencil badges
are desired, handle that as a separate change with its own performance review.
