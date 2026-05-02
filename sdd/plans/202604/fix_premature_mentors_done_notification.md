---
create_time: 2026-04-25 20:08:04
status: done
prompt: sdd/prompts/202604/fix_premature_mentors_done_notification.md
---
# Fix: Premature "Mentors done" Notification on Draft→Ready Transition

## Goal

Stop the false-positive `[mentors] Mentors done for <changespec> entry <N>` notification that fires after a ChangeSpec
status transition (most visibly Draft→Ready) **before** `sase axe` has actually written the MENTORS field for that
entry. The legitimate "all mentors finished" / "no profiles matched" notification path must continue to work for
genuinely terminal entries.

## Symptom

User flips a ChangeSpec from `Draft` → `Ready`. Within seconds, a notification appears:

```
* [mentors] Mentors done for yserve_dto_fixes entry 2  13s ago  [mentor]  1 file
```

— but the `MENTORS:` field for entry 2 has not yet been added to the `.gp` file. A subsequent axe cycle then writes the
MENTORS field correctly. The notification is therefore both incorrect (mentors aren't done; they haven't even been
matched yet) and idempotency-locked (the sidecar marker at `~/.sase/notifications/mentors_complete.json` now records
this `(project_file, changespec_name, entry_id)` tuple as already notified — silently swallowing the eventual real
"mentors done" notification once mentors actually finish).

## Root Cause

The notification is emitted by `_check_mentor_completion_notifications` in
`src/sase/ace/scheduler/mentor_checks.py:379`, called from `check_mentors` as Phase 2.5 — **after** Phase 2's
`add_matching_profiles_upfront` and **before** Phase 3 starts mentors. The relevant check is:

```python
if matching_entry is None or not matching_entry.profiles:
    mentor_summary = "no mentor profiles matched"
    mark_notified(...); notify_mentors_complete(...)
```

The bug has two compounding causes:

### Cause A — In-memory `ChangeSpec` is not refreshed between Phase 2 and Phase 2.5

`add_matching_profiles_upfront` (`src/sase/ace/scheduler/mentor_profile_matching.py:420`) calls `add_mentor_entry`
(`src/sase/ace/mentors/entries.py:18`) for every newly matched profile. `add_mentor_entry` re-parses the project file
inside its own lock, mutates a freshly-read `MentorEntry` list, and atomically writes the file. It does **not** mutate
the `changespec` Python object that was passed in to `check_mentors` — it doesn't even receive it.

Phase 2.5 then inspects exactly that stale `changespec.mentors` and (correctly, given its inputs) concludes "there is no
MentorEntry for the latest entry_id" → fires the "no mentor profiles matched" path.

This is reliably triggered on Draft→Ready because:

1. While in `Draft`, `add_matching_profiles_upfront` short-circuits (its own status guard at
   `mentor_profile_matching.py:439`).
2. So when the user flips to `Ready`, the **next** axe cycle is the very first chance to write any MENTORS entry for the
   entry — exactly the cycle where the in-memory `changespec.mentors` is `None`.
3. `clear_mentor_draft_flags` (called from the status transition handler at
   `src/sase/status_state_machine/handlers.py:174`) is a no-op when there were no Draft mentor entries to clear, so it
   doesn't seed MENTORS either.

### Cause B — Single-cycle "no match" is not load-bearing evidence

Independently of Cause A, `_get_matching_profiles_for_entry` can legitimately return an empty list in a single cycle
even when matching profiles **do** exist for the commit:

- The local DIFF file at `commit.diff` may not exist yet (e.g. cross-machine path, transient FS issue).
- The VCS fallback (`_load_latest_diff_from_vcs`) may fail (`get_workspace_directory` raises, provider not yet seeing
  the revision, network blip).

In these cases `_build_commit_match_artifacts` produces artifacts with empty `changed_files` / no `diff_content`, so
`_profile_matches_commit_artifact` returns False for every glob/regex profile. The next cycle, when the diff is
available, the same profiles do match and get registered. If Phase 2.5 had already fired "no mentor profiles matched" in
the earlier cycle, the legitimate completion notification later is suppressed by the idempotency marker.

