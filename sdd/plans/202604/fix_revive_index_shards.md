---
create_time: 2026-04-24 21:55:27
status: done
prompt: sdd/prompts/202604/fix_revive_index_shards.md
---
# Plan: Fix Agents-tab revive visibility after dismissed bundle sharding

## Goal

Make the `R` revive flow on the `sase ace` Agents tab show all revivable dismissed agents again, including agents whose
bundle files exist under sharded `~/.sase/dismissed_bundles/YYYYMM/` directories even if `dismissed_agents.json` was
partially pruned.

## Current diagnosis

The local data shows the revive source data is mostly still present:

- `~/.sase/dismissed_bundles/` contains thousands of bundle files and over a thousand unique suffixes.
- `~/.sase/dismissed_agents.json` has been reduced to a tiny subset of those suffixes.
- `AgentRevivalMixin._revive_agent()` only sees `_dismissed_agent_objects`, which is populated by
  `load_agents_from_disk()`.
- `load_agents_from_disk()` currently loads saved bundles only for suffixes present in `dismissed_agents.json`.

That means most saved bundles are unreachable from the revive modal even though the actual serialized agent data still
exists.

There is also a concrete pruning bug in `_compute_loader_cleanup()`:

- It tries to decide whether a dismissed identity is orphaned by checking `~/.sase/dismissed_bundles/{raw_suffix}.json`
  and top-level `{raw_suffix}__c*.json`.
- The current bundle layout is sharded under `dismissed_bundles/YYYYMM/`.
- Therefore valid sharded bundles can be classified as missing, and the cleanup then removes their identities from
  `dismissed_agents.json`.

This explains both symptoms: the dismissed index shrinks over time, and the `R` modal can only offer a small number of
agents.

## Design

Use the bundle archive as the durable source for revive, while keeping the lightweight dismissed identity index useful
for normal filtering and fast loading.

1. Add a bundle existence helper in `src/sase/ace/dismissed_agents.py`.
   - It should answer whether a raw suffix has either a parent bundle or any child bundle.
   - It must use the existing sharded-aware helpers (`_find_bundle()` / `_iter_bundle_paths()`), not direct top-level
     `Path.exists()` checks.
   - This gives loader cleanup one canonical way to reason about bundle existence across current and legacy layouts.

2. Fix `_compute_loader_cleanup()` in `src/sase/ace/tui/actions/agents/_loading.py`.
   - Replace the direct top-level path/glob orphan check with the new sharded-aware bundle existence helper.
   - Keep the cleanup behavior for genuinely orphaned dismissed identities that have neither live artifacts nor bundle
     data.
   - This stops future TUI refreshes from deleting valid dismissed identities.

3. Make revive recover from already-pruned indexes.
   - Update `load_agents_from_disk()` in `src/sase/ace/tui/actions/agents/_loading_helpers.py` so
     `dismissed_from_loader` is supplemented by all saved bundle agents, not only bundle agents whose suffix is still in
     `dismissed_agents.json`.
   - Deduplicate by identity and raw suffix against loader-discovered dismissed agents so active/non-dismissed entries
     are not duplicated in the revive list.
   - Keep active filtering governed by `self._dismissed_agents`; this change is for the revive list, not for hiding
     arbitrary active agents.

4. Reconcile the in-memory dismissed identity set from recovered bundles.
   - In `_apply_loaded_agents()`, when `_dismissed_agent_objects` includes bundle-loaded agents not present in
     `_dismissed_agents`, add their identities to `_dismissed_agents` and persist once.
   - This repairs `dismissed_agents.json` from the existing bundle archive gradually and makes later targeted loads work
     again.
   - Only add bundle/revive candidates, not arbitrary active loader agents, to avoid hiding live agents by accident.

5. Preserve performance.
   - `load_dismissed_bundles()` already reads bundle files through the loader executor and supports sharded traversal.
   - Loading all bundles adds work on Agents refresh, but the archive is the only complete source after the index has
     been pruned. If this is too costly later, add a small metadata index; do not reintroduce a correctness dependency
     on the already-damaged identity file.

## Tests

Add focused regression coverage:

- `tests/test_dismissed_agents.py`: bundle existence helper finds parent/child bundles in sharded directories and legacy
  top-level directories.
- `tests/test_agent_loader_self_heal.py`: loader cleanup does not orphan-prune an identity when only a sharded bundle
  exists.
- A loading-helper or revive-adjacent test: a bundle whose suffix is absent from `dismissed_agents.json` still appears
  in `dismissed_from_loader`, and the apply step repairs `_dismissed_agents`.

## Validation

Run targeted tests first:

- `.venv/bin/python -m pytest tests/test_dismissed_agents.py tests/test_agent_loader_self_heal.py tests/test_agent_revive.py`

Then follow repo instructions:

- `just install`
- `just check`

Finally, use a local diagnostic command to compare bundle count vs revivable count and confirm the revive path is no
longer limited by the pruned dismissed index.
