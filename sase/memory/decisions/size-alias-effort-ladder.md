---
keyword: Size Aliases Descend The Effort Ladder
aliases:
  [size alias effort ladder, alias reasoning effort rule, alias provider redundancy]
summary:
  Built-in size aliases run a model at xhigh on its first appearance from @xlarge down
  and one rung lower on each reappearance; every alias should span more than one
  provider.
metadata:
  status: accepted
  decided: 2026-09-20
---

**Claim.** Scanning the built-in size aliases from `@xlarge` down to `@xsmall`, a
model's first appearance runs at `xhigh` and each later appearance drops exactly one
rung of `EFFORT_LEVELS_ORDERED`. A model that would need a rung below the bottom of its
provider's supported range does not belong in that alias; swap in a different model
rather than repeating or floor-clamping a rung. That is why Gemini, not a fifth Grok
rung, holds the `@xsmall` slot. A provider that publishes no reasoning-effort mechanism
and bakes effort into the model slug (Antigravity today) expresses its rung by choosing
the variant (`agy/gemini-3.8-flash-high`) and carries no `@effort` suffix; attaching one
raises `LLMInvocationError` at invoke time, because an alias-supplied effort is
explicit. Every model alias should also reach more than one LLM provider, through a `|`
pool, a `||` ordered fallback, or a `(A | B) || C` last resort, whenever more than one
provider can serve that size.

**Why.** A size alias should buy capability through the _model_, not by starving a good
model of reasoning budget, and reusing one model across adjacent sizes without dropping
its rung collapses the distinction between those sizes. Rejected alternative: per-alias
hand-tuned efforts, because five aliases times three members is fifteen independently
drifting values with no invariant a test can check. A single-provider alias makes one
vendor's outage or rate limit a total outage for that size.

**Cost.** Rungs are coupled: replacing one model in one alias can force edits in the
aliases below it, and `@small` ends up at the same Claude rung as `@large`.

**Reopens when.** A provider ships a non-linear effort ladder, or measured quality at
`xhigh` on a small model proves worse than the same model at `high`.
