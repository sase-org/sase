---
create_time: 2026-04-30 01:16:59
status: done
bead_id: sase-1h
prompt: sdd/prompts/202604/agent_cleanup_panel.md
---
# Agent Cleanup Panel and Rust Backend Migration Plan

## Goal

Replace the Agents-tab `X` and `,X` cleanup shortcuts with one `X` entry point that opens a polished, keyboard-first
cleanup panel. The panel should make common actions one keypress away, while also offering a custom selector for more
granular kill/dismiss operations. At the same time, move reusable backend logic for choosing, planning, and eventually
executing agent/workflow cleanup operations into `../sase-core`, so future web/mobile surfaces do not need to
reimplement Ace TUI behavior.

This is intentionally split into phases that can be run by distinct agent instances. Each phase should leave the tree in
a coherent state with tests passing for the files it touches.

## Current State

Relevant Python surfaces in `sase_102`:

- Agents-tab `X` is `action_toggle_axe()` on `src/sase/ace/tui/actions/axe.py`; on Agents it calls
  `_dismiss_all_done_agents()`.
- Agents-tab `,X` is `leader_mode.kill_all`; `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` calls
  `_kill_and_dismiss_all_agents()`.
- Single-row `x`, marked-agent cleanup, and group cleanup route through
  `src/sase/ace/tui/actions/agents/_kill_action.py`, `src/sase/ace/tui/actions/agents/_marking.py`, and
  `src/sase/ace/tui/actions/agents/_killing.py`.
- Dismiss persistence and dismissal-prefix/name rewrite behavior lives in
  `src/sase/ace/tui/actions/agents/_dismissing.py`.
- Kill persistence/project-file side effects live in `src/sase/ace/tui/actions/agents/_kill_persistence.py`.
- Dismissed identities/bundles live in `src/sase/ace/dismissed_agents.py`.
- Agent tags live in `src/sase/ace/agent_tags.py`; `Agent.tag` is already loaded onto the TUI model.
- Keymap metadata/help/footer updates must touch `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/types.py`,
  `src/sase/ace/tui/bindings.py`, `src/sase/ace/tui/modals/help_modal/bindings.py`, and footer widgets as needed.

Relevant Rust surfaces in `../sase-core`:

- `crates/sase_core/src/agent_scan/` already models artifact snapshots.
- PyO3 bindings are exposed from `crates/sase_core_py/src/lib.rs` via `sase_core_rs`.
- Python facades use strict `require_rust_binding(...)`; new bindings should follow that pattern.

## Product Design

On the Agents tab, pressing `X` opens an `AgentCleanupPanel` modal. The panel should feel like a command surface rather
than a scary confirm dialog: compact, high-contrast, and scan-friendly. It should show a top summary for the currently
focused panel plus global totals:

- running/killable count
- completed/dismissable count
- failed count
- marked count
- current tag/panel, if focused
- destructive actions separated visually from dismiss-only actions

Single-key actions in the first version:

- `d` dismiss completed agents in the focused tag panel
- `D` dismiss completed agents across all loaded agent panels
- `k` kill running and dismiss completed agents in the focused tag panel
- `K` kill running and dismiss completed agents across all loaded agent panels
- `m` kill/dismiss marked agents, if marks exist
- `g` kill/dismiss focused collapsed group, if a group banner is focused
- `t` choose a tag and kill/dismiss entries with that tag, with `@foo` displayed even though the stored tag is `foo`
- `c` open the custom selector
- `q`/`escape` cancel

Destructive actions (`k`, `K`, `m`, `g`, tag kill) should keep the existing final confirmation semantics. Dismiss-only
actions can remain one confirm or no confirm according to current behavior, but the modal must preview counts before
execution. Preserve AXE-tab `X` as clear-output unless a later phase explicitly changes Axe ergonomics; this plan only
replaces the Agents-tab `X` and Agents-tab `,X` cleanup paths.

The custom selector should optimize for minimal keypresses:

- Starts with the same candidate set as the focused panel.
- Has quick filters: `d` done, `r` running, `f` failed, `w` waiting, `t` tag filter, `/` text filter.
- Supports `space` to toggle focused row, `a` to toggle all filtered rows, `enter` to preview/confirm, and `q` to
  cancel.
- Shows selection totals and a split of "will kill" vs "will dismiss" at all times.
- Reuses the existing Agents visual vocabulary: status colors, tag chips, workflow child indentation, and no nested
  cards.

## Rust Backend Shape

Do not try to port the whole TUI model. Add a backend-oriented cleanup module with rectangular wire types.

Suggested pure-Rust module:

