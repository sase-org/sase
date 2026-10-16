---
title: Contribute
description: Contributor guides, internals, contracts, and runbooks for SASE.
---

# Contribute

This section collects everything a contributor needs: setup and architecture, runbooks,
contracts, and the docs process itself.

## Build and develop

- [Development](development.md) — Setup, verification, and source layout.
- [Architecture](architecture.md) — Runtime flow, state ownership, and provider
  boundaries.
- [Rust backend](rust-backend.md) — The required core and its boundary.
- [Fakey testing provider](fakey.md) — The fake provider for tests.

## Runbooks

- [Telemetry](telemetry.md) — What SASE measures and where it goes.
- [Performance runbook](perf-runbook.md) — Diagnosing slow paths.
- [Mobile MVP runbook](mobile-mvp-runbook.md) — The mobile gateway pilot.

## Contracts and internals

- [Commit workflow orchestrator](commit-workflow-orchestrator.md) — Finalization and
  workflow internals.
- [VCS provider API](vcs-provider-api.md) — Provider hooks and classification.
- [Workspace provider](workspace-provider.md) — Workspace hooks and ownership.
- [Agent sidecar synchronization](agents-sidecar-sync.md) — Publication and
  reconciliation internals.
- [SDD storage](sdd-storage.md) — How work units persist.
- [Integration APIs](integration-apis.md) — Python helpers for plugins, chat, mobile,
  and editor clients.
- [Artifacts pane contract](artifacts-pane-contract.md) — The pane API.
- [Artifacts visual grammar](artifacts-pane-visual-grammar.md) — Pane visuals.
- [Tool run receipts](tool-run-receipts.md) — Internal receipt policy and verification.
- [Prepared monitor completion](monitor-completion.md) — Internal completion policy.

## Docs process

- [Writing docs](writing-docs.md) — The documentation contract for humans and agents:
  tiers, templates, budgets, and routing.
- [Reader testing](reader-testing.md) — Observed reader rounds and how label changes are
  proposed.

## Thanks

- [Acknowledgements](acknowledgements.md) — Everyone who built SASE.
