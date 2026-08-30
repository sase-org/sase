---
keyword: Memory Links Are Authored
aliases: [authored memory links, wiki-style memory links]
summary:
  A memory file declares how its links are detected and rendered, and authors links
  inline as `[[target]]` / `![[target]]`.
metadata:
  status: accepted
  decided: 2026-08-30
---

**Claim.** A memory file declares how its links are detected and rendered, and authors
links inline as `[[target]]` / `![[target]]`.

**Why.** The corpus outgrew prose cross-references. Three webs plus the flat notes
already named each other in running text, and [[decisions/gates-never-block]] already
contained an authored `![[decisions/single-turn-agents]]` that `sase memory show`
printed as a literal. That is the corpus a retrieval rule can actually rest on: a
specific, already-existing body of notes that plain audited reads could not serve.

Rejected alternatives: staying on implicit phrase matching — it works only for a
glossary-shaped corpus, cannot be authored per link, and cannot be scoped to one target;
and the `supersedes` / `superseded-by` artifact relations that [[decisions/memory-webs]]
named as the adopted mechanism — they are out-of-band typed relations between artifacts,
recorded in an index rather than authored in the prose that motivates them, and cannot
express "render this target's body at the bottom of this read." See
[[sase_artifacts.md]].

This record supersedes the "not a new, parallel link syntax" clause of
[[decisions/memory-webs]]. It satisfies the reopen condition of
[[decisions/corpus-before-mechanism]].

**Cost.** A second link vocabulary in the tree; unresolved links that only warn; two
more frontmatter keys on every memory kind.

**Reopens when.** Authors need a relation `[[target]]` cannot express — a typed,
queryable edge such as supersession that must be found without reading the note that
states it — or unresolved-link warnings become noise that hides real breakage. A
display-text form `[[target|label]]` would be a compatible addition, not a reopen.
