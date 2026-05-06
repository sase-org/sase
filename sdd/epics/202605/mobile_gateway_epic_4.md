---
legend_bead_id: sase-26
bead_id: sase-26.4
tier: epic
create_time: 2026-05-06 15:08:41
status: done
prompt: sdd/prompts/202605/mobile_gateway_epic_4.md
---

# Plan: Mobile MVP Epic 4 - Workflow Helper APIs

## Context

Epic 4 from `sdd/legends/202605/sase_mobile_mvp_legend.md` replaces Telegram slash-command helper flows with native
mobile gateway endpoints. The intended user-facing Android capabilities are native pickers for ChangeSpec tags,
xprompts, and beads, plus a way to start and monitor the SASE update worker from the phone.

The current base already includes the earlier mobile gateway shape:

- `../sase-core/crates/sase_gateway` serves the authenticated `/api/v1` gateway, pairing/session, SSE, notifications,
  notification actions, attachments, and agent lifecycle endpoints.
- This repo starts the gateway through `sase mobile gateway start` and has a hidden JSON bridge pattern under
  `sase mobile agent-bridge`.
- `src/sase/integrations/changespec_tags.py` already lists active ChangeSpec xprompt tags with project filtering and
  terminal-status exclusion, but it is not yet exposed through the mobile gateway.
- `src/sase/xprompt/catalog.py` already gathers all visible xprompts and can optionally render a PDF catalog.
- `src/sase/bead/workspace.py` and `src/sase/core/bead_read_facade.py` already provide merged read-only bead views
  across known project workspaces, backed by Rust bead bindings.
- `src/sase/integrations/chat_install.py` already starts the detached update worker and writes completion JSON records.

The Rust core/backend boundary applies: stable wire records, result semantics, endpoint routing, auth, audit, and SSE
event records belong in `../sase-core`; host-owned discovery and side effects stay in this repo behind fixed JSON bridge
operations. The gateway must expose product-shaped helper commands only. It must not accept arbitrary shell commands,
arbitrary host paths, arbitrary cwd, or user-supplied bridge argv from Android.

## Goal

Deliver authenticated mobile gateway endpoints for:

- listing active ChangeSpec workflow tags, optionally filtered by project;
- listing xprompts as structured records, with optional generated catalog PDF attachment metadata;
- listing and showing beads across known projects while preserving project-context resolution from mobile agent flows;
- starting the SASE update worker and polling update status by `job_id`;
- returning standardized helper command result records so Android can render partial success, skipped entries, warnings,
  and failures without parsing human prose.

## Non-Goals

- Android UI, Android local cache, or Android notification delivery. Those belong to Android epics.
- Mutating ChangeSpecs, xprompts, or beads from mobile. This epic is read-only for helpers except update start/status.
- Replacing the existing `sase changespec`, `sase xprompt`, `sase bead`, or update CLI behavior.
- Re-implementing ChangeSpec parsing, bead storage, or xprompt loading in gateway routes when structured Python/Rust
  APIs already exist.
- Running arbitrary shell commands for helper endpoints. The update worker may continue to execute the configured
  `chat_install.command` inside `chat_install.py`; mobile only starts/statuses that fixed worker.

## API Contract For This Epic

Add authenticated endpoints under `/api/v1`:

- `GET /changespec-tags`
- `GET /xprompts/catalog`
- `GET /beads`
- `GET /beads/{id}`
- `POST /update/start`
- `GET /update/{job_id}`

Use direct JSON success records and the existing `ApiErrorWire` error shape. Add helper-specific error codes only where
the existing gateway set is too vague, for example `helper_not_found`, `helper_unavailable`, `update_already_running`,
or `update_job_not_found`.

Every helper response should include:

- `schema_version`;
- the primary data payload;
- a common helper result object with `status`, `message`, `warnings`, `skipped`, and optional `partial_failure_count`;
- project/context metadata where relevant.

