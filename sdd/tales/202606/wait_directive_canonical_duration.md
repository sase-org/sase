---
create_time: 2026-06-25 08:00:25
status: done
prompt: sdd/prompts/202606/wait_directive_canonical_duration.md
---
# Fix: `%wait:<name>` rejects duration-shaped agent names (e.g. `%w:05s`)

## Problem / Product Context

Using `%w:05s` (or `%wait:05s`) in an agent prompt fails with:

```
DirectiveError: %wait:05s is a time wait; use %wait(time=05s) or #t:05s instead
```

This is wrong. `05s` is a **valid agent name**, and the user intended to wait for the agent named `05s`. The positional
`%wait:<arg>` form is supposed to mean "wait for the agent named `<arg>`"; the keyword form `%wait(time=...)` (and
`#t:`) is the syntax for timed/wall-clock waits.

This is not a contrived edge case. The auto-name sequence is `0, 1, …, 9, a, …, z, 00, 01, …, 05, …` (base-36).
Digit-leading names such as `05s`, `5m`, `1h`, `30s` are routinely generated as agents accumulate (the durable registry
keeps every allocated slot reserved, so the sequence advances into 2- and 3-character names over time). So agents
legitimately end up with duration-shaped names, and waiting on them via `%w:<name>` currently errors out.

### Reproduction (confirmed)

```
parse_duration("05s")            -> 5.0          # matches the duration regex
extract_prompt_directives("%w:05s\nDo work")     -> DirectiveError (the bug)
extract_prompt_directives("%w:`05s`\nDo work")   -> DirectiveError (backtick doesn't help)
```

## Root Cause

`src/sase/xprompt/directives.py`, the positional `%wait:` migration guard (≈ lines 413-442). For every positional
`%wait` argument it asks "does this look like a time?" and, if so, raises a migration hint:

```python
if parse_duration(raw_arg) is not None:
    raise DirectiveError(
        f"%wait:{raw_arg} is a time wait; use "
        f"%wait(time={raw_arg}) or #t:{raw_arg} instead"
    )
if parse_absolute_time(raw_arg) is not None:
    raise DirectiveError(... same hint ...)
resolved_wait.append(raw_arg)   # otherwise treat as an agent name
```

This guard was added when time waits moved from positional `%wait:5m` to the `%wait(time=5m)` keyword form (commits
`9c6eb6722`, `86322d43b`). Its purpose is to catch the _legacy_ `%wait:5m` syntax and point the user at the new form.

The duration matcher is too loose for this disambiguation. In `src/sase/xprompt/_directive_time.py`:

```python
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
```

`\d+` accepts leading zeros, so `05s` matches and `parse_duration("05s")` returns `5.0`. The guard therefore
misclassifies the agent name `05s` as a legacy time wait.

The key insight: **a canonical duration never has a leading zero** in a numeric component — the canonical form of "5
seconds" is `5s`, never `05s`. A leading zero is a strong, purely syntactic signal that the argument is an agent name,
not a duration the user typed on purpose.

## Scope Decision (where the fix belongs)

`parse_duration` / `parse_absolute_time` are also used in **time-only** contexts where there is no agent-name ambiguity
and leading-zero leniency is harmless or even desirable:

- `src/sase/xprompt/directives.py` — the `%wait(time=...)` keyword branch (≈ line 454).
- `src/sase/ace/tui/modals/wait_modal.py` — the wait modal's **time** field.
- `src/sase/ace/tui/modals/snooze_duration_modal.py` — snooze duration input.

In all of those, the value is _known_ to be a time, so `05s == 5s` and rejecting `05s` would be a pointless regression.
Therefore the fix must live in the **`%wait:` positional guard**, not in the shared `parse_duration`. We keep
`parse_duration` lenient and add a stricter _canonical-duration_ predicate used only for the agent-name-vs-time
disambiguation.

Confirmed out of scope:

- **Rust core**: this directive/duration parsing is Python-only. `../sase-core` has no `%wait`/duration parsing, so no
  cross-repo mirroring is required.
- **`parse_absolute_time`** (HHMM / `yymmdd/HHMM`): leading zeros are _canonical_ for clock times (`0930`), so this side
  is left unchanged. `05s` does not match an absolute time anyway, so the reported bug is unaffected by it.

## Proposed Fix (primary, targeted)

1. **Add a canonical-duration predicate** in `src/sase/xprompt/_directive_time.py`, e.g.:

   ```python
   def is_canonical_duration(s: str) -> bool:
       """True only for canonical durations (no leading-zero components)."""
   ```

   Semantics (verified against a prototype):
   - Reuses the existing duration match, then rejects any numeric component whose length is > 1 and starts with `0`.
   - `True`: `5s`, `5m`, `30s`, `10s`, `1h30m`, `1h30m15s`, `0s`, `0h0m0s`
   - `False`: `05s`, `00s`, `1h05m`, `007`, `abc`, `""`
   - `parse_duration` itself is **unchanged** (time-only callers keep their leniency).

