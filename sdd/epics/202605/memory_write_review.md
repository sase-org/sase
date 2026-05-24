---
create_time: 2026-05-23 18:00:32
status: done
bead_id: sase-42
tier: epic
prompt: sdd/prompts/202605/memory_write_review.md
---
# Plan: `sase memory write` and `sase memory review`

## Goal

Add a proposal-and-review workflow for long-term memories:

- Agents can run `sase memory write` to propose durable long-term memory with one or more evidence items.
- Users can run `sase memory review` to list, inspect, reject, approve, or approve with edits.
- The first implementation must keep proposal state outside ephemeral workspaces, never let `write` modify canonical
  `memory/long/*.md`, and preserve a clear audit trail.

This plan follows `sdd/research/202605/sase_memory_write_review_commands.md` and is split so each phase can be handled
by a distinct agent instance. Each phase should be committed independently through the normal SASE commit workflow when
that phase is complete.

## Current Code Anchors

- CLI parser: `src/sase/main/parser_memory.py`
- CLI dispatch: `src/sase/main/memory_handler.py`
- Existing read audit storage: `src/sase/memory/read_log.py`
- Existing read/list/log handlers: `src/sase/memory/cli_read.py`, `src/sase/memory/cli_list.py`,
  `src/sase/memory/cli_log.py`
- Memory inventory and reachability: `src/sase/memory/inventory.py`
- Dynamic long-memory loader: `src/sase/xprompt/loader_memory.py`
- Textual review precedents: `src/sase/ace/tui/modals/mentor_review_modal.py`,
  `src/sase/ace/tui/modals/plan_approval_modal.py`, `src/sase/ace/tui/modals/approve_options_modal.py`
- Notification and telemetry hooks for the polish phase: `src/sase/notifications/store.py`,
  `src/sase/telemetry/metrics.py`

Per `memory/short/rust_core_backend_boundary.md`, the v1 implementation can remain Python-only because no other frontend
consumes proposal state yet. Keep the event schema stable and dataclass-backed so it can move behind `sase-core` later
without changing CLI semantics.

## Phase 1: Proposal Domain Model and `sase memory write`

Owner scope:

- `src/sase/memory/proposals.py`
- `src/sase/memory/cli_write.py`
- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- Focused tests under `tests/test_memory_proposals.py` and `tests/main/test_memory_parser_handler.py`

Implement the pure storage/domain layer first, with no Textual or Rich imports in `proposals.py`.

Required behavior:

- Store proposal state under `~/.sase/projects/<project>/`, using:
  - `memory_proposals.jsonl` as an append-only ledger.
  - `memory_proposals.lock` as the lock companion.
  - `memory_proposals/<proposal_id>/draft.md` for the proposed body.
- Use `fcntl.flock` via the existing `read_log._locked` helper or an extracted shared helper.
- Define frozen dataclasses for proposal events, evidence records, warnings, and reduced proposal state.
- Generate ids shaped like `mem-YYYYMMDD-HHMMSS-<8hex>`.
- Parse evidence into typed records:
  - Path evidence with resolved path, existence flag, byte count, and SHA-256 when available.
  - `chat:<id>` evidence.
  - `url:<url>` or `https?://...` evidence.
  - `note:<text>` evidence only as supplemental evidence.
- Reject proposals with no evidence, blank evidence, or only note evidence.
- Require an attributable agent by default by reusing `require_agent_identity()`.
- Permit explicit manual authors only through visible CLI flags intended for tests/demos, never anonymous writes.
- Validate target paths as one-level `long/<slug>.md`; reject absolute paths, traversal, nested paths, non-`.md`, and
  invalid slugs.
- Accept `--title`, repeatable `--evidence`, `--target` or `--slug`, repeatable `--keyword`, `--from-chat`, `--file`,
  `--body`, stdin, `--allow-large`, and `--json`.
- Enforce body size caps: warn above 16 KiB unless `--allow-large`; reject above 256 KiB.
- Record prompt-injection warning matches in the proposal event, but do not block on warnings.
- Emit deterministic JSON for `--json`; otherwise print a concise human-readable proposal id, status, target, body path,
  and ledger path.

Acceptance tests:

- Parser registers `memory write` with the expected flags and rejects missing required evidence.
- `write` rejects invalid targets, missing body, oversized body, anonymous agent writes, and note-only evidence.
- `write` creates `draft.md`, appends stable JSONL, hashes path evidence, preserves keyword order while deduplicating,
  and reduces to a pending state.
- Ledger reading skips malformed rows without failing.
- `git diff --check`, targeted pytest for new proposal tests, then `just install && just check`.

