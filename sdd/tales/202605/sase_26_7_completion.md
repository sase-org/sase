---
create_time: 2026-05-06 21:21:46
status: done
prompt: sdd/prompts/202605/sase_26_7_completion.md
---
# Plan: Finish sase-26.7 Background Delivery Verification

## Context

Verification of the completed `sase-26.7` child beads found one remaining cross-repo integration issue: the Rust gateway
FCM provider emits the push event identifier as `hint_id`, while Android's FCM parser and the checked mobile API
contract expect `id`. Real FCM messages would be dropped as invalid before triggering local notification rendering or
authoritative refresh.

## Steps

1. Update `../sase-core` FCM data payload generation to send the push event identifier as `id`, matching the wire
   contract and Android parser.
2. Update Rust push-provider tests to assert the contract-compatible `id` key and guard against reintroducing `hint_id`.
3. Run focused Rust tests for the FCM payload/provider and Android push parser/handler tests that cover wake-to-refresh.
4. Update the epic plan frontmatter status to `done` after verification.
5. Close `sase-26.7` as the final bead step.
