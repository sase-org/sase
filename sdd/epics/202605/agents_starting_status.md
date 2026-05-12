---
create_time: 2026-05-12 17:18:40
status: done
prompt: sdd/prompts/202605/agents_starting_status.md
bead_id: sase-38
tier: epic
---
# Agents STARTING Status Plan

## Context

The Agents tab currently uses `RUNNING` for rows as soon as a launch claim exists. That conflates two different states:

- The row is visible because a prompt was submitted and a child runner process/workspace claim exists.
- The agent is actually executing the LLM/workflow body.

This matters because the runner still has meaningful pre-run work after the row appears: xprompt expansion, directive
extraction, validation, dependency waits, timer waits, deferred workspace allocation, and prompt reference resolution. A
prompt can also fail before it ever reaches the actual agent execution loop. The new lifecycle should represent that
pre-run state as `STARTING`, allow `STARTING -> WAITING`, and only use `RUNNING` after a recorded run timestamp exists.

Important existing constraints:

- Shared backend behavior belongs in `../sase-core/crates/sase_core`; Python/TUI should stay thin around shared
  lifecycle and scan contracts.
- The ProjectSpec `RUNNING:` field is a workspace/liveness claim, not necessarily the row display status. This plan
  keeps that storage name unless implementation finds a hard compatibility reason to rename it.
- Existing `agent_meta.json` already has `run_started_at`, but it is only populated by wait paths and is currently too
  early for a strict “actual execution began” timestamp. No-wait agents generally lack it.
- `Agent.start_time` is currently the artifact/launch timestamp. The metadata panel labels it `BEGIN`, and runtime
  calculations fall back to it when `run_start_time` is absent.

## Target Semantics

- `STARTING` means: an agent row has been created, but no `run_started_at` has been recorded and no
  wait/question/plan/terminal marker has taken precedence.
- `WAITING` means: a wait marker exists before actual execution, and it may be reached from `STARTING`.
- `RUNNING` means: `run_started_at` exists and no more specific active/paused status has taken precedence.
- `START` timestamp means: launch/artifact timestamp, the moment the row was started/created.
- `RUN` timestamp means: the moment the agent transitions from `STARTING` or `WAITING` into actual execution.
- Runtime duration uses `RUN`, not `START`. Rows without a `RUN` timestamp should not display active runtime.
- Existing completed historical agents without `run_started_at` can temporarily fall back to `START` for compatibility,
  but new live agents should get `RUN` reliably.

## Phase 1: Define The Lifecycle Contract

Owner: one agent instance.

Goals:

- Add shared constants/helpers for agent active statuses and runtime start selection.
- Decide the source of truth for display status:
  - A live `RUNNING:` claim or home `running.json` marker initially loads as `STARTING`.
  - Metadata enrichment promotes to `RUNNING` only when `run_started_at` is present.
  - `waiting.json`, `pending_question.json`, plan review markers, retry markers, and terminal markers still override in
    their existing precedence order.
- Update docs/comments in the touched lifecycle modules so future code does not treat ProjectSpec `RUNNING:` as the
  display status.

Likely files:

- `src/sase/agent/status_buckets.py`
- `src/sase/ace/tui/models/agent_time.py`
- `src/sase/ace/tui/models/agent.py`
- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`
- Rust mirror points if constants or scan-index status summaries live in core.

Tests:

- Unit tests for `STARTING -> WAITING`, `STARTING -> RUNNING`, and “no RUN timestamp means no runtime suffix”.
- Keep old fixtures passing by allowing completed historical rows to calculate from `START` only when `RUN` is missing.

Exit criteria:

- A loaded live agent with no `agent_meta.run_started_at` displays as `STARTING`, not `RUNNING`.
- `waiting.json` can convert that row to `WAITING`.
- Existing terminal rows remain readable.

## Phase 2: Record RUN At The Correct Point

Owner: one agent instance.

Goals:

- Move `run_started_at` recording out of `wait_for_dependencies()`.
- Record `run_started_at` once, immediately before entering `run_execution_loop(ctx, prompt)`, after:
  - xprompt expansion and directive extraction,
  - dynamic memory injection,
  - any `%wait` dependency/time waits,
  - deferred workspace allocation/prep,
  - agent-reference resolution,
  - validation steps that can still prevent execution.
- Ensure no-wait agents also write `run_started_at`.
- Preserve UTC ISO format and existing wire field name.
- Make the write idempotent so retries/follow-up metadata updates do not rewrite the original RUN timestamp.

Likely files:

- `src/sase/axe/run_agent_runner.py`
- `src/sase/axe/run_agent_phases.py`
- `src/sase/axe/run_agent_runner_setup.py` if a helper belongs there.
- Tests around runner setup/phase behavior.

Tests:

- No-wait runner path writes `run_started_at`.
- Wait path writes `run_started_at` after `waiting.json` is removed and after deferred workspace claim/prep.
- Validation/error-before-run path leaves row as `STARTING` until failure marker appears.
- Killed-while-waiting path never writes `run_started_at`.

Exit criteria:

- New agents no longer rely on launch/artifact timestamp for runtime.
- `run_started_at` is the one timestamp that marks actual execution start.

## Phase 3: Update Agents Tab Presentation

Owner: one agent instance.

Goals:

- Render `STARTING` distinctly in list rows.
- Add `Starting` to the status grouping strategy and keep it separate from `Running`.
- Add status-bucket glyph/style coverage for `Starting`.
- Update top strip and panel title metrics so users can see starting rows separately from running rows.
- Keep keyboard actions honest:
  - Wait/resume should allow `STARTING` where it makes sense for pre-run wait editing.
  - Kill/cleanup should still handle `STARTING` rows because a child process/workspace claim may exist.
  - Actions that assume an LLM is already running should continue to require `RUNNING`.

Likely files:

- `src/sase/agent/status_buckets.py`
- `src/sase/integrations/agent_status_groups.py`
- `src/sase/ace/tui/models/agent_groups/_buckets.py`
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
- `src/sase/ace/tui/widgets/_agent_list_styling.py`
- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `src/sase/ace/tui/actions/agents/_display_detail.py`
- `src/sase/ace/tui/actions/agents/_display_panels.py`
- `src/sase/ace/tui/actions/agents/_wait_resume.py`
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`