SSE should gain an `update_changed` or broader `helpers_changed` event for update job completion/status transitions. If
the first implementation only emits on `POST /update/start` and explicit status checks, document that limitation and
leave Android to poll `GET /update/{job_id}` after reconnect.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Keep mobile wire records, route auth, error mapping, audit calls, SSE payloads, and contract snapshots in
  `../sase-core`.
- Keep host helper discovery, PDF generation, bead workspace resolution, and update worker side effects in this repo
  behind fixed JSON bridge operations.
- Reuse existing structured APIs before considering subprocesses. If the Rust gateway invokes Python, it must do so via
  fixed `sase mobile helper-bridge <operation>` commands with JSON stdin/stdout.
- Do not introduce runtime-specific Claude/Gemini/Codex branches.
- Add tests in the same phase as behavior. Later agents should not have to backfill basic safety coverage.
- Every new public or hidden CLI argument needs both long and short options unless it is a subcommand name.
- If this repo changes, run `just install` first in the ephemeral workspace, then focused tests, then `just check`
  before handoff unless the phase is documentation-only.
- If `../sase-core` changes, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace`, or the equivalent repo `just` target if one exists.
- Refresh the gateway contract snapshot whenever route or wire shape changes.

## Phase 1: Rust Helper Wire Contract And Gateway Bridge Skeleton

Owner: one agent. Write scope: `../sase-core` only, primarily `crates/sase_gateway`.

Purpose: define stable mobile helper records and route skeletons before production host behavior is added.

Concrete work:

- Add mobile helper wire records for:
  - common `MobileHelperResultWire`;
  - ChangeSpec tag list request/response and entry records;
  - xprompt catalog request/response, entry records, stats records, and optional catalog attachment metadata;
  - bead list/show request/response and bead summary/detail records;
  - update start/status request/response and update job records.
- Extend `EventPayloadWire` with update/helper state-change events.
- Add helper-specific `ApiErrorCodeWire` entries only if existing codes cannot express the needed behavior precisely.
- Add a gateway-side `HelperHostBridge` trait or equivalent abstraction with unavailable and static/fake implementations
  for route tests.
- Register authenticated route skeletons for the six Epic 4 endpoints. Skeletons should call the fake/static bridge in
  tests and return typed `bridge_unavailable` in production until the Python bridge is wired.
- Add JSON snapshot tests, route auth tests, route success shape tests, error mapping tests, and SSE payload tests.
- Update `crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.

Acceptance:

- Rust tests prove JSON field names, enum tags, optional/null behavior, and helper error codes are stable.
- Authenticated fake-bridge route tests cover every new endpoint.
- Unauthenticated requests to helper endpoints fail with the existing auth error shape.
- No production host helper code is invoked in this phase.

## Phase 2: Python Helper Bridge And ChangeSpec Tag Endpoint

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: establish the production helper bridge pattern and expose the first read-only helper endpoint.

Concrete work:

- Add a hidden fixed JSON bridge namespace under `sase mobile`, for example `sase mobile helper-bridge`.
- Add bridge operation `changespec-tags` backed by `src/sase/integrations/changespec_tags.py`.
- Implement request parsing for project filters and optional limits without accepting arbitrary project files or host
  paths from mobile.
- Implement production gateway bridge invocation with safe argv and JSON stdin/stdout. Prefer a new
  `CommandHelperHostBridge` mirroring the established agent bridge pattern.
- Implement authenticated `GET /api/v1/changespec-tags` with query parameters for `project` and `limit` if supported by
  the wire contract.
- Preserve existing semantics: exact project filter, terminal status exclusion after suffix normalization, archive file
  mapping to main project file for workflow detection, and skipped entries returned structurally.
- Add Python tests for bridge JSON handling, project filtering, terminal status exclusion, workflow detection failure
  reporting, invalid request JSON, and parser dispatch.
- Add Rust route tests for command-backed bridge success, malformed bridge JSON, bridge exit failures, auth failure, and
  query-to-request mapping.

