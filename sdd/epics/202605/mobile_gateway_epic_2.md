---
create_time: 2026-05-06 11:21:20
status: done
prompt: sdd/prompts/202605/mobile_gateway_epic_2.md
bead_id: sase-26.2
legend_bead_id: sase-26
tier: epic
---

# Plan: Mobile MVP Epic 2 - Notification Inbox, Pending Actions, And Attachments

## Context

Epic 2 from `sdd/legends/202605/sase_mobile_mvp_legend.md` exposes Telegram-equivalent outbound notification behavior
through the workstation gateway created by Epic 1. Epic 1 is already present as `sase-26.1` with
`sdd/epics/202605/mobile_gateway_epic_1.md`, and the current base includes:

- `../sase-core/crates/sase_gateway` with authenticated `/api/v1/health`, pairing/session, and `/api/v1/events`.
- `../sase-core/crates/sase_core/src/notifications/*` with Rust-backed JSONL notification reads and state updates.
- This repo's `src/sase/notifications/*` Python facade and CLI catalog helpers over
  `~/.sase/notifications/notifications.jsonl`.
- TUI action handlers in `src/sase/ace/tui/actions/agents/_notification_modals.py` that unblock agents by writing
  `plan_response.json`, `hitl_response.json`, and `question_response.json`.
- Telegram pending-action behavior in `../sase-telegram`, especially `pending_actions.py`, `formatting.py`, and
  `inbound.py`. This epic should use those semantics as reference material, not create a mobile-only duplicate.

The architectural boundary from repo memory applies: deterministic models, action-state decisions, stale detection, and
response-file intent planning belong in `../sase-core/crates/sase_core` or gateway wire modules. Host filesystem writes,
agent metadata side effects, and compatibility with existing Python notification storage belong in this repo behind a
thin bridge. The phone remains an authenticated client; it must not receive arbitrary host file access or generic shell
execution.

## Goal

Deliver gateway endpoints that let a paired client list and inspect notifications, understand whether an action is
currently available/stale/handled, perform plan/HITL/question responses that unblock the same agents as TUI and
Telegram, and download declared attachments through short-lived authenticated tokens.

## Non-Goals

- Android UI, local notifications, SSE client work, or push hints. Those belong to later Android/hardening epics.
- Agent launch, kill, retry, image input, ChangeSpec/xprompt/bead/update helper APIs. Those belong to Epics 3 and 4.
- Replacing Telegram immediately. Telegram should continue to work and can migrate to shared pending-action APIs after
  this epic lands.
- Arbitrary host file browsing. Attachments are limited to files already attached to notifications or action request
  manifests.
- Full content rendering parity with Telegram Markdown/PDF formatting. Mobile receives structured records and attachment
  metadata; presentation belongs to Android.

## API Contract For This Epic

Add or complete these authenticated endpoints under `/api/v1`:

- `GET /notifications`
- `GET /notifications/{id}`
- `POST /notifications/{id}/mark-read`
- `POST /notifications/{id}/dismiss`
- `GET /attachments/{token}`
- `POST /actions/plan/{prefix}/approve`
- `POST /actions/plan/{prefix}/run`
- `POST /actions/plan/{prefix}/reject`
- `POST /actions/plan/{prefix}/epic`
- `POST /actions/plan/{prefix}/legend`
- `POST /actions/plan/{prefix}/feedback`
- `POST /actions/hitl/{prefix}/accept`
- `POST /actions/hitl/{prefix}/reject`
- `POST /actions/hitl/{prefix}/feedback`
- `POST /actions/question/{prefix}/answer`
- `POST /actions/question/{prefix}/custom`

Every mutating endpoint must authenticate, audit device/endpoint/target/outcome, validate that the action still matches
the pending notification, and return deterministic API errors for missing, duplicate, stale, or already-handled actions.
SSE should publish notification-state events with stable IDs and enough metadata for Android to know when to refresh,
but the REST list/detail response remains authoritative.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Keep deterministic action matching, stale/handled detection, response payload construction, attachment manifest
  filtering, and JSON wire records in Rust where practical.
