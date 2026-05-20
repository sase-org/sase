---
bead_id: sase-3s
tier: epic
status: done
---
# Plan: Agent Artifact Index Lifecycle For ACE Agents Tab

## Goal

Make normal ACE Agents-tab refreshes scale with the visible working set instead of the full historical artifact tree,
while preserving the current canonical artifact layout, dismissed-bundle revive flow, and all currently visible agents.

The implementation should treat `~/.sase/agent_artifact_index.sqlite` as the maintained materialized view for normal
loads. The artifact directories under `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` remain the source of
truth and must not be physically moved.

## Context

The TUI already has a Tier 1 loader path in `src/sase/ace/tui/models/agent_loader.py` that queries the SQLite artifact
index for active plus recent completed rows. The problem is lifecycle drift: the index is read on refresh but is not
kept current when agents are launched, dismissed, killed, revived, or when marker files change. Dismissal currently
removes marker files such as `done.json` and `workflow_state.json`, which can cause a rebuilt row to satisfy the current
"active" predicate even though the agent is dismissed.

Because artifact visibility semantics are shared backend behavior, the durable query/reconciliation rules belong in
`../sase-core`. Python should own thin lifecycle calls where the mutation is still Python-side.

## Phase 1 - Core Index Visibility And Reconciliation

Owner: Rust/core agent.

Scope:

- Update `../sase-core/crates/sase_core/src/agent_scan/index.rs` so active and visible artifact-index queries exclude
  identities present in the index's `dismissed_agents` table unless `include_hidden` is true.
- Keep recent completed rows visible when not dismissed, so done-but-not-dismissed agents still appear in ACE.
- Add a small index reconciliation API, or extend rebuild behavior, so an index rebuilt from source artifacts does not
  reintroduce dismissed rows as active.
- Add Rust unit tests for:
  - active query excludes a dismissed identity even if marker files make it look incomplete;
  - full-history hidden-inclusive query can still inspect dismissed rows when requested;
  - recent completed rows remain visible when they are not dismissed.

Acceptance:

- `query_agent_artifact_index(... include_active=True, include_hidden=False)` no longer returns phantom dismissed rows.
- Existing index tests still pass.

## Phase 2 - Python Lifecycle Hooks

Owner: Python lifecycle agent.

Scope:

- Add a small Python adapter around existing facade calls in `src/sase/core/agent_scan_facade.py` or a nearby module:
  - default index path and projects root resolution;
  - best-effort `upsert` for artifact changes;
  - best-effort `delete` or hide for dismissed artifacts;
  - best-effort revive upsert.
- Wire dismissal and kill persistence:
  - `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
  - `src/sase/ace/tui/actions/agents/_kill_persistence.py`
  - cleanup-plan intent handling, where artifact deletion is driven by core intents.
- Wire revive after marker restoration in `src/sase/ace/tui/actions/agents/_revive_artifacts.py` or its caller.
- Do not block the UI on index maintenance. Failures should be swallowed or logged and should fall back to existing
  loader behavior.

Acceptance:

- Dismissing an agent removes or hides its row from the index in the same worker-side persistence path that removes
  loader-visible marker files.
- Reviving an agent upserts its restored artifact row.
- Existing dismissal and revive tests keep passing, with new focused tests asserting index maintenance calls.

## Phase 3 - Launch/Completion Marker Maintenance

Owner: Python/Rust lifecycle agent.

Scope:

- Wire index upserts at artifact creation and marker mutation points, starting with the highest-impact paths:
  - `src/sase/axe/run_agent_runner_setup.py::setup_artifacts_directory`;
  - final marker writes in the run-agent completion/finalization path;
  - home-mode/running marker writes if they are not covered by the setup/finalize paths.
- Prefer one shared helper so future marker writers do not need to know index details.
- Keep all runtimes uniform; no provider-specific branches.

Acceptance:

- Newly launched agents appear through the index without requiring `sase agents index rebuild`.
- Completed agents have their indexed status updated after `done.json` is written.
- Tests cover launch/setup upsert and completion upsert at the helper boundary.

## Phase 4 - CLI Reconciliation And Diagnostics

Owner: CLI/reconciliation agent.

Scope:

- Add or extend a `sase agents index` subcommand for one-shot cleanup of existing stale indexes, such as
  `sase agents index gc`.
- The reconciliation should be safe to run on old machines with thousands of historical artifacts and dismissed bundles.
- JSON output should report rows indexed, deleted/hidden, skipped, and index path.
- Parser, handler, and CLI dispatch tests should cover the new command.

Acceptance:

- A user can repair the existing workstation index without launching the TUI.
- Existing `rebuild` and `verify` behavior remains compatible.

## Phase 5 - Loader/Performance Guardrails

Owner: TUI loader/perf agent.

Scope:

- Keep `_query_artifact_index_for_loader()` as the normal Tier 1 path:
  - active rows;
  - recent completed limit of 200;
  - no full history;
  - no hidden/dismissed rows.
- Add tests that the Tier 1 loader uses the index and does not call full source scans when the index is present.
- Add a synthetic large-index or mocked-query performance sentinel that protects the hot path from filesystem fan-out.
- Preserve Tier 2 full source scan only for explicit full-history reconciliation.

Acceptance:

- Loader tests demonstrate bounded Tier 1 behavior.
- A bad or missing index still falls back to the current bounded source scan.

## Phase 6 - End-To-End Verification

Owner: final integration agent.

Scope:

- Run focused Rust and Python tests for the changed areas.
- Run `just install` if needed, then `just check` before final handoff.
- Rebuild or reconcile the local artifact index if the implementation requires it for the live workstation state.
- Start the TUI with `sase ace --tmux`, switch to the Agents tab if needed, capture the tmux pane contents, and verify
  that the 24 agents from the provided snapshot are still present: `@at2`, `@ars.r1`, `@ars`, `@aqr`, `@ap5.r1`, `@ap5`,
  `@aj5`, `@aip.1.plan`, `@aaaaa`, `@aq2.r1`, `@aq2`, `@aud`, `@aqa.gem`, `@aqa.cdx`, `@aqa.cld`, `@aug`, `@aug.r1`,
  `@aug.r1.r1`, `@sase-3r`, `@sase-3r.5`, `@sase-3r.4`, `@sase-3r.3`, `@sase-3r.2`, `@sase-3r.1`.

Acceptance:

- Captured tmux output shows the same 24 agent names or a clear, investigated reason for any legitimate state change.
- Normal ACE startup does not visibly scan the full artifact archive.

## Risks And Constraints

- Do not move canonical artifact directories; path stability is part of the runtime contract.
- Dismissed rows must not become active merely because marker files were deleted.
- Running liveness remains a post-query PID check in Python; an indexed row is not proof that a process is alive.
- Existing worktrees may be dirty; phase agents must not revert unrelated edits.
- Memory files under `memory/` and `.sase/memory/` must not be modified without explicit user approval.
