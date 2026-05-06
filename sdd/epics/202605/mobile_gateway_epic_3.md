---
create_time: 2026-05-06 13:14:53
status: wip
prompt: sdd/prompts/202605/mobile_gateway_epic_3.md
bead_id: sase-26.3
tier: epic
legend_bead_id: sase-26
---
# Plan: Mobile MVP Epic 3 - Agent Lifecycle, Launch, Retry, And Image Input

## Context

Epic 3 from `sdd/legends/202605/sase_mobile_mvp_legend.md` adds the mobile gateway surface for managing and launching
agents. Epics 1 and 2 are already present in the current base:

- `../sase-core/crates/sase_gateway` serves the workstation-hosted authenticated gateway with pairing, session, SSE,
  notification/action/attachment routes, audit logging, and committed API contract snapshots.
- This repo starts the gateway through `sase mobile gateway start` and owns the Python host behavior for agent launch,
  running-agent scans, process lifecycle, xprompt expansion, VCS/workspace context, and image-file handling.
- `src/sase/agent/launcher.py` already preserves the important launch semantics: xprompt expansion, default VCS workflow
  normalization, multi-prompt expansion, `%m`/`%alt`/`%r` fan-out, wait handling, auto-naming, workspace claiming, and
  prompt history.
- `src/sase/agent/running.py` already provides the read/kill primitives used by `sase agents status` and
  `sase agents kill`.
- The Rust core/backend boundary still applies: stable mobile wire records and deterministic API decisions belong in
  Rust; host filesystem/process side effects belong behind a narrow Python bridge.

The key architectural decision for this epic is to add a product-shaped agent bridge between the Rust gateway and the
Python host runtime. The gateway must not expose arbitrary shell, file, or RPC behavior. It should call fixed,
operation-specific bridge commands or functions with typed JSON records, and the Python side should route those records
to existing SASE launch/scan/kill/retry helpers.

## Goal

Deliver authenticated gateway endpoints that let a paired client:

- list running and recent agents with mobile-appropriate summaries;
- fetch resume/wait prompt options for native copy/share or direct follow-up launch;
- launch one or more text agents while preserving current SASE launch semantics;
- launch image agents after safely storing uploaded images on the host;
- kill a running agent by name;
- retry a previous or killed agent from durable launch context;
- receive consistent result records, audit entries, and state-change SSE events.

## Non-Goals

- Android app UI or Android networking work. That belongs to later Android epics.
- Notification plan/HITL/question actions. Those are Epic 2 and should not be reimplemented here.
- Workflow helper APIs for ChangeSpecs, xprompts, beads, or update workers. Those are Epic 4.
- Arbitrary host file upload, directory browsing, shell execution, or mobile-controlled cwd selection.
- Replacing the existing TUI/CLI launch path. Existing `sase run`, `sase ace`, and `sase agents` behavior must remain
  compatible.

## API Contract For This Epic

Add authenticated endpoints under `/api/v1`:

- `GET /agents`
- `GET /agents/resume-options`
- `POST /agents/launch`
- `POST /agents/launch-image`
- `POST /agents/{name}/kill`
- `POST /agents/{name}/retry`

Use direct JSON success records and the existing `ApiErrorWire` error shape. Add agent-specific error codes only when
the existing set is not precise enough, for example `agent_not_found`, `agent_not_running`, `launch_failed`,
`invalid_upload`, or `bridge_unavailable`.

The first mobile launch request should be intentionally product-shaped:

- prompt text;
- optional display name/name directive behavior;
- optional model/runtime directives using existing SASE syntax;
- optional project context token or project hint once Phase 7 persists contexts;
- optional dry-run/preview flag only if a phase needs it for tests.

It should not accept arbitrary command argv, arbitrary cwd, or arbitrary environment variables.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Keep stable wire records, route auth, error mapping, audit calls, SSE event payloads, and contract snapshots in
  `../sase-core`.
- Keep process launch, process kill, raw prompt extraction, retry-name allocation, prompt history, workspace claiming,
  and image storage side effects in this repo behind a typed mobile agent bridge.
- Do not introduce runtime-specific Claude/Gemini/Codex branches. All supported runtimes have the same SASE capability
  surface.
- Do not shell out when an existing structured Python API is available. If the Rust gateway invokes Python, it must do
  so through fixed bridge subcommands and JSON stdin/stdout, not through user-supplied shell strings.
