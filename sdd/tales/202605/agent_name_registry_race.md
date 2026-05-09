---
create_time: 2026-05-08 22:02:25
status: done
prompt: sdd/prompts/202605/agent_name_registry_race.md
---
# Plan: Fix concurrent agent-name registry writes

## Problem

The failed agent died while auto-allocating its name:

`get_next_auto_name()` -> `get_reserved_agent_names()` -> `load_name_registry()` -> `rebuild_name_registry()` ->
`_write_registry()` -> `os.replace(tmp_path, path)`.

The exception says the source temp file did not exist:

`/home/bryan/.sase/agent_name_registry.json.tmp` -> `/home/bryan/.sase/agent_name_registry.json`

The registry writer currently uses one deterministic temp path for every writer:

`path.with_suffix(f"{path.suffix}.tmp")`

During parallel agent launch, multiple runner processes can rebuild or save the registry at the same time. If process A
and process B both write `agent_name_registry.json.tmp`, whichever process calls `os.replace()` first moves that shared
temp file to the final registry path. The other process can then reach `os.replace()` after the shared temp path has
already been moved, producing exactly the `FileNotFoundError` shown in the `sase ace` snapshot.

## Approach

1. Replace the fixed temp path in `src/sase/agent/names/_registry.py` with a unique temp file created in the same
   directory as the final registry.
2. Keep the existing atomic-write property by continuing to use `os.replace(temp, final)` after a complete JSON write.
3. Clean up the unique temp file on exceptional paths so failed partial writes do not accumulate.
4. Add a focused regression test in `tests/test_agent_name_registry.py` that simulates the previous shared-temp race:
   open/write the first temp file, perform a nested registry write before the outer `os.replace()`, and assert both
   writes can complete without `FileNotFoundError`.
5. Run the targeted registry/name tests first, then run `just install` and `just check` per repo memory after code
   changes.

## Expected Outcome

Concurrent agent startups can still race logically over which registry snapshot wins, but each writer owns its own temp
file, so one writer can no longer delete another writer's replace source. The agent runner should no longer fail during
name allocation with a missing `agent_name_registry.json.tmp`.