Phase 1 should not implement review, canonical memory writes, notifications, telemetry, or Textual UI.

## Phase 2: Non-Interactive `sase memory review`

Owner scope:

- `src/sase/memory/proposals.py`
- `src/sase/memory/cli_review.py`
- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- Tests under `tests/test_memory_proposals.py`, `tests/main/test_memory_review.py`,
  `tests/main/test_memory_parser_handler.py`, and help tests as needed

Build on Phase 1's reducer and event model. Keep this phase CLI-only.

Required command surface:

- `sase memory review --list [--json] [--all]`
- `sase memory review PROPOSAL_ID --show [--json]`
- `sase memory review PROPOSAL_ID --approve [--target long/topic.md] [--edited-file edited.md] [--json]`
- `sase memory review PROPOSAL_ID --edit [--target long/topic.md] [--json]`
- `sase memory review PROPOSAL_ID --reject --reason "..." [--json]`

Required behavior:

- Resolve proposal ids by exact id or unambiguous prefix.
- Make `--list`, `--show`, `--approve`, `--edit`, and `--reject` mutually exclusive.
- Default `sase memory review` to launching the TUI only after Phase 3. In Phase 2, when no action is supplied, print a
  clear message that interactive review is not implemented yet and suggest `--list`.
- Record reviewer identity with `getpass.getuser()` and `socket.gethostname()`.
- Refuse approvals/rejections when an agent identity is present in the environment, so agents cannot self-approve.
- `--reject` requires a non-empty reason and appends a `rejected` event.
- `--approve` writes a new canonical file under `memory/long/<slug>.md`.
- Canonical file frontmatter should be compact:
  - `keywords` from the proposal, when present.
  - `source_candidate: <proposal_id>`.
- Do not embed full evidence in canonical memory files.
- Refuse existing targets by default. Use exclusive create semantics so concurrent reviewers cannot clobber each other.
- `--edited-file` copies the edited body to `reviewed.md`, writes that content to the canonical target, and records
  `approved_with_edits`.
- `--edit` opens `$VISUAL`/`$EDITOR` on `reviewed.md`, validates after return, then approves. If no editor is set, fail
  clearly.
- After approval, call `build_memory_inventory()` or equivalent reachability checks and warn if the new memory is only
  available but not loaded or dynamically discoverable. In particular, missing `keywords` frontmatter should be called
  out because `loader_memory.py` skips such files.
- Provide deterministic `--json` for every non-interactive path.

Acceptance tests:

- Listing pending and all proposals is deterministic.
- Show returns full proposal detail including evidence and warnings.
- Prefix resolution handles exact, unknown, and ambiguous ids.
- Reject records reviewer fields and reason.
- Approve writes frontmatter/body correctly, refuses existing targets, and records approval.
- Approve with edited file records `approved_with_edits`.
- Agent self-approval guard fails when `SASE_AGENT_NAME` or `SASE_AGENT` is set.
- `--edit` is covered with a fake editor script.
- `git diff --check`, targeted pytest for review tests, then `just install && just check`.

Phase 2 should not add the Textual app, notifications, telemetry, or log integration.

## Phase 3: Interactive Textual Review App

Owner scope:

- `src/sase/memory/review_tui.py`
- `src/sase/memory/cli_review.py`
- Textual-focused tests under `tests/main/test_memory_review_tui.py` or `tests/test_memory_review_tui.py`

Build the terminal review experience on top of Phase 2's CLI/domain APIs. Avoid duplicating storage or approval logic
inside widgets.

Required behavior:

- `sase memory review` launches the app only on a TTY.
- On non-TTY, fall back to a static pending list or a clear suggestion to use `--list`.
- First screen:
  - Proposal table with pending proposals by default.
  - Columns for status, age/time, author, target, evidence count, and title.
  - Right-side detail/preview pane for the selected proposal.
- Drill-down view:
  - Sections for Memory, Evidence, Target, and Audit.
  - Markdown preview for the body.
  - Evidence rows with typed status and small excerpts for path evidence.
  - Target status and unified diff when the target exists.
  - Audit details from the ledger events.
- Keybindings:
  - `j/k`, arrows, `g/G` navigation.
  - `/` filter.
  - `enter` or `d` drill down.
  - `escape` back from drill-down.
  - `a` approve.
  - `e` edit then approve through `$EDITOR`.
  - `r` reject with a reason modal.
  - `t` edit target path before approval.
  - `y` copy proposal id when supported.
  - `q` quit.