- Add tests in the same phase as behavior. Later phases should not be expected to backfill core safety coverage.
- If this repo changes, run `just install` first in the ephemeral workspace, then focused tests, then `just check`
  before handoff unless the phase is documentation-only.
- If `../sase-core` changes, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace`, or the repo-equivalent `just` target if one exists.
- Refresh the gateway contract snapshot whenever route or wire shape changes.

## Phase 1: Rust Agent Wire Contract And Gateway Bridge Skeleton

Owner: one agent. Write scope: `../sase-core` only, primarily `crates/sase_gateway` and shared wire modules.

Purpose: define the stable mobile agent API records and gateway bridge seam before any production host side effects are
added.

Concrete work:

- Add mobile agent wire records for:
  - agent list request/query and response;
  - mobile agent summary with name, project, status, pid, model, provider, workspace number, started time, duration,
    prompt snippet, artifact directory presence, retry lineage, action affordances, and display labels;
  - resume/wait option records with prompt text suitable for copy/share/direct launch;
  - text launch request and result records;
  - image launch request and result records;
  - kill/retry request and result records;
  - common launch slot result records so multi-prompt, multi-model, alt, and repeat fan-out can return more than the
    historical first result.
- Add `AgentEvent` or extend `EventPayloadWire` for `agents_changed` with reason and optional agent name/timestamp.
- Add agent-specific `ApiErrorCodeWire` entries only where the existing gateway errors are too vague.
- Add a gateway-side `AgentHostBridge` trait or equivalent abstraction with fake implementation for route tests.
- Register route skeletons that authenticate and call the fake bridge, but keep production bridge operations returning
  typed `bridge_unavailable` until Phase 2 wires the Python bridge.
- Add JSON snapshot tests and route tests for auth, success shape, error mapping, and SSE event payload shape.
- Update the committed mobile API contract snapshot with the new records and routes.

Acceptance:

- Rust tests prove the JSON field names, enum tags, null/default behavior, and new error codes are stable.
- Authenticated fake-bridge route tests cover every endpoint shape listed above.
- No production host process is launched or killed in this phase.

## Phase 2: Python Agent Bridge And Read-Only Agent Endpoints

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: expose read-only agent state through the gateway using existing scan/list primitives.

Concrete work:

- Add a Python module such as `src/sase/integrations/mobile_agents.py` that projects existing agent state into the Phase
  1 mobile records.
- Add a fixed JSON bridge entry point under `sase mobile`, for example a hidden/internal `sase mobile agent-bridge`
  subcommand with operation-specific subcommands. Every argument must have a short option if exposed through argparse.
- Implement bridge operations for:
  - list agents, backed by `list_running_agents()` / `list_all_agents()` and existing scan options;
  - resume/wait options, backed by raw prompt/chat metadata and existing `#resume` / `%wait` syntax rather than ad hoc
    prompt strings where possible.
- Implement production gateway bridge invocation with safe argv and JSON stdin/stdout. The command path should come from
  gateway config or default to the current `sase` executable, not from mobile requests.
- Implement authenticated `GET /agents`:
  - include running agents by default;
  - allow recent completed/failed rows via query;
  - support project/status filters only if they can be implemented without changing semantics.
- Implement authenticated `GET /agents/resume-options`:
  - return useful options for running and recent agents;
  - include enough metadata for Android to display native copy/share/direct-launch actions.
- Add Python tests for bridge projections and Rust route tests using both fake and command-backed bridge harnesses.

Acceptance:

- A paired curl client can list running and recent agents.
- Read-only routes do not require TUI imports or startup of the Textual app.
- Malformed bridge JSON, bridge exit failures, and missing helper command produce deterministic typed gateway errors.
- Existing `sase agents status --json` behavior is unchanged.

## Phase 3: Text Launch Endpoint And Mobile Launch Normalization

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: let mobile launch text agents while preserving current SASE launch behavior.

Concrete work:

- Add a Python mobile launch facade that calls the existing launch path instead of reimplementing launch behavior.
- Refactor `src/sase/agent/launcher.py` conservatively so the mobile bridge can return all spawned `AgentLaunchResult`
  records for multi-prompt, multi-model, alt, and repeat launches. Keep the existing `launch_agent_from_cwd()` API
  returning the first result for current callers.
- Normalize legacy Telegram-style `#workflow@ref` shorthand before launch only through a shared helper. Prefer
  converting it to the SASE-native VCS xprompt syntax already understood by the launcher; do not add a mobile-only
  grammar inside the gateway.
