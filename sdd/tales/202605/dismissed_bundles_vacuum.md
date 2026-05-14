---
create_time: 2026-05-14 19:58:22
status: wip
prompt: sdd/prompts/202605/dismissed_bundles_vacuum.md
---
# Plan: Reclaim ~131M from the dismissed-bundle index and refresh the artifact index

## Context

`sdd/research/202605/ace_run_artifact_cleanup.md` evaluates several cleanup levers for the oversized
`~/.sase/projects/sase/artifacts/ace-run/` tree and adjacent SQLite stores. It ranks `VACUUM` against
`~/.sase/dismissed_bundles/index.sqlite` as the single highest reward-to-risk action available today:

- Current file size: **132.2M**, of which **~131.0M (99.1%) is freelist** (31,972 of 32,267 pages dead).
- One-shot reclaim, no schema/code change, no behavioral change to revive/dismiss flows.
- "Improves any future read that mmap's or seeks within the file" — relevant to the dismissed-bundles read paths in
  `src/sase/ace/dismissed_agents.py` and `src/sase/ace/dismissed_agents_bundles.py`.

Pairing it with `sase agents index rebuild` (research step 2) is also low-risk: the `agent_artifacts` table in
`~/.sase/agent_artifact_index.sqlite` currently has 0 rows (file size 37K), so the Tier 1 fast path is effectively
disabled. Rebuilding restores it without touching any on-disk artifacts.

Verified pre-conditions on this workstation (2026-05-14):

- `~/.sase/dismissed_bundles/index.sqlite` is 132M.
- `~/.sase/agent_artifact_index.sqlite` is 37K (empty `agent_artifacts` table per research).
- `sase agents index {rebuild,verify}` subcommands exist.
- A `sase ace` TUI is currently running (PID 853458). The research explicitly requires VACUUM to be offline.

Out of scope (explicitly deferred — these are higher-risk and require a guarded CLI per the research):

- Archiving / pruning markerless `ace-run` directories.
- Compacting rich artifact payloads (Option 4).
- Implementing the scanner/index ignore-markerless product fix (Option 3).
- Bundle-retention policy or `auto_vacuum=FULL` schema migration in `src/sase/ace/dismissed_agents_bundles.py`.

## Goal

Execute the two zero-risk operational steps the research ranks first, in order, and record before/after evidence so the
next iteration can decide whether deeper cleanup (Options 2 / 3 / 4) is warranted.

## Approach

This is operational work, not a code change. The plan is a short, ordered runbook with explicit safety gates.

### Step 1 — Confirm the TUI is closed

VACUUM acquires an exclusive lock. The running `sase ace` process (currently PID 853458) must be exited by the user
before proceeding. The agent should **not** kill the TUI unilaterally; instead, surface the running PID, ask the user to
close it, and re-check `pgrep -af "sase ace"` before continuing.

### Step 2 — Capture before-state evidence

```bash
ls -la ~/.sase/dismissed_bundles/index.sqlite
python3 -c "import sqlite3; c = sqlite3.connect('$HOME/.sase/dismissed_bundles/index.sqlite'); \
  print('page_count', c.execute('PRAGMA page_count').fetchone()[0]); \
  print('freelist_count', c.execute('PRAGMA freelist_count').fetchone()[0]); \
  print('page_size', c.execute('PRAGMA page_size').fetchone()[0]); \
  print('rows', c.execute('SELECT COUNT(*) FROM dismissed_bundle_summaries').fetchone()[0])"
ls -la ~/.sase/agent_artifact_index.sqlite
python3 -c "import sqlite3; c = sqlite3.connect('$HOME/.sase/agent_artifact_index.sqlite'); \
  print('rows', c.execute('SELECT COUNT(*) FROM agent_artifacts').fetchone()[0])"
```

Numbers should match the research's snapshot (~132M, ~32k pages, ~31.9k freelist, 2,280 rows; agent_artifacts = 0 rows).

### Step 3 — VACUUM the dismissed-bundle index

The exact command from the research (run with the TUI confirmed closed):

```bash
python3 -c "import sqlite3; sqlite3.connect('$HOME/.sase/dismissed_bundles/index.sqlite').execute('VACUUM')"
```

No backup is taken because:

- VACUUM is crash-safe (writes a rollback journal; if interrupted the original file is preserved).
- The dismissed-bundle JSON files under `~/.sase/dismissed_bundles/*.json` are the revive source of truth (per research
  §Dismissed Bundles); the SQLite file is only a summary index and can be rebuilt from the JSON bundles if
  catastrophically corrupted.

If the user wants a belt-and-suspenders backup, an optional pre-VACUUM `cp` is documented but not enabled by default.

### Step 4 — Verify reclaim

```bash
ls -la ~/.sase/dismissed_bundles/index.sqlite
python3 -c "import sqlite3; c = sqlite3.connect('$HOME/.sase/dismissed_bundles/index.sqlite'); \
  print('page_count', c.execute('PRAGMA page_count').fetchone()[0]); \
  print('freelist_count', c.execute('PRAGMA freelist_count').fetchone()[0]); \
  print('rows', c.execute('SELECT COUNT(*) FROM dismissed_bundle_summaries').fetchone()[0])"
```

Acceptance: file shrinks to roughly 1-2 MB, freelist_count drops to ~0, row count unchanged (still 2,280).

### Step 5 — Rebuild the agent artifact index

```bash
sase agents index rebuild
sase agents index verify
```

Acceptance: `verify` exits clean; `agent_artifacts` row count goes from 0 to ~11,369 (matches the research's full-scan
record count).

### Step 6 — Report and stop

Print a short summary to the user with before/after sizes and row counts. **Do not** proceed to Options 2/3/4 in this
session — those need their own plans and (for Option 3) core/backend code work crossing the boundary into
`../sase-core`.

## Risks & Mitigations

| Risk                                                                           | Mitigation                                                                                                                           |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| TUI still running during VACUUM → lock contention or partial corruption window | Hard gate in step 1; re-check `pgrep` before step 3. Refuse to run otherwise.                                                        |
| Power loss mid-VACUUM                                                          | SQLite rollback journal guarantees atomicity; original file is preserved. JSON bundles remain the source of truth.                   |
| `agent_artifacts` index rebuild fails partway                                  | `sase agents index verify` catches it; rebuild is idempotent and re-runnable.                                                        |
| User has a different workstation state than the research snapshot              | Step 2 captures actual numbers before acting; if freelist is small, the reward shrinks and we can re-evaluate before running step 3. |

## Follow-ups (out of scope here, recorded for later)

- Make VACUUM not a one-and-done: switch the dismissed-bundle index schema to `auto_vacuum=FULL` or run
  incremental_vacuum on a schedule. Touch `src/sase/ace/dismissed_agents_bundles.py`.
- Implement `sase agents artifacts prune-markerless` per the research's required-behavior list (dismissed-suffix filter,
  marker refusal, manifest, index refresh).
- File a Rust-core follow-up to teach the scanner/Tier 1 index predicate to ignore markerless dismissed directories
  (Option 3 — the structural fix).
