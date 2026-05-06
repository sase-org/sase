---
create_time: 2026-05-06 10:02:06
status: done
prompt: sdd/prompts/202605/mobile_gateway_epic_1.md
bead_id: sase-26.1
tier: epic
legend_bead_id: sase-26
---
# Plan: Mobile MVP Epic 1 - Host Gateway Foundation And Pairing

## Context

Epic 1 from `sdd/legends/202605/sase_mobile_mvp_legend.md` creates the workstation-hosted gateway that the future
Android app will pair with and query. This is the foundational API surface for later mobile notification, action, agent,
and helper epics.

The current repository shape matters:

- `../sase-core` is the required Rust backend workspace. It currently has `crates/sase_core` for deterministic domain
  logic and `crates/sase_core_py` for the `sase_core_rs` PyO3 extension. It has no gateway crate yet.
- This repo is the Python SASE product shell. CLI registration lives under `src/sase/main/`, config loading under
  `src/sase/config/`, and notification facades already use Rust-backed store behavior through `sase_core_rs`.
- The referenced research recommends a Rust `axum`/`tokio` host gateway with product-shaped endpoints, not arbitrary
  file or shell access, and a Python bridge only for host lifecycle/config integration.
- The gateway should bind to `127.0.0.1` by default. LAN/tailnet binds must be explicit. Tailscale Serve should be the
  documented private remote-access path.

## Goal

Deliver a minimal secure host gateway that can be started from SASE, pair an Android/client device, authenticate future
requests with a long-lived per-device token, expose health/session endpoints, provide a skeletal SSE event stream with
heartbeat and resume IDs, and publish a stable JSON/OpenAPI-ish contract snapshot for future Android phases.

## Non-Goals

- Notification inbox/list/detail behavior beyond whatever is needed for a no-op event stream. That belongs to Epic 2.
- Agent launch, kill, retry, image input, ChangeSpec/xprompt/bead/update helper APIs. Those belong to later epics.
- Public internet exposure, hosted relay, FCM, UnifiedPush, or Android app work.
- Arbitrary host file access, arbitrary shell execution, or generic RPC.
- A complex crypto protocol in the first pass. The MVP can use auditable one-time pairing codes plus random bearer
  tokens, leaving SPAKE2/mTLS hardening for a later security epic if needed.

## API Contract For This Epic

Use versioned endpoints under `/api/v1`:

- `GET /health` - unauthenticated liveness with version/build/bind summary and no secrets.
- `GET /session` - authenticated session/device summary.
- `POST /session/pair/start` - create a short-lived one-time pairing challenge from the local host.
- `POST /session/pair/finish` - exchange the one-time code and client/device metadata for a long-lived device token.
- `GET /events` - authenticated SSE stream with heartbeat events, stable event IDs, and `Last-Event-ID` support.

Every response should use a stable envelope or stable error record. No unauthenticated mutating endpoint may exist
except the constrained pairing start/finish flow, and those endpoints must be rate-limitable/short-lived by design.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Keep deterministic wire records in Rust. Keep Python as thin CLI/config/lifecycle glue.
- Use explicit short flags for any new `sase` CLI arguments.
- Add tests in the same phase as behavior. Do not leave a phase relying on later agents for baseline correctness.
- If this repo changes, run `just install` first in the ephemeral workspace, then focused tests, then `just check`
  before handoff unless the phase is documentation-only.
