# ace-run Artifact Cleanup Research

Date: 2026-05-14

## Question

`~/.sase/projects/sase/artifacts/ace-run/` is large enough to slow the ACE TUI. Determine what can be reduced without
breaking SASE behavior, especially the ability to revive old dismissed agents.

## Current Local Footprint

Measured on 2026-05-14:

| Path / group | Count | Disk size |
| --- | ---: | ---: |
| `~/.sase/projects/sase/artifacts/ace-run/` | 10,311 timestamp dirs, 91,626 files | 712M |
| 202603 dirs | 2,703 dirs | 117M |
| 202604 dirs | 3,859 dirs | 173M |
| 202605 dirs | 3,749 dirs | 423M |
| Dirs with loader-visible markers | 2,461 dirs | 227M |
| Dirs with no loader-visible markers | 7,855 dirs | 486M |
| Markerless dirs before 2026-05-01 | 5,428 dirs | 204M |
| Markerless dirs before 2026-05-08 | 6,426 dirs | 316M |

The "loader-visible marker" set is `done.json`, `workflow_state.json`, or `prompt_step_*.json`. These are the files
whose presence makes the scanner/loaders turn an artifact directory into a visible done/workflow row.

By apparent file bytes, loader markers are not the bulk of the data:

| File group | Count | Apparent size |
| --- | ---: | ---: |
| Loader marker files (`done`, `workflow_state`, `prompt_step_*`) | 14,795 | 35.8M |
| Other files | 72,825 | 169.2M |

Large non-marker contributors:

| File | Count | Apparent size |
| --- | ---: | ---: |
| `commit_diff.diff` | 2,725 | 59.5M |
| `sase.md` | 6,882 | 37.5M |
| `raw_xprompt.md` | 8,758 | 15.4M |
| `live_reply.md` | 6,895 | 13.0M |
| `workflow_state.json` | 2,457 | 11.3M |

The disk-size gap between apparent file bytes and `du` is expected: this tree has many tiny files and directories, so
filesystem block and directory overhead matter.

## Relevant Product Behavior

### Artifact Scanning

The Rust scanner walks `projects_root/<project>/artifacts/<workflow>/<timestamp>/` and collects every timestamp
directory under supported workflow directories before parsing marker files:

- `../sase-core/crates/sase_core/src/agent_scan/scanner.rs`
- `src/sase/core/agent_scan_facade.py`

For each candidate directory, the scanner reads marker files including `agent_meta.json`, `done.json`, `running.json`,
`waiting.json`, `pending_question.json`, `workflow_state.json`, `plan_path.json`, `prompt_step_*.json`, and optionally
`raw_xprompt.md`.

The TUI loader uses:

- Tier 1: persistent artifact index if present, otherwise bounded source scan.
- Tier 2: full source scan for full history and deliberate revive/search paths.

Relevant files:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/actions/agents/_loading_disk.py`
- `src/sase/ace/tui/actions/agents/_revive.py`

### Dismissal and Revival

Dismissal saves a dismissed bundle, then removes only loader marker files from the artifact directory:

- Dismiss persistence: `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
- Marker deletion: `src/sase/ace/tui/actions/agents/_killing_utils.py`
- Rust deletion implementation: `../sase-core/crates/sase_core/src/agent_cleanup/execution.rs`

The marker deletion set is deliberately small:

- `workflow_state.json`
- `done.json`
- `prompt_step_*.json`

Revive does not require the original marker files to still exist. It loads the dismissed bundle, removes the dismissed
identity, then recreates minimal loader-visible artifacts:

- Running/done agents: recreate `done.json`, merge `agent_meta.json`.
- Workflow parents: recreate `workflow_state.json`, and sometimes `done.json`.
- Workflow children: recreate `prompt_step_<idx>.json`.

Relevant file:

- `src/sase/ace/tui/actions/agents/_revive_artifacts.py`

Therefore, marker-stripped artifact directories are not the source of revive truth. The source of revive truth is the
dismissed bundle archive under `~/.sase/dismissed_bundles/`.

### Dismissed Bundles

Current dismissed bundle footprint:

| Path / group | Count | Size |
| --- | ---: | ---: |
| `~/.sase/dismissed_bundles/` | 19,635 files | 297M disk |
| JSON bundle files | 19,567 | 129.4M apparent |
| `~/.sase/dismissed_agents.json` | n/a | 1.3M |

The dismissed bundle index exists and is substantial:

- `~/.sase/dismissed_bundles/index.sqlite`
- SQLite file has many free pages, so it may be worth vacuuming or rebuilding separately.

Revive and run-log UI use dismissed bundle summaries and hydrate only selected bundle details:

- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_agents_bundles.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py`

## Performance Findings

Timed against the current `~/.sase/projects` on 2026-05-14:

| Path | Time | Records | Dirs visited |
| --- | ---: | ---: | ---: |
| Full source scan | 2.214s | 11,369 | 11,369 |
| Tier 1 bounded source scan | 1.166s | 8,953 | 11,369 |
| Current artifact index query | 0.053s | 0 | 0 |
| Rebuild temp artifact index | 2.451s | 11,369 rows | n/a |
| Query rebuilt temp index, Tier 1 | 0.579s | 7,216 | 7,216 |
| Query rebuilt temp index, full history | 1.271s | 11,369 | 11,369 |

Important: `~/.sase/agent_artifact_index.sqlite` exists but its `agent_artifacts` table currently has zero rows. This
matches `sdd/tales/202605/revive_empty_artifact_index.md`.

Rebuilding the artifact index should improve normal Tier 1 reads, but it is not enough by itself. The current index
query treats `has_done_marker = 0` as active, so marker-stripped dismissed directories can still come back in the Tier 1
query even though they are not visible agent rows.

## Safety Analysis

### Safe to remove from loader perspective

Deleting or moving marker-stripped timestamp directories should not prevent a dismissed agent from being revived into a
visible row, as long as the matching dismissed bundle remains. Revive recreates the required marker files and creates
the artifact directory if missing.

This covers the 7,855 markerless directories currently occupying 486M.

### Not fully safe from rich-artifact perspective

Deleting markerless directories can still remove useful auxiliary files:

- `live_reply.md`
- `sase.md`
- `raw_xprompt.md`
- `commit_diff.diff`
- `usage.json`
- generated PDFs/images or other explicit artifacts

If a dismissed bundle's `response_path`, `diff_path`, or `output_path` points into the old artifact directory, those
details may no longer open after pruning. The visible revive flow should still work, but historical run-log/detail
fidelity may be reduced.

### Not safe by default

Do not delete directories that still have loader-visible markers unless the intent is to remove or archive visible
non-dismissed history. These directories are what the full-history source scan uses to show completed rows that are not
currently represented only by dismissed bundles.

Also do not delete `~/.sase/dismissed_bundles/` or `~/.sase/dismissed_agents.json` if revive functionality matters.

## Options

### Option 1: Rebuild the Existing Artifact Index

Command:

```bash
sase agents index rebuild
sase agents index verify
```

Pros:

- No history loss.
- Likely improves normal Tier 1 startup when the daemon/index path is active.
- Supported by current CLI/docs.

Cons:

- Does not reduce disk usage.
- Does not solve full-history scans.
- Current Tier 1 index predicate still returns many marker-stripped directories because `has_done_marker = 0` is treated
  as active.

Recommendation: do this as a low-risk first step, but do not expect it to fully fix the slowdown.

### Option 2: Move Old Markerless Directories to a Quarantine Archive

Example policy:

- Keep all dirs newer than 7-14 days.
- Keep every dir with `done.json`, `workflow_state.json`, or `prompt_step_*.json`.
- Move older markerless dirs out of `~/.sase/projects/*/artifacts/ace-run/` into a compressed dated archive.
- Rebuild or verify the artifact index afterward.

Expected local impact:

- Moving markerless dirs before 2026-05-01 would remove 5,428 scanned dirs and about 204M from the hot tree.
- Moving markerless dirs before 2026-05-08 would remove 6,426 scanned dirs and about 316M from the hot tree.
- Moving all current markerless dirs would remove 7,855 scanned dirs and about 486M from the hot tree.

Pros:

- Directly reduces TUI scan work and disk usage.
- Keeps a rollback path if the directories are archived rather than deleted.
- Should preserve revive-to-visible-row behavior because bundles remain.

Cons:

- Historical detail panels may lose auxiliary files stored only inside the old artifact dirs.
- Needs a careful script that does not touch live/running dirs or marker-visible dirs.
- Should update/delete artifact index rows for moved dirs, or rebuild the index afterward.

Recommendation: best immediate storage reduction if a small loss of rich historical artifact detail is acceptable.
Prefer "move to archive, then delete after a cooling-off period" over immediate deletion.

### Option 3: Product Fix: Ignore Markerless Dirs in Startup/Index Paths

Implement a scanner/index mode for the TUI that skips directories with no loader-visible or live marker:

- Include dirs with `done.json`, `workflow_state.json`, `prompt_step_*.json`, `running.json`, `waiting.json`, or
  `pending_question.json`.
- Exclude dirs that only have `agent_meta.json` and auxiliary outputs.
- Adjust the index active predicate so marker-stripped dirs are not classified as active solely because
  `has_done_marker = 0`.

Pros:

- Preserves on-disk files while removing most TUI scan/query cost.
- Reduces pressure to delete history.
- Correctly models dismissed marker-stripped dirs as archive/detail data, not active rows.

Cons:

- Requires code changes in `../sase-core` and Python loader/query callers.
- Must preserve running/home agents and waiting/question agents.

Recommendation: best long-term fix. This belongs in the Rust core boundary because scanner/index semantics are shared
backend behavior.

### Option 4: Compact Rich Artifact Payloads

For old dismissed markerless dirs, keep only a compact manifest plus selected files, or compress the whole directory.

Potential keep set:

- `agent_meta.json`
- `raw_xprompt.md`
- `live_reply.md` or `sase.md`
- `commit_result.json`
- `usage.json`
- files referenced by bundle `response_path`, `diff_path`, `output_path`, or `extra_files`

Pros:

- Preserves more historical detail than full pruning.
- Can reduce file count and block overhead by archiving many tiny files.

Cons:

- Requires a reference-aware compactor.
- Existing viewers expect plain paths, so compressed artifacts need a restore/open path.

Recommendation: useful later, but not the first move.

## Recommended Plan

1. Rebuild the artifact index now:

   ```bash
   sase agents index rebuild
   sase agents index verify
   ```

2. For immediate disk reduction, archive old markerless dirs rather than deleting them. Start conservatively with
   markerless dirs older than 2026-05-01. That removes about 204M and 5,428 scanned dirs from this project while
   preserving all marker-visible history.

3. After a few days without missing-history issues, consider extending the archive cutoff to 2026-05-08. That would
   remove about 316M and 6,426 scanned dirs from the hot tree.

4. Do not prune `~/.sase/dismissed_bundles/` until SASE has a bundle-retention policy. It is the revive source of
   truth.

5. Add a SASE maintenance command before making this routine:

   ```text
   sase agents artifacts prune-markerless --project sase --before YYYY-MM-DD --archive-to <path> --dry-run
   ```

   Required behavior:

   - Refuse to touch dirs with loader-visible markers.
   - Refuse to touch dirs with `running.json`, `waiting.json`, or `pending_question.json`.
   - Verify a dismissed bundle exists for the raw suffix before archiving, or require `--allow-unbundled`.
   - Write a manifest listing moved dirs, sizes, bundle match status, and referenced paths.
   - Rebuild or update `~/.sase/agent_artifact_index.sqlite`.

6. File a core/backend follow-up to make the TUI/index path ignore markerless dismissed dirs. This is the structural fix
   that avoids forcing users to delete history for TUI responsiveness.

## Bottom Line

The safest high-impact cleanup target is old markerless `ace-run` timestamp directories. They are already dismissed
from the loader's perspective, and revive can recreate the minimal markers from dismissed bundles. The tradeoff is loss
of rich historical sidecar files unless those directories are archived or compacted instead of deleted.

The best immediate operational sequence is:

1. Rebuild the artifact index.
2. Archive, not delete, markerless dirs older than a conservative cutoff.
3. Keep dismissed bundles.
4. Implement a scanner/index fix so markerless dirs stop slowing the TUI even when retained on disk.
