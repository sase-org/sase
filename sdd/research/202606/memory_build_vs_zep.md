---
create_time: 2026-06-11
status: research
---

# Memory System Build-vs-Buy: From Scratch vs Zep

## Research Question

Should SASE keep building its memory system from scratch, or adopt an existing agent-memory framework — specifically
Zep (<https://github.com/getzep/zep>)?

This builds on `sdd/research/202605/memory_system_prior_art.md`, which surveyed Zep/Graphiti (among ~14 systems) as a
source of *design ideas*. This document pressure-tests Zep as an *adoption candidate*, using web research current as of
2026-06-11. Findings below were produced by a fan-out research pass (22 sources fetched, 110 claims extracted, 25
adversarially verified with 3-vote panels; 20 confirmed, 5 over-strong formulations killed).

## Short Answer: BUILD

Do not adopt Zep, and do not adopt Graphiti as the canonical store. Keep SASE's custom file-based memory system and
close its one real gap (retrieval quality) incrementally inside `sase-core`. A narrow hybrid remains open later:
derived, rebuildable retrieval indexes (SQLite FTS / local embeddings, or experimentally Graphiti) layered on top of
the git-canonical markdown/JSONL memory — never as the source of truth.

The decision is driven by three things: (1) Zep no longer offers a maintained self-hostable product at all, (2) the
remaining open-source path (Graphiti) violates SASE's core design invariants, and (3) Zep's evidenced benefits are
chat-workload token compression, not coding-agent memory quality.

## Where SASE Stands Today

SASE's memory system is not a greenfield. It is ~84 files / ~16K LOC in `src/sase/memory/`:

- Tier 1/2 canonical memory as markdown+YAML in git (`memory/short/`, `memory/long/`), audited reads via
  `sase memory read` with an append-only read log.
- Human-review-gated writes: agents file proposals (`sase memory write`), humans approve via a review TUI
  (`sase memory review`), with a locked JSONL proposal ledger.
- A deterministic episodic store (JSONL index, sha256 source verification) with lexical BM25-style recall — no
  embeddings, no external database, no LLM in the write path.

The known gap (per the 202605 prior-art doc and the episodic-memory MVP epic) is a runtime discovery/search layer
(`sase memory search`), not memory fundamentals.

## Zep's Current State (verified June 2026)

### Self-hostable Zep is dead

**Confidence: high (6 claims, all 3-0 unanimous).** Zep Community Edition — the self-hostable open-source Zep server —
was deprecated on 2025-04-02 and receives no updates or support. The code remains Apache 2.0 but was moved to a
`legacy/` folder, and the `getzep/zep` repo was repurposed as an examples/integrations repo for Zep Cloud.
Post-announcement activity on the CE code is Dependabot bumps only. Self-hosting "Zep" in 2026 means running abandoned
software.

> Vendor blog (2025-04-02): "we've decided to stop maintaining and releasing Zep Community Edition... The existing
> repository will remain open under the Apache 2.0 license, but we will no longer provide updates or active support."

### The supported product is a metered cloud SaaS

**Confidence: high (3-0 unanimous).** Zep Cloud is hosted and usage-metered: free tier ~1,000 "episode credits"/month
(processing halts when depleted; credits are consumed per ~350 bytes of episode payload), paid Flex plans at ~$104/mo
(50k credits) and ~$312/mo (200k credits), with API rate limits and processing-concurrency limits. The only
self-managed option is enterprise BYOC — which still runs in a cloud VPC. This is a hard mismatch with SASE's
local-first/offline requirement.

### Graphiti is the only maintained open-source path

**Confidence: high (4 claims, all 3-0 unanimous).** Graphiti (<https://github.com/getzep/graphiti>) — Zep's temporal
knowledge graph engine — is Apache 2.0 and actively maintained (v0.29.2 released 2026-06-08, 196 releases). Zep itself
is positioned as a proprietary enterprise product built on Graphiti plus a proprietary "Context Graph Engine". The
`zep-python`/`zep-js`/`zep-go` SDKs are open source but are Zep Cloud *clients*, not self-hostable products. So the
real adoption question is "adopt Graphiti", not "adopt Zep".

## Why Graphiti Conflicts with SASE's Invariants

### Nondeterministic, LLM-driven, embedding-dependent writes

**Confidence: high (3 claims, all 3-0 unanimous).** Graphiti's ingestion pipeline is structurally LLM-driven: entity
extraction (with a reflexion pass), entity resolution/dedup, fact extraction, temporal extraction, and edge
invalidation are all LLM-prompt-driven with structured JSON output, plus a required embedding provider (OpenAI by
default; the quick start requires `OPENAI_API_KEY`). Zep's own docs state "each episode involves multiple LLM calls",
and a 2026 Zep blog concedes LLM-only extraction "created variance, retry loops, and token burn". Local models via
Ollama are possible but non-default and fragile (docs warn small models cause ingestion failures; open issue #1116
shows the OpenAI provider ignoring `api_base`).

This directly conflicts with SASE's deterministic JSONL episodic store, its no-hidden-LLM-writes philosophy, and the
human-review write gate. Escape hatches (`add_fact_triple`, MinHash/LSH dedup) exist but still require embeddings and
bypass the value proposition.

### External graph database for retrieval

**Confidence: medium (core claim 2-1; backend details unanimous).** The Zep paper's stack is Neo4j (cosine similarity
and Okapi BM25 via Neo4j's Lucene, plus breadth-first traversal). As of mid-2026, Graphiti supports Neo4j 5.26
(default), FalkorDB 1.1.2, and Amazon Neptune; the embedded Kuzu backend is deprecated. Verifiers rejected over-strong
"hard requirement" phrasings of this (Kuzu *was* an embedded option), so state it precisely: **every non-deprecated
backend is an external database service.** That is a heavyweight dependency versus SASE's no-external-DB, file-based
design, and an awkward fit behind the `sase-core` Rust boundary (a Python + Neo4j + hosted-LLM pipeline wrapped by a
Rust API serving multiple frontends).

### Opaque canonical store

Graphiti's graph *is* the memory. Adopting it as the canonical store would replace git-versioned, human-reviewable
markdown with LLM-extracted graph records in a database — breaking SASE's audit/provenance trail, the review-gate
trust model, and the "retrieved memory is evidence, not instructions" stance. (Using it as a *derived* index avoids
this, at the operational cost above.)

## Benchmark Evidence Is Chat-Centric and Vendor-Reported

**Confidence: high (2 claims, both 3-0 unanimous).** Zep's headline Deep Memory Retrieval win over MemGPT (94.8% vs
93.4%) is marginal — the trivial full-conversation baseline scored 94.4% — and the paper's own authors call DMR
inadequate: "The high performance achieved by simple full-context approaches using modern LLMs further highlights the
benchmark's inadequacy for evaluating memory systems."

The genuinely strong result is LongMemEval_s (~115k-token conversations): +15.2%/+18.5% accuracy over full-context
baselines while compressing context 115k→1.6k tokens and cutting latency ~29-31s→~2.6-3.2s. But these are vendor
self-reported numbers from a non-peer-reviewed preprint, on conversational workloads — not coding-agent memory. No
independent replication was found; Emergence AI later matched/beat the figure (76.75%) with simple RAG at comparable
latency; and a separate Zep LoCoMo claim (84%) was independently re-evaluated down to ~58% (documented in
`getzep/zep-papers` issue #5). No benchmark measuring memory systems on coding-agent workloads was found at all.

## The File-Based Path Is the Prevailing Coding-Agent Convention

**Confidence: high (2 claims, both 3-0 unanimous).** Cline's official Memory Bank is plain markdown files in the
project repo, readable/editable by human and agent alike, with no database, graph store, or external service — and
explicitly tool/model-agnostic ("works with any AI that can read docs"), carrying zero vendor lock-in. Claude Code's
CLAUDE.md/memory conventions follow the same pattern (not among the verified claims, but consistent with the 202605
survey). SASE's approach is a more engineered instance of an established convention, not an outlier.

## Alternatives (Brief)

The web-research pass attempted claims about Mem0/OpenMemory, Letta, LangMem, and Cognee, but none survived
adversarial verification, so this document makes no current-state assertions about them. Two points still hold:

- The design-level comparison in `sdd/research/202605/memory_system_prior_art.md` (what to borrow/avoid from each)
  remains the best internal reference for those systems.
- The BUILD recommendation does not depend on ranking the alternatives: it is driven by SASE's invariants
  (local-first, deterministic writes, git-canonical human-reviewable storage, review-gated promotion), which every
  framework in this category violates to some degree because they all center LLM-extracted records in a database.

## Build-vs-Buy Scorecard

| SASE invariant | Zep Cloud | Graphiti (self-host) | Keep building |
| --- | --- | --- | --- |
| Local-first / offline-capable | No — metered SaaS | Partial — external graph DB + (default) hosted LLM/embeddings | Yes |
| Deterministic writes, no hidden LLM | No | No — multi-stage LLM extraction | Yes |
| Git-versioned human-reviewable canonical memory | No — opaque cloud graph | No — graph DB is the store | Yes |
| Audit/provenance + human review gate | Partial (API logs) | No native review gate | Yes (already built) |
| Fits `sase-core` Rust multi-frontend boundary | API client only | Poor — Python+Neo4j+LLM behind Rust | Yes (index API in core) |
| Vendor/license risk | High — already killed CE once (Apr 2025) | Medium — Apache 2.0, single-vendor roadmap (Kuzu embedded backend already dropped) | None |
| Retrieval quality at scale | Strong claims (chat workloads only) | Same engine | Gap — needs `memory search`, FTS, optional embeddings |

The only cell where buy beats build is retrieval quality — and the evidence for it is conversational, vendor-reported,
and contested. That gap is addressable incrementally (SQLite FTS5 in `sase-core`, then `sqlite-vec`/local embeddings
per the 202605 roadmap) without surrendering any invariant.

## Recommended Decision

**BUILD.** Specifically:

1. Keep canonical memory exactly as designed: markdown+YAML in git, audited reads, review-gated writes, deterministic
   episodic JSONL.
2. Close the retrieval gap in `sase-core` per the existing 202605 roadmap: `sase memory search` over SQLite FTS5
   first, embeddings (`sqlite-vec` + local model) only after lexical baselines show measurable misses.
3. Keep borrowing Zep/Graphiti *ideas* (temporal validity fields, supersession over edits, fact provenance) without
   the dependency.
4. Re-evaluate Graphiti only as an optional, derived, rebuildable index plugin if temporal-relational queries
   ("what did we believe about X before commit Y?") become a demonstrated need — and only if a credible embedded
   backend replaces the deprecated Kuzu option. The graph must always be rebuildable from the files.

The decisive facts: Zep abandoned its self-hostable product in April 2025 (a concrete lock-in precedent for exactly
the failure mode SASE would be exposed to); the surviving open-source engine requires an external graph database and
nondeterministic LLM/embedding pipelines that contradict SASE's trust model; and ~16K LOC of working, opinionated
memory infrastructure already exists with only the discovery layer missing.

## Caveats

- Benchmark numbers (DMR, LongMemEval) are vendor self-reported from Zep's non-peer-reviewed preprint; no independent
  replication found; one separate Zep benchmark claim (LoCoMo 84%) was independently re-evaluated to ~58%.
- The external-graph-DB finding is medium confidence: read it as "every non-deprecated backend is an external DB
  service", not "no local option ever existed" (Kuzu was embedded, now deprecated).
- No claims about Mem0/OpenMemory, Letta, LangMem, or Cognee survived verification; the BUILD recommendation is robust
  to this gap because it rests on SASE's invariants, not alternative-ranking.
- All vendor-state facts (CE deprecation, pricing, Graphiti v0.29.2, Kuzu deprecation) verified as of June 2026; Zep's
  strategy has already pivoted once and could again.
- Third-party ingestion latency/cost measurements for Graphiti are thin — supported mainly by Zep's own admissions and
  open GitHub issues (#1193, #1116).

## Open Questions

- How do Mem0/OpenMemory, Letta, LangMem, and Cognee actually compare on SASE's axes (local-first, deterministic
  writes, human-reviewable storage, license stability)? None survived verification this pass; one could conceivably
  fit better than Graphiti, though all share the LLM-extraction-into-database shape.
- What concrete retrieval-quality gap exists between SASE's lexical episodic recall and graph/embedding retrieval *on
  coding-agent workloads*? No such benchmark exists; SASE could build prompt-to-memory fixtures (per the 202605
  evaluation plan) to measure its own misses before buying anything.
- What is Graphiti's measured per-episode LLM cost and ingestion latency at SASE-scale volume with local models?
- Does any credible embedded/in-process graph backend land on Graphiti's roadmap post-Kuzu?

## Sources

Primary (vendor/repo/paper):

- Zep open-source strategy change: <https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/>
- getzep/zep repo (CE deprecation notice): <https://github.com/getzep/zep>
- Zep FAQ: <https://help.getzep.com/faq>
- Zep pricing: <https://www.getzep.com/pricing>
- Graphiti repo: <https://github.com/getzep/graphiti>
- Graphiti overview: <https://help.getzep.com/graphiti/getting-started/overview>
- Graphiti quick start: <https://help.getzep.com/graphiti/getting-started/quick-start>
- Zep/Graphiti paper: <https://arxiv.org/pdf/2501.13956>
- LoCoMo re-evaluation dispute: <https://github.com/getzep/zep-papers/issues/5>
- Cline Memory Bank docs: <https://docs.cline.bot/features/memory-bank>

Secondary (experience reports, comparisons):

- Graphiti ingestion latency issue: <https://github.com/getzep/graphiti/issues/1193>
- Graphiti Ollama/api_base issue: <https://github.com/getzep/graphiti/issues/1116>
- Zep benchmark-war post (vs Mem0): <https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/>
- Graphiti agent-memory writeup: <https://codex.danielvaughan.com/2026/03/30/graphiti-agent-memory-store/>
- Neo4j on Graphiti: <https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/>
- Markdown+SQLite memory pattern: <https://towardsdatascience.com/memweave-zero-infra-ai-agent-memory-with-markdown-and-sqlite-no-vector-database-required/>

Internal:

- `sdd/research/202605/memory_system_prior_art.md` — design-level survey of Zep/Graphiti, Mem0, Letta, LangGraph, etc.
- `sdd/research/202605/structured_episodic_memory_for_agent_chats.md` — episodic store design.
- `sdd/epics/202605/structured_episodic_memory_mvp.md` — implemented MVP spec.
