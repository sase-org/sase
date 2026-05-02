---
create_time: 2026-04-21 18:36:14
status: wip
prompt: sdd/prompts/202604/fast_dismiss.md
---

# Plan: Make `sase ace` Agent Dismissal WAY Faster

## Problem

Dismissing an agent from the Agents tab of the `sase ace` TUI takes ~11 seconds per dismiss. Profile data at
`.sase/home/tmp/ace_profile_20260421_182457.txt` (two dismisses, 33s total) shows that the UI is frozen on the main
thread for the entire duration.

## Root Cause

`_dismiss_done_agent` (and the batch counterpart `_do_dismiss_all`) ends with a synchronous call to
`self._load_agents()`, which performs a complete disk scan to rebuild the agent list. From the profile, per-dismiss:

| Section                                                                     | Time                |
| --------------------------------------------------------------------------- | ------------------- |
| `_load_agents`                                                              | **10.925 s** (94 %) |
| &nbsp;&nbsp;&nbsp; `load_agents_from_disk` → `load_all_agents`              | 5.308 s             |
| &nbsp;&nbsp;&nbsp; `load_agents_from_disk` → `load_dismissed_bundles`       | 4.324 s             |
| &nbsp;&nbsp;&nbsp; `_apply_loaded_agents` (mostly `delete_agent_artifacts`) | 1.276 s             |
| `_refresh_agents_display`                                                   | 0.57 s              |
| **Total**                                                                   | **≈ 11.6 s**        |

Two subtler pieces stand out:

1. `load_dismissed_bundles` glob-scans the `~/.sase/dismissed_bundles/` directory **once per dismissed suffix** via
   `glob(f"{suffix}__c*.json")`. The user's local directory contains ~2 000 JSON files, so every per-suffix scan is a
   full directory walk.
2. `_apply_loaded_agents` iterates over every loader-sourced dismissed agent and calls `delete_agent_artifacts`, even
   though most of those artifacts were already cleaned up in earlier dismisses.

But the big lever is that **a full disk rescan is not needed at all** when the user dismisses one agent. The only state
that changes is:

- `_dismissed_agents` set ← already persisted before the reload.
- The agent's artifact files on disk ← already deleted before the reload.
- The in-memory agent list ← just needs the one agent (plus any workflow children) removed.

The codebase already has the building blocks: `_refilter_agents()` (`_loading.py:259`) re-runs the full in-memory
pipeline — fold filtering, custom ordering, search filter, status overrides, panel indices, selection restoration,
tab-bar counts, and display refresh — from the cached `_agents_with_children` list, with zero disk I/O. Periodic disk
reconciliation happens via `_on_auto_refresh` (`event_handlers.py:73`) on a timer; dismiss does not need to trigger it.

## Goals

1. Take the ~11 s user-visible dismiss cost down to well under 100 ms.
2. Keep current correctness guarantees: bundle persistence, dismissed-set persistence, revive-after-dismiss in the
   current session, workflow child handling, notification dismissal, workspace release.
3. Opportunistically fix two related inefficiencies that slow down every reload (startup, periodic refresh, revive).

## Non-Goals