- Reuse local modal/layout patterns from `MentorReviewModal`, `PlanApprovalModal`, `ApproveOptionsModal`, and
  `CopyModeForwardingMixin` where practical.
- Use Textual `DataTable` for proposal lists and `Markdown` or the local Rich markdown rendering pattern for previews.
- Surface warnings and approval/rejection failures in the app without corrupting the underlying ledger.

Acceptance tests:

- `App.run_test()` opens with pending proposal rows.
- Navigation changes the selected proposal and preview.
- Drill-down opens and exits.
- Reject modal dispatches to the same domain function as CLI rejection.
- Approve action dispatches to the same domain function as CLI approval, with failures surfaced.
- Edit path can be covered with a fake editor or factored callback.
- `git diff --check`, targeted Textual tests, then `just install && just check`.

Phase 3 should not change proposal schemas unless Phase 2 left an explicit gap.

## Phase 4: Memory Log, Notifications, Telemetry, and Docs

Owner scope:

- `src/sase/memory/cli_log.py`
- `src/sase/main/parser_memory.py`
- `src/sase/memory/cli_write.py`
- `src/sase/memory/proposals.py`
- `src/sase/notifications/*` only if needed for action labels/tests
- `src/sase/telemetry/metrics.py`
- User docs and parser help tests

This phase is polish and integration after the core workflow works.

Required behavior:

- Extend `sase memory log` with `--include proposals` so read logs remain the default but users can inspect proposal and
  review events in the same memory audit surface.
- Keep existing `sase memory log` JSON shape unchanged unless `--include proposals` is set.
- Add an opt-in `sase memory write --notify` flag. On successful proposal creation, best-effort append a
  `memory.proposed` notification carrying `proposal_id`; notification failures must not fail the write.
- Add telemetry stubs and metric definitions:
  - `MEMORY_PROPOSALS_PROPOSED`
  - `MEMORY_PROPOSALS_APPROVED` with `edited`
  - `MEMORY_PROPOSALS_REJECTED`
- Increment telemetry counters in the CLI/domain boundary, not inside TUI rendering code.
- Update help text examples for `write`, `review`, and `log --include proposals`.
- Add or update docs in the repo's existing CLI/user-doc location discovered by the phase owner. Do not modify
  `memory/short/*.md` or `memory/long/*.md` as documentation.

Acceptance tests:

- Existing memory log tests pass unchanged without `--include proposals`.
- Proposal-inclusive log JSON and Rich output include proposal/review events deterministically.
- `write --notify` attempts notification append with expected action data and ignores notification exceptions.
- Telemetry metric definitions initialize cleanly.
- Parser help includes the new examples and keeps subcommands sorted.
- `git diff --check`, targeted tests, then `just install && just check`.

## Phase 5: Hardening Pass and Cross-Phase Cleanup

Owner scope:

- Any files touched by Phases 1-4, but only for integration fixes and cleanup
- No new product surface unless needed to fix a documented gap

This final phase should be run by a fresh agent after the prior phases have landed.

Required checks:

- Exercise an end-to-end workflow in a temp project:
  - `sase memory write ... --json`
  - `sase memory review --list --json`
  - `sase memory review <id> --show --json`
  - `sase memory review <id> --approve --json`
  - `sase memory read long/<slug>.md --reason ...` from an attributed agent env
- Verify proposal state lives under `~/.sase/projects/<project>/` and does not dirty the workspace until approval.
- Verify canonical approval writes exactly one `memory/long/*.md` file and no `memory/short/*` files.
- Review all public dataclasses and JSON schemas for future `sase-core` migration friendliness.
- Confirm `sase memory review` behaves clearly in non-TTY contexts.
- Confirm target conflict and concurrent-review behavior fail safely.
- Run the full required validation: `just install && just check`.

Expected cleanup:

- Remove duplication that accumulated across handlers.
- Tighten error messages to be consistent with `sase memory read/log`.
- Ensure tests do not leak state into the real `~/.sase`.
- Update this plan or follow-up SDD notes only if implementation materially diverged.

## Implementation Guardrails

- Do not modify any files under `memory/short/` or existing `memory/long/` as part of implementation.
- Do not let `sase memory write` modify canonical memory files.
- Do not implement auto-approval or agent approval in v1.
- Do not support append/replace of existing memory targets in v1.
- Do not fetch URL evidence in v1.
- Keep storage/reducer code independent of Textual and Rich.
- Preserve existing behavior for `sase memory list`, `read`, and `log` unless a phase explicitly extends it.
- Every phase that touches source code must run `just install && just check` before completion.
