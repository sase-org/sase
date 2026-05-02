---
create_time: 2026-04-27 12:14:03
status: done
prompt: sdd/prompts/202604/auto_agent_name_reuse.md
---
# Fix Auto Agent Name Reuse

## Problem

Auto-assigned agent names should use the lowest available alphabetic name (`a`, `b`, ..., `z`, `aa`, ...). In the
provided `sase ace` snapshot, only three agents are running, yet new agents are being assigned names around `bn`, `bo`,
and `bp` instead of reusing `a`. That means the allocator believes earlier alphabetic slots are still active.

## Diagnosis

The auto-name allocator lives in `src/sase/agent/names.py`. `get_next_auto_name()` delegates to
`_get_active_agent_names()`, which scans `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` and returns the names
that should block reuse.

The root cause is ordering inside `_get_active_agent_names()`:

1. It extracts a dotted auto-name prefix from `name` / `workflow_name`.
2. If the artifact has `parent_timestamp`, it immediately reserves that prefix and continues.
3. Only after that does it check `done.json`.
4. Only after that does it verify process liveness.

That means completed parent-tracked children such as `a.2`, `d.code`, `bm.epic`, `bn.gemini`, or `bn.claude` continue
reserving their base name even after they have `done.json`. The current artifact tree confirms this: many
`parent_timestamp` artifacts with `done.json` are still being counted as active prefix reservations.

This contradicts the documented behavior in the same function: done agents should release their slot, and stale/dead
agents without `done.json` should not block reuse.

## Desired Behavior

An auto-name slot should be reserved only by an artifact that is both:

- not dismissed,
- not done,
- and backed by a live process.

For parent-tracked children, the full child name should still not independently reserve the pool, but a live
parent-tracked child should reserve its dotted auto-name prefix so a fresh bare `a` cannot collide visually or
semantically with a running `a.code` / `a.2` / `a.codex.plan` workflow.

## Implementation Plan

1. Update `_get_active_agent_names()` so `done.json` is checked before the `parent_timestamp` prefix reservation.
2. For parent-tracked artifacts without `done.json`, require `is_process_alive(data, artifact_dir)` before reserving the
   prefix.
3. Keep existing behavior for root/live artifacts:
   - root live `name="a"` reserves `a`;
   - root live `name="m.plan"` reserves `m.plan` and `m`;
   - workflow child/root metadata with `workflow_name` continues reserving the base workflow name while live.
4. Add regression tests covering:
   - a done parent-tracked child releases its prefix;
   - a dead parent-tracked child without `done.json` releases its prefix;
   - a live parent-tracked child still reserves its prefix.
5. Run focused tests for `sase.agent.names` and related repeat-name behavior.
6. Because this repo requires it after file changes, run `just install` if needed and then `just check` before final
   response.

## Risk

The main compatibility risk is changing parent-tracked child semantics. The fix keeps live children reserved and only
releases done/dead children, which matches the existing stated allocator contract and the user-visible expectation that
completed agents do not consume the auto-name pool forever.
