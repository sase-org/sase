---
keyword: Goals Host Binds
aliases: [goal binding, bound goal]
summary:
  The host binds every LLM turn to exactly one goal before spawn; agents only name or
  adopt their own draft and claim or keep open; only a human settles.
metadata:
  status: accepted
  decided: 2026-09-28
---

**Claim.** The host binds every LLM turn to exactly one goal before spawn. Agents only
name or adopt their own draft, and only claim or keep a goal open; settling a goal —
verifying, acknowledging, canceling, merging, or superseding it — is a human act. This
holds invariants only: it says who may move a goal, never how turns are stored, how
attention is scheduled, or what happens when binding fails.

**Why.** An unbound agent optimizes the prompt in front of it, which is how goals drift:
the work completes while the record says nothing, or the record moves without evidence.
Binding before spawn makes the goal part of the turn's identity rather than its payload,
so claims stay attributable per [[decisions/host-owned-completion]], continuation never
waits on a decision per [[decisions/gates-never-block]], and settlement evidence stays
checkable per [[decisions/receipts-prove-before-they-skip]].

**Cost.** Every launch path must resolve one goal id before spawning, and turns without
a meaningful goal still carry one. Per-model claim precision is contained by per-model
policy, not by weakening the bind.

**Reopens when.** A launch path can be bound neither in the runner nor on the unit wire,
or per-model claim precision stays under the floor and a per-model policy cannot contain
it.
