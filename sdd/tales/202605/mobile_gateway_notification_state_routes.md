---
create_time: 2026-05-06 12:59:31
status: done
prompt: sdd/prompts/202605/mobile_gateway_notification_state_routes.md
---

# Plan: Complete Mobile Gateway Notification State Routes

## Context

Epic `sase-26.2` defines notification inbox, pending action, and attachment gateway behavior for the SASE mobile MVP.
The implemented gateway already supports authenticated notification list/detail reads, plan/HITL/question action
mutations, attachment downloads, API contract snapshots, and smoke coverage.

During final bead verification, the epic plan's API contract still lists two notification state mutation endpoints that
are not implemented in the Rust gateway:

- `POST /api/v1/notifications/{id}/mark-read`
- `POST /api/v1/notifications/{id}/dismiss`

The Rust notification store already exposes `NotificationStateUpdateWire::MarkRead` and `MarkDismissed`, and the gateway
already publishes `notifications_changed` SSE events plus audit records for successful action mutations.

## Goal

Close the contract gap by adding authenticated mark-read and dismiss endpoints that mutate only notification state,
return deterministic API results, audit attempts, emit refresh events on success, and are documented in the mobile
gateway contract material.

## Scope

- Add route handlers in `../sase-core/crates/sase_gateway`.
- Extend the notification host bridge abstraction with read/dismiss mutation operations backed by the Rust JSONL store.
- Add route tests for auth failure, not found, successful mark-read, successful dismiss, audit output, and refresh event
  emission where practical.
- Refresh `crates/sase_gateway/src/contract.rs` and the committed `contracts/api_v1/mobile_api_v1.json` snapshot.
- Update mobile gateway docs in this repo with curl examples and semantics.
- Run focused tests and final verification.

## Non-Goals

- No generic notification edit API.
- No passive file watching.
- No Android client implementation.
- No changes to plan/HITL/question response-file semantics.

## Verification

- `cargo test -p sase_gateway notification`
- `cargo run -p sase_gateway -- --contract-out crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`
- Focused Python docs/bridge tests if this repo changes code beyond docs.
- Final close flow: close `sase-26.2`, run `just pyvision`, and mark the epic plan frontmatter `status: done`.
