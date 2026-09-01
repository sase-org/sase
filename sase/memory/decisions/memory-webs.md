---
keyword: Memory Webs
aliases: [memory strands, web-backed memory]
summary:
  A keyed memory collection is a flat descriptor note plus a sibling strand directory,
  addressed web:keyword.
metadata:
  status: superseded-in-part
  decided: 2026-08-24
  superseded_by:
    - decisions/webs-render-in-their-own-section
    - decisions/memory-links-are-authored
---

**Claim.** A keyed memory collection is one flat descriptor note
(`sase/memory/<web>.md`) plus a sibling directory of independently addressable strands
(`sase/memory/<web>/<slug>.md`), read on demand as `sase memory read <web>:<keyword>`.
The descriptor's own body, not any strand body, participates in core or reference
rendering. [[glossary/memory-web]] and [[glossary/memory-strand]] name this same shape.

> _Partially superseded:_ the sentence above on core/reference rendering is retired by
> [[decisions/webs-render-in-their-own-section]].

**Why.** This shape had been hand-built three times before it had a name: the glossary,
task types, and artifact relations each grew their own keyed-collection code, and the
glossary note alone moved between core and reference tiers four times because a
collection's rendering tier had nowhere to be declared. Rejected alternatives: a
config-backed keyed store (loses git-native diffing and per-strand identity), a nested
`sase/memory/webs/` segment (six document-layer path matchers hard-code a flat memory
filename with a character class that excludes `/`, so nesting would force changes across
all of them), one large note per collection (reintroduces the "inline everything or
nothing" problem this decision exists to solve), and a generic artifact database
(over-general for what is, in practice, always a small keyed set of short records). Per
[[decisions/corpus-before-mechanism]], this ships only with three real corpora already
proven: decisions, task types, and the migrated glossary.

**Cost.** One extra frontmatter field (`web: true`) to tell a web descriptor from an
ordinary note; per-strand scope merge across project and home roots; and an eleven-rule
fail-closed validator that must run in both `sase memory init` and `sase doctor`.

**Reopens when.** A web's strand count or supersession rate outgrows prose
cross-references, at which point the existing `supersedes` / `superseded-by` artifact
relations are the adopted mechanism — not a new, parallel link syntax.

> _Partially superseded:_ the "not a new, parallel link syntax" clause above is retired
> by [[decisions/memory-links-are-authored]].
