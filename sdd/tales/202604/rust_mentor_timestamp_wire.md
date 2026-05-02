---
create_time: 2026-04-29 12:14:06
status: done
prompt: sdd/prompts/202604/rust_mentor_timestamp_wire.md
---
# Fix Rust Backend Query Crash On Mentor Status Lines

## Problem

Running `SASE_CORE_BACKEND=rust sase ace` crashes during ACE startup while filtering ChangeSpecs:

```
ValueError: specs[1955] is not a valid ChangeSpecWire dict: invalid type: null, expected a string
```

The failing record is `sase_fix_no_mentors__260403_213426` in `~/.sase/projects/sase/sase-archive.gp`. It contains a
`MENTORS` status line in the running-line format:

```
| complete:<mentor> - RUNNING - (@: mentor_complete-...)
```

Python intentionally omits the timestamp prefix when formatting RUNNING mentor status lines, and the Python parser
therefore rehydrates those lines with `MentorStatusLine.timestamp == None`. The current wire model still declares mentor
status timestamps as required strings on both sides of the Python/Rust boundary, so the PyO3 `evaluate_query_many`
binding rejects otherwise valid Python wire records before Rust query evaluation starts.

## Plan

1. Treat missing mentor timestamps as part of the wire contract.
   - Update Python `MentorStatusLine` and `MentorStatusLineWire` annotations from `str` to `str | None`.
   - Keep formatting behavior unchanged: RUNNING mentor lines without a timestamp remain valid and display without a
     timestamp prefix.

2. Update the Rust `sase-core` wire model to match.
   - Change `MentorStatusLineWire.timestamp` to `Option<String>`.
   - Update the Rust project parser to emit `None` for mentor status lines that omit the optional timestamp instead of
     the current empty string placeholder.
   - Adjust Rust tests/fixtures so null mentor timestamps are explicitly covered.

3. Add Python regression coverage.
   - Add a test that builds or parses a ChangeSpec with a RUNNING mentor status line lacking a timestamp and verifies
     the JSON wire payload contains `timestamp: None`.
   - Add or extend a facade test with a fake Rust `evaluate_query_many` implementation that validates the batch path can
     forward such records without Python-side coercion.

4. Verify the fix in both repos.
   - Run the focused Python tests for wire/facade behavior.
   - Run the focused Rust tests in `../sase-core`.
   - Rebuild/install the Rust extension into the uv-tool venv and rerun a non-interactive reproduction of
     `evaluate_query_many('"only"', find_all_changespecs())`.
   - Because this repo changed, run `just check` before reporting back.

## Expected Outcome

The Rust backend accepts the same ChangeSpec wire records the Python backend already accepts. `SASE_CORE_BACKEND=rust`
no longer crashes on archived RUNNING mentor lines without timestamps, and the fix is covered at the Python/Rust wire
boundary rather than patched only in the ACE UI.