2. **Use it in the `%wait:` guard** in `src/sase/xprompt/directives.py`: replace the duration check
   `if parse_duration(raw_arg) is not None:` with `if is_canonical_duration(raw_arg):`. Leave the `parse_absolute_time`
   check as-is. Update the import on line 39 (and the `__all__`/re-export block if tests import it from
   `sase.xprompt.directives`).

### Resulting behavior

| Input              | Before            | After                         |
| ------------------ | ----------------- | ----------------------------- |
| `%w:05s`           | error (time wait) | **wait for agent `05s`** ✅   |
| `%w:00s`, `%w:007` | error / name      | wait for agent (name)         |
| `%w:5m`, `%w:30s`  | error (migration) | error (migration) — unchanged |
| `%w:1430`          | error (migration) | error (migration) — unchanged |
| `%wait(time=05s)`  | 5s duration       | 5s duration — unchanged       |
| `%wait(time=5m)`   | 5m duration       | 5m duration — unchanged       |

The fix is backward compatible: every existing test (legacy `%wait:5m` / `%wait:1430` migration errors, `time=` keyword
parsing, `parse_duration` unit tests) keeps passing.

## Known Residual Limitation (call out; recommend separate follow-up)

A _canonical_ duration-shaped name — `5m`, `30s`, `1h`, etc. — remains genuinely ambiguous: it is both a valid auto-name
and a canonical duration. After this fix those still resolve to the legacy-time-wait migration hint, so `%w:5m` for an
agent literally named `5m` still cannot be expressed positionally. The same latent issue affects internal launchers that
_prepend_ `%wait:<prevname>` for auto-named predecessors (`src/sase/agent/repeat_launcher.py`,
`src/sase/agent/multi_prompt_launcher.py`): if a predecessor's auto-name is canonical-duration-shaped, the generated
`%wait:5m` would also hit the guard.

This is a deliberately _narrower_ problem than the reported bug and is **out of scope** here. Recommended follow-up
options (to be tracked separately, user's choice):

- **Registry-aware guard** (most complete): only emit the migration hint when no known/reserved agent has that exact
  name; otherwise treat it as an agent wait. Fixes the `5m` case and the launcher case, at the cost of coupling the
  parser to registry state (precedent already exists — bare `%wait` calls `get_most_recent_agent_name`).
- **Backtick-literal escape hatch**: make
  `%w:`5m``bypass the guard. Requires per-arg literal tracking for multi-value directives (today`literal_directives` is
  keyed by directive name only).
- **Auto-namer avoidance**: skip canonical-duration-shaped tokens when generating auto-names (touches the Rust-core
  token generator — heavier, crosses the backend boundary).

I recommend shipping the primary fix now and opening a separate bead for the canonical-duration collision if the user
wants it addressed.

## Files to Change

- `src/sase/xprompt/_directive_time.py` — add `is_canonical_duration`; leave `parse_duration` / `parse_absolute_time`
  untouched.
- `src/sase/xprompt/directives.py` — use `is_canonical_duration` in the `%wait:` guard; update import / re-export.

## Tests

- `tests/test_directives_time_parsing.py` — unit tests for `is_canonical_duration` (`05s`/`00s`/`1h05m` → False;
  `5s`/`5m`/`1h30m`/`0s`/`0h0m0s` → True). Existing `parse_duration` tests stay green (parser unchanged).
- `tests/test_directives_wait.py` and `tests/test_directives_name_wait.py`:
  - **New**: `%w:05s` → `wait == ["05s"]`; also `%w:00s`, `%w:007` resolve to names.
  - **New (lock-in)**: `%wait(time=05s)` still yields `wait_duration == 5.0` (confirms the time-only path keeps its
    leniency).
  - **Keep**: `%wait:5m` and `%wait:1430` still raise with the migration hint.

## Verification

- `just install` (ephemeral workspace) then `just check` (lint + mypy + tests) — required by repo policy for source
  changes.
- Manual repro: `%w:05s` resolves to a wait on agent `05s`; `%wait:5m` still shows the migration hint.
- Doc/help sweep: grep user-facing help (e.g. `binding_common.py`, any `%wait` docs) to confirm none claim
  duration-shaped positional args are time waits; the help already describes `%wait:` as "complete visible agent names",
  so no help-text change is expected — verify and adjust only if needed.

## Non-Goals

- No change to `parse_duration` / `parse_absolute_time` semantics for time-only callers.
- No change to absolute-time (HHMM / dated) handling.
- No Rust-core changes.
- The canonical-duration-shaped-name collision (`5m`, `30s`, …) and the launcher interaction are documented but deferred
  to a separate follow-up.
