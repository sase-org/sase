---
create_time: 2026-05-06 14:56:21
status: done
prompt: sdd/prompts/202605/mobile_gateway_request_id_completion.md
---
# Plan: Preserve Mobile Agent Request IDs

## Context

The `sase-26.3` epic records durable mobile launch context in `src/sase/integrations/mobile_agents.py`. That code
already stores a `request_id` when it is present in the bridge request, but the Rust gateway request wire types do not
currently include the field, so gateway-originated text, image, and retry launches drop it before dispatching to the
Python bridge.

## Goal

Finish the Phase 6 launch-context requirement by preserving an optional mobile request ID through the public gateway
contract and fixed bridge invocation.

## Implementation

- Add `request_id: Option<String>` to the Rust text launch, image launch, and retry request wire records.
- Include `request_id` in the retry bridge JSON wrapper, matching the automatic serde forwarding used for text and image
  launch requests.
- Refresh the committed mobile API contract snapshot and contract source descriptions so Android/client work can rely on
  the field.
- Add or update focused route/bridge tests that prove `request_id` survives gateway dispatch.

## Verification

- Run the focused mobile Python tests.
- Run focused Rust gateway tests for the mobile agent routes/command bridge.
- Run the repo-level checks before closing the epic.
