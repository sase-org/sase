---
create_time: 2026-05-10 11:54:25
status: done
prompt: sdd/prompts/202605/time_directive_1.md
---
# Plan: Add `%t` / `%time` Directive For Time-Based Waits

## Goal

Split the overloaded `%wait` directive into two clearer directives:

- `%wait` / `%w` — wait for named agents or workflows to complete successfully.
- `%time` / `%t` — wait for a duration or absolute wall-clock time.

Today `%wait` accepts agent names, durations (`5m`, `1h30m`), and absolute times (`1430`, `260415/0900`)
interchangeably, which is confusing. After this change `%wait` accepts only agent/workflow names; `%time` accepts only
durations and absolute times. This is a hard cutover: `%wait:5m` will raise a `DirectiveError` with a migration hint
rather than being silently accepted.

The runtime layer does not change. `%time` populates the same `wait_duration` / `wait_until` fields on
`PromptDirectives` that time-style `%wait` populated before, so `agent_meta.json`, `waiting.json`, the WAITING UI state,
and `wait_for_dependencies()` all continue to work unchanged.

## What's Already Done

- **Rust core is ahead.** `../sase-core/crates/sase_core/src/editor/directive.rs` already registers `%time` with alias
  `%t`, completion hints (`5m`, `1h`), description, and tests. Phase 4 below is largely verification.
- **`%t` alias was freed up yesterday.** Commit `5ebfc3e6` renamed `%tag` / `%t` → `%group` / `%g`, removing `t -> tag`
  from `_DIRECTIVE_ALIASES`. So `%t` is unowned in Python today and ready to map to `%time`.
- **A prior SDD tale exists** at `sdd/tales/202605/time_directive.md` (status: `wip`). This plan supersedes it.

## Current State (Python)

Directive parsing lives in `src/sase/xprompt/directives.py` with shared types in `src/sase/xprompt/_directive_types.py`.

- `_KNOWN_DIRECTIVES` includes `wait` but not `time`.
- `_MULTI_VALUE_DIRECTIVES = {"wait"}`.
- `_DIRECTIVE_ALIASES`: `w -> wait`, `g -> group`. No `t` mapping.
- `extract_prompt_directives()` (lines 223–263) classifies each `%wait` argument as bare, duration, absolute time, or
  agent name in a single tangled branch.
- `PromptDirectives` already has separate runtime fields: `wait: list[str]`, `wait_duration: float | None`,
  `wait_until: str | None`. **No data-model migration needed.**
- `has_wait_directive(prompt)` at `directives.py:71-79` matches `%wait/%w` and is used both for semantic detection
  (multi-prompt bare-wait chain) and for workspace deferral at the launch boundary.

## Desired Semantics

### `%wait` / `%w`

- Accepts agent/workflow dependency names. Multi-value (colon, comma, paren).
- **Bare `%wait`** keeps current behavior: resolve to the most recently named agent (used heavily in multi-prompt
  segments where it rewrites to the previous agent).
- A duration or absolute-time argument raises `DirectiveError` with a direct migration hint:
  `"%wait:5m is a time wait; use %time:5m instead"`.

### `%time` / `%t`

- Accepts duration arguments (`%time:5m`, `%t:1h30m`, `%time:90s`) and absolute-time arguments (`%time:1430`,
  `%time:260415/0900`). Multi-value (colon, comma, paren).
