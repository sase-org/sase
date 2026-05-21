---
create_time: 2026-05-21 16:06:59
status: wip
prompt: sdd/prompts/202605/plan_approval_coder_index_refresh.md
---
# Plan: Make Approved-Plan Coder Agents Visible From Tier 1

## Context

Approving a plan in the ACE TUI writes a `plan_response.json` file immediately, then the running agent process handles
the approval and calls `create_followup_artifacts(...)` to create the next phase, usually the `-code` coder agent. The
TUI normally refreshes from the persistent agent artifact index for Tier 1 loads. The problem is that the follow-up
artifacts directory is created on disk, but it is not explicitly upserted into the persistent artifact index at creation
time, so a Tier 1 refresh can miss it until a later full-history Tier 2 scan.

There is already a related polling pattern for existing `STARTING` rows: the TUI keeps a tiny per-row cache and nudges a
refresh when `agent_meta.json` appears or changes, because it knows a `STARTING` row should soon become `RUNNING` or
`WAITING`. The approved-plan handoff needs the same kind of bounded “expected soon” refresh, but keyed to the artifact
index itself because the coder row may not exist in memory yet.

## Implementation Plan

1. Update the runner-side follow-up artifact creation path so newly created plan-chain follow-up directories are added
   to the Tier 1 artifact index immediately.

   The narrowest place is `src/sase/axe/run_agent_helpers.py:create_followup_artifacts`, after it writes both
   `agent_meta.json` and the initial `workflow_state.json`. At that point the directory is parseable as an active
   workflow/agent row, and the existing lifecycle helper
   `update_agent_artifact_index_for_marker_mutation(new_artifacts_dir)` already routes through the Rust-backed
   artifact-index upsert. This benefits coder, feedback, question, epic, and legend follow-ups uniformly without adding
   runtime-specific behavior.

   The upsert should remain best-effort. If the Rust index is missing or temporarily unavailable, the runner should
   still continue launching the follow-up agent.

2. Add a small TUI-side “expected plan follow-up” polling nudge.

   When the TUI approves a plan and the result implies a follow-up agent is expected (`run_coder` true, or epic/legend
   paths that also launch follow-up agents), record a short-lived expectation in app state and schedule an immediate
   Tier 1 refresh. On each countdown tick while the expectation is alive, stat the persistent index file
   (`~/.sase/agent_artifact_index.sqlite`) and request a debounced agents refresh when its `(mtime_ns, size)` changes or
   appears.

   This mirrors the `STARTING` transition poll but does not require an in-memory agent row. It should expire after a
   small number of ticks to avoid permanent polling if the runner is killed, approval commits only a plan, or the index
   cannot be updated.

3. Keep the polling state small and initialized with the rest of TUI state.

   Add fields such as `_agent_index_expected_refresh_ticks` and `_agent_index_expected_refresh_signature` in
   `src/sase/ace/tui/actions/_state_init.py`. Put the polling and arming methods in
   `src/sase/ace/tui/actions/agents/_loading_refresh.py`, near `_poll_starting_agent_transitions`, and call the poll
   from the existing agents-tab countdown path in `src/sase/ace/tui/actions/_event_activity.py`.

   Use `request_agents_refresh(...)` rather than directly running the loader so existing refresh coalescing, navigation
   gating, and loading guards stay intact.

4. Wire plan approval to arm the expected-index poll.

   In `src/sase/ace/tui/actions/agents/_notification_modals.py`, after the plan response is written successfully and
   after any immediate status override refresh, call the new arming method only when
   `_plan_approval_protocol_fields(result)` indicates a follow-up coder/epic/legend agent should be launched. Do not arm
   it for reject, feedback, or approve-with-commit-only cases.

5. Add focused tests.

   Add/extend runner tests to assert `create_followup_artifacts` calls the artifact-index lifecycle upsert after writing
   the metadata/state files, while tolerating helper failure.

   Add a TUI refresh test alongside `tests/ace/tui/test_starting_agent_poll.py` that uses a minimal
   `AgentLoadingRefreshMixin` harness, arms the expected-index poll, changes a fake index file’s signature, and verifies
   exactly one debounced refresh is requested and that the expectation expires/clears.

   Add a plan-approval modal action unit test, if feasible with existing harnesses, to verify approve-with-coder arms
   the expected-index poll while commit-only approval does not.

6. Verify.

   Run the targeted tests for the runner helper, TUI expected-index poll, and plan-approval action wiring first. Because
   this repo’s memory requires it after code changes, run `just install` if needed, then `just check` before finishing.

## Risks And Guardrails

- The index upsert must not become a launch blocker. Keep it best-effort and log only at debug level on failure.
- The TUI poll should be bounded and cheap: one `stat` per countdown tick only while a follow-up is expected.
- Avoid a Tier 2 scan for this path; the point is to make the Tier 1 index current and have the TUI notice that index.
- Keep the behavior runtime-neutral. Plan-chain follow-ups should be treated uniformly across supported LLM runtimes.
