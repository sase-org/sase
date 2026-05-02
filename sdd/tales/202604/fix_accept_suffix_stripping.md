---
create_time: 2026-04-14 21:30:21
status: done
prompt: sdd/prompts/202604/fix_accept_suffix_stripping.md
---

# Fix: Strip NEW/BROKEN PROPOSAL suffix when accepting proposals

## Problem

When a proposal is accepted via the accept workflow, the `(!: NEW PROPOSAL)` or `(~!: BROKEN PROPOSAL)` suffix should be
stripped from the commit entry note. Currently, only the `(!: ...)` variant is stripped — the `(~!: ...)` variant is
left in place, resulting in accepted entries like:

```
(3) Add new feature - (~!: BROKEN PROPOSAL)
```

instead of the expected:

```
(3) Add new feature
```

## Root Cause

In `src/sase/workflows/accept/renumber.py:439-440`, the stripping regex is:

```python
r" - \([!~]: [^)]+\)$"
```

The character class `[!~]` matches a **single** character — either `!` or `~`. This handles `(!: NEW PROPOSAL)` (where
`[!~]` matches `!`) but fails on `(~!: BROKEN PROPOSAL)` because `[!~]` matches `~`, then expects `:` but encounters `!`
instead.

The `~!:` prefix is the "rejected_proposal" marker (see `_PREFIX_MAP` in `suffix_utils.py`), used by:

- `reject_all_new_proposals()` → `(~!: NEW PROPOSAL)`
- `mark_proposal_broken()` → `(~!: BROKEN PROPOSAL)`

Both scenarios are reachable before acceptance: a rejected proposal can be re-accepted, and a broken proposal can be
accepted after fixing the underlying issue.

## Plan

### Phase 1: Fix the regex

**File:** `src/sase/workflows/accept/renumber.py:439-440`

Change:

```python
r" - \([!~]: [^)]+\)$"
```

to:

```python
r" - \(~?!: [^)]+\)$"
```

This makes the `~` optional before `!:`, correctly matching both `(!: ...)` and `(~!: ...)`.

### Phase 2: Add test coverage

**File:** `tests/workflows/test_renumber_entries.py`

Add two tests:

1. **Accepting a rejected proposal** (`(~!: NEW PROPOSAL)`) — verify the suffix is stripped from the resulting regular
   entry.
2. **Accepting a broken proposal** (`(~!: BROKEN PROPOSAL)`) — verify the suffix is stripped from the resulting regular
   entry.
