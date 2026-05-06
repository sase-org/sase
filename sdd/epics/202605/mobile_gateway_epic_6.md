---
bead_id: sase-26.6
legend_bead_id: sase-26
tier: epic
create_time: 2026-05-06 18:04:55
status: done
prompt: sdd/prompts/202605/mobile_gateway_epic_6.md
---

# Plan: Mobile MVP Epic 6 - Android Action, Agent, And Helper UX

## Context

Epic 6 from `sdd/legends/202605/sase_mobile_mvp_legend.md` turns the Android foundation into a useful Telegram-parity
client. The earlier mobile work establishes the host gateway, Android session layer, SSE/cache behavior, inbox/detail
screens, and the checked API contract. This epic should build on that foundation rather than change the host control
plane.

Current repository state:

- `../sase-android` is the primary implementation repo for this epic. It already contains a Kotlin/Compose app under
  package `org.sase.mobile`, manual/QR pairing, Keystore-backed token storage, `GatewayApiClient`, `GatewaySseClient`,
  `NotificationRepository`, inbox/detail/settings UI, fake gateway tests, and a copied gateway contract snapshot at
  `app/src/test/resources/contracts/mobile_api_v1.json`.
- The checked Android contract snapshot already lists the Epic 6 REST surface: plan/HITL/question action endpoints,
  agent list/resume/launch/image-launch/kill/retry endpoints, ChangeSpec/xprompt/bead helper endpoints, update
  start/status endpoints, attachment download, `agents_changed`, and `helpers_changed` events.
- `../sase-core` owns gateway wire contracts and host endpoint behavior. This epic should read the contract but should
  not redesign or mutate it unless an unavoidable drift bug is discovered and explicitly handed back to the gateway
  epics.
- This repo, `sase_100`, owns SASE planning/docs. It should only be touched for final documentation links or handoff
  notes. Most implementation phases should touch only `../sase-android`.

The product bar for Epic 6 is: a paired Android user can respond to actionable notifications, launch and manage agents,
pick workflow helpers, start/check updates, and recover cleanly from stale actions, disconnected host, expired auth,
launch/upload failures, and helper partial failures.

## Goal

Deliver Android UI, repositories, API client methods, fixtures, and tests for all foreground Telegram-parity workflows:

- Plan approval choices: approve, run, reject, epic, legend, feedback.
- HITL choices: accept, reject, feedback.
- User-question choices: option answer and custom answer.
- Two-step feedback/custom-answer UX with draft preservation and retry after transport or stale-state failures.
- Agent list, kill, retry, resume/wait affordances, and launch result display.
- Text launch with prompt editor, code-friendly input, project/helper insertion, and preservation of SASE model/runtime
  directive syntax.
- Image launch from camera/gallery/content URI without granting arbitrary host writes.
- ChangeSpec, xprompt, and bead helper pickers.
- Update start/status screen.

## Non-Goals

- Background push, foreground service behavior, Android notification permission UX, release packaging, or remote
  delivery hardening. Epic 7 owns those.
- Host gateway endpoint implementation or wire-contract redesign. Those belong to Epics 1-4.
- Running SASE locally on Android, embedding Rust core, arbitrary shell execution, arbitrary host file browsing, or
  generic RPC.
- Full attachment viewer/editor. This epic may add authenticated download/open affordances if needed for action context,
  but rich document rendering can remain a follow-up unless it blocks an action flow.
- Replacing Telegram immediately. Android should reach foreground functional parity while Telegram remains a fallback.

## Android Architecture Rules

- Keep using the existing package layout:
  - `data.api` and `data.api.dto` for DTOs and REST/SSE client methods.
  - New `data.actions`, `data.agents`, and `data.helpers` packages for repositories and domain state.
  - New `ui.actions`, `ui.agents`, `ui.launch`, and `ui.helpers` packages for Compose screens/components.
  - Existing `ui.notification.NotificationDetailScreen` should become the entry point for action controls; do not
    duplicate notification detail in a separate flow.
