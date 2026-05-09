---
create_time: 2026-05-09 00:17:20
status: done
prompt: sdd/prompts/202605/agent_name_registry_race_1.md
---
# Agent Name Registry Race Plan

## Problem

The failed agent died before writing `agent_meta.json`:

`FileNotFoundError: ~/.sase/agent_name_registry.json.tmp -> ~/.sase/agent_name_registry.json`

That traceback is consistent with concurrent registry rebuilds/writes sharing a single temporary filename. This
workspace already uses `tempfile.mkstemp()` for unique registry temp files, which removes that exact crash mode.
However, the underlying race remains: agent name allocation reads the registry, then the runner writes
`agent_meta.json`, then `claim_agent_name()` updates the registry. Concurrent agents can interleave in that gap and both
choose the same next auto name, or concurrent registry read-modify-write operations can lose each other's claims.

## Root Cause

Agent name state is global (`~/.sase/agent_name_registry.json`), but the critical operations are not consistently
serialized:

- `get_next_auto_name()` only reads reserved names.
- `claim_agent_name()` writes the reservation later.
- `extract_directives_and_write_meta()` currently uses `agent_name_allocation_lock()` only for resume-derived names.
- `_registry.claim_registered_name()` performs load-modify-save without its own interprocess lock.

The existing unique-temp-file write helper makes individual writes safer, but it does not make allocation atomic and
does not prevent lost updates.

## Implementation Plan

1. Keep the unique-temp-file registry writer, since it fixes the `FileNotFoundError` class from the report.
2. Add an explicit registry/allocation lock around registry mutation helpers so concurrent `claim_registered_name()`,
   `delete_registered_name()`, and rebuild/save paths cannot interleave read-modify-write state.
3. Broaden runner-side name critical sections so auto names, planned names, repeat names, resume names, and explicit
   claims are allocated/written/claimed under the same interprocess lock whenever the agent will claim a name.
4. Add focused regression tests:
   - concurrent registry writes do not fail or leave malformed registry JSON;
   - concurrent runner auto-name extraction does not assign duplicate names;
   - explicit name collisions still reject correctly under the lock.
5. Run targeted tests for agent-name registry/allocation and then `just install && just check` because this repo's
   project memory requires `just check` after source changes.

## Risks

The lock should not be held across long-running agent execution. It should cover only directive extraction, metadata
write, and registry claim. This keeps launch contention minimal while making the global name reservation atomic.
