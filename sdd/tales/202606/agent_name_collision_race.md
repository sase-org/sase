---
create_time: 2026-06-02 23:37:11
status: done
prompt: sdd/prompts/202606/agent_name_collision_race.md
---
# Fix Explicit Agent Name Collision Race

## Context

`just test` reported a flaky failure in
`tests/test_agent_names_extract.py::test_concurrent_explicit_extract_rejects_collision` where both concurrent
`%name:dupe` extraction calls succeeded. Focused reruns of that test and adjacent agent-name tests pass, so this is a
race rather than a stable assertion mismatch.

The relevant flow is:

- `extract_directives_and_write_meta()` parses `%name:dupe`.
- It enters `agent_name_allocation_lock()` for name allocation, claim, and metadata write.
- `claim_agent_name(..., explicit=True)` checks existing artifact payloads, then calls `claim_registered_name()`.
- `claim_registered_name()` loads the durable name registry, rejects another owner if present, and writes the new owner.
- `agent_meta.json` is written only after the claim succeeds.

The intended invariant is that explicit user names are permanent unique names: one concurrent claimant may publish
`dupe`; the other must fail with a `NameCollisionError` suggesting `dupe1`.

## Root Cause Hypothesis

The implementation splits explicit collision protection across two sources of truth: a direct artifact scan in
`_claim.py` and the durable registry in `_registry.py`. The direct scan cannot observe an in-flight owner before
`agent_meta.json` exists, and registry rebuild/cache paths can produce a fresh view from the artifact tree. In the rare
interleaving seen by the suite, the second explicit claimant can miss the first reservation and then publish the same
explicit name.

The fix should make the durable registry claim the single atomic authority for explicit name ownership. Artifact
scanning remains useful for registry rebuilds and stale-index recovery, but an explicit launch should not rely on a
pre-publication artifact scan to enforce uniqueness.

## Plan

1. Tighten the registry claim path.
   - Keep `claim_registered_name()` under `agent_name_allocation_lock()`.
   - Ensure it always works from an isolated copy of the current `entries` mapping before mutation, so failed or
     concurrent paths cannot observe or mutate the cached registry object in place.
   - Preserve the current same-owner idempotency behavior and `replace_existing` semantics.

2. Simplify explicit claim enforcement.
   - In `claim_agent_name()`, remove the separate pre-claim artifact scan for normal explicit claims.
   - Let `claim_registered_name(..., replace_existing=False)` be the collision gate for explicit names.
   - Keep forced reuse behavior unchanged.

3. Add deterministic regression coverage.
   - Extend registry tests with a stale-or-missing registry scenario where two explicit claims target the same name
     before any metadata write is available.
   - Assert exactly one succeeds and the failing error suggests the lowest free suffix (`dupe1`).
   - Keep the existing extraction-level concurrency test as the end-to-end guard.

4. Verify.
   - Run the focused failing test.
   - Run focused agent-name registry/extraction tests.
   - Because product files will change, run `just check` before finishing, per the project instructions.