The `_all_non_skip_hooks_ready` gate in Phase 2.5 ensures hooks have finished, but it does **not** guarantee that
profile matching has had a chance to evaluate against real diff content.

## Design

Two narrowly-targeted changes, both in `src/sase/ace/scheduler/`:

### Fix 1 — Pass Phase 2's outcome through to Phase 2.5 (addresses Cause A)

`add_matching_profiles_upfront` already knows the list of `(entry_id, profile)` pairs it just wrote to disk
(`matching_profiles` local variable). Surface that list to the caller so Phase 2.5 can reason about the post-write
state, not the pre-write in-memory snapshot.

Concrete change in `mentor_profile_matching.py`:

- Change `add_matching_profiles_upfront` signature to return a small dataclass /
  `tuple[list[str], list[tuple[str, MentorProfileConfig]]]`:
  - `updates` (existing list of human-readable strings, unchanged)
  - `newly_matched` — the `matching_profiles` list, for the caller's use.

In `mentor_checks.py::check_mentors`:

- After Phase 2 returns, if `newly_matched` is non-empty for the latest `entry_id`, treat the entry as "MENTORS just got
  populated this tick, no completion check possible yet" and **skip** Phase 2.5 entirely for that ChangeSpec on this
  cycle. The next cycle will reload `changespec` from disk via `lumberjack`, see the populated MENTORS field, and Phase
  2.5 will then have an accurate view.

This is preferable to mutating `changespec.mentors` in-place from Phase 2: the disk is the source of truth, Phase 2.5's
existing "all status_lines terminal" branch already requires populated `status_lines` (which only get there via
`set_mentor_status` writes from running mentors), and skipping for one tick costs at most one polling interval before
the real notification has a fresh chance to fire.

### Fix 2 — Confirm "no profiles matched" with fresh matching (addresses Cause B)

Before taking the "no mentor profiles matched" branch in `_check_mentor_completion_notifications`, re-evaluate profile
matching for the latest entry. If matching now returns a non-empty result, this means either (a) Phase 2 just populated
MENTORS but in-memory state is stale (subsumed by Fix 1) or (b) profile matching is non-deterministic across cycles for
this entry due to diff availability. In either case, defer.

Implementation: pull `_get_matching_profiles_for_entry(changespec, mentor_profiles=…)` into the no-match branch as a
guard. If it returns non-empty → `return updates` without notifying or marking. Pass the same preloaded
`mentor_profiles` list that `check_mentors` already has so we don't re-load profiles from disk.

This guard is cheap (no VCS calls beyond what Phase 2 already did this tick — diffs are read on the same cycle from the
same paths) and makes the no-match notification load-bearing only when matching has positively evaluated to zero on the
**same data** that Phase 2.5 sees.

### Why both fixes, not one

- Fix 1 alone: still vulnerable to Cause B if Phase 2 returned zero matches due to diff-unavailability. Fix 1 only kicks
  in when Phase 2 wrote something.
