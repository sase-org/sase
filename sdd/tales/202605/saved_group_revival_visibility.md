---
create_time: 2026-05-27 15:06:10
status: done
prompt: sdd/prompts/202605/saved_group_revival_visibility.md
---
# Saved Group Revival Visibility Plan

## Context

The `S` keymap saves marked Agents-tab rows as a dismissed agent group, hides them in memory, persists dismissed
bundles, and writes a saved group record. The `R` keymap opens the saved group revival modal, resolves saved refs back
to dismissed bundles, removes the revived identities from `dismissed_agents.json`, restores loader marker files, and
schedules a full-history refresh.

Recent commits added this flow and later split the revive modules. The current focused tests cover routing, batch
execution, and artifact restoration calls, but they do not assert that a saved group revived through the TUI actually
reappears in `app._agents` after pressing Enter. The existing E2E test monkeypatches the startup loader and only waits
for `_restore_agent_artifacts` to be called, so it can pass while the visible Agents-tab result is wrong.

## Findings

The basic real-loader path can work for a simple `ace-run` done agent and a simple workflow parent. That narrows the
likely failure to state reconciliation around the real user workflow rather than the modal selection itself.

There are two concrete risks in the current implementation:

1. Revive syncs the artifact-index dismissed projection with
   `sync_dismissed_agent_artifact_index(self._dismissed_agents)` after bundles are preserved. Without the authoritative
   `added` fast path, the sync helper rebuilds the dismissed projection from every dismissed bundle summary as well as
   the dismissed set. A just-revived saved bundle can therefore remain projected as dismissed in Tier 1 even after
   `dismissed_agents.json` no longer contains it.

2. Saved bundles intentionally omit `Agent.tag`, and restored `agent_meta.json` also omits the tag. If a revived row is
   surfaced from the bundle cache during an incomplete/stale Tier 1 refresh, or if its loader markers had to be rebuilt
   from the bundle, it can lose the tag that determines the side panel and `tag:` query visibility. That matches the
   user's requirement that revived groups come back exactly as they were, including agent tags.

## Plan

1. Add regression coverage that exercises the real saved-group TUI flow through `S` then `R` and asserts the row returns
   to `app._agents`, with its original tag.
   - Avoid the current mocked-loader blind spot for the new regression.
   - Include the marker-deleted case by forcing a full dismissed refresh before revive, so restore-from-bundle is
     exercised rather than just unfiltering still-present markers.

2. Make revive's dismissed-index sync authoritative for the post-revive dismissed set.
   - Use the existing `sync_dismissed_agent_artifact_index(..., added=...)` contract or a small wrapper if needed so
     preserved dismissed bundles do not re-project revived suffixes as dismissed.
   - Keep the existing full-history refresh because revive still needs a source-of-truth reload after marker
     restoration.

3. Preserve tags in saved/revived groups.
   - Include `Agent.tag` in dismissed bundle serialization.
   - Include tag in saved group refs where useful for previews/future compatibility.
   - Restore `tag` into `agent_meta.json` when rebuilding markers so source scans recover the same tag even when only
     the bundle survived.

4. Keep changes scoped to the Python TUI/archive layer unless tests show Rust core behavior must change.
   - The Rust index already treats its dismissed table as authoritative; the bug is how Python builds that table during
     revive.

5. Verify with focused tests first, then run `just check` after file changes as required by repo instructions.