- Keep Python as host bridge code for filesystem writes, plan archiving side effects, notification-store path
  resolution, and integration with existing SASE modules.
- Do not introduce runtime-specific Claude/Gemini/Codex branches.
- Do not shell out when a structured API exists.
- Add tests in the same phase as behavior. Later phases should not be expected to backfill basic safety coverage.
- If this repo changes, run `just install` first in the ephemeral workspace, then focused tests, then `just check`
  before handoff unless the phase is documentation-only.
- If `../sase-core` changes, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace`, or the equivalent repo `just` target if one exists.
- If `../sase-telegram` is touched, run its `just check` before handoff.

## Phase 1: Rust Mobile Notification And Action Wire Contract

Owner: one agent. Write scope: `../sase-core` only, primarily `crates/sase_core` and `crates/sase_gateway`.

Purpose: define stable mobile notification, action, and attachment records before endpoint behavior is added.

Concrete work:

- Add mobile notification wire structs for:
  - list page request/response and detail response;
  - notification card projection with id, timestamp, sender, priority/actionability flags, read/dismissed/silent/muted,
    notes summary, file count, and action summary;
  - action detail state for `PlanApproval`, `HITL`, `UserQuestion`, and non-action notifications;
  - pending-action identity using the notification ID prefix semantics currently used by Telegram, while making
    collision behavior explicit;
  - action-state values such as `available`, `already_handled`, `stale`, `missing_request`, `missing_target`, and
    `unsupported`;
  - attachment manifest records with id/token placeholder, display name, kind, MIME-ish content type, byte size when
    available, source notification id, and safe download capability flags.
- Add action request/response wire records for plan, HITL, and question endpoints. Include optional feedback/custom
  fields, selected option identifiers/labels, and a common `ActionResultWire`.
- Add deterministic response-intent planners in Rust that build the JSON data to be written later:
  - plan approve/run/reject/epic/legend/feedback;
  - HITL accept/reject/feedback;
  - question option/custom answers from `question_request.json` data supplied as bytes or a parsed value.
- Extend gateway `ApiErrorCodeWire` with action-specific deterministic errors such as conflict/already-handled,
  gone/stale, ambiguous-prefix, unsupported-action, and attachment-expired.
- Add JSON snapshot tests and committed contract snapshots for the new records.

Acceptance:

- Rust tests prove JSON field names, enum tags, null/default behavior, and error codes are stable.
- Response-intent planner tests cover every action choice listed in the legend and match the existing TUI/Telegram JSON
  shapes.
- No host files are read or written in this phase except test fixtures and contract snapshots.

## Phase 2: Host Notification Bridge And Read-Only Gateway Endpoints

Owner: one agent. Write scope: `../sase-core/crates/sase_gateway`, this repo's `src/sase/integrations/` and
`src/sase/notifications/`, plus focused tests.

Purpose: expose notification list/detail over the authenticated gateway without mutating pending actions yet.

Concrete work:

- Add a Python bridge module, likely `src/sase/integrations/mobile_notifications.py`, that:
  - resolves the active notifications JSONL path using existing notification store settings;
  - returns read-only notification rows and counts through the Rust-backed notification store facade;
  - preserves current dismissed/silent/read/muted behavior and home-path normalization where appropriate;
  - returns enough raw absolute host paths for the gateway to build attachment manifests while keeping display paths
    safe.
- Add a gateway-side host bridge abstraction so route tests can run against a fake bridge and product runs can call the
  Python bridge through the integration mechanism chosen by Epic 1. If Epic 1 left no Python-call mechanism in Rust,
  keep the boundary explicit and implement a small local adapter rather than embedding ad hoc CLI parsing in routes.
- Implement authenticated:
  - `GET /api/v1/notifications` with filters for unread, include dismissed, include silent, limit, high-water/newer-than
    if the event contract needs it, and deterministic newest-first ordering;
  - `GET /api/v1/notifications/{id}` including full notes, action detail, request-file-derived question options where
    available, and attachment manifest placeholders without download tokens yet.
- Derive mobile priority/actionability from the existing priority rules plus the new action state model.
- Publish `notification_changed` or `notifications_changed` SSE events when the gateway observes a state-changing host
  bridge result. If true file watching is too much for this phase, document and test explicit publication from gateway
  route mutations and keep passive polling for later.
- Update contract snapshots and gateway README notes for list/detail shapes.

Acceptance:

- A paired curl client can list and inspect notification types that currently exist in the SASE notification store:
  plan, HITL, user question, workflow complete, axe error digest, image/generic, and ChangeSpec/mentor jump actions.
- Route tests cover auth failure, empty store, unread/dismissed/silent filters, detail not found, priority/actionability
  metadata, and stable SSE event payload shape.
- This repo focused tests cover the Python bridge against temporary notification stores.

## Phase 3: Host-Generic Pending Action Store And Stale/Handled Detection

Owner: one agent. Write scope: mostly `../sase-core`, with this repo bridge hooks and optional `../sase-telegram`
compatibility adapters if needed.

Purpose: move Telegram's pending-action concept into host-generic storage so mobile and Telegram can share matching and
cleanup semantics instead of racing on separate state.

Concrete work:

- Design and implement a host-generic pending action store under a SASE-owned location such as
  `~/.sase/pending_actions/actions.json`, keeping Telegram's current `~/.sase/telegram/pending_actions.json` as a
  compatibility source during migration.
- Store pending entries keyed by notification prefix and backed by the full notification id, action kind, action_data,
  attached file list, created/updated timestamps, stale deadline, originating transport records, and current state.
- Add atomic writes and locking suitable for multiple transports and the gateway process.
- Add deterministic prefix resolution:
  - exact full notification id wins;
  - unique prefix succeeds;
  - ambiguous prefix returns a deterministic error;
  - stale entries are cleaned without deleting unrelated transport metadata prematurely.
- Add external-handled detection equivalent to Telegram's `find_externally_handled()`:
  - plan handled if `plan_response.json` exists, `plan_approved.marker` exists, or the request file was consumed;
  - HITL handled if `hitl_response.json` exists or the request is no longer actionable;
  - question handled if `question_response.json` exists or the request is no longer actionable.
- Ensure new notifications create or mirror pending entries. Prefer adding shared core/Python sender-side registration
  when `append_notification()` writes actionable notifications; if that is too risky, add an explicit bridge refresh
  that indexes actionable notifications before list/detail/action requests.
- Add a compatibility plan for `../sase-telegram`:
  - either teach Telegram to call the shared pending store in this phase, or leave a small adapter and document the
    expected follow-up;
  - do not break existing Telegram tests or pending callback behavior.

Acceptance:

- Tests cover stale cleanup, ambiguous prefixes, duplicate notification prefixes, external-handled detection for
  plan/HITL/question, compatibility with existing Telegram pending JSON shape, and concurrent-ish atomic writes.
- Gateway list/detail can surface `available`, `stale`, and `already_handled` action states without performing a
  mutation.
- Telegram remains functional if `../sase-telegram` is installed.

## Phase 4: Plan Action Mutations And Host Side Effects

Owner: one agent. Write scope: `../sase-core`, this repo bridge modules/tests, and gateway routes. Avoid Telegram edits
unless Phase 3 established a shared adapter requiring a small call-site change.

Purpose: implement the plan approval endpoints first because they are the highest-value and have the most side effects.

Concrete work:

- Implement authenticated plan endpoints:
  - `POST /actions/plan/{prefix}/approve`;
  - `POST /actions/plan/{prefix}/run`;
  - `POST /actions/plan/{prefix}/reject`;
  - `POST /actions/plan/{prefix}/epic`;
  - `POST /actions/plan/{prefix}/legend`;
  - `POST /actions/plan/{prefix}/feedback`.
- Use the Rust action planner from Phase 1 to produce response JSON. Python should execute the write atomically to
  `plan_response.json` only after stale/already-handled checks pass.
- Preserve existing TUI/Telegram semantics:
  - approve writes `{"action": "approve"}` plus optional `commit_plan`, `run_coder`, `coder_prompt`, and `coder_model`
    where supplied;
  - run maps to approve with `commit_plan=false` and `run_coder=true`;
  - feedback maps to reject with feedback text;
  - epic and legend actions write those exact action names.
- Implement best-effort non-critical side effects through a reusable Python host function:
  - mark the notification dismissed after a successful response write;
  - persist plan approval metadata in `agent_meta.json` when the matching agent can be resolved;
  - archive approved epic/legend/tale plan files into SDD paths when the same existing helper can be reused safely;
  - never delay the response-file write on archiving or metadata side effects.
- Add deterministic conflict behavior: if another transport already wrote a response file between check and write,
  return an already-handled/conflict error rather than overwriting.
- Audit every action attempt with device id, endpoint, prefix/full notification id, and outcome.

Acceptance:

- Route and bridge tests cover approve, run, reject, epic, legend, feedback, missing response_dir, missing plan request,
  no plan file, already-handled response file, externally consumed request, ambiguous prefix, and notification
  dismissal.
- Response-file JSON exactly matches existing SASE consumers.
- The agent-unblocking response write happens before slow plan archiving or metadata work.

## Phase 5: HITL And Question Action Mutations

Owner: one agent. Write scope: `../sase-core`, this repo bridge modules/tests, and gateway routes.

Purpose: complete the remaining user-blocking action endpoints after the shared pending/action machinery is in place.

Concrete work:

- Implement authenticated HITL endpoints:
  - `POST /actions/hitl/{prefix}/accept`;
  - `POST /actions/hitl/{prefix}/reject`;
  - `POST /actions/hitl/{prefix}/feedback`.
- Implement authenticated question endpoints:
  - `POST /actions/question/{prefix}/answer`;
  - `POST /actions/question/{prefix}/custom`.
- For HITL, write `hitl_response.json` using the same shape consumed by `workflow_hitl.py`:
  - accept: `{"action": "accept", "approved": true}`;
  - reject: `{"action": "reject", "approved": false}`;
  - feedback: `{"action": "feedback", "approved": false, "feedback": "..."}` unless the Rust planner finds a current
    consumer requiring a different approved value.
- For question answers, read and validate `question_request.json` through the host bridge, then use the Rust planner to
  build `question_response.json` with `answers` and `global_note`. Support option selection by stable option id when
  present, by index for Telegram parity, and custom free text.
- Dismiss the notification and refresh pending action state only after successful writes.
- Return deterministic errors for malformed question requests, invalid option index/id, stale request files, duplicate
  writes, and unsupported action kinds.
- Emit notification/action SSE events for successful mutations and conflict/stale transitions where useful.

Acceptance:

- Tests cover HITL accept/reject/feedback and question option/custom responses against temporary artifact directories.
- A curl client can unblock a waiting HITL workflow and an AskUserQuestion hook in the same way the TUI and Telegram
  can.
- Duplicate, stale, invalid option, and already-handled requests do not overwrite response files.

## Phase 6: Attachment Manifests And Short-Lived Downloads

Owner: one agent. Write scope: `../sase-core/crates/sase_gateway`, this repo bridge modules/tests, and docs/snapshots.

Purpose: expose safe authenticated attachment downloads for notification files and action request artifacts.

Concrete work:

- Build attachment manifests for:
  - notification `files`;
  - plan markdown files and any generated PDF path already present;
  - HITL request output files when request metadata marks values as path-typed;
  - question request files only if useful and not sensitive beyond the notification action;
  - diffs, images, error digest files, generic text/PDF/doc files.
- Classify kind/content type from extension and lightweight file inspection where appropriate. Keep detection
  deterministic and conservative.
- Add a token store for short-lived attachment tokens:
  - token maps to canonical absolute host path plus notification/action identity;
  - token TTL is short and configurable for tests;
  - token is bound to authenticated device or otherwise revalidated against the bearer token at download time;
  - tokens are never logged in full.
- Implement `GET /api/v1/attachments/{token}` with:
  - authentication;
  - canonical path validation against the manifest entry;
  - no path traversal or arbitrary path expansion;
  - content length/type headers where known;
  - deterministic errors for expired/missing/path-gone tokens.
- Decide whether detail/list responses mint tokens eagerly or expose a manifest endpoint/mint action. Prefer short-lived
  eager tokens only for detail responses; list cards should usually show counts/kinds without tokens.
- Add file-size limits and document behavior for files too large for MVP download.

Acceptance:

- Tests cover manifest construction, missing files, `~` normalization, symlink/path traversal rejection, token expiry,
  token/device auth, content type/length headers, and download of markdown, PDF, diff, digest, and image fixtures.
- Attachment URLs are useless without gateway authentication and expire predictably.
- Android can render a detail view with file metadata and download a selected attachment.

## Phase 7: Integration, Documentation, And Contract Gate

Owner: one final integration/land agent after Phases 1-6 are merged.

Purpose: verify Telegram-parity notification behavior end to end and leave a clean contract for Android Epic 5/6 agents.

Concrete work:

- Refresh gateway contract snapshots and document all notification/action/attachment routes in the gateway README and
  this repo's mobile gateway docs.
- Add curl examples for:
  - list unread notifications;
  - inspect a plan approval detail;
  - approve/run/reject/feed back on a plan;
  - accept/reject/feed back on HITL;
  - answer a question with an option and custom text;
  - download an attachment.
- Add an end-to-end smoke harness or script using temporary SASE home/artifact dirs that:
  - appends representative notifications;
  - pairs a client;
  - lists and details notifications;
  - performs one plan, one HITL, and one question action;
  - verifies response files and notification state;
  - downloads at least one attachment.
- Run cross-repo verification:
  - this repo: `just install && just check`;
  - Rust repo: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo test --workspace`;
  - Telegram repo `just check` if any compatibility code changed.
