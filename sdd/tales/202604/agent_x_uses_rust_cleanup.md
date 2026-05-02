---
create_time: 2026-04-30 11:10:29
status: done
prompt: sdd/prompts/202604/agent_x_uses_rust_cleanup.md
---
# Plan: Route single-agent `x` cleanup through Rust planner

## Goal

Make the Agents tab `x` keymap for a single focused agent use the same Rust-backed cleanup planning logic as the `X`
cleanup panel uses for dismiss/kill decisions, while keeping the existing fast immediate UI removal behavior.

## Current Findings

- `src/sase/default_config.yml` maps Agents tab `kill_agent` to `x` and `open_agent_cleanup_panel` to `X`.
- `X` opens the cleanup panel via `AgentKillMixin.action_open_agent_cleanup_panel()`. Panel actions create
  `AgentCleanupRequestWire` values and call `sase.core.agent_cleanup_facade.plan_agent_cleanup()`.
- `plan_agent_cleanup()` calls the `sase_core_rs.plan_agent_cleanup` Rust binding when available, with a Python fallback
  only for stale/missing local bindings.
- The Rust planner already supports the scope and mode needed for a single selected agent:
  `CLEANUP_SCOPE_EXPLICIT_IDENTITIES` plus `CLEANUP_MODE_KILL_AND_DISMISS`.
- The current single-agent `x` path in `AgentKillMixin.action_kill_agent()` bypasses that planner: it checks
  `DISMISSABLE_STATUSES`, checks `agent.pid`, calls `_dismiss_done_agent()` for dismissable/pidless agents, and shows
  `ConfirmKillModal` before `_do_kill_agent()` for live agents.
- `_do_bulk_kill_agents()` already uses `_plan_bulk_kill_cleanup_side_effects()`, which builds the Rust-backed cleanup
  plan and passes it into `persist_bulk_kill_side_effects()`.
- `_do_kill_agent()` still uses Python `_classify_kill_kind()` and ad hoc immediate identity collection for the kill
  decision. Its persistence path also calls `persist_kill_side_effects()` directly instead of consuming cleanup-plan
  side-effect intents.
- Existing tests cover the important performance constraints: no synchronous disk I/O on immediate kill, one persistence
  task, row-removal fast path, and bulk kill using the planner-backed path.

## Approach

1. Add a focused-agent cleanup planner helper in `src/sase/ace/tui/actions/agents/_killing.py`.
   - Build an `AgentCleanupRequestWire` with:
     - `scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES`
     - `mode=CLEANUP_MODE_KILL_AND_DISMISS`
     - the selected agent identity
     - `include_pidless_as_dismissable=True`
     - `taken_dismissed_names` from `collect_dismissed_taken_names()`
   - Call `plan_agent_cleanup(agents_to_cleanup_targets(self._agents_with_children), request)`.
   - This mirrors the `X` cleanup-panel core path and lets Rust determine whether the agent is killable, dismissable,
     skipped, and which workflow children or dismissal side effects are involved.

2. Refactor the single-agent branch of `AgentKillMixin.action_kill_agent()`.
   - Keep marked-set and focused-group behavior unchanged.
   - For the focused row, build the Rust-backed single-agent cleanup plan before deciding what to do.
   - If the plan has one or more `dismiss_items` and no `kill_items`, call a new planner-aware single dismiss method
     rather than deciding dismissability in Python.
   - If the plan has `kill_items`, use the plan’s first kill item for the confirmation dialog and then pass the plan
     into the kill execution path.
   - If the planner returns no actionable items, notify with an appropriate warning using skipped reason/detail.

3. Add planner-aware single execution methods while preserving fast UI removal.
   - For single dismiss, reuse the same immediate operations currently in `_dismiss_done_agent()`: apply rename intents,
     update dismissed sets, remove rows through `_apply_dismissal_in_memory()`, rewrite in-memory wait references, and
     schedule `_run_dismiss_persistence_async()` with the cleanup plan.
   - For single kill, update `_do_kill_agent()` or add a sibling that accepts an `AgentCleanupPlanWire`.
   - Use the plan’s `kill_items[0].kind` instead of `_classify_kill_kind()` for the kill classification.
   - Use `dismissed_identities_from_plan(plan)` plus `plan.cascaded_workflow_children` as the authoritative identities
     to hide/update immediately, falling back to `_collect_immediate_kill_identities()` only if needed for defensive
     compatibility.
   - Continue to signal the process group synchronously because the TUI must still stop the process immediately.
   - Continue to schedule persistence via `call_later` so the UI thread avoids disk/project-file I/O.

4. Make single-kill persistence consume the cleanup-plan side-effect intents.
   - Extend `_run_kill_persistence_async()` and/or `persist_kill_side_effects()` to accept an optional cleanup plan.
   - When present, execute deterministic Rust-planned side effects through `persist_cleanup_side_effect_intents()`.
   - Avoid duplicate legacy side effects for running/workflow kills when the cleanup plan consumed the relevant intents,
     matching `persist_bulk_kill_side_effects()`.
   - Keep existing Python/Rust execution fallbacks for hook, mentor, and CRS project-file status mutations because those
     still depend on parsing and updating the project file on the Python side.

5. Add focused regression coverage.
   - Test that pressing `x` for a single running agent calls `plan_agent_cleanup()` with
     `CLEANUP_SCOPE_EXPLICIT_IDENTITIES` / `CLEANUP_MODE_KILL_AND_DISMISS` before confirmation and passes the resulting
     plan into the confirmed kill path.
   - Test that pressing `x` for a single DONE agent uses the planner-backed dismiss path and passes the cleanup plan
     into persistence.
   - Test that a pidless non-completed focused agent is dismissed only because the Rust-backed request sets
     `include_pidless_as_dismissable=True`.
   - Update existing single-kill tests as needed for the new optional cleanup-plan argument without weakening their
     assertions about fast UI removal and deferred persistence.

6. Verification
   - In `sase_101`, run `just install` first if the local environment needs bootstrapping.
   - Run focused tests:
     - `just test tests/test_agent_kill_single.py tests/test_agent_kill_dismiss_fast_path.py tests/test_agent_kill_bulk.py tests/test_agent_kill_phase1_async_io.py`
     - plus any new or changed single-agent cleanup test file.
   - Run `just check` before final response, per repo instructions.
   - If any Rust source changes become necessary in `../sase-core`, also run `cargo test --workspace` there and rebuild
     the extension with `just rust-install` in `sase_101`; current inspection suggests this should not be necessary.

## Risks and Constraints

- The immediate UI path must not perform disk I/O. Planning is pure and Rust-backed, but persistence must remain in the
  async worker.
- The single-agent fast row-removal path should remain intact. The change should alter the source of cleanup decisions,
  not force a full list rebuild.
- Hook/mentor/CRS status-line updates are not fully represented as Rust side-effect intents today. The implementation
  should preserve existing Python persistence for those kinds unless the Rust core already provides the exact mutation
  helper through `sase.core.agent_cleanup_execution`.
- The Rust facade has a Python fallback for stale/missing local bindings. Tests should assert that the TUI routes
  through `plan_agent_cleanup()`, not that the local extension is always present.