- Treat the gateway as authoritative. Drafts and recent launch results may be cached locally, but host state must be
  refreshed after mutations, reconnect, stale/conflict errors, and auth changes.
- Use structured `ApiErrorWire` and typed transport errors. Do not parse human error strings.
- Never log bearer tokens, pairing codes, attachment tokens, raw image bytes, or sensitive prompt contents.
- Keep request shapes product-specific. Android may send prompt text, selected helper IDs, option IDs, content URI
  bytes, model/provider/runtime text fields, and request IDs; it must not send arbitrary command argv, cwd, env, or host
  paths.
- Compose UI should stay utilitarian and dense: predictable navigation, compact status rows, icons for repeated actions,
  clear disabled/stale states, and no marketing surfaces.
- Add tests in the same phase as behavior. Later agents should not have to backfill basic DTO, repository, or UI safety
  coverage.

## Cross-Phase Rules

- Start every phase with `git status --short` in every repo it will touch and preserve unrelated dirty changes.
- Most phases should touch only `../sase-android`; this repo is for final docs/handoff only.
- Do not modify `../sase-core` in Epic 6 unless the implementing agent finds a blocking contract defect. If that
  happens, stop and produce a narrow gateway follow-up instead of silently changing host contracts from Android work.
- Keep the Android contract snapshot checked against
  `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`. Refresh fixtures only when the host contract
  has intentionally moved.
- Each implementation phase should run `./gradlew testDebugUnitTest lintDebug assembleDebug` from `../sase-android`
  unless it is documentation-only. Run `./gradlew connectedDebugAndroidTest` when an emulator/device is available.
- If this repo changes outside `sdd/beads/`, run `just install && just check` before handoff.

## Phase 1: Epic 6 DTOs, API Methods, Fixtures, And Fake Gateway Expansion

Owner: one agent. Write scope: `../sase-android` only.

Purpose: make the Android data/API layer understand the full Epic 6 contract before UI phases depend on it.

Concrete work:

- Add Kotlin serialization DTOs for:
  - `ActionResultWire`, `PlanActionRequestWire`, `HitlActionRequestWire`, `QuestionActionRequestWire`;
  - all agent list/resume/launch/image-launch/kill/retry request and response records;
  - all helper response records for ChangeSpec tags, xprompt catalog, bead list/show, update start/status, and common
    `MobileHelperResultWire`;
  - attachment download metadata only if the current DTO set is insufficient for opening/downloading selected files.
- Extend `GatewayApiClient` with typed methods for every Epic 6 endpoint:
  - plan/HITL/question action mutations;
  - `GET /agents`, `GET /agents/resume-options`, `POST /agents/launch`, `POST /agents/launch-image`,
    `POST /agents/{name}/kill`, `POST /agents/{name}/retry`;
  - `GET /changespec-tags`, `GET /xprompts/catalog`, `GET /beads`, `GET /beads/{id}`;
  - `POST /update/start`, `GET /update/{job_id}`;
  - `GET /attachments/{token}` if selected attachment download is implemented in later phases.
- Expand contract tests so they fail if any Epic 6 route disappears or changes method/path/auth expectation.
- Add representative JSON fixtures for:
  - action success, stale, already-handled, unsupported, and ambiguous-prefix results;
  - agent list, resume options, launch result with multiple slots, image launch result, kill, retry, and launch failure;
  - ChangeSpec tag list, xprompt catalog with warnings, bead list/show, update running/success/failure;
  - `agents_changed` and `helpers_changed` SSE events.
- Extend the existing fake gateway/MockWebServer harness to serve the new endpoints and validate auth headers, request
  bodies, path parameters, and common failure modes.
- Add unit tests for DTO fixture parsing, REST request encoding, response decoding, typed error mapping, and auth header
  behavior.

Acceptance:

