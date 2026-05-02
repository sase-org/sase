---
create_time: 2026-04-25 17:40:52
status: done
prompt: sdd/prompts/202604/agent_name_in_completion_toast.md
---
# Plan: Include the agent's name in agent completion toasts

## Problem

When an agent run finishes, the toast / notification message looks like:

    CLAUDE(opus) completed: ace(run)-260425_161716
    CLAUDE(opus) failed:    ace(run)-260425_161716

Even though the AXE detail panel shows a `Name:` field (e.g. `@sase-q.land`), the toast itself does not — so a user
glancing at a stack of toasts can identify the model and the workflow timestamp, but not _which named agent_ just
finished. With multiple concurrent agents in the Agents tab, this is a real ergonomic gap.

## Goal

Surface the agent's name in the completion toast when one is set, e.g.:

    CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716
    CLAUDE(opus) @sase-q.land failed:    ace(run)-260425_161716

Anonymous agents (no `agent_name` — auto-named hidden runs, edge cases, etc.) keep the current format unchanged so we
don't render a stray space or `@` separator.

## Relevant code

- `src/sase/axe/run_agent_runner.py:284-292` — `agent_name = info.name` is already populated locally from
  `extract_directives_and_write_meta()`.
- `src/sase/axe/run_agent_runner.py:582-589` — single site where the `notes[0]` toast text is constructed:

  ```python
  agent_label = format_provider_model_label(agent_llm_provider, agent_model)
  notes = [
      f"{agent_label} {'completed' if success else 'failed'}: {workflow_name}"
  ]
  ```

- `src/sase/axe/run_agent_runner.py:610-619` — `agent_name` is _already_ propagated through `action_data` for both the
  `JumpToAgent` and `ViewErrorReport` paths. No plumbing change needed.
- `src/sase/ace/tui/actions/agents/_toasts.py:51-102` — toast formatter. The `JumpToAgent` and `ViewErrorReport`
  branches return `notes[0]` verbatim, so changing the sender automatically updates the toast surface.
- Naming convention (verified across `_toasts.py`, `revive_agent_modal.py`, `agent_tag_modal.py`,
  `_agent_display_parts.py`): `agent_name` is stored bare (e.g. `sase-q.land`) and `@` is prepended at display time.
- Tests: `tests/test_notification_toasts.py` exercises `_format_notification_toast` and `format_batch_toasts`. There is
  **no current assertion** on the exact `"completed:"` / `"failed:"` string, so existing tests should not break.

## Approach

Modify the **sender** (`run_agent_runner.py`) — the note text is the canonical persisted message and is reused
everywhere the notification surfaces (toasts, persisted notification feed, action handlers). Doing it at the sender is
one line and keeps a single source of truth; the formatter for `JumpToAgent`/`ViewErrorReport` continues to fall through
to `notes[0]` and inherits the new format for free.

Placement: insert the name between the model label and the verb, so the sentence reads `<who> completed: <what>`. This
matches how the existing `PlanApproval` and `UserQuestion` toasts read (`"Plan ready for @<name>: …"`).

## Phases

### Phase 1: Update the toast text in the sender

**File:** `src/sase/axe/run_agent_runner.py`

Replace the `notes` construction (lines 587-589) with:

```python
name_part = f" @{agent_name}" if agent_name else ""
notes = [
    f"{agent_label}{name_part} {'completed' if success else 'failed'}: {workflow_name}"
]
```

No other changes in this file. `action_data["agent_name"]` continues to be set for downstream consumers.

### Phase 2: Tests

**File:** `tests/test_notification_toasts.py`

Add two assertions on `_format_notification_toast` for the `JumpToAgent` action — these pin the new format end-to-end
because that branch returns `notes[0]` verbatim:

1. With `agent_name` set: a `Notification` whose `notes[0]` is
   `"CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716"` produces the same string as the toast.
2. Without `agent_name`: a `Notification` whose `notes[0]` is `"CLAUDE(opus) completed: ace(run)-260425_161716"`
   produces the same string (legacy shape preserved).

Pre-flight: grep tests for `"completed:"` and `"{agent_label}"` to confirm no existing assertion needs updating
(expected: none, based on prior search).

### Phase 3: Verification

1. `just check`.
2. Manual sanity check: spawn a named agent (`%name foo` directive) and an anonymous agent, confirm the toast text in
   each case via `sase ace`.

## Tradeoffs / open questions

- **Placement of `@name`**: chose `"<label> @name completed: <workflow>"` (between label and verb). Alternative is
  trailing: `"<label> completed: <workflow> (@name)"`. Recommending the leading placement; flag for review.
- **Formatter-side fallback for old notifications**: We could also have `_toasts.py` synthesize the `@name` prefix from
  `action_data["agent_name"]` if missing from `notes[0]`, which would retroactively format previously-persisted
  notifications. Not doing this — straightforward to add later if desired.
- **Hidden agents**: `agent_hidden` is also available at the call site. Not gating on it: a hidden agent with a name is
  still useful to identify in the toast, and the `if agent_name else ""` guard already covers truly anonymous runs.

## Out of scope

- The `Name:` field in the AXE detail panel and other UI surfaces (already shown there).
- Format of `workflow_name` (`ace(run)-{timestamp}`).
- Backfilling already-persisted notification notes.
