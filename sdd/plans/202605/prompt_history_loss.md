---
create_time: 2026-05-01 13:45:59
status: done
prompt: sdd/prompts/202605/prompt_history_loss.md
---
# Plan: Fix prompt history data loss

## Diagnosis

The `.` prompt-history modal is showing only about 20 entries because the backing store, `~/.sase/prompt_history.json`,
currently contains only 22 entries. They are all from May 1, 2026 after `13:06`, so this is not a modal
rendering/filtering issue. The history file itself was overwritten with a much smaller data set.

The likely root cause is the prompt-history writer in `src/sase/history/prompt.py`. `add_or_update_prompt()` performs a
read-modify-write cycle against one shared JSON file:

1. `_load_prompt_history()` reads the entire JSON file.
2. `add_or_update_prompt()` mutates the in-memory list.
3. `_save_prompt_history()` opens the real history file with `"w"` and rewrites it in place.

That sequence has two data-loss risks:

- There is no cross-process lock around the read-modify-write cycle. Multiple TUI/CLI/agent-launch processes can load
  stale copies and overwrite each other.
- The save is not atomic. While one process has truncated the file and is writing JSON, another process can read a
  partial file, hit `json.JSONDecodeError`, and `_load_prompt_history()` silently returns `[]`. The second process can
  then save only its new prompt, wiping the previous history.

Recent changes increased the chance of concurrent prompt-history writes:

- Multi-prompt launches save the combined prompt and then recursively save individual segments.
- TUI launch, cancel-save, CLI launch, and agent launch entry points all call the same writer.
- Recent fan-out / multi-agent workflows can launch several agents close together.

## Implementation

1. Make prompt-history persistence atomic.
   - Write JSON to a temporary file in the same directory.
   - Replace the real file with `os.replace()` only after the JSON write succeeds.
   - Use a per-process-unique temp file name so concurrent writers do not clobber each other's temp files.

2. Add a file lock for prompt-history mutations.
   - Introduce a lock file beside `prompt_history.json`, for example `prompt_history.json.lock`.
   - Hold an exclusive `fcntl.flock()` lock across the complete load, dedup/update, and save sequence.
   - Keep display reads lock-free or optionally shared-locked. The critical fix is that writers cannot interleave
     read-modify-write cycles.

3. Make corrupt/partial reads safer.
   - Under the writer lock, a JSON decode failure should not be treated as an empty history and then saved over the
     store.
   - Preserve the current forgiving behavior for display reads if needed, but avoid destructive writes after a failed
     load.

4. Reduce write amplification from multi-prompts.
   - Prefer building all entries for a combined multi-prompt and its segments in one locked mutation, rather than
     recursively loading and saving once per segment.
   - Preserve existing behavior: exact-text dedup, `last_used` bumping, cancelled-to-non-cancelled upgrade, no downgrade
     from non-cancelled to cancelled, and short-prompt skipping.

5. Add regression tests.
   - Verify `_save_prompt_history()` writes atomically using replacement semantics.
   - Verify `add_or_update_prompt()` does not overwrite existing history when the file is temporarily
     unreadable/corrupt.
   - Verify multi-prompt segment saving still produces the same entries, but through one mutation path.
   - Add a concurrency-oriented test that simulates two writers or a transient JSON decode failure and proves existing
     entries are preserved.

6. Verification.
   - Run `just install` if the workspace is stale.
   - Run the targeted prompt-history tests.
   - Run `just check` before finishing because this repo requires it after code changes.

## Data Recovery

The current code fix can prevent future loss but cannot reconstruct entries that are already absent from
`~/.sase/prompt_history.json`. I checked for obvious `prompt_history` backup files under `~/.sase` and did not find one.
After the fix, possible recovery options are outside the direct code path: reconstruct from chat/agent artifacts, shell
backups, filesystem snapshots, or any external backup if available.
