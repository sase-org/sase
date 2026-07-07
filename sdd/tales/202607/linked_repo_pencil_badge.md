---
create_time: 2026-07-07 14:01:54
status: done
prompt: sdd/prompts/202607/linked_repo_pencil_badge.md
---
# Linked Repo Pencil Badge Plan

## Goal

Make the Agents tab pencil badge reflect file changes made in linked repositories, including linked workspaces opened
during a run with `sase workspace open -p ...`, not only changes in the agent's primary workspace.

The user-facing rule should be:

- if the agent has real primary-repo deltas, show the pencil;
- if the agent has real linked-repo deltas, show the pencil;
- if the only known changes are plan/prompt bookkeeping files, keep suppressing the pencil;
- do not run Git, parse JSON markers, or read diff files from the row render path.

## Current Findings

The row pencil is rendered by the existing agent-list formatter from `agent_file_change_hint()`. That hint currently
comes from:

- `agent.diff_has_real_edits`, computed from the persisted primary `diff_path`;
- `agent.live_file_change_hint`, computed after first paint by the deferred live-hint worker;
- a fallback `bool(agent.diff_path)` for unclassified persisted primary diffs.

The live-hint worker is already the right performance boundary. It runs after the first Agents load, coalesces repeated
requests, waits for navigation idle, and does VCS work off the Textual event loop.

The primary gap is that the live classifier calls the primary diff path only. It resolves the agent's primary workspace
and calls `diff_with_untracked()` there, but it does not look at linked workspaces.

Linked-repo deltas already exist elsewhere:

- active linked deltas are computed for the selected detail/file panel by `compute_linked_delta_groups()`;
- completed linked commits are rendered from persisted `meta_commits` diff metadata;
- `sase workspace open -p ...` records opened linked workspaces in the agent artifact marker
  `opened_linked_workspaces.json`, which the TUI already loads for the `SASE CONTEXT` `WORKSPACES` lane and the tmux
  chooser;
- commit finalization already uses the same opened-linked marker to enforce dirty linked workspaces.

So the row badge should reuse those existing state sources, but only through cached/background classification helpers.

## Design

Add a single aggregate "has real file changes" signal for row badges while preserving the existing renderer and glyph
placement.

1. Keep the renderer simple.

   `format_agent_option()` should continue to render the pencil from `agent_file_change_hint()`. The renderer should not
   inspect linked repositories, read marker files, or call VCS providers.

2. Add explicit linked-change state to the agent model.

   Add a compare-free field such as `linked_file_change_hint: bool | None` to `Agent`.

   Update `agent_file_change_hint()` to consider, in order:
   - redirected Plan row live hint when the row is borrowing an active coder child;
   - persisted primary diff classification;
   - persisted linked diff classification;
   - live primary/linked hint;
   - existing `bool(diff_path)` fallback.

   This keeps the old primary behavior intact and makes linked changes a first-class badge input rather than overloading
   `diff_has_real_edits`.

3. Classify persisted linked commit diffs during the cheap badge-classification pass.

   Extend the loader-side badge classification so completed linked-only commits can show the pencil even when the
   primary `diff_path` is absent or bookkeeping-only.

   The classifier should inspect persisted per-commit diff metadata, consider non-primary commit diff records, and use
   the existing `diff_has_real_edits()` / `diff_text_has_real_edits()` filtering semantics so plan/prompt bookkeeping
   remains suppressed. Reuse the existing mtime/size diff cache where possible.

   This should be a bounded disk-read operation analogous to the current primary `diff_path` classification, not part of
   row rendering.

4. Make the deferred live-hint classifier linked-repo aware.

   Update `classify_live_file_change_hint()` / `live_agent_file_change_hint()` so the returned live boolean is true when
   either:
   - the resolved primary workspace has real live edits; or
   - any eligible linked workspace has real live edits.

   Preserve the existing terminal-status and persisted-`diff_path` gates for primary diffs, but do not let a missing
   primary diff hide linked dirty work.

