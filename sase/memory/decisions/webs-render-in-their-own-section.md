---
keyword: Memory Webs Render In Their Own Section
aliases: [web kind decides placement, tier-free web descriptors]
summary:
  A memory web's placement in generated agent instructions follows from its kind, not
  from a `type:` declaration on its descriptor.
metadata:
  status: accepted
  decided: 2026-08-30
---

**Claim.** A memory web descriptor does not declare `type:` or `parent:`;
`sase memory init` ignores both if present and strips them on convergence. A web's kind
— not a rendering choice — decides its placement: every web descriptor renders as its
own subsection of a dedicated Memory Webs section in generated agent instructions,
between core memory and reference memory, and a strand body never inlines regardless of
the web's frontmatter.

**Why.** The prior shape ([[decisions/memory-webs]]) treated a descriptor as an ordinary
note that happened to declare `type: core` or `type: reference`, so kind and rendering
tier were two independent axes for something that is structurally a third kind. That
record's own Why section names the cost this caused directly: "the glossary note alone
moved between core and reference tiers four times because a collection's rendering tier
had nowhere to be declared." This decision supersedes the sentence in
[[decisions/memory-webs]] reading "The descriptor's own body, not any strand body,
participates in core or reference rendering" — a descriptor's body now participates in
neither; it has its own section. Rejected alternatives: keep `type:` on descriptors (the
status quo that caused the churn above); add a numbered third tier such as "Tier 3: web
memory" (rejected because the goal was for no tier vocabulary to survive anywhere in the
repo, its generated output, or its linked repos — a third numbered tier just relocates
the vocabulary instead of retiring it).

**Cost.** A web descriptor's body is now always paid for on every turn; there is no
longer a way to make one read-on-demand the way a `type: reference` flat note is.
`type:` and `parent:` are silently stripped rather than rejected, so a descriptor that
still declares them on disk gets no error, only silent convergence on the next
`sase memory init`.

**Reopens when.** A project accumulates enough memory webs that unconditionally inlining
every descriptor becomes a real token-budget problem. That would need a new, explicitly
scoped opt-out mechanism designed for that purpose — not a revival of `type:` on
descriptors, which is the exact conflation this decision retires.