- Implement the Python bridge launch operation:
  - accepts the Phase 1 launch request JSON;
  - records prompt history through the existing launcher;
  - returns a primary result plus all slot results where fan-out occurs;
  - reports deterministic validation and launch errors without leaking internal tracebacks to the mobile client.
- Implement authenticated `POST /agents/launch` in the gateway with audit logging and `agents_changed` event emission on
  successful launches.
- Add tests for single launch, multi-prompt launch, multi-model/fan-out preservation, launch validation errors, and
  `#workflow@ref` normalization.

Acceptance:

- A paired curl client can launch a text agent and list it afterward.
- Multi-model and multi-prompt mobile requests retain current SASE behavior and expose all launched slots in the result.
- Existing CLI/TUI launch tests continue to pass.

## Phase 4: Image Storage And Image Launch Endpoint

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: support image input without letting the phone write arbitrary host files.

Concrete work:

- Extend the Rust wire contract for image launches if Phase 1 left only placeholders. Use a simple MVP request shape:
  prompt/caption text, original filename, content type, byte length, and base64 image bytes. Multipart can be added
  later if Android needs it, but the first contract should be easy to test with curl.
- Add host-side image storage under a SASE-owned directory such as
  `<sase_home>/mobile_gateway/uploads/images/<device_id>/`.
- Validate uploads before writing:
  - maximum size;
  - supported extension/content type;
  - lightweight magic-byte checks for PNG/JPEG/WebP/GIF where practical;
  - no path traversal or caller-controlled directories;
  - atomic write to a generated filename.
- Build the final agent prompt so it references the saved absolute host path in the format existing SASE image-capable
  launches expect.
- Implement authenticated `POST /agents/launch-image` with audit logging and `agents_changed` event emission.
- Add tests for valid image launch, invalid base64, extension/content-type mismatch, oversize upload, path traversal
  attempts, and launch failure cleanup policy.

Acceptance:

- Image launch stores the image on the host and starts an agent whose prompt references a valid local path.
- Rejected uploads leave no partial caller-named files behind.
- The storage path is deterministic enough for cleanup/audit, but not guessable as a client-controlled arbitrary write.

## Phase 5: Kill Endpoint And Lifecycle Result Semantics

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: let mobile stop running agents with consistent result records and state-change events.

Concrete work:

- Add a Python bridge kill operation backed by `kill_named_agent()`.
- Adjust or wrap `kill_named_agent()` only if needed to return structured failure reasons while preserving the existing
  `sase agents kill` CLI messages and exit codes.
- Implement authenticated `POST /agents/{name}/kill` with:
  - exact name matching;
  - deterministic not-found/already-completed/not-running/permission-denied errors;
  - audit logging with device id, endpoint, agent name, pid when available, and outcome;
  - `agents_changed` event on success and on idempotent already-stopped cleanup if the endpoint changes host state.
- Persist minimal kill context needed by Phase 6 retry support: agent name, artifact directory/timestamp, project
  context, raw prompt reference if available, killed pid, device id, and timestamp.
- Add tests for successful kill, missing agent, completed agent, missing pid, process already gone, permission error,
  and workspace/running-marker cleanup.

Acceptance:

- A paired curl client can kill a running agent by name and see the list update afterward.
- Existing `sase agents kill <name>` behavior is unchanged.
- Kill attempts are audited and do not delete agent artifacts needed for retry.

## Phase 6: Retry Endpoint And Durable Launch Context

Owner: one agent. Write scope: this repo and `../sase-core/crates/sase_gateway`.

Purpose: let mobile retry agents, including agents previously killed from mobile, without depending on transient pending
action entries.

Concrete work:

- Add a durable mobile launch-context store under SASE-owned state, for example
  `<sase_home>/mobile_gateway/agent_launch_contexts.jsonl` or a small JSON/SQLite store if existing project state
  helpers favor that.
- Record launch context for all mobile-launched text/image agents from Phases 3 and 4, and augment it from kill context
  in Phase 5. Include project name/file, artifact timestamp, agent name, raw prompt path or prompt snapshot, image host
  path if applicable, originating request id, device id, and retry lineage.
- Extract the retry-name and prompt rewrite logic used by the TUI into a shared non-TUI helper. Do not import Textual
  action modules from the bridge.
- Implement a Python bridge retry operation:
  - resolve by current agent name, artifact name, or stored launch context;
  - prefer the artifact raw prompt when present;
  - fall back to the stored prompt snapshot when the artifact prompt is unavailable;
  - allocate a retry name consistently with `allocate_retry_name()`;
  - optionally kill the source first only when an explicit request flag asks for that behavior.