- Multiple durations take the maximum (preserving today's `%wait` duration behavior).
- Multiple absolute times → error.
- Duration + absolute time within `%time` → error.
- Combines freely with `%wait:<agent>`. Dependencies wait first, then time floor applies (existing
  `wait_for_dependencies()` behavior).
- **Bare `%time` is invalid:** `"Bare '%time' requires a duration or absolute time argument"`.
- A non-time `%time` argument is invalid:
  `"Invalid %time value 'review'; %time accepts only durations (e.g. 5m) and absolute times (e.g. 1430). Use %wait:review to wait for an agent."`
  (The hint nudges users who may have written `%t:review` thinking of the old tag alias toward `%group:review` for
  groups or `%wait:review` for agents — pick whichever phrasing is clearest in code.)
- `%time` does **not** participate in the multi-prompt bare-wait previous-agent rewrite (only `%wait` does).

## Implementation Plan

### Phase 1 — Directive registration

`src/sase/xprompt/_directive_types.py`:

- Add `"time"` to `_KNOWN_DIRECTIVES`.
- Add `"time"` to `_MULTI_VALUE_DIRECTIVES`.
- Add `"t": "time"` to `_DIRECTIVE_ALIASES`.
- `PromptDirectives` dataclass is unchanged — `%time` reuses `wait_duration` and `wait_until`.

### Phase 2 — Split parsing in `extract_prompt_directives()`

`src/sase/xprompt/directives.py`:

- The current wait disambiguation block (lines 223–263) becomes two narrower branches.
- **`%wait` branch:** for each value, if bare → resolve to most-recent agent name; if `parse_duration()` matches → raise
  migration error; if `parse_absolute_time()` matches → raise migration error; otherwise → treat as agent name. Build
  `directives.wait` only from this branch.
- **`%time` branch:** for each value, if bare → error; if `parse_duration()` matches → fold into `wait_duration` (max of
  all); if `parse_absolute_time()` matches → set `wait_until` (error if already set, error if combined with a duration);
  otherwise → raise the helpful "use `%wait:` for agents" error.
- Reuse `parse_duration` and `parse_absolute_time` from `_directive_time.py` unchanged.
- Consider extracting a small helper (e.g. `_classify_time_arg(value) -> Duration | AbsoluteTime | None`) so both
  branches share classification logic and tests can target it directly.

### Phase 3 — Preserve workspace deferral

`src/sase/xprompt/directives.py`:

- Keep `has_wait_directive(prompt)` semantically scoped to `%wait/%w` only (its caller in `multi_prompt_references.py`
  depends on this — bare `%time` is invalid and must not enter the prev-agent chain).
- Add a new helper `has_deferred_start_directive(prompt)` that matches `%wait/%w` **or** `%time/%t`. Pattern:
  `r"(?:^|\s)%(?:wait|w|time|t)(?:[:+(]|\s|$)"`.

Update workspace-deferral call sites to use the new helper:

- `src/sase/agent/launch_cwd.py:312-326`
- `src/sase/agent/multi_prompt_launcher.py:188`
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py:183`

**Do not change** `src/sase/agent/multi_prompt_references.py:74-100` (`has_bare_wait_directive`) — bare-wait prev-agent
rewriting stays scoped to `%wait`.

### Phase 4 — Rust core verification

`../sase-core/crates/sase_core/src/`:

- `editor/directive.rs` — confirm `%time` metadata, `t -> time` alias, completion hints, and tests are present (they
  are). No changes expected.
- Search `agent_launch/` and any wait/deferred-start helpers for places that recognize `%wait/%w` for workspace
  deferral; if any do not also recognize `%time/%t`, add coverage. If the Rust side already handles this generically via
  the directive metadata, no change is needed.
- Run targeted Rust tests in `../sase-core` only if files there are modified.

### Phase 5 — Completion metadata and docs

`src/sase/ace/tui/widgets/directive_completion.py`:

- Add `%time`: hint `:duration or :HHMM`, description e.g. `defer launch until a duration or wall-clock time`.
- Update `%wait`: hint `:agent`, description e.g. `defer launch until agents complete` (drop time wording).

`docs/xprompt.md` (lines ~861–1163):

- Split the `%wait` row in the supported-directives table; add a `%time` row.
- Move duration / absolute-time examples and prose under `%time`.
- Keep agent-dependency examples under `%wait`, including bare-wait prev-agent semantics.
- Sweep the file for any remaining user-facing `%t:` examples — they predated the rename and should now be `%group:`
  (for tag/group examples) or `%time:` (for the few that meant time). Verify each in context.
- Quick grep across `docs/`, `sdd/`, and any user-facing prompt templates for `%t:` and `%tag:` to catch leftovers.

### Phase 6 — Tests (land alongside each phase)

`tests/test_directives_types.py` (primary):

- `%time:5m`, `%time:1h30m`, `%time:90s`, `%t:5m` set `wait_duration`.
- Multiple durations take max (`%time:5m %time:10m` → 600.0).
- `%time:0000`, `%time:260415/0900` set `wait_until`.
- `%time` + `%wait:agent` coexist (dep + time floor).
- Bare `%time` errors.
- `%time:agent_name` errors with the `%wait:` migration hint.
- Duration + absolute time within `%time` errors.
- Multiple absolute times error.
- `%wait:5m`, `%wait:1430`, `%wait:260415/0900` error with migration hint.
- `%wait:agent` and bare `%wait` still work.
- `%group:review` works (regression); `%t:review` errors helpfully (used to be a tag alias).

`tests/test_directives_extract.py`: integration / coexistence cases.

`tests/test_directives_has_helpers.py`:

- `has_wait_directive()` detects only `%wait/%w` (negative case for `%time/%t`).
- `has_deferred_start_directive()` detects both.

`tests/ace/tui/widgets/test_directive_completion.py`:

- `%t` completes to `%time`.
- `%wait` description no longer mentions time.
- `%group` still listed (regression).

`tests/test_directives_time_parsing.py`: untouched — `parse_duration` / `parse_absolute_time` are unchanged.

Launch tests touched by the new helper: confirm a `%time:5m`-only prompt defers workspace allocation the same way
`%wait:5m` did before.

### Phase 7 — Verification

```bash
uv run pytest \
  tests/test_directives_types.py \
  tests/test_directives_extract.py \
  tests/test_directives_has_helpers.py \
  tests/ace/tui/widgets/test_directive_completion.py
```

Then targeted launch tests around the touched helper. If `../sase-core` was modified, run its tests from that repo.

Finally:

```bash
just install   # workspace may be stale
just check
```

before declaring done.

## Risks And Decisions

- **Hard cutover, not deprecation.** `%wait:5m` raising an error rather than warning is intentional — silent acceptance
  during a transition would defeat the clarity goal. The migration hint in the error message makes the fix one
  keystroke.
- **`has_wait_directive` stays scoped to `%wait/%w`.** Splitting the concept (semantic wait vs. deferred-start) is what
  prevents `%time` from accidentally entering bare prev-agent chain rewrites.
- **No persisted-data migration.** Runtime storage stays `wait_duration` / `wait_until`, so `agent_meta.json`,
  `waiting.json`, and `ready.json` formats don't change.
- **Scope discipline.** Don't broaden into a `%group` follow-up cleanup; that rename already shipped. This task only
  takes ownership of `%t` for `%time`.
- **Rust/Python alignment.** Rust is ahead; Python catches up. After this lands, both runtimes will agree on `%time/%t`
  and `%wait/%w` semantics.