- Refactoring the agent loader architecture.
- Speeding up `load_all_agents` beyond the incidental wins below (it is off the dismiss hot path once Fix #1 lands).
- Any UI/UX changes to the dismiss flow.

## Approach

Three fixes, sequenced so the user's pain is gone after the first one and the rest are incremental wins.

### Fix 1 — Skip the full reload on dismiss (primary; solves the complaint)

Replace the `self._load_agents()` tail call in each dismiss path with an in-memory update:

1. **Build the set of identities being dismissed.**
   - Single dismiss: `{agent.identity}` plus workflow-child identities when the agent is a workflow parent.
   - Batch dismiss: the same, unioned across the whole batch.
2. **Remove those entries from `_agents_with_children`** (the cached unfiltered list that `_refilter_agents` reads
   from).
3. **Add the dismissed Agent object(s) to `_dismissed_agent_objects`** so that the Revive modal can un-dismiss them in
   the same session without waiting for the next periodic reload. Avoid duplicates (identity already present).
4. **Pop entries from `_agent_status_overrides` and `_agent_pre_question_status`** — already handled today.
5. **Call `_refilter_agents()`** to re-run the in-memory pipeline (no disk I/O) and refresh the display.

Share the logic between single and batch dismiss via a small helper on `AgentDismissingMixin` — something like
`_apply_dismissal_in_memory(agents: Iterable[Agent]) -> None`. The helper owns steps 1–5 above; `_dismiss_done_agent`
and `_do_dismiss_all` each call it after their disk-side work (bundle save, artifact delete, notification dismissal,
workspace release).

#### Risks and how the plan handles them

- **Revive still works.** Revive reads from `_dismissed_agent_objects`. Appending the just-dismissed Agent to that list
  preserves the behavior. On the next full reload, the loader will reproduce these entries from the bundles written by
  `save_dismissed_bundle` / the dismissed-set file, so the appended objects are eventually replaced by loader-sourced
  ones — this is fine as long as identity-based dedupe in the revive modal is not surprised by duplicates. Action:
  dedupe by `identity` when appending. If an entry with the same identity already exists, leave the existing one alone.
- **ChangeSpec-loaded agents (hooks/mentors/CRS).** These don't have artifacts to delete, but the existing code already
  handles them via `_from_changespec`. In-memory removal is the same logic.
- **Workflow children.** The existing code already walks `_agents_with_children` to find children by
  `parent_timestamp` + `parent_workflow`. Keep that walk; feed the resulting children into the identity set built in
  step 1.
- **Workspace release.** Already done before the reload; no change needed.
- **Notification count.** Already refreshed in the dismiss path.
- **Auto-dismiss of hidden completed agents.** Today this happens inside `_apply_loaded_agents`. Skipping the reload
  means we miss a chance to auto-dismiss. This is fine because the periodic `_on_auto_refresh` still runs that logic —
  worst case, a hidden completed agent lingers until the next tick. (Document this trade-off in the PR; the cost is a
  cosmetic delay, not a correctness issue.)
- **Orphaned `_dismissed_agents` entries / stale artifact self-healing.** These run inside `_apply_loaded_agents` during
  full reloads. Same argument: still covered by periodic refresh and startup. No correctness regression.
- **`_dismissed_agent_objects` drift.** We are populating this list from two sources now (loader + direct dismiss). The
  next full reload re-assigns it, which reconciles any drift. No long-term drift.
- **Loading guard (`_agents_loading`).** The new path does not touch the flag, so it cannot deadlock with a concurrent
  `_load_agents_async`. If a background reload finishes after an in-memory dismiss, it will observe the updated
  `_dismissed_agents` set and filter the agent out of its results — the correct outcome.

#### Expected result

Dismiss latency drops from ~11 s to <100 ms (just the cost of `_refilter_agents` + display refresh, both in the profile
as sub-second work).

#### Test coverage

- Unit/integration test for `_dismiss_done_agent` on a running-agent identity: agent disappears from `self._agents`,
  appears in `self._dismissed_agent_objects`, `_dismissed_agents` set contains its identity.
- Same for a workflow parent: parent _and_ matching child step identities are removed from `_agents_with_children` and
  added to dismissed set.
- Same for a ChangeSpec-sourced agent (hooks / mentors / CRS).
- Batch dismiss (`_do_dismiss_all`): identities are removed atomically.
- Revive-after-dismiss in the same session: dismiss agent → open revive modal → agent appears → revive it → it reappears
  in the main list.
- Regression guard: no call to `self._load_agents` / `load_agents_from_disk` during a dismiss (assertable via a spy in
  tests).

### Fix 2 — Collapse `load_dismissed_bundles` per-suffix globs into one listdir

Currently:

```python
for suffix in suffixes:
    filepath = _DISMISSED_BUNDLES_DIR / f"{suffix}.json"
    …
    for child_path in _DISMISSED_BUNDLES_DIR.glob(f"{suffix}__c*.json"):
        …
```

With ~2 000 files in the directory and N dismissed suffixes, this is N full directory scans.

Change to: one `os.scandir()` (or `os.listdir()`) of the directory, build a `dict[str, list[str]]` mapping `raw_suffix`
→ list of child filenames (keyed by the portion of the filename before `__c`). Then each suffix lookup is O(1).

- Parent bundle lookup stays a direct file check (`Path.exists`) — no change needed there.
- The helper `_load_bundle_file` stays unchanged.
- Keep the `suffixes is None` branch (full load) intact; it already uses a single `glob("*.json")` which is not the
  issue.

#### Risks

- The `_maybe_migrate_bundles` and `_maybe_fix_child_collisions` hooks run before the listing; they must still run
  first. Keep their invocation at the top of the function.
- Filename parsing must correctly split on `__c` because raw suffixes never contain `__c` (they are 14-digit timestamps;
  child filenames always have the `__c{index}.json` suffix). Add an explicit guard/assert and unit test.

#### Expected result

~3–4 s shaved off full reloads (startup, periodic refresh, revive). User- visible benefit: startup feels snappier;
periodic refresh no longer stutters.

#### Test coverage

- Unit test on a temp directory with mixed parent and child bundle files that `load_dismissed_bundles(suffixes=...)`
  returns the same set of agents as the old per-suffix glob implementation.
- Edge case: child-only suffix (no parent `.json`).
- Edge case: ignore files that do not match the `{suffix}.json` or `{suffix}__c{index}.json` patterns.

### Fix 3 — Stop re-deleting artifacts for already-cleaned dismissed agents

`_apply_loaded_agents` (`_loading.py:187–199`) walks every loader-sourced dismissed agent and calls
`delete_agent_artifacts`. The first time we dismissed agent X, its artifacts were removed, but on every subsequent
reload we still iterate over X and re-glob its artifacts directory.

Change: before calling `delete_agent_artifacts`, fast-check `Path(artifacts_dir).is_dir()` and skip the call if the
directory no longer exists (or contains no loader-interesting files). Even better, track a per-process set of
already-cleaned `artifacts_dir` paths so we skip them on subsequent reloads.

#### Risks

- The self-healing is meant to cover cases where the dismiss path failed to delete artifacts (e.g., OSError). Keep a
  fallback path that still calls `delete_agent_artifacts` when the directory exists — just short-circuit the common
  no-op case.

#### Expected result

~0.5–0.6 s shaved off full reloads when there are many dismissed agents.

#### Test coverage

- Unit test that after one reload with a dismissed agent, a second reload does not re-invoke the `glob` inside
  `delete_agent_artifacts` for that agent. A spy on `delete_agent_artifacts` is enough.

## Sequencing and Delivery

Three independent commits, one PR:

1. **Fix 1 — in-memory dismiss.** Standalone; solves the user's complaint. Land first, test in isolation.
2. **Fix 2 — single listdir in `load_dismissed_bundles`.** Benefits the remaining reload paths (startup, periodic,
   revive).
3. **Fix 3 — skip no-op artifact deletes.** Smaller win, defense in depth.

Fix 1 alone is enough to close the bug. Fixes 2 and 3 keep the rest of the app from feeling sluggish when the user has
many dismissed agents.

## Validation

- Manual: reproduce the ~11 s dismiss on the user's machine before the change, then re-profile after Fix 1 to confirm
  dismiss is interactive (<100 ms). Re-profile again after Fix 2 to confirm startup / periodic refresh are faster.
- Automated: `just check` must pass. Add the unit/integration tests listed under each fix.
- Smoke the full dismiss → revive round-trip for a workflow parent + child step in the TUI.

## Files Touched (expected)

- `src/sase/ace/tui/actions/agents/_dismissing.py` — shared in-memory helper and swap both dismiss tails
  (`_dismiss_done_agent`, `_do_dismiss_all`).
- `src/sase/ace/tui/actions/agents/_loading.py` — possibly a small helper / signature tweak on `_refilter_agents` if
  needed; Fix 3 edits the self-healing loop in `_apply_loaded_agents`.
- `src/sase/ace/dismissed_agents.py` — Fix 2 rewrites `load_dismissed_bundles` to use a single directory scan.
- `tests/` — new tests for each fix.