- If `../sase-core` changes, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace`, or the equivalent `just rust-check` from this repo if available.

## Phase 1: Rust Gateway Crate And Core Wire Contract

Owner: one agent. Write scope: `../sase-core` only, except optional notes in the final response.

Purpose: create the gateway crate skeleton and stable JSON contract types without adding auth state yet.

Concrete work:

- Add `crates/sase_gateway` to the `../sase-core` workspace with `axum`, `tokio`, `serde`, `serde_json`, `thiserror`,
  `tower-http` as needed, and no Python dependency.
- Expose a binary or library entry point that can bind an address and serve:
  - `GET /api/v1/health`
  - placeholder authenticated-route scaffolding that returns a typed unauthorized error until Phase 2 wires auth.
- Add shared gateway wire modules for:
  - health response;
  - session/device records;
  - auth/pairing request and response records;
  - common error response;
  - event record skeleton;
  - pagination/filter structs only if they are needed by future snapshots, not endpoints yet.
- Decide and document the response shape. Prefer direct records for success plus a consistent `ApiErrorWire` for errors,
  unless the agent finds an existing SASE wire-envelope convention to reuse.
- Add JSON serialization snapshot tests so field names, `null` vs omitted behavior, enum tags, and schema versions are
  deliberate.
- Add route tests for health success and unknown-route typed error behavior.

Acceptance:

- `cargo test --workspace` passes in `../sase-core`.
- A local `cargo run -p sase_gateway -- --bind 127.0.0.1:0` or equivalent test harness can serve `GET /api/v1/health`.
- No mutating route exists except inert scaffolding.

## Phase 2: Pairing, Token Store, And Auth Middleware

Owner: one agent. Write scope: `../sase-core`, focused on `crates/sase_gateway`.

Purpose: make the gateway actually pair and authenticate devices while keeping storage simple and auditable.

Concrete work:

- Define gateway state storage under a configurable SASE home path, defaulting to a host-controlled location such as
  `~/.sase/mobile_gateway/`.
- Implement a device/token store with atomic writes and locking appropriate for a single host process:
  - paired device ID;
  - display name/platform metadata;
  - token hash, not raw token;
  - created/last_seen/revoked timestamps;
  - audit-friendly stable device identity.
- Implement `POST /api/v1/session/pair/start`:
  - short-lived one-time code;
  - expiry timestamp;
  - host label/fingerprint-ish identifier if useful;
  - no long-lived credential in this response.
- Implement `POST /api/v1/session/pair/finish`:
  - validates the code;
  - records the device;
  - returns a long-lived bearer token exactly once.
- Implement authenticated request middleware for all non-health and non-pairing endpoints.
- Implement `GET /api/v1/session` using the authenticated device context.
- Add token revocation primitives in storage even if no public revocation endpoint is exposed yet. This gives tests and
  future settings UI a deterministic path.
- Add basic per-endpoint audit logging from this phase onward: device ID when available, endpoint, target ID when
  available, and outcome. Logs should avoid secrets and raw bearer tokens.

Acceptance:

- Tests cover pair start, pair finish, one-time-code expiry, token success, missing/invalid/revoked token failures, and
  `GET /api/v1/session` returning the authenticated device.
- Mutating routes other than pairing reject unauthenticated requests.
- Raw bearer tokens are never written to disk or audit logs.

## Phase 3: Bind Policy, Gateway CLI Shape, And Local Contract Runner

Owner: one agent. Write scope: mostly `../sase-core`; this repo only if a tiny local smoke wrapper is needed before the
main Python integration phase.

Purpose: harden server startup behavior before exposing it through `sase`.

Concrete work:

- Add a gateway config struct and CLI flags to the Rust binary:
  - `--bind` / `-b` for host:port;
  - `--sase-home` / `-H` or equivalent state root;
  - `--allow-non-loopback` / `-L` or a clearer explicit opt-in flag for LAN/tailnet binds;
  - `--contract-out` / `-o` if contract snapshot generation is implemented by the binary.
- Enforce bind policy:
  - default bind is loopback, ideally `127.0.0.1:0` for tests and a documented fixed/default port for product use;
  - non-loopback bind fails unless the explicit opt-in flag/config is present;
  - error text must be clear enough for the Python CLI to relay.
- Add a local contract/smoke test client in Rust tests that starts the app on an ephemeral port and exercises health,
  pairing, auth, and session without shelling out.
- Generate or hand-maintain the first JSON contract snapshot under a stable path in `../sase-core`, for example
  `crates/sase_gateway/contracts/api_v1/*.json` or `docs/contracts/mobile_api_v1.json`.

Acceptance:

- Tests cover default loopback behavior, explicit LAN/tailnet bind opt-in, and failure for accidental `0.0.0.0` bind.
- Contract snapshots are committed and stable.
- The gateway can be exercised with `curl` using a token produced by the pairing flow.

## Phase 4: Python CLI, Config, And Lifecycle Integration

Owner: one agent. Write scope: this repo only unless a tiny Rust CLI adjustment is discovered.

Purpose: let users start the gateway through SASE instead of manually running a Rust binary.

Concrete work:

- Add a Python integration module, likely `src/sase/integrations/mobile_gateway.py`, that:
  - reads merged SASE config;
  - resolves the gateway binary path or command;
  - constructs safe argv from config/CLI options;
  - starts the gateway in foreground mode for MVP visibility;
  - prints the bind URL and pairing instructions/code returned by the gateway flow or a startup status endpoint.
- Add a `sase mobile gateway ...` or `sase gateway ...` CLI namespace. Prefer `sase mobile gateway start` if future
  Android/mobile commands are expected under the same namespace.
- Define default config in `src/sase/default_config.yml`, including:
  - bind address defaulting to `127.0.0.1`;
  - port;
  - state directory override;
  - explicit LAN/tailnet allow flag defaulting false;
  - gateway binary/command override for source checkouts.
- Wire parser and handler files following existing `src/sase/main/parser_*.py` and `*_handler.py` patterns.
- Add tests for config defaults, CLI arg construction, non-loopback rejection/opt-in propagation, missing binary error
  text, and foreground lifecycle using a fake subprocess instead of launching the real server.
- Update `sase core health` or add a separate health check only if it can probe the gateway binary without requiring it
  to be running. Do not blur `sase_core_rs` extension health with gateway runtime health if that would confuse users.

Acceptance:

- `sase mobile gateway start` or the chosen command can launch the gateway from this repo.
- Tests prove loopback is the default and LAN/tailnet exposure requires explicit user config or CLI opt-in.
- `just install && just check` passes in this repo.

## Phase 5: SSE Event Skeleton, Resume IDs, And Heartbeat Coverage

Owner: one agent. Write scope: `../sase-core` first, this repo only for CLI docs/help if needed.

Purpose: add the event stream substrate that later notification and agent epics can publish into.

Concrete work:

- Implement `GET /api/v1/events` as an authenticated SSE stream.
- Add typed event records for:
  - `heartbeat`;
  - `session`;
  - `notification_placeholder` or a generic `state_changed` only if needed for tests. Avoid modeling Epic 2
    notifications prematurely.
- Give every event a stable monotonic/resumable ID. The first implementation can keep an in-memory ring buffer with a
  documented restart limitation, as long as the wire shape supports `Last-Event-ID`.
- Honor `Last-Event-ID` on reconnect:
  - replay buffered events newer than the provided ID where possible;
  - otherwise send a typed resync-required event or documented error so Android knows to fetch full state.
- Add heartbeat interval config/test hooks so tests do not sleep in real time.
- Add a test client that pairs, connects with auth, observes heartbeat/event IDs, reconnects with `Last-Event-ID`, and
  verifies unauthorized SSE requests fail cleanly.

Acceptance:

- Authenticated clients can subscribe to `/api/v1/events`.
- Unauthenticated clients cannot subscribe.
- Reconnect behavior is deterministic in tests.
- The event record contract is stable enough for Android Epic 5 to build an SSE client against it.

## Phase 6: Documentation, Local Setup, And Cross-Repo Integration Gate

Owner: one final integration/land agent after Phases 1-5 are merged.

Purpose: make the foundation usable and verify the pieces together.

Concrete work:

- Add user-facing documentation in this repo, likely `docs/mobile_gateway.md`, covering:
  - architecture: phone as client, workstation as host;
  - local loopback default;
  - Tailscale Serve as the recommended private remote-access option;
  - pairing flow;
  - token storage/revocation basics;
  - example `curl` health/session/events commands;
  - security warnings for LAN/public binds.
- Link the doc from `README.md` and `docs/rust_backend.md` only where it naturally belongs.
- Add a short Rust-side gateway README/contract note in `../sase-core` if the contract snapshots live there.
- Perform an end-to-end smoke:
  - start the gateway through the SASE CLI;
  - run pair start/finish;
  - call authenticated session;
  - subscribe to events long enough to receive a heartbeat;
  - restart/reconnect with `Last-Event-ID` and confirm documented behavior.
- Ensure contract snapshots are current and included in the final notes.

Acceptance:

- The desktop user path is documented and works without manually invoking a Rust binary.
- Cross-repo verification passes:
  - this repo: `just install && just check`;
  - Rust repo: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo test --workspace`.
- The final handoff explicitly lists any known limitations, especially in-memory event buffering and non-production
  pairing crypto.

## Suggested Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_mobile_gateway_epic_1.md`: add the `sase_gateway` Rust crate in `../sase-core` with
> the health endpoint and stable gateway wire/error/event contract tests. Do not implement pairing or Python CLI
> integration yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_mobile_gateway_epic_1.md`: add pairing, token storage, auth middleware, session
> endpoint, revocation primitives, and audit logging in `../sase-core/crates/sase_gateway`.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_mobile_gateway_epic_1.md`: harden Rust gateway startup with bind policy, CLI flags,
> local contract runner coverage, and committed API contract snapshots.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_mobile_gateway_epic_1.md`: add the SASE Python CLI/config/lifecycle integration so
> users can start the gateway from this repo, with tests and default config.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_mobile_gateway_epic_1.md`: add the authenticated SSE event skeleton with heartbeat,
> resumable event IDs, `Last-Event-ID` behavior, and test-client coverage.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_mobile_gateway_epic_1.md`: document the mobile gateway setup, run the cross-repo
> integration smoke, refresh contract snapshots, and record final limitations.

## Final Definition Of Done

- A desktop user can start the gateway from SASE.
- A client can pair, receive a token, call health/session, and subscribe to authenticated events.
- The gateway binds to loopback by default and rejects accidental LAN/public exposure without explicit opt-in.
- Contract tests cover auth success/failure, token revocation, bind-address defaults, and SSE reconnect semantics.
- Audit logs record device, endpoint, target ID where applicable, and outcome without leaking secrets.
- OpenAPI/JSON contract snapshots exist for future Android agents.
