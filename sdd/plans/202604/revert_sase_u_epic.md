---
create_time: 2026-04-27 09:42:54
status: wip
prompt: sdd/prompts/202604/revert_sase_u_epic.md
---
# Plan: Revert the `sase-u` epic ("Instant j/k Navigation in the TUI")

## Context

The `sase-u` epic landed 5 phases that reworked the TUI's input/refresh/render plumbing. Suspected to be the source of
recent "laggy and weird" behavior. We want to back out the entire epic.

### Verified phase commits (from `git log`, not the stale NOTES hashes)

| Bead     | SHA        | Subject                                                                       |
| -------- | ---------- | ----------------------------------------------------------------------------- |
| sase-u.1 | `e32eab2f` | feat: add SASE_TUI_PERF=1 j/k key-to-paint instrumentation + baseline harness |
| sase-u.2 | `3780207d` | feat: move TUI auto-approve and bulk-dismiss disk I/O off the event loop      |
| sase-u.3 | `e2f4617b` | feat(ace): selective row updates + render-result cache for agents tab         |
| sase-u.4 | `e44715f2` | feat(ace): tab-agnostic detail-panel debouncer for j/k navigation             |
| sase-u.5 | `3e8a9f97` | feat(ace): event-driven artifact refresh with j/k nav gate                    |

Plus bead-state chores (not strictly part of the code change but live alongside):

- `9fac2660` chore: close bead sase-u.1
- `fb040cfb` chore: close bead sase-u and mark instant_jk_navigation plan done

### What the epic introduced (will disappear on revert)

New modules under `src/sase/ace/tui/util/`:

- `debounce.py` — `DetailPanelDebouncer`
- `fs_watcher.py` — inotify-based artifact watcher
- `io_async.py` — off-event-loop persistence helper
- `nav_gate.py` — "user is navigating" gate
- `perf.py` — `SASE_TUI_PERF=1` instrumentation

Plus memoized `format_agent_option` / `format_banner_option`, `OptionList.replace_option_at` selective updates, and the
Pilot benchmark harness in `tests/ace/tui/bench_tui_jk.py`.

## The hard part: collateral commits since the epic

The epic merged ~3 weeks ago. **15+ subsequent commits touch the same TUI files**, several of them are explicit
follow-ups to sase-u behavior:

- `66cbb479` fix(ace): eliminate post-launch j/k lag in Agents tab — directly tunes nav-gate/debouncer
- `1a1360ea` fix(ace): refresh agent-list highlight on j/k across folded banners — depends on selective-row-update path
- `a34fd6e4` fix(ace): guard `#list-panel` queries on changespec refresh paths — guards inotify-driven refresh
- `91c01dd0`, `ef738fde`, `5da7ccf3`, `8506be97`, `a0374e96`, `922038ab`, `31c10fc3`, `650859cc` — feature/fix work on
  top of the cached/format_agent_option rendering pipeline.

A naive `git revert e32eab2f..3e8a9f97` will conflict heavily. The revert strategy must decide what to do with these.

## Strategy options

### Option A — Reverse-topological per-phase reverts (recommended)

`git revert --no-commit` each phase commit in reverse order (5 → 4 → 3 → 2 → 1), resolve conflicts as they arise, then
commit each revert separately. One commit per phase keeps git history legible and bisectable, mirroring the way the epic
landed.

Order (parents before children → revert children first):

1. `git revert -n 3e8a9f97` (sase-u.5)
2. `git revert -n e44715f2` (sase-u.4)
3. `git revert -n e2f4617b` (sase-u.3)
4. `git revert -n 3780207d` (sase-u.2)
5. `git revert -n e32eab2f` (sase-u.1)

Commit per phase with message `Revert "<original subject>" (sase-u.<N>)` so each revert is greppable.

### Option B — One bundled revert commit

Single `git revert -n` for all 5, resolve everything at once, one commit. Smaller history footprint but harder to bisect
if part of the revert turns out to be load-bearing (e.g., we discover `io_async` was used by one of the follow-up fixes
and want to keep it).

### Option C — Surgical revert with follow-up preservation

For each post-epic fix that touches the new code paths, decide whether to:

- Keep the fix as-is (if it touches behavior orthogonal to sase-u).
- Revert it alongside the epic (if it only exists because of sase-u).
- Re-implement it on the pre-epic surface area (if the underlying user-visible bug still applies).

This is the most work but produces the cleanest end state.

**Recommendation: Option A**, with Option C reserved for the handful of `fix(ace): …` commits that are clearly sase-u
follow-ups (`66cbb479`, `1a1360ea`, `a34fd6e4`). We'll evaluate each during conflict resolution rather than up front.

## Expected conflict surface

Files most likely to conflict (touched both by sase-u phases and by post-epic commits):

- `src/sase/ace/tui/widgets/agent_list.py` (or equivalent OptionList-bearing widget) — selective row updates landed
  here, then got tweaked by the highlight-refresh and BY_STATUS bucketing fixes.
- `src/sase/ace/tui/screens/agents_tab.py` — keymaps/grouping mode, post-launch j/k lag fix, Pretty headings.
- `src/sase/ace/tui/event_handlers.py` (or wherever nav-gate hooks in) — j/k input flow tweaked multiple times after
  sase-u.4/5.