- Android has typed, tested client coverage for all Epic 6 REST routes.
- Fake gateway fixtures can drive later repository/UI phases without a live SASE host.
- No user-facing UI behavior changes are required in this phase.

## Phase 2: Action Repository And Immediate Notification Action Controls

Owner: one agent. Write scope: `../sase-android` only.

Purpose: let notification detail execute the direct, one-tap/two-button action choices that do not require free-form
text entry.

Concrete work:

- Add `data.actions` repository/state models that:
  - derive action availability from `MobileActionDetailWire`;
  - call the correct plan/HITL/question endpoint with the notification prefix from the action identity;
  - map `ApiErrorWire` codes to UI states for stale, already handled, ambiguous prefix, unsupported, disconnected, auth
    expired, and bridge unavailable;
  - refresh notification detail and inbox after successful mutations and after stale/conflict failures.
- Add direct controls to `NotificationDetailScreen` for:
  - plan approve, run, reject, epic, and legend;
  - HITL accept and reject;
  - question option answer where choices are present and no custom text is required.
- Use confirmation only where the action is destructive or starts follow-up work. The action surface should remain fast
  for routine approve/accept/answer flows.
- Add result affordances:
  - success banner with response-file/action summary;
  - stale/already-handled state with a refresh action;
  - auth expired route to settings;
  - disconnected host retry action;
  - disabled controls for missing request/target/unsupported state.
- Add Compose previews and UI tests for available, stale, already-handled, missing, unsupported, and offline action
  states.
- Add repository tests with fake gateway success and deterministic failure fixtures.

Acceptance:

- A user can approve/run/reject/epic/legend a plan, accept/reject HITL, and answer a simple question option from Android
  notification detail.
- Duplicate/stale/already-handled action errors do not look like silent failures; the user sees the recovery path.
- Existing read/dismiss behavior still works.

## Phase 3: Feedback, Custom Answer, Draft Preservation, And Retry UX

Owner: one agent. Write scope: `../sase-android` only.

Purpose: complete the action flows that require user-entered text and make failure recovery safe.

Concrete work:

- Add a small local draft store for action text drafts keyed by notification ID, action kind, and choice. DataStore is
  sufficient unless the existing cache abstraction makes Room easier.
- Add two-step flows for:
  - plan feedback;
  - HITL feedback;
  - question custom answer;
  - question option answer with optional global note if the current contract/fixtures support it.
- Preserve drafts across rotation, process recreation, navigation away/back, and failed submit.
- Add submit retry behavior that reuses the draft after transport failures and refreshes host action state after stale,
  already-handled, ambiguous-prefix, and auth failures.
- Add clear discard semantics. Do not silently erase typed feedback unless the mutation succeeds or the user discards
  it.
- Add tests for draft persistence, discard, successful clear-after-submit, failed-submit preservation, stale refresh,
  and auth-expired routing.

Acceptance:

- A user can provide feedback/custom answers from Android without losing text on navigation or transient failures.
- Stale and already-handled responses refresh the detail view and keep the draft visible until the user decides what to
  do.

## Phase 4: Agents Repository, Agents Screen, Kill/Retry, And Resume/Wait UX

Owner: one agent. Write scope: `../sase-android` only.

Purpose: add the native agent-management surface before building launch flows.

Concrete work:

- Add `data.agents` repository/state models backed by the Phase 1 client methods:
  - list agents with running/recent/project/status filters where supported;
  - fetch resume/wait options;
  - kill agent;
  - retry agent;
  - react to `agents_changed` events by refreshing list state.
- Add an Agents tab or destination to app navigation. Keep bottom navigation manageable; if there are more than three
  primary areas, use a top-level route with tabs or a navigation drawer only if it fits the existing app style.
