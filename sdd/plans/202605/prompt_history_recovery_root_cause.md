---
create_time: 2026-05-01 14:48:17
status: proposed
prompt: sdd/prompts/202605/prompt_history_recovery_root_cause.md
---

# Plan: Prompt History Root Cause Verification and Full Recovery

## Current Findings

The prompt history loss is real and is in the backing data file, not only the picker UI:

- Live `~/.sase/prompt_history.json` is valid JSON but has only about 20 records, all from May 1, 2026 after the loss
  window.
- `/mnt/hercules/backup/home/daily/bryan/.sase/prompt_history.json` has 4,451 records as of May 1, 2026 00:13.
- Later May 1 hourly snapshots are already damaged:
  - `hourly-4`: 21 records at May 1, 2026 10:10.
  - `hourly-3`: 9 records at May 1, 2026 11:09.
  - `hourly-2`: 12 records at May 1, 2026 13:18.
  - `hourly`: 13 records at May 1, 2026 14:18.
- A dry merge of live history plus all backup prompt-history snapshots yields 4,506 unique prompt texts, including 59
  entries with May 1 timestamps at or after the daily backup point.

The prior diagnosis in `plans/202605/prompt_history_loss.md` is consistent with the observed damage. The old writer in
`src/sase/history/prompt.py` loaded the full JSON file, mutated it, and rewrote the real file in place with no
cross-process lock. A concurrent writer could see a partially written JSON file, interpret the decode failure as empty
history, and then save a tiny file. Recent multi-prompt and background launch paths increased the chance of overlapping
writes.

The current checkout and the installed `sase` uv tool both resolve `sase.history.prompt` to code that contains the
expected hardening from commit `c301913e`:

- Exclusive `fcntl.flock()` around writer read/modify/write cycles.
- Atomic temp-file write followed by `os.replace()`.
- Writer-side load failures return without overwriting the store.
- Multi-prompt combined and segment entries are applied in one mutation path.

So the likely remaining task is recovery plus verification that no secondary root cause remains.

## Implementation Plan

1. Verify the original fix under the actual installed runtime.
   - Confirm the uv-tool `sase` import path points at the same fixed `src/sase/history/prompt.py`.
   - Run targeted prompt-history tests covering atomic replacement, load-failure safety, concurrent writers,
     multi-prompt batching, cancelled prompt semantics, and short-prompt filtering.
   - Add or adjust tests only if this verification exposes a missing scenario.

2. Preserve the current damaged live file before restoration.
   - Copy `~/.sase/prompt_history.json` to a timestamped backup beside it.
   - Leave `/mnt/hercules/backup` untouched.
   - Do not remove `prompt_history.json.lock`.

3. Restore from a deterministic merge of all available sources.
   - Input sources: live `~/.sase/prompt_history.json` plus every
     `/mnt/hercules/backup/home/*/bryan/.sase/prompt_history.json` that parses.
   - Filter to entries with the required fields: `text`, `branch_or_workspace`, `timestamp`, `last_used`, and
     `workspace`.
   - Deduplicate by exact `text`, matching current prompt-history behavior.
   - Preserve the earliest `timestamp` and associated original metadata for a prompt.
   - Set `last_used` to the maximum observed value across duplicates.
   - Preserve non-cancelled upgrade semantics: a restored prompt is cancelled only if every observed copy is cancelled.
   - Sort the output stably by `last_used` and then `timestamp` for inspectability; UI sorting still happens at read
     time.

4. Atomically replace the live history file.
   - Write pretty JSON to a temp file in `~/.sase`.
   - `flush`, `fsync`, and `os.replace()` into `~/.sase/prompt_history.json`.
   - Validate the file with `json.tool` immediately after replacement.

5. Verify the restored behavior end to end.
   - Report final total entries, cancelled entries, max `last_used`, and top workspaces.
   - Load the restored file through `sase.history.prompt.get_prompts_for_fzf()` using the repo venv to confirm the
     picker backend sees thousands of entries.
   - Exercise one non-destructive `add_or_update_prompt()` write against a temp copied file, not the live file, to prove
     the fixed writer preserves the restored record count under normal mutation.

6. Final checks.
   - If product code changes are needed, run `just install` and then `just check` before finishing.
   - If only the user data file and this plan artifact are changed, run the targeted prompt-history tests and report
     that no additional product-code change was necessary beyond the already-present hardening commit.

## Rollback

If restoration output looks wrong, replace `~/.sase/prompt_history.json` with the timestamped live backup created in
step 2. The original external backups remain read-only inputs and are not modified.