- Implement authenticated `POST /agents/{name}/retry` with audit logging and `agents_changed` event emission on success.
- Add tests for retrying running, completed, failed, and mobile-killed agents; retry after missing pending action; retry
  name allocation; missing raw prompt fallback; and invalid/missing context errors.

Acceptance:

- A paired curl client can retry an agent after killing it from mobile.
- Retry launches preserve the original prompt semantics, including image path references when the original was an image
  launch.
- Retry lineage is visible enough in later `GET /agents` responses for Android to show that a retry was started.

## Phase 7: Project Context Persistence, Integration, Docs, And Contract Gate

Owner: one final integration/land agent after Phases 1-6 are merged.

Purpose: harden the end-to-end user path and leave a clean contract for Android agents.

Concrete work:

- Finish project-context persistence across list, launch, image launch, kill, and retry:
  - remember the last mobile project/ref context per paired device where useful;
  - keep context IDs product-shaped and derived from known SASE projects, not arbitrary host paths;
  - document how Android should supply or omit context for home-mode, project-level, and VCS-ref launches.
- Verify resume/wait option records still make sense after text/image launch and retry phases have landed.
- Refresh gateway contract snapshots and update:
  - `../sase-core/crates/sase_gateway/README.md`;
  - `docs/mobile_gateway.md`;
  - any CLI help/docs touched by the new bridge commands.
- Add curl examples for list, resume-options, text launch, image launch, kill, and retry.
- Add an end-to-end smoke harness using temporary SASE home/artifact dirs where practical:
  - pair a client;
  - launch a text agent through a fake/safe runner seam;
  - list it;
  - kill it;
  - retry it;
  - launch an image agent and verify the saved host image path in the prompt.
- Run the cross-repo verification gate:
  - this repo: `just install && just check`;
  - Rust repo: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo test --workspace`.

Acceptance:

- A paired client can launch one or more agents, receive launch confirmation, list them, kill one by name, and retry it.
- Image launch stores the image on the host and starts an agent with a valid local path reference.
- Multi-model launch requests retain current SASE behavior.
- Contract snapshots and docs are current enough for independent Android Epic 5/6 work.

## Suggested Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_mobile_gateway_epic_3.md`: add the Rust mobile agent wire contract, gateway route
> skeletons, fake agent host bridge, auth/error/event tests, and contract snapshot updates in `../sase-core`. Do not
> invoke production Python host behavior yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_mobile_gateway_epic_3.md`: add the Python mobile agent bridge for read-only agent
> list/resume-options and wire the authenticated gateway `GET /agents` and `GET /agents/resume-options` routes through
> the fixed JSON bridge.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_mobile_gateway_epic_3.md`: add the text launch bridge and authenticated
> `POST /agents/launch`, preserving current SASE xprompt, VCS, multi-prompt, multi-model, alt, repeat, auto-naming, and
> prompt-history behavior.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_mobile_gateway_epic_3.md`: add host-side image upload storage and authenticated
> `POST /agents/launch-image`, with validation, safe generated paths, prompt construction, and image launch tests.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_mobile_gateway_epic_3.md`: add the kill bridge and authenticated
> `POST /agents/{name}/kill`, with structured lifecycle results, audit logging, SSE events, and mobile kill-context
> persistence.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_mobile_gateway_epic_3.md`: add durable launch context and authenticated
> `POST /agents/{name}/retry`, extracting shared retry prompt/name helpers outside the TUI and supporting retry after a
> mobile kill.

Phase 7 prompt:

> Implement Phase 7 from `sase_plan_mobile_gateway_epic_3.md`: complete project-context persistence, refresh docs and
> contract snapshots, add the end-to-end smoke harness, run the cross-repo verification gate, and record final
> limitations.

## Final Definition Of Done

- A paired client can list running/recent agents with mobile-appropriate metadata.
- A paired client can launch text agents and receive all launched slot results when fan-out occurs.
- A paired client can launch image agents; images are stored under SASE-owned host state and prompts reference valid
  local paths.
- A paired client can kill and retry agents by name, including retry after a mobile kill.
- Resume/wait options are available for Android copy/share/direct-follow-up UX.
- Gateway route responses, errors, audit entries, SSE events, and contract snapshots are stable.
- Existing CLI/TUI launch and agent-management behavior remains compatible.