- Build an Agents screen with:
  - running/recent grouping or filters;
  - agent status, model/provider, project, duration, prompt snippet, retry lineage, and action affordances;
  - kill and retry actions with confirmations/result states;
  - resume/wait options as copy/share/direct-launch affordances;
  - empty, loading, offline, auth-expired, and bridge-unavailable states.
- Add recent launch result affordances if the repository has stored mobile launch results from later phases; otherwise
  define the state model now and leave empty until Phase 5.
- Add fake gateway tests and Compose UI tests for list, kill success/failure, retry success/failure, resume/wait option
  rendering, and `agents_changed` refresh.

Acceptance:

- A paired user can list agents, kill a running agent, retry an agent, and use resume/wait prompts from Android.
- Agent lifecycle failures are actionable and do not require memorizing CLI commands.

## Phase 5: Text Launch Screen, Prompt Editor, Helper Insertion, And Launch Results

Owner: one agent. Write scope: `../sase-android` only.

Purpose: let Android launch text agents while preserving SASE prompt/directive behavior.

Concrete work:

- Add a Launch destination reachable from the main navigation and from resume/wait actions.
- Build a code-friendly prompt editor:
  - multiline monospaced input option or code-style text area;
  - paste/share support where practical;
  - request ID generation for launch correlation;
  - optional name/display-name, provider/runtime/model fields;
  - project/context selector using helper data where available;
  - no automatic rewriting of `%`, `#`, model, runtime, or xprompt directives except explicit helper insertion.
- Add text launch repository behavior:
  - call `POST /agents/launch`;
  - store recent launch result summaries locally for display and direct navigation to Agents;
  - handle multi-slot launch results;
  - map launch failure, bridge unavailable, disconnected host, and auth expired to recovery actions.
- Add helper insertion affordances that can insert text into the prompt without hiding the raw SASE syntax:
  - ChangeSpec tag insertion;
  - xprompt reference insertion;
  - bead reference/context insertion where supported by the product syntax.
- Add tests for request encoding, directive preservation, multi-slot result rendering, launch failure, direct-launch
  from resume/wait option, and prompt text not being lost after failed submit.

Acceptance:

- A user can launch one or more text agents from Android and see all launched slots/results.
- Existing SASE directive syntax is preserved; the app helps insert known references but does not invent a mobile-only
  prompt grammar.

## Phase 6: Image Attach, Camera/Gallery URI Handling, And Image Launch

Owner: one agent. Write scope: `../sase-android` only.

Purpose: support image-agent launch from Android without treating the phone as a host filesystem writer.

Concrete work:

- Add image attach actions to the Launch screen:
  - pick from gallery through Android photo picker or `ACTION_OPEN_DOCUMENT`;
  - capture from camera using a content URI and scoped storage-safe temporary file;
  - clear/replace selected image.
- Read selected content URI safely:
  - determine display filename, MIME type, and byte length where available;
  - enforce a client-side maximum that matches or is below the gateway limit;
  - base64 encode only at submit time or stream into the request path without keeping duplicate large copies longer than
    needed;
  - never expose raw local URI paths as host paths.
- Call `POST /agents/launch-image` with prompt, image metadata, byte length, and base64 image data.
- Add image-specific error states for permission denied, missing content, unsupported type, oversize upload, upload
  failure, and launch failure.
- Add tests for content URI metadata extraction with fakes, request encoding, oversize rejection, camera/gallery state,
  image launch success/failure, and prompt/result rendering.

Acceptance:

- A user can launch an image agent from a camera capture or selected gallery/document image.
- Upload failures leave the prompt/draft intact and explain the recovery path.

## Phase 7: Workflow Helper Screens And Pickers

Owner: one agent. Write scope: `../sase-android` only.

Purpose: expose ChangeSpec, xprompt, and bead helper flows as native screens and reusable pickers for Launch.

Concrete work:

- Add `data.helpers` repository methods for:
  - ChangeSpec tag list with project filtering;
  - xprompt catalog with query/source/tag filters;
  - bead list and bead detail with project/status/type/tier filters where supported.
