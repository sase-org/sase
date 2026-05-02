---
create_time: 2026-04-27 09:10:59
status: done
prompt: sdd/prompts/202604/auto_name_reserves_dotted_prefix.md
---
# Plan: Auto-name Reserves Dotted Prefix (`<base>.*`)

## Problem

`get_next_auto_name()` hands out the next free single-letter (then double-letter, etc.) name from the sequence
`a, b, ..., z, aa, ab, ...`. It scans active agents to build the "used" set in `_get_active_agent_names()`
(`src/sase/agent/names.py:425`), but the only dotted-name pattern that reserves a base letter is `<letter>.<digits>`
(the `_AUTO_CHILD_NAME_RE` regex on line 30). All other dotted suffixes — `.plan`, `.code`, `.epic`, `.q`, `.claude`,
`.gemini`, `.codex`, `.claude-opus`, `.claude-sonnet`, `.claude.plan`, etc. — do **not** reserve their prefix.

Concrete repro (matching the user's `sase ace` snapshot):

- Agent A: `name="m.plan"`, `workflow_name="m"` → `m` is reserved (via `workflow_name`).
- Agent B: `name="m.claude.plan"`, `workflow_name="m.claude"` → only `m.claude` is reserved.

If A is later dismissed but B remains, the next `get_next_auto_name()` call returns `m`. The user then sees a fresh
agent named `m`, which visually collides with `m.claude.plan` on the Agents tab and becomes ambiguous when typing `@m`
in prompts.

The bug also fires while both A and B are alive if A had been spawned with a `parent_timestamp` (currently
parent-tracked agents are skipped when computing reservations) or whenever a multi-model fan-out exists with no
plain-base sibling.

## Goal

When picking the next auto-assigned name, treat any active agent whose name matches `<base>` **or** `<base>.<anything>`
as occupying the slot `<base>` — provided `<base>` is itself a valid auto-name (`[a-z]+`, the same shape that
`_name_sequence()` produces).

In other words: after this fix, if any active agent has a name starting with `m.` (or just `m`), the next auto-name will
skip `m`.

## Non-goals

- Do **not** reserve user-chosen multi-segment bases like `sase-z` for the auto-name pool — those bases can't be
  returned by `_name_sequence()` anyway, so a hypothetical reservation would be a no-op. Keeping the regex anchored to
  `[a-z]+` matches existing behavior of `_AUTO_CHILD_NAME_RE` and the comment at `names.py:25-29`.
- Do **not** change the meaning of `workflow_name` or `parent_timestamp`. Those fields stay exactly as they are; we only
  widen which strings additionally feed the "used" set.
- Do **not** change `find_named_agent`, `resolve_agent_changespec`, or repeat-batch reservation logic
  (`_get_active_child_names`, `reserve_repeat_name_base`). Those are separate concerns.
- Do **not** rename or restructure existing agents. This only affects what name a _new_ agent gets.

## Approach

### Single-point change in `_get_active_agent_names()`

Replace the narrow `_AUTO_CHILD_NAME_RE = r"^([a-z]+)\.\d+$"` extraction with a broader prefix extraction that captures
the base before the first `.` whenever the base is purely lowercase letters. The new regex is essentially `^([a-z]+)\.`
(anchored at the start, requiring at least one dot to follow — bare `m` is already handled by the existing
`names.add(name)` line).

The extraction needs to run against **both** the `name` field and the `workflow_name` field, because:

- `name="m.plan"` → prefix `m`. (Today: not extracted — `m` happens to be reserved via `workflow_name="m"`, but that
  coincidence is not guaranteed for all suffix paths.)
- `name="m.claude.plan"`, `workflow_name="m.claude"` → prefix `m` from either field. (Today: only `m.claude` is
  reserved; `m` leaks.)
- `name="a.1"`, `workflow_name="a"` → prefix `a`. (Today: the existing child-base path already handles this; the new
  logic must remain compatible.)

The `parent_timestamp` skip should be re-examined: today it returns early so child agents do not reserve any names. We
need child-of-multi-model-plan agents (e.g. coder spawned from `m.claude.plan` with `name="m.claude.code"` and
`parent_timestamp` set) to still contribute the prefix `m`. The cleanest way is to compute the prefix _before_ the
`parent_timestamp` early-return and add it to `names` regardless — then keep the early-return for everything else (so
the full name `m.claude.code` is still not added on its own).

Pseudocode for the modified inner loop:

```python
prefix = _extract_auto_name_prefix(name_field, data.get("workflow_name"))
if prefix:
    names.add(prefix)

if data.get("parent_timestamp"):
    continue

# ...existing logic adding `name` (and child_base for the legacy `<letter>.<digits>` case)...
```

Where `_extract_auto_name_prefix(name, workflow_name)` returns the longest `[a-z]+` segment that appears as the
prefix-before-first-dot in either field, or `None` if neither qualifies.

### Optional cleanup

`_AUTO_CHILD_NAME_RE` becomes redundant once the broader prefix extraction is in place — every `<letter>.<digits>`
name's prefix is already captured by `^([a-z]+)\.`. Keep the constant only if it is referenced elsewhere (verify with a
grep); otherwise inline-remove and update the explanatory comment block at `names.py:25-30`.

