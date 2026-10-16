---
title: Prepared monitor completion
description: Internal details for opt-in no-new prepared monitor completion.
---

# Prepared monitor completion

This page records internal details for opt-in prepared monitor completion.

## Opt-in no-new prepared completion (E4 verdict-completion)

The default prepared intent accepts `pass`: only a verify monitor whose child exited
zero can complete. An explicitly prepared `accept: no-new` intent additionally permits a
verify monitor whose settled ToolRun is the bound named verification to complete when
that run's verdict is `no_new_failures` — every failure item KNOWN or FLAKY, none NEW or
UNKNOWN. The manifest spells it `accept: no-new` (omitted means `pass`); only a verify
monitor whose settled ToolRun is the bound run may use it, so a raw command, an
unrelated ToolRun, a lost monitor, or a missing owner link can never complete no-new.

For the no-new path the host re-observes each obligated checkout at the last host-owned
precommit boundary and Rust-looks-up its covering receipt: the verified fingerprint and
source run, expiry, invalidation, verdict, policy, and current tree must all still
agree, and every obligated repository must appear in the receipt's fingerprint. Any
mismatch withholds all commits and launches ordinary recovery with the typed reason.
Resumed host completion and multi-repo obligations re-verify the same receipt and source
run before finishing; a stale once-checked result is never reused. The default
`accept: pass` path keeps its existing eligibility and gains no receipt requirement.

Commits and bead closes record verdict provenance: the receipt id, source run, verdict,
and KNOWN list when a covering receipt authorized the completion, or `unverified` for
the ordinary `/sase_final` path without one. The `unverified` mark is nonblocking
provenance, not a refusal. No-new never masks NEW/UNKNOWN items and never changes a
child's exit code.

## Related

- [Monitors](../reference/automation/monitors.md)