- `crates/sase_core/src/agent_cleanup/mod.rs`
- `crates/sase_core/src/agent_cleanup/wire.rs`
- `crates/sase_core/src/agent_cleanup/planner.rs`

Suggested request/response concepts:

- `AgentCleanupTargetWire`: identity, agent type, status, pid, workflow, parent workflow/timestamp, raw suffix, project
  file, artifacts dir, workspace, tag, agent name, display name, timestamps, and flags needed for parent/child cascade.
- `AgentCleanupScopeWire`: focused panel tag, all panels, explicit identities, tag, focused group identity set, custom
  selected identities.
- `AgentCleanupModeWire`: dismiss completed only, kill running and dismiss completed, preview only.
- `AgentCleanupPlanWire`: selected identities, kill items with kind, dismiss items, cascaded workflow children, skipped
  items with reason, counts, confirmation severity, and user-facing summary lines.
- Later side-effect wires: dismissed index snapshot, dismissal rename map, bundle writes, artifact deletes, workspace
  releases, changespec field mutations, notification dismiss candidates, and process signal requests/results.

The first Rust phase should produce a plan only. Python continues executing side effects until parity is proven.

## Phase 1: Rust Cleanup Planning Contract

Owner: one backend-focused agent in `../sase-core`.

Implement pure Rust cleanup planning and expose it through PyO3.

Tasks:

- Add `agent_cleanup` wire types and planner functions to `sase_core`.
- Implement target classification equivalent to Python's `_classify_kill_kind`, dismissable filtering, workflow-child
  cascade expansion, de-duplication, and skipped-reason reporting.
- Add `sase_core_rs.plan_agent_cleanup(targets: list[dict], request: dict) -> dict`.
- Add Rust unit tests for focused panel, all panels, marked/explicit identities, tag scope, workflow parent cascade,
  child de-duplication, no-op plans, and unknown kill kinds.
- Add PyO3 conversion tests in `sase-core` matching existing JSON-shape conventions.

Acceptance:

- `cargo fmt --all -- --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`

## Phase 2: Python Facade and Parity Adapter

Owner: one integration agent in `sase_102`.

Add a Python facade that converts current `Agent` objects into Rust cleanup wires and compares Rust plans against the
legacy Python partitioning behavior.

Tasks:

- Add `src/sase/core/agent_cleanup_wire.py` and `src/sase/core/agent_cleanup_facade.py`.
- Add conversion helpers from `sase.ace.tui.models.agent.Agent` to `AgentCleanupTargetWire` dicts.
- Keep a pure-Python fallback planner for tests and for environments where the binding is temporarily older.
- Add tests that prove Rust and Python planners agree for: focused-panel dismiss all done, focused-panel kill/dismiss
  all, marked set, collapsed group, tag scope, workflow parent with children, pid-less dismiss fallback, and duplicate
  child inputs.
- Do not change UI behavior in this phase.

Acceptance:

- `just install` if the workspace has not been installed recently.
- Targeted tests for the new facade and existing kill/dismiss tests.
- `just check` before handoff.

## Phase 3: Rust Side-Effect Planning, Not Execution

Owner: one backend-focused agent across both repos, primarily `../sase-core`.

Move reusable side-effect planning to Rust while leaving actual process signaling and file writes in Python.

Tasks:

- Extend `AgentCleanupPlanWire` with side-effect intents: dismissed index additions, bundle-save candidates,
  artifact-delete paths, workspace-release requests, notification dismiss candidates, dismissal rename allocations, and
  wait/reference rewrite map.
- Port deterministic pieces of `_apply_dismissal_rename`, dismissal child inclusion, and dismissal name allocation to
  Rust. Inputs should include already-taken dismissed names so Rust stays pure and deterministic.
- Add Python facade support for side-effect intent plans.
- Update existing Python persistence code to consume the Rust intent plan where possible while still performing the file
  writes through current Python helpers.
- Preserve current async/optimistic UI behavior.

Acceptance:

- Cross-repo tests cover identical side-effect intent output for current single dismiss, bulk dismiss, bulk kill, and
  workflow parent cleanup cases.
- `cargo test --workspace` in `../sase-core`.
- `just check` in `sase_102`.

## Phase 4: TUI Panel Shell and Keymap Migration

Owner: one TUI-focused agent in `sase_102`.

Replace Agents-tab `X`/`,X` with the new `X` cleanup panel, initially backed by existing backend actions through the new
facade.

Tasks:

- Add a new modal, likely `src/sase/ace/tui/modals/agent_cleanup_modal.py`.
- Add an action such as `action_open_agent_cleanup_panel()`.
- Change Agents-tab `X` to open the panel instead of dismissing done agents directly.
- Remove or deprecate Agents-tab `leader_mode.kill_all` so `,X` no longer appears as a separate cleanup command. Avoid
  breaking unrelated leader-mode commands.