### Edge cases to nail down in tests

1. `m.plan` alone → `m` is reserved.
2. `m.claude.plan` alone → `m` is reserved (this is the headline bug).
3. `m.claude.plan` with `parent_timestamp` set (coder/plan child) → `m` still reserved even though the agent is
   otherwise skipped.
4. `sase-z.2` (multi-segment user base) → `m`/auto-pool unaffected; `sase-z` still reserved via existing `workflow_name`
   path; no spurious entries added to the `[a-z]+` pool.
5. Bare `m` (no dot, no suffix) → `m` reserved (already handled today; regression-guard).
6. Dismissed `m.claude.plan` → `m` is **not** reserved (dismissal already removes the artifact dir).
7. Orphaned/dead `m.claude.plan` (no `done.json`, dead PID) → `m` is **not** reserved (the existing `is_process_alive`
   gate must still apply to the prefix add — i.e. the prefix-add lives inside the same conditional branches as today's
   `names.add(name)`).

(7) is important: the prefix add must only happen when the agent itself counts as active. So the prefix-extraction goes
at the top of the per-agent block, but the actual `names.add(prefix)` call must be guarded by the same liveness check
that guards `names.add(name)` today. The early-return on `parent_timestamp` is the one exception — for parent-tracked
children we still want the prefix reserved (case 3), because the parent is by definition alive (otherwise the parent
would have been dismissed and this artifact dir gone with it). The simplest implementation: compute `prefix` once, then
add it inside both the `done.json` branch and the `is_process_alive` branch (mirroring how `child_base` is added today),
and additionally add it inside the `parent_timestamp` early-return.

## Test plan

Extend `tests/test_agent_names.py` (`TestGetNextAutoName`) with cases that fixture artifact directories whose
`agent_meta.json` exercises the seven scenarios above. Each test asserts the return value of `get_next_auto_name()` (or
`_get_active_agent_names()` directly for the "is `m` in the set?" assertions, which are easier to read).

Reuse the existing helpers in that file for laying down fake artifact dirs; no new fixtures should be needed. Run
`just check` afterward.

## Files touched (expected)

- `src/sase/agent/names.py` — modify `_get_active_agent_names()`, possibly remove `_AUTO_CHILD_NAME_RE` and update the
  comment block.
- `tests/test_agent_names.py` — add ~5–7 new test cases under `TestGetNextAutoName`.

No production callers of `_AUTO_CHILD_NAME_RE` outside `names.py` are expected; verify with a grep before deletion.

## Risk / blast radius

Low. The change strictly grows the "used" set, which means:

- New auto-named agents may skip a letter they would have previously claimed. Worst case: the user sees `n` instead of
  `m` for one launch — clearly desirable.
- No existing agent is renamed; `find_named_agent`, `@name` resolution, and repeat-batch logic are untouched.
- The `parent_timestamp` early-return is preserved for everything except the new prefix add, so child-coder agents
  continue to not reserve their full names.

The only subtle risk is over-reservation: e.g. if a user explicitly named an agent `m.notes` and later wants `m` for a
separate workspace, they cannot auto-get it until `m.notes` is dismissed. This matches the user's stated goal (treat
`m.*` as occupying `m`), so it is intended behavior, not a regression. Users who want `m` specifically can still pass
`%name:m` explicitly — that path goes through `reserve_repeat_name_base` / explicit collision checks, not the auto-name
pool.
