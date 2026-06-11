---
create_time: 2026-06-11
status: research
---

# SASE Memory: Build From Scratch or Adopt Zep? (Consolidated)

## Research Question

Should SASE implement its memory system with SASE-owned storage and retrieval primitives, or adopt an existing
agent-memory framework — specifically Zep (<https://github.com/getzep/zep>)?

This builds on `sdd/research/202605/memory_system_prior_art.md`, which surveyed Zep/Graphiti (among ~14 systems) as a
source of *design ideas*. This document pressure-tests Zep as an *adoption candidate*. It consolidates two independent
research passes (2026-06-11): one grounded in the SASE codebase plus live Zep/Graphiti docs, and one web fan-out pass
(22 sources fetched, 25 claims adversarially verified with 3-vote panels; 20 confirmed, 5 over-strong formulations
killed). Confidence labels below come from that verification pass.

## Short Answer: BUILD

Do not adopt Zep, and do not adopt Graphiti as the canonical store. Keep SASE's custom file-based, review-gated memory
system and close its one real gap — runtime discovery/search — incrementally inside `sase-core`. Borrow Zep/Graphiti's
strongest ideas without the dependency:

- temporal validity (`valid_at`, `invalid_at`, supersession instead of silent overwrite);
- raw episodes as first-class provenance;
- hybrid retrieval over lexical, semantic, and graph signals;
- derived facts/observations that never replace source evidence;
- context assembly that returns a bounded, cited context block.

A narrow hybrid stays open later: derived, rebuildable retrieval indexes (SQLite FTS / local embeddings, or
experimentally Graphiti) layered on top of the git-canonical markdown/JSONL memory — never as the source of truth.

Three things drive the decision: (1) Zep no longer offers a maintained self-hostable product at all, (2) the remaining
open-source path (Graphiti) violates SASE's core design invariants, and (3) Zep's evidenced benefits are chat-workload
token compression, not coding-agent memory quality.

## Where SASE Stands Today

SASE's memory system is not a greenfield — it is ~84 files / ~16K LOC in `src/sase/memory/`, and it is a governance
product, not just a retrieval problem:

- **Instruction memory**: `memory/short/*.md` loaded through `AGENTS.md`; **long-term reference memory**:
  `memory/long/*.md` as canonical, human-readable markdown+YAML in git.
- **Audited reads**: `sase memory read` accepts only approved long-memory paths, requires an agent identity and a
  reason, strips frontmatter, and records a JSONL read event.
- **Governed writes**: agents file proposals (`sase memory write`); humans promote via `sase memory review` over a
  locked JSONL proposal ledger. Agents cannot directly mutate canonical files.
- **Episodes**: deterministic `episode.json` evidence records under `~/.sase/projects/<project>/episodes/` with source
  refs, sha256 verification, indexes, aliases, and lexical BM25-style recall — no embeddings, no external database, no
  LLM in the write path.
- **Rebuildable projections**: `lesson.md`, `sources.jsonl`, and indexes are projections of canonical episode JSON.
- **Security posture**: retrieved memories are evidence unless reviewed; proposed memory must carry evidence.

The known gap (per the 202605 prior-art doc and the episodic-memory MVP epic) is a runtime discovery/search layer
(`sase memory search`), not memory fundamentals. Any replacement framework must therefore preserve local provenance,
human review, deterministic rebuilds, CLI/TUI workflows, multi-repo workspace semantics, and the `sase-core` API
boundary serving CLI, TUI, mobile, and editor frontends.

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
(50k credits) and ~$312/mo (200k credits), with API rate limits. The only self-managed option is enterprise BYOC —
which still runs in a cloud VPC. Beyond the hard mismatch with SASE's local-first/offline requirement, cloud-canonical
memory breaks SASE's governance questions outright: diffing memory in git, proving which source produced a fact,
reviewing/reverting proposals without leaving SASE, deterministic behavior across ephemeral workspaces, and not leaking
private repo/chat/artifact content to a hosted service by default.

### Graphiti is the only maintained open-source path

**Confidence: high (4 claims, all 3-0 unanimous).** Graphiti (<https://github.com/getzep/graphiti>) — Zep's temporal
knowledge graph engine — is Apache 2.0 and actively maintained (v0.29.2 released 2026-06-08, 196 releases). Zep itself
is a proprietary enterprise product built on Graphiti plus a proprietary "Context Graph Engine". The
`zep-python`/`zep-js`/`zep-go` SDKs are open source but are Zep Cloud *clients*, not self-hostable products. So the
real adoption question is "adopt Graphiti", not "adopt Zep".

## What Zep/Graphiti Does Well

This style of memory is genuinely relevant to SASE: agent work changes over time, old facts become invalid, and
retrieval often needs relationships such as "this retry fixed that failure" or "this memory was promoted from this
episode". Graphiti's strongest mechanics — episodic ingestion with provenance, facts with `valid_at`/`invalid_at` that
are invalidated rather than deleted, hybrid retrieval (semantic similarity + BM25 + graph traversal, optional
graph-distance reranking), and custom entity/edge types — are exactly the ideas worth copying into SASE's own contract.

## Why Graphiti Conflicts with SASE's Invariants

### Nondeterministic, LLM-driven, embedding-dependent writes

**Confidence: high (3 claims, all 3-0 unanimous).** Graphiti's ingestion pipeline is structurally LLM-driven: entity
extraction (with a reflexion pass), entity resolution/dedup, fact extraction, temporal extraction, and edge
invalidation are all LLM-prompt-driven, plus a required embedding provider (OpenAI by default; the quick start requires
`OPENAI_API_KEY`). Zep's own docs state "each episode involves multiple LLM calls", and a 2026 Zep blog concedes
LLM-only extraction "created variance, retry loops, and token burn". Local models via Ollama are possible but
non-default and fragile (docs warn small models cause ingestion failures; open issue #1116 shows the OpenAI provider
ignoring `api_base`). This directly conflicts with SASE's deterministic JSONL episodic store, its no-hidden-LLM-writes
philosophy, and the human-review write gate. Escape hatches (`add_fact_triple`, MinHash/LSH dedup) exist but still
require embeddings and bypass the value proposition.

### External graph database for retrieval

**Confidence: medium (core claim 2-1; backend details unanimous).** The Zep paper's stack is Neo4j (cosine similarity
and Okapi BM25 via Neo4j's Lucene, plus breadth-first traversal). As of mid-2026, Graphiti supports Neo4j 5.26
(default), FalkorDB 1.1.2, and Amazon Neptune; the embedded Kuzu backend is deprecated. Verifiers rejected over-strong
"hard requirement" phrasings (Kuzu *was* an embedded option), so state it precisely: **every non-deprecated backend is
an external database service.** That is a heavyweight dependency versus SASE's no-external-DB, file-based design —
heavy for a local-first tool whose memory must work in arbitrary repos and ephemeral agent workspaces — and an awkward
fit behind the `sase-core` Rust boundary (a Python + Neo4j + hosted-LLM pipeline wrapped by a Rust API serving multiple
frontends).

### Opaque canonical store, and governance still left to build

Graphiti's graph *is* the memory. Adopting it as the canonical store would replace git-versioned, human-reviewable
markdown with LLM-extracted graph records in a database — breaking SASE's audit/provenance trail, the review-gate trust
model, and the "retrieved memory is evidence, not instructions" stance. And even then, Graphiti supplies only graph
mechanics: SASE would still need to build canonical schemas, proposal/review UX, source hashing and verification,
filesystem/git integration, audit logs, workspace-aware identity, security policies, rebuild/migration tooling, and the
frontend API contracts. That is most of the SASE memory system — adopting Graphiti early would couple SASE's product
semantics to a graph library before its own memory contract is stable. (Using it as a *derived* index avoids the
canonical-store problem, at the operational cost above.)

### Memory-safety research favors the review gate

Recent research argues against eager LLM consolidation. The 2026 "Useful Memories Become Faulty When Continuously
Updated by LLMs" paper (<https://arxiv.org/abs/2605.12978>) found continuously rewritten memory can degrade below
no-memory baselines while raw episodic retention remains competitive — supporting SASE's existing direction of keeping
episodes canonical and promoting durable lessons through review. OWASP's Agent Memory Guard frames persistent memory as
a runtime-writeable attack surface and calls for integrity checks, read/write policies, snapshots, and rollback. SASE's
proposal/review/audit model maps to that threat model far better than an opaque auto-updating memory bank.

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
explicitly tool/model-agnostic, carrying zero vendor lock-in. Claude Code's CLAUDE.md/memory conventions follow the
same pattern (consistent with the 202605 survey, though not among the verified claims). SASE's approach is a more
engineered instance of an established convention, not an outlier.

## Alternatives (Brief)

The web-research pass attempted claims about Mem0/OpenMemory, Letta, LangMem, and Cognee, but none survived adversarial
verification, so this document makes no current-state assertions about them. The design-level comparison in
`sdd/research/202605/memory_system_prior_art.md` remains the best internal reference. The BUILD recommendation does not
depend on ranking them: it is driven by SASE's invariants, which every framework in this category violates to some
degree because they all center LLM-extracted records in a database.

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
and contested. That gap is addressable incrementally without surrendering any invariant.

## Recommended Path

Build SASE memory in layers, keeping canonical truth in files and treating every index as a rebuildable projection:

1. **Canonical local memory stays as designed**: `memory/short/*.md`, `memory/long/*.md`, audited-read and proposal
   JSONL ledgers, and `episodes/<id>/episode.json` evidence. Do not store canonical truth in a vector DB, Graphiti DB,
   or Zep Cloud.
2. **Define the SASE memory contract before choosing retrieval engines**, in `sase-core` per the repo's core-boundary
   guidance, with thin Python adapters. The contract should capture: kind (semantic/procedural/episodic/observation),
   scope (home/project/sibling/changespec/agent_family), trust level (canonical/proposed/derived/untrusted_evidence),
   subject anchors (entities, files, commands), temporal fields (`valid_at`, `invalid_at`, `supersedes`), and evidence
   links to episodes/sources.
3. **Close the retrieval gap with deterministic local indexes**: `sase memory search` over SQLite FTS5 (per the 202605
   roadmap; Tantivy is the Rust-native alternative), plus explicit extraction of high-signal SASE entities (paths,
   symbols, commands, agents, ChangeSpecs, beads, branch names, memory/episode ids) and simple graph edges derived from
   existing evidence (episode→source, episode→proposal, proposal→memory, fact-supersedes-fact, agent retry/fork
   lineage). Most SASE queries contain exact anchors, so lexical + structured entity search should be a strong
   baseline.
4. **Add embeddings only after lexical baselines show measurable misses** (`sqlite-vec` + local model per the 202605
   roadmap), measured via prompt-to-memory fixtures on real SASE workloads.
5. **Gate LLM-generated memory behind review**: a background "memory candidate" generator may propose
   facts/observations, but nothing becomes canonical without `sase memory review`. Add temporal/supersession semantics
   to proposals before adding any LLM extraction.
6. **Re-evaluate Graphiti only as an optional, derived, rebuildable index plugin** — behind an explicit backend
   boundary (`sase memory search --backend local|graphiti|auto`, `sase memory index rebuild --backend ...`), feeding it
   SASE episodes/memories keyed by SASE ids, treating its facts as derived search results, and only if (a) the local
   search API and result schema are stable, (b) temporal-relational queries ("what did we believe about X before commit
   Y?") become a demonstrated need, and (c) a credible embedded backend replaces the deprecated Kuzu option. The graph
   must always be rebuildable from the files, and disabling the adapter must lose nothing.
7. **Expose retrieval as bounded, cited context**: results carry type, trust level, score, source path/hash, excerpt,
   and "why matched" terms; unreviewed or transcript-derived content stays clearly marked untrusted; retrieved memory
   is never injected as system-level instruction unless it is canonical reviewed memory. This copies the useful part of
   Zep's context blocks without adopting Zep as the source of truth.

## Final Recommendation

**BUILD.** Implement SASE's memory system as a SASE-native, local-first, review-gated memory contract. Do not use Zep
as the core memory system; use Zep/Graphiti as design input and, at most, as a future optional derived retrieval
backend.

The decisive facts: Zep abandoned its self-hostable product in April 2025 (a concrete lock-in precedent for exactly the
failure mode SASE would be exposed to); the surviving open-source engine requires an external graph database and
nondeterministic LLM/embedding pipelines that contradict SASE's trust model; the claimed retrieval benefits are
vendor-reported on chat workloads with no coding-agent benchmark in existence; and ~16K LOC of working, opinionated
memory infrastructure already exists with only the discovery layer missing. Adopting Zep/Graphiti would outsource the
wrong layer.

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

- How do Mem0/OpenMemory, Letta, LangMem, and Cognee actually compare on SASE's axes? One could conceivably fit better
  than Graphiti, though all share the LLM-extraction-into-database shape.
- What concrete retrieval-quality gap exists between SASE's lexical episodic recall and graph/embedding retrieval *on
  coding-agent workloads*? No such benchmark exists; SASE should build prompt-to-memory fixtures (per the 202605
  evaluation plan) to measure its own misses before buying anything.
- What is Graphiti's measured per-episode LLM cost and ingestion latency at SASE-scale volume with local models?
- Does any credible embedded/in-process graph backend land on Graphiti's roadmap post-Kuzu?

## Sources

Primary (vendor/repo/paper):

- Zep open-source strategy change: <https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/>
- getzep/zep repo (CE deprecation notice): <https://github.com/getzep/zep>
- Zep FAQ: <https://help.getzep.com/faq>
- Zep key concepts: <https://help.getzep.com/concepts>
- Zep vs Graphiti: <https://help.getzep.com/zep-vs-graphiti>
- Zep pricing: <https://www.getzep.com/pricing>
- Graphiti repo: <https://github.com/getzep/graphiti>
- Graphiti overview: <https://help.getzep.com/graphiti/getting-started/overview>
- Graphiti quick start: <https://help.getzep.com/graphiti/getting-started/quick-start>
- Zep/Graphiti paper: <https://arxiv.org/abs/2501.13956>
- LoCoMo re-evaluation dispute: <https://github.com/getzep/zep-papers/issues/5>
- Cline Memory Bank docs: <https://docs.cline.bot/features/memory-bank>
- OWASP Agent Memory Guard: <https://owasp.org/www-project-agent-memory-guard/>
- Useful Memories Become Faulty When Continuously Updated by LLMs: <https://arxiv.org/abs/2605.12978>

Secondary (experience reports, comparisons):

- Graphiti ingestion latency issue: <https://github.com/getzep/graphiti/issues/1193>
- Graphiti Ollama/api_base issue: <https://github.com/getzep/graphiti/issues/1116>
- Zep benchmark-war post (vs Mem0): <https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/>
- Graphiti agent-memory writeup: <https://codex.danielvaughan.com/2026/03/30/graphiti-agent-memory-store/>
- Neo4j on Graphiti: <https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/>
- Markdown+SQLite memory pattern: <https://towardsdatascience.com/memweave-zero-infra-ai-agent-memory-with-markdown-and-sqlite-no-vector-database-required/>

Internal:

- `docs/memory.md`, `memory/README.md`, `src/sase/memory/` — current memory system docs and implementation.
- `sdd/research/202605/memory_system_prior_art.md` — design-level survey of Zep/Graphiti, Mem0, Letta, LangGraph, etc.
- `sdd/research/202605/structured_episodic_memory_for_agent_chats.md` — episodic store design.
- `sdd/research/202605/memory_episode_connected_components_and_events.md` — episode/event linkage design.
- `sdd/research/202604/dynamic_memory_implementation.md` — earlier dynamic-memory implementation research.
- `sdd/epics/202605/structured_episodic_memory_mvp.md` — implemented MVP spec.