- Build helper screens:
  - ChangeSpec tags list with copy/insert affordance and skipped/warning display;
  - xprompt catalog with search/filter, preview, copy/insert, and optional catalog attachment metadata;
  - bead list/show with status/type/tier/project metadata and copy/insert/context affordances.
- Make these screens usable standalone and as modal/picker flows from Launch.
- Render `MobileHelperResultWire` partial-success, skipped, warning, failed, and empty states without parsing human
  prose.
- Refresh helper data after `helpers_changed` events where relevant, while allowing manual refresh.
- Add tests for helper repository parsing/error mapping, partial-success rendering, search/filter behavior, picker
  return values, launch insertion behavior, and standalone navigation.

Acceptance:

- A user can browse/pick ChangeSpec tags, xprompts, and beads from Android without memorizing slash commands.
- Helper partial failures are visible and do not block successful entries from being used.

## Phase 8: Update Screen, Status Polling, And Helper Event Integration

Owner: one agent. Write scope: `../sase-android` only.

Purpose: complete the remaining Telegram-parity helper command by exposing SASE update start/status.

Concrete work:

- Add update repository behavior:
  - call `POST /update/start`;
  - poll `GET /update/{job_id}` until terminal status or user cancellation;
  - refresh on `helpers_changed` events with matching `job_id`;
  - persist the most recent update job enough to resume status after app restart.
- Build an Update screen/status affordance:
  - show current/last job status, timestamps, warnings, and result message;
  - start update action with confirmation;
  - handle already-running, job-not-found, launch-failed, disconnected, auth-expired, and bridge-unavailable states;
  - expose log path metadata only as display text/copy if the contract returns it. Do not attempt arbitrary log file
    browsing.
- Integrate Update into Helpers or Settings navigation without crowding the primary inbox/action path.
- Add tests for start success, already-running, polling success/failure, app restart with remembered job, helper event
  refresh, and UI state rendering.

Acceptance:

- A user can start a SASE update and monitor its status from Android.
- Update status is rendered from structured fields and does not require reading host logs or Telegram text.

## Phase 9: End-To-End UX Integration, Documentation, And Final Verification Gate

Owner: one final integration/land agent after Phases 1-8 are merged.

Purpose: verify that the foreground mobile MVP flows work together and leave clear handoff notes for Epic 7.

Concrete work:

- Review navigation and state ownership across Inbox, Detail actions, Agents, Launch, Helpers, Update, and Settings.
  Remove duplicate state models or one-off UI paths that emerged across phases.
- Add or expand fake-gateway end-to-end tests:
  - pair app;
  - approve a plan;
  - submit feedback/custom answer;
  - list agents;
  - launch text;
  - launch image through a fake content URI path;
  - kill and retry;
  - pick a ChangeSpec/xprompt/bead helper;
  - start/poll update;
  - simulate stale action, disconnected host, auth expired, launch failure, upload failure, and helper partial failure.
- Add connected instrumentation smoke coverage for the highest-value paths that are practical on emulator:
  - action detail controls;
  - launch text;
  - agents list/kill/retry against fake gateway;
  - helper picker insertion;
  - update start/status fake path.
- Refresh `../sase-android/README.md` with:
  - Epic 6 capability list;
  - fake gateway/test commands;
  - manual real-host smoke checklist for action, launch, agent, helper, and update flows;
  - known limitations that Epic 7 still owns.
- If useful, add a short link from this repo's mobile docs to the Android README, but avoid broad docs churn.
- Run final verification:
  - `./gradlew testDebugUnitTest lintDebug assembleDebug`;
  - `./gradlew connectedDebugAndroidTest` if an emulator/device is available;
  - this repo `just install && just check` only if this repo was changed outside `sdd/beads/`.

Acceptance:

