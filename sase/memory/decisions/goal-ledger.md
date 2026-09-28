---
keyword: Goal Ledger
aliases: [goal store, goal events]
summary:
  A goal is its own Rust-owned domain, not a bead type. State is immutable events plus
  live markers through the hidden clone, with O(unsettled) hot reads and
  shown-never-promised freshness.
metadata:
  status: accepted
  decided: 2026-09-28
---

**Claim.** A [[glossary/goal]] is its own Rust-owned domain, not a bead type. State is
immutable events plus live markers, written only through the hidden clone. Hot reads are
O(unsettled): settled history is never opened. Freshness is shown, never promised.
Drafts stay local until named.

**Why.** Beads and goals change for different reasons at different rates; making goals a
bead type would couple the agent-work lifecycle to the person's outcome records and
force every goal read through bead machinery. Immutable events make concurrent machines
converge without conflict repair, markers keep the hot set small, and the hidden-clone
write lane keeps machine writes off the primary checkout. The G1 benchmark measured the
shape: hot-list p95 moves -6% from 25k to 100k settled goals (settled files are never
opened), and push contention under write-for-write alternation retried cleanly with
every write published. Known miss at landing: warm list p50 is ~37ms at 1000 unsettled
goals against a 5ms contract, because the read path re-reduces every live goal instead
of consulting projection signatures; the fix is core surgery and is tracked as
follow-up, not as a reopening.

**Cost.** Two stores to reason about (events plus markers) with an invariant between
them, and one more sidecar directory (`goals/`) that bead tooling must ignore. Readers
carry the reduction cost per live goal until the projection short-circuit lands.

**Reopens when.** Push contention or hot-list p95 grows with settled history. Splitting
`goals.host_role` into its own repository is a config change, not a reopening.
