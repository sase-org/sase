---
keyword: No Retrieval Mechanism Before Its Corpus
aliases: [mechanism before corpus, corpus first]
summary:
  SASE does not build memory retrieval or linking machinery ahead of a corpus that
  demonstrably needs it.
metadata:
  status: accepted
  decided: 2026-07-13
---

**Claim.** SASE does not ship memory retrieval, linking, or recall machinery ahead of a
corpus that demonstrably needs it. Mechanism follows corpus; the corpus is the evidence
that the mechanism is the right shape.

**Why.** This was learned three times, at real cost, and every artifact of the learning
was deleted from the tree. Keyword-triggered dynamic memory was built 2026-04-12 and
removed 2026-05-31 (`e8c2f14bb`). A smaller episode-recall path was built 2026-05-23 and
removed 2026-06-15 (`37973b8b3`) — that removal alone deleted a CLI command family, a
wire/facade layer, an ACE modal, a doctor check, and a docs page. Memory note
`keywords:` metadata, a runtime trigger for the dynamic engine, was removed 2026-07-13
(`21e1640ee`). Rejected alternative: keep building retrieval mechanisms speculatively,
on the theory that agents will eventually want them — rejected because that theory was
tested three times and failed each time at nontrivial cleanup cost.

**Cost.** Waiting for a corpus means real requests for retrieval sit unaddressed until
something concrete demonstrates the need, which can feel slow when the need is real but
not yet evidenced.

**Reopens when.** A specific, already-existing corpus demonstrably needs a mechanism
that plain audited reads cannot serve — never speculatively. The
[[decisions/memory-webs]] decision itself leans on this record: the `decisions` web
ships with a real corpus of six records and deliberately no closure engine or typed
links in its first version.