- Record known limitations in the plan or docs, especially around passive notification file watching, large attachments,
  and any Telegram pending-action migration that remains incomplete.

Acceptance:

- A paired curl client can see all notification types described in Telegram docs/tests and perform every user-blocking
  plan/HITL/question action listed in the legend.
- Duplicate, stale, ambiguous-prefix, and already-handled actions return deterministic API errors instead of overwriting
  state.
- Contract snapshots are current enough for independent Android agents to implement against them.

## Suggested Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_mobile_gateway_epic_2.md`: add the Rust mobile notification/action/attachment wire
> contract and response-intent planners in `../sase-core`, with JSON snapshot tests and contract snapshots. Do not add
> gateway endpoint behavior yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_mobile_gateway_epic_2.md`: add the Python host notification bridge and authenticated
> read-only gateway notification list/detail endpoints, including actionability metadata and notification SSE event
> shapes.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_mobile_gateway_epic_2.md`: move pending-action storage and stale/already-handled
> detection into host-generic shared storage, preserving Telegram compatibility and adding deterministic prefix
> resolution tests.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_mobile_gateway_epic_2.md`: implement plan action endpoints through the gateway and
> Python host bridge, writing `plan_response.json` safely and preserving TUI/Telegram side-effect semantics.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_mobile_gateway_epic_2.md`: implement HITL and question action endpoints through the
> gateway and Python host bridge, with stale/duplicate/error handling and response-file parity tests.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_mobile_gateway_epic_2.md`: add attachment manifests, short-lived authenticated
> download tokens, and `GET /api/v1/attachments/{token}` with path-safety and expiry tests.

Phase 7 prompt:

> Implement Phase 7 from `sase_plan_mobile_gateway_epic_2.md`: refresh docs and contract snapshots, add the cross-repo
> smoke harness, run the verification gate, and record final limitations.

## Final Definition Of Done

- A paired client can list and inspect notifications with unread, silent, dismissed, priority, high-water/actionability,
  and attachment metadata.
- Plan approve/run/reject/epic/legend/feedback, HITL accept/reject/feedback, and question option/custom responses
  unblock the same agents as TUI and Telegram flows.
- Pending actions are represented in host-generic storage or a documented compatibility adapter, with deterministic
  stale/already-handled behavior.
- Duplicate, stale, ambiguous, unsupported, and already-handled actions return stable API errors instead of overwriting
  state.
- Attachments are only downloadable through authenticated short-lived tokens generated from declared manifests.
- Telegram remains a working fallback.
