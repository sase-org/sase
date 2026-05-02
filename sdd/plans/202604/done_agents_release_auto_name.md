---
create_time: 2026-04-27 10:23:40
status: draft
prompt: sdd/prompts/202604/done_agents_release_auto_name.md
---

# Plan: Done Agents Should Not Block Alphabetic Auto-Names

## Problem

`get_next_auto_name()` (`src/sase/agent/names.py:430`) hands out names by walking the alphabetic sequence
`a, b, ..., z, aa, ab, ...` and skipping names already in use, where "in use" is computed by `_get_active_agent_names()`
at `src/sase/agent/names.py:441`. That function reserves a name slot for any agent whose `agent_meta.json` is found on
disk and is not in the dismissed set — **including done-but-not-dismissed agents** (lines 510-517):

```python
# Done agents still hold their name until dismissed
# (dismissal deletes the artifact directory).
done_path = artifact_dir / "done.json"
if done_path.exists():
    names.add(name)
    if prefix is not None:
        names.add(prefix)
    continue
```

The TUI's Agents tab, however, shows agents through a different filter — `compute_apply_loaded_agents()` in
`src/sase/ace/tui/actions/agents/_loading_compute.py:98`. With the default `hide_non_run_agents=True`
(`src/sase/ace/tui/app.py:123`), it hides every non-RUNNING agent that isn't on a hard-coded "always-visible" list. So
done agents are simultaneously **invisible** on the Agents tab and **reserving** their auto-name slot.

### Concrete repro

A user with one running agent `@aw` launched two new multi-model agents (via `%m`) and they were named `@bb.codex` and
`@bb.claude` instead of the expected `@a.codex` / `@a.claude`. Inspecting the artifact tree shows:

- 19 done agents in `~/.sase/projects/sase/artifacts/ace-run/*` carry `name="a"` or `workflow_name="a"`.
- None of them are in `~/.sase/dismissed_agents.json`.
- Running `_get_active_agent_names()` returns 59 reserved names — every letter `a` through `ba` plus `bb`-`bd`.
- Next available was `bb` (then `bc`, `bd` for the multi-model siblings, leaving `be` as the next free letter).

The user only ever sees `@aw` on the tab because every other reserved name belongs to a hidden done agent.

### Why the existing reservation rationale doesn't fit done agents

The comment at `names.py:490-495` explains why `<base>.<anything>` reserves the bare `<base>` slot:

> A fresh `m` agent next to `m.claude.plan` would visually collide on the Agents tab and become ambiguous when typing
> `@m` in prompts.

That reasoning applies to **running** agents and live follow-up workflows. For done agents that are hidden by default,
there is no visual collision and `@m` already disambiguates: `find_named_agent()` (`src/sase/agent/names.py:112-208`)
prefers running over done and most-recent timestamp among done. Multiple done agents with the same name already coexist
routinely — the user has 19 done `a`s right now, and the system handles `@a` lookups against them without issue.

## Goal

Make auto-name reservation consistent with what's visible on the Agents tab: **done agents should not block alphabetic
auto-name slots.** Running agents and live (parent-tracked, process-alive) follow-ups continue to reserve their slot.

## Non-goals

- Don't change the dismissed-agent or artifact-cleanup story.
- Don't change `find_named_agent()` resolution semantics — `@a` continues to resolve to running > most-recent done.
- Don't change `claim_agent_name()` (which already preserves done-agent name fields for `#resume` and historical lookup,
  line 336-339).
- Don't touch reservations of _non-alphabetic_ bases (e.g. `sase-z` from manual workflows). Those are out of the
  alphabetic auto-name pool already.

## Approach

Drop the done-branch of `_get_active_agent_names()`. Concretely, in `src/sase/agent/names.py:441`:

1. Remove the lines that add `name` (and `prefix`) to the reserved set when `done.json` exists. A done agent contributes
   nothing to the reserved set.
2. Keep the existing handling for parent-tracked / process-alive agents unchanged. Those branches are what reserve slots
   for running multi-model fan-outs and live workflow children — they still need to block.
3. Update the function docstring to state the new contract: "names of currently-running (or live follow-up) agents are
   reserved; dismissed and done agents do not block reuse."

The change is a deletion plus a docstring touch-up — no new fields, no schema changes, no migrations.

### Why this is safe

