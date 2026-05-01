---
status: wip
bead_id: sase-1t
---

# Independent Plan-Chain Agents

## Goal

Split plan/question/feedback/coder handoff phases into independent entries on the `sase ace` Agents tab while preserving
the visible naming convention users already rely on:

- planner: `<name>.plan`
- question prompt: `<name>.q`
- feedback replans: `<name>.<N>`
- coder: `<name>.coder`

Each phase of this implementation should be small enough for a distinct agent instance to complete. The implementation
must preserve lineage, status summaries, cleanup/dismiss/revive behavior, chat links, `#resume`, `%wait`, and name
reservation. Existing `.code` artifacts must continue to load and resolve as legacy coder phases.

## Current Shape

- `src/sase/axe/run_agent_exec_plan.py` handles `sase plan` and `sase questions` markers. It mutates the current
  artifacts for `.plan` / `.q`, then creates follow-up artifacts via `create_followup_artifacts()`.
- `src/sase/axe/run_agent_helpers.py` writes follow-up metadata with `parent_timestamp`, `role_suffix`, optional
  `workflow_name`, and `name`. New coder metadata already uses `.coder`, while legacy tests and UI paths still mention
  `.code`.
- `src/sase/plan_chain.py` already centralizes canonical plan-chain suffixes and legacy `.code` handling.
- `src/sase/ace/tui/models/agent_loader.py` currently treats `parent_timestamp and not parent_workflow` as a follow-up
  child relationship. It attaches those entries to a parent, propagates status/timestamps/diff data, and inserts them
  next to workflow steps in `_sort_and_reorder()`.
- `Agent.is_workflow_child` currently treats any `parent_timestamp` as child-like, which blurs independent handoff
  agents with actual workflow prompt-step children.
- `src/sase/agent/running.py` skips all `parent_timestamp` records for CLI running/done listings, which matches the
  current dedup model but conflicts with independent phase entries.

## Phase 1: Metadata Contract And Classification

Owned area: shared plan-chain helpers, runner metadata, focused tests.

1. Treat `src/sase/plan_chain.py` as the authority for plan-chain suffix classification, visible names, and legacy
   `.code` normalization.
2. Audit `handle_plan_marker()`, `handle_questions_marker()`, `create_followup_artifacts()`, and any direct `.code`
   checks so new artifacts use `.coder` consistently and readers canonicalize legacy `.code`.
3. Keep existing `parent_timestamp` for backward compatibility, but standardize `plan_chain_parent_timestamp` as the
   explicit handoff-lineage field for new artifacts.
4. Add focused metadata tests for first plan, questions, feedback rounds, coder, and legacy `.code` classification.

Acceptance criteria:

- New coder phase artifacts are named `<name>.coder` with `role_suffix=".coder"`.
- Legacy `.code` artifacts still classify as coder and preserve existing behavior.
- New plan-chain artifacts carry enough metadata to distinguish handoff lineage from workflow-step parentage.

Verification:

- `pytest tests/test_plan_chain_roles.py tests/test_axe_run_agent_helpers.py tests/test_axe_run_agent_exec_retry.py`

## Phase 2: Model Split In The Agents Loader

Owned area: `Agent` model semantics and status derivation.

1. Add an explicit model-level distinction for plan-chain phase entries versus workflow prompt-step children. This can
   be a property derived from `role_suffix` / `plan_chain_parent_timestamp`, or a stored boolean if that keeps call
   sites clearer.
2. Update `Agent.is_workflow_child` or introduce a narrower property so actual workflow children remain nested, while
   plan-chain phases can be treated as independent agents.
3. Refactor `_apply_status_overrides()` to use plan-chain classification instead of raw
   `parent_timestamp and not parent_workflow` checks.
4. Preserve root plan summaries:
   - `PLANNING` while waiting for plan approval
   - `QUESTION` while a submitted question is unanswered
   - `PLAN APPROVED` while coder/epic follow-up is active
   - `PLAN DONE` / `EPIC CREATED` after completion
5. Keep timestamp, diff, and meta propagation to the root as summary data, but avoid making those relationships imply
   child-row rendering.

Acceptance criteria:

- Loader output can identify independent plan-chain entries separately from true workflow children.
- Root plan summary statuses remain stable.
- Old artifacts that only have `parent_timestamp` still link correctly.

Verification:

- `pytest tests/test_agent_loader_status_overrides.py tests/test_agent_loader_dedup_pid.py tests/test_agents_tab_query_integration.py tests/test_fold_filtering.py`

## Phase 3: Independent Agents-Tab Rendering

Owned area: Agents-tab ordering, grouping, folding, counts, and selection.

1. Change `_sort_and_reorder()` so plan-chain phase agents are not inserted as indented child rows under the root plan.
2. Keep real workflow prompt-step children nested under workflow parents.
3. Let normal grouping place related phase names (`a.plan`, `a.q`, `a.2`, `a.coder`) near each other when grouping mode
   supports it, but keep each phase selectable as its own row.