- Keep `x` single-row/marked/group behavior unchanged for now.
- Update default config, keymap types, command catalog/availability, footer conditional labels, and help modal.
- The panel should show disabled/unavailable actions instead of hiding everything; this makes discoverability better
  while keeping single-key actions stable.

Acceptance:

- Existing keymap tests updated to expect a single Agents cleanup entry point.
- Help/footer tests updated.
- TUI modal unit tests for action availability and selected result.
- `just check`.

## Phase 5: Custom Selector and Tag Cleanup Flow

Owner: one TUI/backend integration agent in `sase_102`.

Implement the `c` custom selector and `t` tag-scoped cleanup path.

Tasks:

- Add a selector modal or second screen inside `AgentCleanupPanel`.
- Use Rust/Python cleanup planning on every filter/selection change to keep counts and skipped reasons live.
- Implement quick filters and low-keystroke selection controls.
- Implement tag chooser using known tags from loaded agents and `~/.sase/agent_tags.json`.
- Ensure workflow children inherit parent tag behavior consistently with `agent_panels.py`.
- Route confirmed custom selections through `_do_bulk_kill_agents(...)` or the new backend execution facade.
- Preserve focus restoration, mark clearing, notification count refresh, and optimistic row removal behavior.

Acceptance:

- Tests for custom filtered selection, select-all-filtered, tag scope, selected workflow parent cascade, and cancel
  paths.
- Manual smoke test in `sase ace` with fake/stub agents if a full interactive test harness is not practical.
- `just check`.

## Phase 6: Migrate Side-Effect Execution to Rust Where Worthwhile

Owner: one backend agent across both repos.

Move the backend operations future clients need into `../sase-core`, with Python calling one facade instead of owning
the operation details. Process signaling can remain an explicit host operation if keeping it outside pure `sase_core`
makes the API cleaner.

Tasks:

- Decide and document the boundary: Rust pure crate owns planning and deterministic filesystem/project-file mutations;
  Python/TUI owns event-loop, notifications, and possibly process signaling.
- Add Rust helpers for dismissed index read/write, bundle filename/shard logic, bundle JSON writing from wire data,
  artifact deletion, workspace release text mutation, and changespec suffix marking for hook/mentor/comment kills.
- Expose execution or execution-intent bindings from PyO3 with structured result wires.
- Update Python persistence functions to delegate to Rust-backed helpers.
- Keep robust error reporting so the TUI can still notify and schedule a refresh on partial failure.

Acceptance:

- Parity tests for dismissed index/bundle layout, workspace release, hook kill marking, mentor kill marking, CRS/comment
  kill marking, artifact deletion intent, and notification candidate selection.
- Regression tests from `test_dismissed_agent_lifecycle.py`, `test_agent_kill_phase2_kill_all.py`,
  `test_agent_loader_self_heal.py`, `test_agent_revive.py`, and relevant hook/mentor/comment kill tests still pass.
- `cargo test --workspace` and `just check`.

## Phase 7: Polish, Documentation, and Backward Compatibility Cleanup

Owner: one finishing agent in `sase_102`.

Make the feature feel finished and remove transitional rough edges.

Tasks:

- Review visual styling against existing modals and the Ace footer/help guidelines.
- Update help popup copy with concise labels that fit the 57-character help boxes.
- Add a short user-facing note in any relevant docs/changelog location used by this repo.
- Remove dead code paths once `X` panel fully covers old `X` and `,X` behavior.
- Check command palette entries so there is one cleanup command, not duplicate legacy commands.
- Ensure future web/mobile app contracts are documented near the Rust wire types and Python facade.

Acceptance:

- `just check`.
- Manual `sase ace` smoke test for: `X d`, `X k`, `X K`, `X t`, `X c`, cancel paths, no-op paths, AXE-tab `X`, and
  existing `x` row cleanup.

## Cross-Phase Guardrails

- Do not regress `x` single-agent, marked-set, or group cleanup behavior while introducing `X`.
- Preserve optimistic UI updates and async persistence; cleanup should not block the Textual event loop.
- Preserve dismissed-name prefix semantics and wait/reference rewrites.
- Be careful with dirty worktrees. Do not revert unrelated user changes.
- When changing keymaps, update `src/sase/default_config.yml`, keymap dataclasses/metadata, help modal, footer logic,
  and command palette/availability in the same phase.
- When touching `sase_102`, run `just install` first if needed and `just check` before handoff.
- When touching `../sase-core`, run Rust fmt/clippy/tests before handoff.