Acceptance:

- A paired curl client can call `GET /api/v1/changespec-tags` and receive active copyable tags such as `#gh:feature` or
  `#hg:feature`.
- Skipped ChangeSpecs are returned in the helper result instead of causing total endpoint failure.
- Existing `list_changespec_xprompt_tags()` behavior and tests remain compatible.

## Phase 3: Xprompt Catalog Endpoint And Optional PDF Attachment

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: expose a structured xprompt catalog for Android pickers while preserving optional PDF generation as an
attachment-like enhancement.

Concrete work:

- Add a pure structured catalog projection in or near `src/sase/xprompt/catalog.py` that reuses `_gather_entries()` and
  `_compute_stats()` but does not require a PDF engine.
- Include entry fields useful for Android:
  - name;
  - display label;
  - description;
  - source bucket;
  - project when applicable;
  - tags;
  - input signature;
  - skill flag;
  - content preview capped to a conservative length;
  - source-path display only when safe to show.
- Add bridge operation `xprompt-catalog` with filters for project/source/tag/query where practical.
- Support optional PDF generation only when explicitly requested, returning generated path metadata through a safe
  manifest record. If no PDF engine is available, return a warning/skipped entry rather than failing the structured
  catalog.
- Implement authenticated `GET /api/v1/xprompts/catalog`.
- Add Python tests around structured projection, filters, no-PDF-engine warning behavior, and project-local xprompt
  discovery with mocked loaders.
- Add Rust route/contract tests for the xprompt catalog response shape and bridge error mapping.

Acceptance:

- Android can build a native picker from structured xprompt records without downloading or parsing a PDF.
- Optional PDF generation is best-effort and never blocks the structured catalog.
- The endpoint does not expose arbitrary file contents beyond intentional capped xprompt previews.

## Phase 4: Bead List/Show Endpoints Across Known Projects

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: expose bead list/show helper flows while preserving SASE project-context resolution.

Concrete work:

- Add bridge operations `beads-list` and `beads-show`.
- Use existing bead read facades and workspace helpers:
  - `get_all_project_beads_dirs()` for cross-project/default mobile list behavior;
  - `get_project_beads_dirs_for_project(project)` for explicit project filters;
  - `MergedBeadView`/Rust read facades for merged read-only views.
- Define mobile bead summaries with id, title, status, type, tier, project, parent id, assignee, updated time,
  dependency counts, child counts when cheap, linked plan path metadata when available, and ChangeSpec fields.
- Define bead detail records with description, notes/design if present, dependencies, parent/children, status, linked
  plan metadata, and owning project/workspace context.
- Preserve project-context behavior from mobile agent flows: if a paired device has a remembered project context from
  list/launch in Epic 3, default bead list/show to that project when the request does not explicitly ask for all known
  projects. If that context store is not stable enough, keep default cross-project behavior and record the follow-up in
  docs.
- Return deterministic `not_found` for missing bead IDs and structured partial results if one project bead store cannot
  be read.
- Add Python tests for cross-project listing, explicit project filtering, status/type/tier filters, missing bead stores,
  merged duplicate IDs, show success, show not found, and project-context defaulting if implemented.
- Add Rust route/contract tests for `GET /beads` and `GET /beads/{id}`.

Acceptance:

- A paired curl client can list active beads across known projects and show a bead by ID.
- The endpoint uses Rust-backed bead read APIs through Python facades rather than shelling out to `sase bead`.
- Partial read failures are visible as structured warnings/skipped entries.

## Phase 5: Update Start/Status Endpoints And Completion Events

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: expose the existing SASE update worker through a safe mobile API with durable job status.

Concrete work:

- Add bridge operations `update-start` and `update-status`.
- Reuse `start_chat_install_worker()` for update start. Do not let mobile supply an install command or workspace path.
- Add a public structured status reader in `src/sase/integrations/chat_install.py` that can:
  - return `running` when the lock is held and no completion exists;
  - read completion JSON by `job_id`;
  - return `not_found` for unknown/expired jobs;
  - include log path display metadata without exposing raw log contents in the MVP.