Tests:

- Status bucket tests include `STARTING -> Starting`.
- Grouping by status produces a `Starting` group.
- Row rendering styles `STARTING`.
- Info panel count strip reports starting separately.
- Action tests cover kill/wait behavior for `STARTING`.

Exit criteria:

- In “by status” grouping, `STARTING` rows appear under `Starting`, not `Running`.
- The Agents tab count strip distinguishes starting from running.

## Phase 4: Rename Timestamp Labels And Runtime Inputs

Owner: one agent instance.

Goals:

- Rename metadata panel label `BEGIN` to `START`.
- Add a separate `RUN` line when `run_start_time` exists.
- Use `RUN` as the default runtime start for active and terminal rows.
- For `WAITING` before execution, show `START` plus wait metadata, but no active runtime.
- For historical completed rows missing `RUN`, use a compatibility fallback from `START` only where needed to avoid
  losing old durations.
- Update wording/comments that say “BEGIN” in runtime explanations.

Likely files:

- `src/sase/ace/tui/models/agent.py`
- `src/sase/ace/tui/models/agent_time.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
- `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py`
- Tests in `tests/test_agent_model_timestamps.py` and `tests/ace/tui/widgets/test_agent_list_runtime_model.py`.

Tests:

- Metadata panel tag sequence examples become `START`, optional `WAIT`, `RUN`, `PLAN`, `CODE`, `END`.
- Runtime for `STARTING` is blank.
- Runtime for `RUNNING` without `run_start_time` is blank for live rows.
- Runtime for `RUNNING` with `run_start_time` starts from `RUN`.
- Terminal compatibility fallback is covered explicitly.

Exit criteria:

- No user-facing metadata label says `BEGIN`.
- Runtime calculations are based on `RUN` for new agents.

## Phase 5: Update Scan, CLI, And Integration Mirrors

Owner: one agent instance.

Goals:

- Keep Python and Rust agent-scan wire parity for any new or reinterpreted fields.
- Update Rust scan/index summarized status logic so records without `run_started_at` are classified as starting instead
  of running when applicable.
- Update CLI/integration summaries (`sase agents status`, mobile/Telegram-facing grouping) to understand `STARTING`.
- Keep backward compatibility with existing JSON schema if no new field is needed; bump schema only if a shape changes.

Likely files:

- `src/sase/core/agent_scan_wire_markers.py`
- `src/sase/core/agent_scan_wire_conversion.py`
- `src/sase/agent/running.py`
- `../sase-core/crates/sase_core/src/agent_scan/wire.rs`
- `../sase-core/crates/sase_core/src/agent_scan/scanner.rs`
- `../sase-core/crates/sase_core/src/agent_scan/index.rs`
- `../sase-core/crates/sase_core/tests/agent_scan_parity.rs`
- `tests/test_running_agents_snapshot.py`
- `tests/test_core_agent_scan_*`

Tests:

- Rust/Python parity tests include one starting artifact record.
- CLI listing reports `STARTING` duration from `START` only as age, not runtime, or uses `?` if the UI contract chooses
  not to expose starting duration.
- Integration status grouping includes `Starting`.

Exit criteria:

- Python and Rust scan paths agree on starting records.
- External status consumers do not silently merge `STARTING` into `RUNNING`.

## Phase 6: End-To-End And Visual Verification

Owner: one agent instance.

Goals:

- Add or update E2E tests that simulate a launch before `run_started_at`, a wait marker, and then the run timestamp.
- Update PNG snapshots if the Agents tab count strip/status colors visibly change.
- Run the project checks after installing dependencies in this workspace.

Commands:

```bash
just install
just test tests/test_agent_model_timestamps.py tests/ace/tui/widgets/test_agent_list_runtime_model.py tests/ace/tui/models/test_agent_groups_grouping_mode_status.py tests/test_agent_status_groups.py
just test-visual
just check
```

Exit criteria:

- Targeted tests pass.
- Visual snapshot changes are reviewed and intentional.
- `just check` passes.

## Risks And Decisions To Confirm During Implementation

- Whether `STARTING` should be serialized in `done.json` is likely no; terminal status should continue to come from
  outcome.
- Whether top-strip “starting” count is wanted. This plan includes it because the feature goal is to distinguish
  starting from running in the Agents tab, not only in grouped mode.
- Whether `run_started_at` should be recorded before or after final prompt reference resolution. This plan records after
  final prompt/reference/wait/workspace prep and immediately before `run_execution_loop()`.
- Historical rows missing `run_started_at` need compatibility. New rows should not.