- Fix 2 alone: re-running profile matching every Phase 2.5 cycle works for Cause A too (since the disk now has the
  MENTORS entry, `get_profiles_registered_for_entry` filters them out, and `_get_matching_profiles_for_entry` returns
  empty → the no-match branch fires anyway and we're back where we started). Without Fix 1, Fix 2 doesn't help Cause A.

So we need Fix 1 to skip the cycle when MENTORS was just written, AND Fix 2 to guard against transient mismatches when
nothing was written.

## Files To Touch

- **`src/sase/ace/scheduler/mentor_profile_matching.py`**
  - Change `add_matching_profiles_upfront` to additionally return the `matching_profiles` list (or a typed result
    object). Update the docstring.

- **`src/sase/ace/scheduler/mentor_checks.py`**
  - In `check_mentors`, capture the new return value and pass it (or just the latest-entry subset) into
    `_check_mentor_completion_notifications` as a new parameter `just_matched_for_latest: bool` (or skip the call
    entirely when True — see "Open Questions" below).
  - In `_check_mentor_completion_notifications`, accept the new parameter; early-return if True.
  - Add the Cause B guard inside the no-match branch — call `_get_matching_profiles_for_entry` and bail if non-empty.

- **`src/sase/axe/hook_jobs.py`**
  - Update the `add_matching_profiles_upfront` call site if/when its return shape changes (currently
    `add_matching_profiles_upfront` is called from `mentor_checks.py:545` only — verify there are no other callers).

- **`tests/test_mentor_checks.py`**
  - New test: ChangeSpec with no MENTORS field on entry but matching profiles exist → first call to `check_mentors`
    writes MENTORS and does NOT fire `notify_mentors_complete`. Second call (with refreshed `changespec`) sees populated
    MENTORS and behaves correctly (no premature "no profiles matched" notification, marker not set).
  - New test: ChangeSpec with empty diffs (Cause B simulation) → matching returns empty in cycle 1 → notification
    deferred. Cycle 2 with diff available → matching returns non-empty → still deferred (until profiles registered &
    mentors run).
  - Existing tests for the legitimate "no mentor profiles matched" path may need adjustment so the fixture has
    `_get_matching_profiles_for_entry` return empty when re-evaluated.

- **`tests/test_mentor_profile_matching.py`** (or wherever `add_matching_profiles_upfront` is tested)
  - Update assertions for the new return shape.

## Open Questions / Tradeoffs

1. **Skip-on-just-matched vs. mutate-in-place.** The plan recommends skipping Phase 2.5 for the cycle in which Phase 2
   wrote MENTORS for the latest entry. Alternative: have Phase 2 also mutate `changespec.mentors` in memory to mirror
   what was written. The mutate-in-place option is more eager (notification can fire on the same tick if the entry
   somehow already had terminal status_lines, which can't happen on a fresh write — so the eagerness is illusory).
   Skipping is simpler and avoids divergence between disk and in-memory representations.

2. **One-cycle delay impact.** The legitimate "all mentors terminal" path is unaffected because that path requires
   populated `status_lines` (mentors must have run, which only happens after MENTORS exists from a prior cycle). The
   only path delayed by Fix 1 is the "no profiles matched" notification — which the user explicitly wants to be slow and
   certain rather than fast and wrong. Worst case: a one-poll-interval delay between MENTORS getting populated and the
   user being told (in the no-match case) that nothing matched.

3. **Idempotency marker pollution.** Some users (including the reporter) may already have a stale entry in
   `~/.sase/notifications/mentors_complete.json` for the false-positive (`yserve_dto_fixes` / entry 2). Once we ship the
   fix, those entries will continue to suppress the legitimate notification when mentors actually finish. We have two
   options:
   - Ship a one-shot cleanup command, e.g. `sase notifications mentor-marker prune --cl <name> --entry <id>`.
   - Document a manual workaround (edit the JSON file or delete it). Recommend the cleanup command as a small standalone
     improvement, scoped after the core fix lands.

4. **Should we tighten the gate further?** We could also require that Phase 2 has had at least one successful diff read
   for the latest entry (i.e. `commit_artifacts[-1].diff_content is not None`) before firing the no-match notification.
   This would catch Cause B without re-running matching. It's an alternative to Fix 2's re-evaluation, but threads more
   state through. Recommend keeping Fix 2 as proposed for cleanliness; revisit if profile-matching cost becomes
   measurable.

## Acceptance

- After Draft→Ready, the false-positive "Mentors done for ... entry N" notification no longer fires on the cycle where
  axe writes the MENTORS field for the first time.
- The legitimate "no mentor profiles matched" notification still fires (one cycle later) when no profiles match an entry
  whose hooks are all ready.
- The legitimate "all mentors finished" notification still fires unchanged.
- New tests exercise both Cause A (just-wrote MENTORS) and Cause B (transient diff unavailability).
- `just check` passes.