- `find_named_agent()` already handles the multi-done-agent case: prefers running, then most recent done by timestamp
  (`names.py:194-206`). A new running `a` will shadow any done `a` for `@a` resolution, and once that new `a` finishes,
  the most-recent-timestamp tie-breaker keeps it the canonical `@a`.
- `claim_agent_name()` already deliberately leaves done agents' name fields intact (`names.py:336-339`) so historical
  `#resume <oldtimestamp>` and similar lookups by artifact dir / done.json still work.
- Multiple done agents sharing a name is already the de-facto state in the user's tree (19 done `a`s) and is not
  triggering bugs elsewhere.
- `_get_active_child_names()` (lines 604+, used by `sase-z.<N>` repeat-batch collision detection) does its own artifact
  scan and is not affected.
- Workflow-level `appears_as_agent` workflows whose names are non-alphabetic (e.g. `sase-z`) are reserved by the manual
  workflow-name path, which is independent of the auto-name pool. The alphabetic auto-namer never returns `sase-z`
  anyway.

## Test plan

Existing tests in `tests/test_agent_names.py` (class `TestGetNextAutoName`, starts at line 234) are the source of truth.
Several existing tests assert the old behavior and will need to be updated:

| Test                                                           | Current assertion                    | New assertion                        |
| -------------------------------------------------------------- | ------------------------------------ | ------------------------------------ |
| `test_done_agent_holds_name` (line 245)                        | done `a` + running `b` → next is `c` | done `a` + running `b` → next is `a` |
| `test_workflow_without_appears_as_agent_holds_name` (line 283) | done workflow `a` → next is `b`      | next is `a`                          |
| `test_workflow_with_appears_as_agent_holds_name` (line 289)    | done `a` → next is `b`               | next is `a`                          |
| `test_mixed_workflow_and_agent_names` (line 295)               | both done → next is `c`              | next is `a`                          |

These tests should be **renamed and inverted** — the new names should reflect "done agents release their slot."
`test_reuses_dismissed_agent_name` (line 252) still passes as-is because it deletes the artifact dir, and the
"reuses_name_of_dead_process" / "reuses_name_when_no_pid" tests already exercise the running-but-dead branch and remain
unchanged.

New tests to add:

1. `test_done_multi_model_releases_base_name`: Stage done `a.codex` and `a.claude` artifacts (with workflow_name=`a`)
   plus a running `aw`. Assert next name is `a` (the regression scenario from the user report).
2. `test_running_follow_up_still_reserves`: A running parent-tracked child `a.plan` (with `parent_timestamp` set, PID
   alive) must still reserve `a`. This protects the rationale at `names.py:490-495`.
3. `test_running_workflow_still_reserves`: A running `m.claude.plan` workflow with `workflow_name="m.claude"` and a live
   PID still reserves both `m.claude` and `m`. This is essentially the existing
   `test_multi_segment_dotted_suffix_reserves_prefix` (line 321) — confirm it still passes unchanged.

## Files touched

- `src/sase/agent/names.py` — delete the done-branch in `_get_active_agent_names()`, update docstring.
- `tests/test_agent_names.py` — update 4 existing tests, add 2-3 new tests.

No other files should need changes. CLI, TUI, xprompt directives, and `find_named_agent` callers are all behind stable
contracts that don't depend on the done-reservation behavior.

## Migration / rollout

None needed. The change is a behavior loosening — names that used to be unavailable become available. Anyone with
done-but-not-dismissed agents (the user's situation) immediately gets back access to the lower alphabetic slots on the
next auto-name pick. No on-disk format change.

## Risks

- **Visual collision when the user toggles `hide_non_run_agents=False`**: with the filter off, both a fresh running `a`
  and several historical done `a`s will appear on the Agents tab. This is already true today for any name a user has
  manually re-used, and is the exact same situation as having multiple dismissed-but-revived agents. Acceptable.
- **`@a` ambiguity inside in-flight prompts written before the new `a` started**: `find_named_agent()` returns the
  running `a`, which is the user's intent in nearly all cases. If a user genuinely wanted to reference an old done `a`,
  they were already in trouble (the old behavior would have prevented reuse for at most one new `a`, but not for the
  second, third, etc. — there are 19 done `a`s already). Acceptable.

## Out of scope (future work)

- An eventual auto-cleanup of long-dead done-but-not-dismissed artifact dirs. The Agents tab's
  `auto_dismissed_identities` mechanism already handles axe-spawned hidden agents (`_loading_compute.py:162-168`);
  extending it to old multi-model children would address the underlying disk-bloat issue but is a separate concern.
