---
create_time: 2026-05-01 14:20:27
status: proposed
prompt: sdd/prompts/202605/prompt_history_restore.md
---

# Plan: Restore prompt history and verify data-loss fix

## Diagnosis

The prompt-history picker triggered by `.` is showing only a few entries because the backing store,
`~/.sase/prompt_history.json`, currently contains only 11 prompt records. The modal path is loading the file correctly;
the data itself has been truncated.

Backup snapshots show the loss clearly:

- `/mnt/hercules/backup/home/daily/bryan/.sase/prompt_history.json` has 4,451 entries as of May 1, 2026 00:13.
- `/mnt/hercules/backup/home/hourly-4/bryan/.sase/prompt_history.json` has only 19 entries as of May 1, 2026 09:08.
- The live file has 11 entries as of May 1, 2026 14:15.

The root cause is the old prompt-history writer in `src/sase/history/prompt.py`: it loaded the full JSON file, mutated
an in-memory list, then opened the real file with `"w"` and rewrote it without a cross-process lock or atomic replace.
If two prompt writes overlapped, one process could read a partially written JSON file, interpret it as empty history,
and then save only its new prompt. Recent multi-agent, cancelled-prompt, and background launch paths increased write
frequency enough to make that race visible.

The current checkout already contains commit `c301913e` (`fix: harden prompt history writes`), which adds a lock, atomic
replacement, writer-side load failure protection, and batched multi-prompt mutations. The installed `sase` tool is also
resolving `sase.history.prompt` from the main repo with those fixed symbols present, so the remaining work is data
recovery and verification rather than another rewrite of the storage code.

## Implementation

1. Preserve the live damaged file before recovery.
   - Copy `~/.sase/prompt_history.json` to a timestamped backup beside it.
   - Do not delete the lock file or any existing backup snapshots.

2. Build a merged recovery set from backups plus live data.
   - Use the large daily backup as the baseline.
   - Include all relevant May 1 hourly snapshots and the live file so prompts created after the daily backup are kept.
   - Deduplicate by exact prompt text, matching current `add_or_update_prompt()` semantics.
   - Preserve the earliest `timestamp` and original metadata for each prompt.
   - Set `last_used` to the maximum observed value.
   - Preserve the non-cancelled upgrade rule: if any copy of a prompt is non-cancelled, recover it as non-cancelled.

3. Atomically replace the live history file with the merged result.
   - Write to a temp file in `~/.sase`.
   - `fsync` and `os.replace()` it into place.
   - Leave JSON pretty-printed to match the existing store format.

4. Verify recovery.
   - Parse the restored live file and report total count, cancelled count, top workspaces, and newest entries.
   - Call `get_prompts_for_fzf()` through the repo venv to confirm the picker backend sees thousands of entries.
   - Run the prompt-history regression tests that cover atomic writes, corrupt-read safety, concurrency, and
     multi-prompt behavior.

5. Final safety check.
   - If any prompt-history source files are changed during this task, run `just install` and `just check`.
   - If recovery only changes the user data file and this plan file, run targeted tests and report that no product code
     needed additional edits beyond the already-present hardening commit.