5. Build eligible linked workspaces from both launch metadata and opened-workspace markers.

   The linked live classifier should consider:
   - suffix-strategy `agent.linked_repos` entries recorded at launch;
   - `opened_linked_workspaces.json` records written by `sase workspace open -p ...`;
   - agent-family context records for Plan rows and follow-up coder rows, matching the existing context-panel behavior.

   Deduplicate by normalized workspace path and repo name. Skip known `workspace.strategy: none` entries, matching
   commit-finalizer enforcement. If an opened marker has a concrete workspace path and no static metadata entry, treat
   it as eligible if the workspace exists and resolves to a VCS provider.

6. Reuse the existing linked-delta/VCS caching shape.

   Factor the linked workspace probing so the selected detail-panel worker and the row live-hint worker share the same
   low-level cache key ingredients:
   - agent identity;
   - repo name;
   - normalized workspace path;
   - VCS provider type;
   - `.git/index` signature;
   - TTL bucket.

   The row live-hint path only needs a boolean, while the detail/file panel still needs full `LinkedDeltaGroup` entries.
   Share the expensive provider calls where practical, but avoid making the row badge depend on the selected-agent
   detail cache.

7. Keep Plan/follow-up redirection consistent.

   Continue resolving primary live diffs through the existing active coder-child rule for root Plan rows. Apply the same
   intent to linked workspaces: a root Plan row should get a linked dirty badge when its active coder follow-up opened
   or dirtied a linked workspace.

## Tests

Add focused unit coverage before changing behavior broadly.

1. Agent-list rendering:
   - row with `linked_file_change_hint=True` renders the pencil;
   - row with `linked_file_change_hint=False` does not;
   - persisted primary `diff_has_real_edits=False` still suppresses primary bookkeeping-only changes unless linked
     changes are true.

2. Persisted linked commits:
   - a completed agent with only linked `meta_commits` diff metadata gets the linked badge classification;
   - bookkeeping-only linked diff content is suppressed;
   - unreadable or unusual linked diff follows the existing fail-open behavior, if that is how `diff_has_real_edits()`
     is reused.

3. Live linked workspaces:
   - primary workspace clean plus one dirty linked workspace returns `True`;
   - primary workspace clean plus all linked workspaces clean returns `False`;
   - missing or providerless linked workspace fails closed and does not crash;
   - terminal agents do not run live linked VCS probes.

4. Opened-workspace records:
   - a linked workspace recorded only in `opened_linked_workspaces.json` is eligible for live linked badge
     classification;
   - family context records are considered for a root Plan row with an active coder child;
   - static `workspace.strategy: none` linked repos are skipped when metadata is available.

5. Performance guardrails:
   - rendering tests or monkeypatch assertions should prove `format_agent_option()` / `agent_file_change_hint()` do not
     read marker files or call VCS providers;
   - existing live-hint scheduling/coalescing tests should remain valid.

## Verification

Run the project-required setup and checks after implementation:

```bash
just install
pytest tests/ace/tui/test_agents_live_hint_refresh.py tests/ace/tui/widgets/test_agent_list_file_change_pencil.py tests/ace/tui/widgets/test_linked_deltas.py tests/ace/tui/widgets/test_agent_deltas.py
just check
```

If the implementation touches visual rendering snapshots beyond the existing suffix pencil placement, also run the
relevant ACE PNG snapshot target and inspect failures before accepting snapshot updates.

## Risks And Constraints

- Do not move linked Git probes into startup or render paths. Keep them in the existing deferred worker or bounded
  loader classification.
- Be careful not to regress Plan-row behavior: the pencil should follow active coder work, not the Plan row's own
  bookkeeping diff.
- Avoid duplicating core linked-repo resolution logic. Use existing launch metadata and opened-workspace markers, and
  keep workspace probing read-only.
- Keep the row badge boolean-only. The rich linked `Deltas:` section and linked file pages remain the detail/file-panel
  responsibility.
