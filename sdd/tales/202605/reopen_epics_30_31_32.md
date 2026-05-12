---
create_time: 2026-05-11 23:06:13
status: done
---
# Plan: Re-open Closed Beads In sase-30, sase-31, sase-32 Epics

## Context

The user asked to re-open every bead in three epics, contingent on verifying that none of the work was actually
completed in this repo. I investigated current bead state and the git history; results are summarized below.

### Current state per epic

**sase-30 — Restore One-to-One Agent Completion Notifications and Agents-Tab Unread State**

- Epic bead `sase-30`: CLOSED. Has a `NOTES` field of `COMMIT: 457791aa`.
- Phases: `sase-30.1`, `sase-30.2`, `sase-30.3`, `sase-30.4` — all CLOSED, no implementation notes.

**sase-31 — GitHub Actions Recovery Plan**

- Epic bead `sase-31`: OPEN.
- Phases:
  - `sase-31.1` — IN_PROGRESS
  - `sase-31.2` — CLOSED; notes describe splitting `axe_dashboard.py` into a helpers module.
  - `sase-31.3` — CLOSED; notes describe a docs PDF size fix.
  - `sase-31.4` — CLOSED; notes describe a `sase_core_rs` binding rebuild (no source changes).
  - `sase-31.5` — IN_PROGRESS
  - `sase-31.6` — IN_PROGRESS

**sase-32 — PNG Snapshot Failure Links In GitHub Actions**

- Epic bead `sase-32`: OPEN.
- All four phase beads (`sase-32.1`–`sase-32.4`): OPEN.
- Nothing to re-open here.

### Verification that work is not done

- Commit `457791aa` referenced in `sase-30`'s notes does not resolve in this repo (`git show 457791aa` → unknown
  revision).
- `src/sase/ace/tui/widgets/_axe_dashboard_helpers.py` (the file `sase-31.2`'s notes claim was created) does not exist
  in the working tree or anywhere in `git log --all`.
- No commits matching the sase-31.3 docs/PDF work appear in recent history; the only docs commits in the relevant window
  belong to other epics (sase-2y, sase-2x).
- sase-31.4's notes explicitly say "no PNG golden or source changes were needed" — so there's nothing in the repo to
  verify either way; re-opening it costs nothing if the binding rebuild needs to happen again.
- The only sase-30/31/32 commits in `git log --all` are bead-management and plan-add commits (e.g. `95f4962b`,
  `693db212`, `217fecac`, `19d5a05f`) — no implementation commits landed.

Conclusion: the closed beads were marked complete based on work in other workspaces that never reached this repo. The
user has authorized re-opening them.

## Plan

### Step 1 — Re-open sase-30 epic and its phases

Run, in order:

```bash
sase bead update sase-30.4 --status open
sase bead update sase-30.3 --status open
sase bead update sase-30.2 --status open
sase bead update sase-30.1 --status open
sase bead update sase-30   --status open
```

Then clear the stale commit pointer on the epic so future readers don't follow a dead reference:

```bash
sase bead update sase-30 --notes ""
```

(If `--notes ""` is rejected by the CLI, fall back to setting an explicit short marker like
`--notes "Previously noted COMMIT: 457791aa is not present in this repo; epic re-opened."` to avoid silent confusion.)

### Step 2 — Re-open the three closed sase-31 phases

```bash
sase bead update sase-31.2 --status open
sase bead update sase-31.3 --status open
sase bead update sase-31.4 --status open
```

Do **not** touch `--notes` on these phases. Their existing implementation notes describe how the work was done in
another workspace and are valuable context for whoever re-attempts the phase.

`sase-31.1`, `sase-31.5`, `sase-31.6` remain `in_progress` and `sase-31` epic remains `open` — no change needed there.

### Step 3 — sase-32

No action. Epic and all four phases are already `open`.

### Step 4 — Verify

```bash
sase bead list --status=open | grep -E "sase-3[012]"
sase bead show sase-30
```

Expected: 11 rows printed by the list grep (sase-30 + 4 phases, sase-31 + 0 newly opened phases from this step's output
but 3 newly open phases plus the existing open epic, sase-32 + 4 phases — actual exact count depends on filtering; the
important check is that every `sase-30*` bead and every `sase-31.2/3/4` shows `○`, and `sase-30`'s notes section no
longer points at the missing commit).

## Out of scope

- Re-doing or re-investigating the underlying implementation work for any phase. That is a separate task once these
  beads are open again.
- Modifying the epic plan documents under `sdd/epics/202605/`.
- Touching `sase-32` in any way.
- Closing or pausing any currently `in_progress` bead.