- Format helpers (`format_agent_option`, `format_banner_option`) — Pretty-headings and humanized-finish-timestamp depend
  on this surface.
- `tests/ace/tui/` — `bench_tui_jk.py` and `test_*_nav_gate.py`, `test_detail_panel_debouncer.py`, `test_fs_watcher.py`,
  `test_io_async.py` will be deleted on revert; conversely, post-epic tests that exercise the new code paths will start
  failing and need to come out.

Conflict-resolution rule: when in doubt, keep the **pre-epic** behavior (that is the goal); only carry forward post-epic
logic that is independent of sase-u's machinery.

## Step-by-step plan

1. **Confirm scope with the user.**
   - Show the 5 phase SHAs and the list of post-epic commits that may need follow-up reverts. Confirm Option A.
   - Confirm whether the bench harness (`tests/ace/tui/bench_tui_jk.py`) and `SASE_TUI_PERF` instrumentation should also
     be removed (yes — they are part of sase-u.1).

2. **Create a working branch** off `master` — `revert/sase-u-epic` — so the revert is reviewable before touching
   `master`.

3. **Run the reverts in reverse-topological order** (Option A above). After each `git revert -n`:
   - Resolve conflicts, preferring pre-epic state.
   - Run `just check` to catch type/test breakage early.
   - Commit with `Revert "<subject>" (sase-u.<N>)`.

4. **Triage post-epic follow-up fixes.** For each of the candidate sase-u-dependent commits (`66cbb479`, `1a1360ea`,
   `a34fd6e4`, and any test-only commits that import the new utilities):
   - Inspect whether the original bug it fixed still exists on the reverted code.
   - If yes → keep the commit (resolve conflicts forward).
   - If the bug was _introduced_ by sase-u → revert the fix too (it becomes dead code).
   - Record the decision per commit in the PR description.

5. **Validation gate.**
   - `just check` (lint + mypy + tests) — must pass.
   - Run TUI manually: launch `sase ace`, exercise j/k bursts, agent dismiss, bulk-dismiss, switch grouping modes,
     switch tabs, observe whether the laggy/weird behavior is gone.
   - Compare against pre-epic behavior in a separate worktree at `e32eab2f^` if a side-by-side is needed.
   - Specifically re-test the symptoms that motivated the epic (j/k latency on full inbox) to confirm we're back to the
     _known_ baseline, not somewhere worse.

6. **Bead/ChangeSpec hygiene.**
   - Mark beads `sase-u`, `sase-u.1` … `sase-u.5` with a `REVERTED` status (or whatever the project's reverted-bead
     convention is — check `sase bead --help` / project docs; current statuses we've seen are `CLOSED`).
   - Append a NOTES entry on each phase bead pointing to the revert commit SHA, so future work that references "the
     inotify watcher" finds the breadcrumb explaining why it isn't there.
   - **Keep** the bead descriptions and the plan file (`../sase/plans/202604/instant_jk_navigation.md`) intact — they
     are a useful record of the attempt. Add a header block to the plan: "Reverted on 2026-04-27 — see commit <SHA>.
     Symptoms: ….".
   - Do **not** revert `fb040cfb` (close-bead chore) — instead update the bead state via `sase bead` so the audit trail
     is forward-only.

7. **Open a PR for the revert branch.** Include:
   - The full list of reverted SHAs.
   - Triage decisions for follow-up fixes from step 4.
   - "Symptoms before / after" notes from the manual TUI exercise in step 5.
   - A "what we lose" section: TUI perf instrumentation, async-IO helper, inotify refresh — so reviewers know the
     regressions that come back (e.g., 10s polling reappears).

## What we're explicitly NOT doing

- **Not** reverting via `git reset --hard` to `e32eab2f^`. That would also wipe ~15 unrelated post-epic commits.
- **Not** force-pushing or rewriting `master` history. The revert is forward-only.
- **Not** deleting the plan file or bead notes — keep the historical record.
- **Not** investigating root cause within the epic before reverting. The user has decided revert-first; root-cause
  analysis can happen on the reverted baseline if/when we re-attempt the work.

## Risks & open questions

- **Regression of the original problem.** The epic existed because j/k was laggy on full inboxes. After reverting, that
  symptom returns. Worth flagging in the PR — user may want to keep one phase (e.g., just sase-u.4's debouncer) if it
  turns out to be benign.
- **Hidden dependencies.** Some post-epic commit may import from `tui/util/io_async.py` or `tui/util/perf.py` without us
  realizing. `just check` will catch import errors; manual TUI exercise will catch behavioral ones.
- **fs_watcher fallback.** If `fs_watcher` was the _only_ refresh mechanism in some code path (i.e., the 10s poller was
  deleted, not just gated), we'll need to confirm the poller comes back cleanly via the revert. Worth a focused
  diff-read of sase-u.5 before resolving conflicts.
- **Bead state convention.** Need to confirm whether `sase bead` has a "reverted" status or if we just re-open +
  annotate. Will check during step 6.

## Deliverables

- Branch `revert/sase-u-epic` with 5 (or 5 + N follow-up) revert commits.
- PR with the breakdown above.
- Updated bead notes for `sase-u` and `sase-u.1`…`sase-u.5`.
- Plan-file annotation noting the revert.
- Confirmation from manual TUI exercise that the laggy/weird behavior is gone.
