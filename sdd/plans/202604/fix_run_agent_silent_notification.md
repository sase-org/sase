---
create_time: 2026-04-25 23:54:11
status: done
prompt: sdd/prompts/202604/fix_run_agent_silent_notification.md
---
# Fix: Run-agent notifications fire for hidden / auto-dismissed agents

## Problem

User received a Telegram completion message at 23:40 for `ace(run)-260425_232621`:

> ✅ CLAUDE(opus) Complete CLAUDE(opus) completed: ace(run)-260425_232621 Prompt:
> `#gh:sase #sase/pylimit_split %approve`

…even though no commits landed in master from this workflow run. The workflow is `pylimit_split` (a periodic
infrastructure xprompt that finds oversized Python files and asks a sub-agent to split each one). The two iterations did
work but neither produced a commit:

- `mentor_profile_matching.py` — sub-agent hit a workspace-sync conflict and asked the user how to proceed (no commit).
- `tests/test_directives_helpers.py` — sub-agent reported success but never invoked the commit skill.

Net result: zero changes against master, but a Telegram notification fired anyway.

The user has fixed neighboring symptoms several times before:

- 035a0e38 — suppress premature "mentors done" notification on Draft→Ready
- 7a52c83a — suppress notifications when only hidden/skipped steps ran
- a3adf066 — pass `project=` to `execute_workflow` so noop suppression actually fires
- d44540e9 — add `silent` flag to `notify_workflow_complete`; route fix_hook / mentor / summarize_hook through it

This specific code path slipped through every prior pass.

## Root cause

`pylimit_split` is launched periodically by the `run_every` lumberjack. Confirmed in
`~/.sase/axe/lumberjacks/run_every/status.json`:

```
"chops": ["sase_pylimit_split", "sase_fix_just", "sase_refresh_docs"]
```

Lumberjack chops set `SASE_AGENT_AUTO_DISMISS=1` so the spawned agent auto-dismisses on completion (doesn't pile up on
the Agents tab). In `src/sase/axe/run_agent_phases.py:89`:

```python
auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")
...
if directives.hide or auto_dismiss:
    agent_meta["hidden"] = True
```

So `~/.sase/projects/sase/artifacts/ace-run/20260425232621/agent_meta.json` correctly records `"hidden": true`, and
`run_agent_runner.py:534` auto-dismisses the agent at the end. The agent IS marked hidden end-to-end.

But the notification gate at `src/sase/axe/run_agent_runner.py:570` only checks:

```python
if not was_killed() and not all_steps_hidden(current_artifacts_dir):
    ...
    notify_workflow_complete(
        sender="user-agent",
        cl_name=cl_name,
        success=success,
        notes=notes,
        action=action,
        action_data=action_data,
        extra_files=extra_files,
        # ← no `silent=` argument
    )
```

It never inspects `agent_hidden`. Compare the sibling runners that already do the right thing:

- `src/sase/axe/fix_hook_runner.py:380` → `silent=True`
- `src/sase/axe/mentor_runner.py:238` → `silent=True`
- `src/sase/axe/summarize_hook_runner.py:281` → `silent=True`

Those three hard-code `silent=True` because they only ever run background work. `run_agent_runner.py` is different — it
serves both interactive `sase run` invocations (must notify) AND lumberjack chops / `%hidden` agents (must not notify),
so it can't hard-code; it has to forward `silent=agent_hidden`.

Note: `all_steps_hidden(current_artifacts_dir)` returned False here because no `workflow_state.json` was written into
the artifacts dir — that's a separate ambient bug worth a follow-up, but irrelevant to this fix. Even with
`all_steps_hidden` working correctly, a hidden `for:`-loop workflow that DOES launch visible sub-agent steps would still
notify under the current gate; only the explicit `agent_hidden` check guarantees silent delivery in all cases.

## Fix

Single-line change in `src/sase/axe/run_agent_runner.py` at the `notify_workflow_complete` call (currently around line
626):

```python
notify_workflow_complete(
    sender="user-agent",
    cl_name=cl_name,
    success=success,
    notes=notes,
    action=action,
    action_data=action_data,
    extra_files=extra_files,
    silent=agent_hidden,   # NEW
)
```

`agent_hidden` is already in scope (set at line 291 from `info.hidden = bool(directives.hide or auto_dismiss)`).

`silent=True` semantics (from d44540e9): the notification is still appended to the JSONL audit log and remains visible
in the in-TUI notification panel, but is excluded from the unread count, the bell/toast, and Telegram delivery — exactly
what we want for hidden agents.

### Decision: silence successes AND failures, or only successes?

Two reasonable variants:

1. **`silent=agent_hidden`** (proposed): hidden agents are silent on both success and failure. Matches the existing
   fix_hook / mentor / summarize_hook runners, which pass `silent=True` unconditionally. Failures are still recorded in
   the audit log + TUI notification panel + `error_report.md` — the user can see them when they open the panel, but no
   Telegram ping.
2. `silent=agent_hidden and success`: hidden agents are silent on success but DO ping Telegram on failure. Useful if the
   user wants real-time alerts for broken infrastructure runs.

Going with variant 1 for consistency with sibling runners; if the user wants variant 2 they can flip a single
`and success` in afterwards.

## Test

Add a focused test for the notification gate in `tests/test_run_agent_runner_notifications.py` (or extend the nearest
existing notification test if there is one — search first):

- Patch `notify_workflow_complete` and exercise the success path of `run_agent_runner`'s finalize block twice:
  - With `agent_hidden=True` → assert `silent=True` is forwarded.
  - With `agent_hidden=False` → assert `silent=False` (default) is forwarded.

If the existing structure of `run_agent_runner.py` makes calling that block in isolation heavy, an acceptable
lighter-weight alternative is to extract the `notify_workflow_complete` invocation into a thin helper (e.g.
`_send_completion_notification(...)`) that takes `agent_hidden` as a parameter, and unit test the helper directly.
Prefer the direct test if feasible; only refactor if the direct test is impractical.

## Manual validation

1. Wait for the next `run_every` cycle to fire `sase_pylimit_split` (or trigger manually via
   `SASE_AGENT_AUTO_DISMISS=1 sase run '#gh:sase #sase/pylimit_split %approve'`).
2. Confirm: no Telegram notification, no bell/toast, no unread badge bump.
3. Confirm: notification IS still appended to `~/.sase/notifications/*.jsonl` and is visible in the TUI notification
   panel (unread count unchanged, but entry present).
4. Run a normal user-initiated `sase run '<plain prompt>'` and confirm the Telegram notification still fires.

## Files

- `src/sase/axe/run_agent_runner.py` — one-line addition: `silent=agent_hidden,`.
- `tests/test_run_agent_runner_notifications.py` (new, or extension of nearest existing file) — verify silent forwarding
  by `agent_hidden` value.
- (Optional, only if the direct test is impractical) extract a tiny helper to make the notification invocation
  unit-testable.

## Out of scope

- **Why `workflow_state.json` is missing from `ace-run/20260425232621/`**: separate ambient bug. The artifacts dir has
  the per-step prompt + diff files but no `workflow_state.json`. Worth a follow-up so `all_steps_hidden` can do its job
  for visible agents too.
- **Why `pylimit_split` sub-agents don't commit despite `%approve`**: the workflow invokes `#sase/pysplit:{file}`, and
  `%approve` only auto-approves plans/questions, not commits. Whether to teach the sub-agent to invoke the commit skill
  is a workflow-design question, not a notification bug.
- **Should silent hidden-agent FAILURES still ping Telegram?** Documented as variant 2 above; not adopted in this
  change.
