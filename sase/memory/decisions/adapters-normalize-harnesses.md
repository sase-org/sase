---
keyword: Adapters Normalize Harnesses
aliases: [adapter harness normalization, harness conformance]
summary:
  Each provider adapter makes its CLI harness conform to the single-turn contract
  instead of the host modeling private wait semantics.
metadata:
  status: accepted
  decided: 2026-09-23
---

**Claim.** Each provider adapter makes its CLI harness conform to the single-turn
contract. Where the CLI allows, it disables native background and wake primitives
mechanically. It tells the model the provider's real synchronous ceiling. Otherwise it
detects violations with a bounded guard and fails loudly. The host never models a
harness's private wait semantics.

**Why.** Muse's wake is an invisible, unbounded keep-alive, not a suspend. Rejected
alternatives: embracing the wait with a host pending-work ledger (it would parse Muse's
private session log and need re-checking on every CLI release), and a prompt-only "use
monitors" rule (Muse's harness, not the model, picks what goes to the background). This
extends [[decisions/single-turn-agents]] to the adapter layer.

**Cost.** Muse loses in-turn waits past 10 minutes, which means more monitor hops, and
it depends on a "legacy" upstream tool.

**Reopens when.** A harness wait meets [[decisions/single-turn-agents]]'s reopen
condition, or a provider offers no way to disable background execution.