- Android can complete every foreground Telegram user-visible command from the legend without slash-command knowledge.
- Primary error states are covered: stale action, disconnected host, auth expired, launch failure, upload failure,
  helper partial failure, and update already running/failure.
- README and tests are good enough for Epic 7 to focus on background delivery, packaging, security review, and e2e
  hardening instead of repairing foreground UX gaps.

## Suggested Phase Dependencies

- Phase 1 is the root dependency for every other phase.
- Phase 2 depends on Phase 1.
- Phase 3 depends on Phases 1 and 2.
- Phase 4 depends on Phase 1 and can run after Phase 2 starts, but final navigation integration should wait for the
  action-detail route shape from Phase 2.
- Phase 5 depends on Phase 1 and benefits from Phase 4 for direct launch from resume/wait options.
- Phase 6 depends on Phase 5.
- Phase 7 depends on Phase 1 and should finish before Phase 5's final helper insertion polish, but standalone helper
  screens can be developed in parallel with Phase 5 if write scopes are coordinated.
- Phase 8 depends on Phase 1 and can run in parallel with Phase 7 after shared helper repository conventions are clear.
- Phase 9 depends on Phases 1-8.

## Suggested Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_mobile_gateway_epic_6.md`: in `../sase-android`, add Epic 6 DTOs, typed
> `GatewayApiClient` methods, fixtures, contract assertions, and fake gateway routes for notification actions, agents,
> helpers, update, image launch, and attachment download where needed. Do not add user-facing UI yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_mobile_gateway_epic_6.md`: add the Android action repository and notification detail
> controls for direct plan/HITL/question actions, including success, stale, already-handled, unsupported, offline, and
> auth-expired states.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_mobile_gateway_epic_6.md`: add feedback/custom-answer two-step flows, draft
> preservation, failed-submit retry behavior, and stale/action refresh handling for plan, HITL, and question actions.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_mobile_gateway_epic_6.md`: add the agents repository and Agents screen with list,
> kill, retry, resume/wait affordances, `agents_changed` refresh, and fake-gateway tests.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_mobile_gateway_epic_6.md`: add the text Launch screen, prompt editor, launch
> repository, multi-slot launch result rendering, helper insertion affordances, and direct launch from resume/wait
> options.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_mobile_gateway_epic_6.md`: add image attach from camera/gallery/content URI and
> image launch request handling, including permissions, metadata extraction, size/type validation, and upload failure
> recovery.

Phase 7 prompt:

> Implement Phase 7 from `sase_plan_mobile_gateway_epic_6.md`: add native ChangeSpec, xprompt, and bead helper screens
> plus reusable picker flows for Launch, with structured partial-success/skipped/warning states.

Phase 8 prompt:

> Implement Phase 8 from `sase_plan_mobile_gateway_epic_6.md`: add update start/status repository behavior, Update UI,
> polling/resume after restart, helper-event refresh, and structured update error states.

Phase 9 prompt:

> Implement Phase 9 from `sase_plan_mobile_gateway_epic_6.md`: perform final foreground UX integration, fake-gateway and
> instrumentation smoke coverage, README/manual smoke updates, and the Android verification gate.

## Final Definition Of Done

- A paired Android user can complete plan, HITL, and question actions from notification detail, including feedback and
  custom answers.
- A paired Android user can list agents, kill, retry, use resume/wait affordances, launch text agents, and launch image
  agents from camera/gallery content.
- A paired Android user can browse or pick ChangeSpec tags, xprompts, and beads, and can start/check SASE updates.
- Every Epic 6 endpoint used by Android has DTO/client/fake-gateway test coverage.
- Action, agent, launch, helper, and update screens render loading, empty, success, stale/offline/auth, and structured
  gateway failure states.
- `../sase-android` passes `./gradlew testDebugUnitTest lintDebug assembleDebug`, with connected tests run where
  available.
- Epic 7 can proceed with background delivery, packaging, e2e hardening, and security review without revisiting the core
  foreground mobile workflows.
