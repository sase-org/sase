---
create_time: 2026-05-04 13:12:52
status: done
prompt: sdd/prompts/202605/epic_directive.md
---
# Plan: `%epic` Directive and Epic Auto-Approval

## Goal

Add a `%epic` prompt directive that causes a later `/sase_plan` submission from that agent to be auto-approved as an
epic. This should enter the existing epic approval path, not a parallel implementation: the result should be equivalent
to the user pressing the TUI Epic action or the Telegram Epic button.

Also extend the `a` key on the `sase ace` Agents tab so a user can mark a running/planning agent for epic auto-approval
even when the original prompt did not include `%epic`.

## Current Flow

Plans are submitted by `sase plan <file>`, which archives the file and writes `.sase_plan_pending` under the agent
artifacts directory. `handle_plan_marker()` then calls `handle_plan_approval()`.

Manual TUI/Telegram approval writes `plan_response.json` with an action such as `"approve"` or `"epic"`. The existing
`PlanApprovalResult(action="epic", ...)` path already writes SDD epic files, commits those SDD files, initializes beads,
and launches the `#bd/new_epic` follow-up agent.

The current auto-approve mechanism is boolean. `%approve` writes `approve: true` to `agent_meta.json`, and
`handle_plan_approval()` maps that to `PlanApprovalResult(action="approve", ...)`. That is not expressive enough for an
epic action.

## Design

Introduce an explicit plan auto-approval action in agent metadata, for example:

```json
{
  "auto_approve_plan_action": "epic"
}
```

Accepted values should initially be `"approve"` and `"epic"`; the implementation can tolerate unknown values by falling
back to no action or normal approve behavior. Keep the existing `approve: true` boolean for backwards compatibility and
for full auto-approval semantics such as automatic question answering.

Add a helper in `sase.main.plan_approve_handler`, such as `get_auto_plan_approval_action()`, that returns:

- `"epic"` when `auto_approve_plan_action` in `agent_meta.json` or an env override requests epic.
- `"approve"` when legacy `SASE_AGENT_AUTO_APPROVE` or `agent_meta["approve"]` is active.
- `None` otherwise.

Update `handle_plan_approval()` to use this helper. If the helper returns `"epic"`, return
`PlanApprovalResult(action="epic", plan_file=plan_file)` immediately, without sending notifications or polling. This
reuses the existing `handle_plan_marker()` epic branch.

When `handle_plan_marker()` accepts any non-feedback plan result, persist the same markers the TUI persists today:
`plan_approved: true` and `plan_action: "approve" | "epic" | "legend" | "commit"`. This makes auto-approved plans
survive TUI reloads with the same status presentation as externally approved plans.

## `%epic` Directive

Extend directive parsing:

- Add `epic` to the known directive list.
- Add `epic: bool = False` to `PromptDirectives`.
- Treat `%epic` as a boolean directive with no short alias, since `%e` is already `%edit`.
- Strip `%epic` from prompts like other directives and reject duplicates like other single-value boolean directives.

In `extract_directives_and_write_meta()`:

- If `directives.epic` is true, write `auto_approve_plan_action: "epic"` to `agent_meta.json`.
- Also write `plan: true` so the Agents tab shows the agent as `PLANNING` while it works on a plan, matching `%plan`
  status behavior.
- Do not make `%epic` imply `approve: true`; epic auto-approval should be plan-specific and should not silently
  auto-answer unrelated user questions.

The directive only affects the approval action when a plan is submitted. It does not need a separate epic execution
path.

## Agents Tab `a` Key

Keep the existing `a` key binding and extend its state model from a boolean toggle to a small plan-auto-action cycle for
eligible agents:

1. Off -> auto-approve normal plan (`approve: true`, no explicit epic action).
2. Auto-approve normal plan -> auto-approve epic (`approve: false`, `auto_approve_plan_action: "epic"`).
3. Auto-approve epic -> off (remove both `approve` and `auto_approve_plan_action`).

Update the in-memory `Agent` model with `auto_approve_plan_action: str | None` and derive `agent.approve` from either
legacy `approve` or the explicit action where existing display code expects a boolean indicator. Update row rendering,
footer labels, and toasts so users can tell whether the next `a` press will enable normal approval, switch to epic, or
disable auto approval.

Persist the new field in the same non-blocking worker path used by `persist_approve_field()`, preserving unrelated
metadata and rolling back optimistic UI state on write failure.

## Files To Change

- `src/sase/xprompt/_directive_types.py`
- `src/sase/xprompt/directives.py`
- `src/sase/axe/run_agent_phases.py`
- `src/sase/main/plan_approve_handler.py`
- `src/sase/llm_provider/_plan_utils.py`
- `src/sase/axe/run_agent_exec_plan.py`
- `src/sase/ace/tui/models/agent.py`
- `src/sase/core/agent_scan_wire.py` and scan/wire conversion as needed
- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`
- `src/sase/ace/tui/actions/agents/_approve.py`
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py` and prompt/detail display helpers if they show approval state
- `docs/xprompt.md`

No default keymap change is expected because the existing `accept_proposal: "a"` binding remains the integration point.

## Tests

Add focused tests for:

- `%epic` parsing, stripping, duplicate rejection, and no `%e` alias conflict.
- Agent directive extraction writing `auto_approve_plan_action: "epic"` and `plan: true`.
- `handle_plan_approval()` returning `PlanApprovalResult(action="epic", ...)` from metadata without sending a
  notification.
- Legacy `%approve` still returning normal `approve` and still auto-answering questions.
- `handle_plan_marker()` persisting `plan_approved` / `plan_action` for auto-approved epic plans.
- Agents-tab `a` behavior cycling through normal auto-approve, epic auto-approve, and off, including persistence and
  rollback on failure.
- Loader/wire enrichment preserving the new auto-approve action across filesystem and snapshot paths.

Run focused pytest targets first, then run `just install` if needed and `just check` after implementation as required by
repo instructions.