4. Update grouping/fold helpers that currently use `is_workflow_child` or `parent_timestamp` so plan-chain phases do not
   inherit parent fold visibility by accident.
5. Update row rendering/tests to expect `.coder` for new coder phases while accepting `.code` in legacy fixtures.

Acceptance criteria:

- A representative chain appears as independent rows on Agents tab: `<name>.plan`, `<name>.q`, `<name>.<N>`,
  `<name>.coder`.
- Workflow prompt steps still appear as nested children.
- Selection restoration, jump hints, marks, hidden toggles, counts, and detail panel updates work for each phase row.

Verification:

- `pytest tests/ace/tui/widgets tests/ace/tui/models tests/ace/tui/test_agent_jk_navigation.py tests/ace/tui/test_agent_fold_transitions.py`

## Phase 4: CLI, Lookup, Wait/Resume, Cleanup, And Revive

Owned area: non-rendering lifecycle behavior.

1. Update `src/sase/agent/running.py` so `sase agents status` / all-listings include independent plan-chain records
   instead of skipping every `parent_timestamp` artifact. Continue skipping only true duplicate workflow children.
2. Update name lookup and workflow completion behavior so both phase names and root workflow references resolve:
   - exact `<name>.plan`, `<name>.q`, `<name>.<N>`, `<name>.coder`
   - root `<name>` workflow references
   - legacy `<name>.code`
3. Audit kill, dismiss, revive, wait, and cleanup behavior so selecting one phase has predictable single-phase scope,
   while root/bulk operations can still operate across the full chain when intended.
4. Update resume behavior that currently searches `followup_agents` for `.code` so it handles `.coder` and independent
   phase rows directly.
5. Address the existing rename TODO around workflow children of renamed parents so phase names stay coherent after a
   root rename or dismissed-prefix rewrite.

Acceptance criteria:

- `%wait:<name>.coder` and `#resume:<name>.coder` resolve.
- `sase agents status --all` can show phase records.
- Dismiss/revive keeps root and phase names consistent, including dismissed-prefix rewrites.
- Legacy `.code` lookup remains supported.

Verification:

- `pytest tests/test_running_agents_snapshot.py tests/test_agent_names_workflow.py tests/test_agent_names.py tests/test_dismissed_agent_lifecycle.py tests/test_agent_revive.py tests/test_core_facade/test_agent_cleanup.py`

## Phase 5: Detail Panels, Chat Links, And Compatibility Polish

Owned area: user-facing details and compatibility fixtures.

1. Update prompt/detail panels so parent summary views do not rely on child-row assumptions. Consolidated root replies
   can remain as summary affordance, but independent phase rows should each display their own prompt/reply/files.
2. Update chat-link labels and history suffixes to use `.coder` for new phases while preserving `.code` links in old
   histories.
3. Confirm plan files, Q&A responses, feedback plans, diffs, PDFs, and image attachments attach to the correct
   independent phase row.
4. Update any tests/help/copy that hard-code `.code` or describe plan-chain entries as child rows.
5. Add compatibility fixtures covering old `.code` and `parent_timestamp`-only metadata.

Acceptance criteria:

- Selecting each independent phase row shows the correct prompt, reply, files, and timestamps.
- Root plan rows retain useful summary data without hiding the independent phases.
- Old plan-chain history still renders.

Verification:

- `pytest tests/history/test_chat_links.py tests/history/test_chat_extras.py tests/test_agent_model_bundle.py tests/ace/tui/widgets/test_agent_display.py tests/ace/tui/widgets/test_agent_display_header_only.py`

## Phase 6: End-To-End Validation

Owned area: final cross-phase verification.

1. Run a real local named-agent chain that asks a question, submits a plan, receives feedback, submits a revised plan,
   and launches a coder.
2. Verify `sase ace` shows independent entries with the expected names:
   - `<name>.plan`
   - `<name>.q`
   - `<name>.2`
   - `<name>.coder`
3. Manually verify selection, detail panels, chat links, kill/dismiss, revive, resume, wait, grouping, and hidden-agent
   behavior.
4. Run repository checks from this workspace:
   - `just install`
   - `just check`
5. Remove or rewrite tests that only asserted the old child-row rendering, while keeping compatibility coverage for old
   artifacts.

## Implementation Notes

- Do not remove support for `.code`; treat it as a legacy input alias indefinitely.
- Avoid runtime-specific branches. Claude, Gemini, Codex, and plugin runtimes should all share the same metadata and
  naming behavior.
- Keep artifact schema changes additive until old-artifact compatibility is covered.
- Be careful with `parent_timestamp`: today it means both “workflow child” and “handoff lineage.” The key design work is
  separating those concepts without breaking existing artifacts.
- If any phase changes `sase ace` options or key/help text, update the `?` help popup per `src/sase/ace/AGENTS.md`.