- Consider a light state index under `~/.sase/chat_install/` if current completion-path discovery by job ID is not
  sufficient.
- Implement authenticated:
  - `POST /api/v1/update/start`;
  - `GET /api/v1/update/{job_id}`.
- Map `config_missing_command`, `workspace_resolution_failed`, `already_running`, `launched`, and `launch_failed` into
  stable mobile update statuses and API errors where appropriate.
- Emit update/helper SSE events on successful start and when a status check observes completion/failure. If passive file
  watching is too much for this epic, document that polling status is authoritative.
- Add Python tests for start mappings, status reader success/failure/running/not-found, malformed completion JSON, and
  no mobile-controlled command/workspace injection.
- Add Rust route tests for start/status success, already-running mapping, not-found mapping, audit logging, and event
  payload shape.

Acceptance:

- A paired curl client can start the update worker and poll by `job_id` until success/failure.
- Mobile cannot override `chat_install.command`, cwd, environment, or workspace through the endpoint.
- Completion/failure can be rendered by Android without parsing human log text.

## Phase 6: Unified Helper Result Model, Docs, Contract Gate, And E2E Smoke

Owner: one final integration/land agent after Phases 1-5 are merged.

Purpose: ensure the helper API surface is coherent, documented, and ready for Android implementation.

Concrete work:

- Reconcile all helper responses to the common `MobileHelperResultWire` conventions:
  - no human-text-only success paths;
  - partial success represented consistently;
  - skipped entries and warnings use stable codes where practical.
- Refresh and review:
  - `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`;
  - `../sase-core/crates/sase_gateway/README.md`;
  - `docs/mobile_gateway.md` or the nearest existing mobile gateway doc.
- Add curl examples for:
  - ChangeSpec tags filtered by project;
  - xprompt catalog structured response;
  - bead list and show;
  - update start/status.
- Add an end-to-end smoke path using temporary SASE home/project fixtures where practical:
  - pair a test client;
  - call all read-only helper endpoints;
  - start update through a fake/safe worker seam;
  - poll completion;
  - observe an update/helper event where implemented.
- Run the cross-repo verification gate:
  - this repo: `just install && just check`;
  - Rust repo: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo test --workspace`.

Acceptance:

- Android has stable contracts for native ChangeSpec, xprompt, bead, and update helper flows.
- The helper endpoints use structured APIs and fixed bridge commands, not ad hoc shell parsing.
- Docs clearly state limitations: read-only helper endpoints except update, optional PDF generation, polling as
  authoritative for update status if passive completion events are not yet implemented.

## Suggested Phase Dependencies

- Phase 1 is the root dependency for all later phases.
- Phase 2 depends on Phase 1.
- Phase 3 depends on Phase 1 and can run after Phase 2 without depending on Phase 2 internals beyond the bridge pattern.
- Phase 4 depends on Phase 1 and should follow Phase 2 so it can reuse the production helper bridge.
- Phase 5 depends on Phase 1 and should follow Phase 2 so it can reuse the production helper bridge.
- Phase 6 depends on Phases 2-5.

## Overall Definition Of Done

- `GET /changespec-tags`, `GET /xprompts/catalog`, `GET /beads`, `GET /beads/{id}`, `POST /update/start`, and
  `GET /update/{job_id}` are authenticated, audited, documented, tested, and present in the mobile API contract
  snapshot.
- Android can present native pickers for ChangeSpec tags, xprompts, and beads without parsing Telegram-style text or
  PDFs.
- Android can start a SASE update and later render completion/failure status from structured records.
- Helper endpoints do not shell out when existing structured APIs are available; any remaining subprocess boundary is
  the fixed gateway-to-SASE bridge or the pre-existing configured update worker.
