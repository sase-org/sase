---
create_time: 2026-06-11
status: research
---

# SASE Memory: Build From Scratch Or Use Zep/Graphiti?

## Research Question

Should SASE implement its memory system with SASE-owned storage and retrieval primitives, or should it use an existing
agent-memory framework such as Zep or Graphiti?

## Short Answer

SASE should **not** make Zep the core memory system. SASE should keep canonical memory local, inspectable, review-gated,
and rebuildable from SASE-owned files/events. It should borrow Zep/Graphiti's strongest ideas:

- temporal validity (`valid_at`, `invalid_at`, supersession instead of silent overwrite);
- raw episodes as first-class provenance;
- hybrid retrieval over lexical, semantic, and graph signals;
- derived facts/observations that never replace source evidence;
- context assembly that returns a bounded, cited context block.

The best implementation path is to build a SASE-native memory contract first, then add Graphiti as an optional
experimental derived-index backend if lexical/SQLite search proves insufficient.

## Sources Checked

External sources checked on 2026-06-11:

- Zep repository: <https://github.com/getzep/zep>
- Graphiti repository: <https://github.com/getzep/graphiti>
- Zep docs, key concepts: <https://help.getzep.com/concepts>
- Zep docs, Zep vs Graphiti: <https://help.getzep.com/zep-vs-graphiti>
- Zep docs, Graphiti overview: <https://help.getzep.com/graphiti/getting-started/overview>
- Zep docs, facts: <https://help.getzep.com/facts>
- Zep docs, episodes: <https://help.getzep.com/episodes>
- Zep docs, search: <https://help.getzep.com/searching-the-graph>
- Zep docs, FAQ: <https://help.getzep.com/faq>
- Zep paper: <https://arxiv.org/abs/2501.13956>
- OWASP Agent Memory Guard: <https://owasp.org/www-project-agent-memory-guard/>
- Useful Memories Become Faulty When Continuously Updated by LLMs: <https://arxiv.org/abs/2605.12978>

Local sources reviewed:

- `docs/memory.md`
- `memory/README.md`
- `sdd/research/202605/memory_system_prior_art.md`
- `sdd/research/202604/dynamic_memory_implementation.md`
- `sdd/research/202605/memory_episode_connected_components_and_events.md`
- `src/sase/memory/read_log.py`
- `src/sase/memory/proposals/`
- `src/sase/memory/episodes/`

## Current SASE Memory Shape

SASE already has a memory product, not just a retrieval problem:

- **Instruction memory**: `memory/short/*.md` is loaded through `AGENTS.md`.
- **Long-term reference memory**: `memory/long/*.md` is canonical, human-readable Markdown with metadata.
- **Audited reads**: `sase memory read` accepts only approved long-memory Markdown paths, requires an agent identity,
  requires a reason, strips frontmatter from output, and records a JSONL read event.
- **Governed writes**: `sase memory write` creates proposals under project state; agents cannot directly mutate canonical
  long-memory files. Human `sase memory review` is the promotion path.
- **Episodes**: `sase memory episodes` builds deterministic `episode.json` evidence records under
  `~/.sase/projects/<project>/episodes/`, with source refs, indexes, aliases, verification, auto-build state, and
  lexical recall.
- **Rebuildable projections**: `lesson.md`, `sources.jsonl`, and indexes are projections of canonical episode JSON.
- **Security posture**: retrieved memories are evidence unless reviewed; proposed memory must carry evidence.

That means a replacement framework must support more than "remember and search." It must preserve local provenance,
review, deterministic rebuilds, CLI/TUI workflows, multi-repo workspace semantics, and future core APIs used by CLI,
TUI, mobile, editor integrations, and sibling repos.

## What Zep Is Now

Important current-state finding: **`getzep/zep` is not a self-hosted open-source Zep server to embed as SASE memory.**

The current `getzep/zep` README describes the repository as examples, integrations, and tools. It says Zep Community
Edition is deprecated and moved into `legacy/`; current Zep development recommends Zep Cloud or example projects. The
Zep FAQ says CE is deprecated and no longer supported; alternatives are Zep Cloud, Graphiti, or enterprise BYOC.

So the realistic choices are:

1. **Zep Cloud/BYOC** as a managed external memory service.
2. **Graphiti** as an open-source temporal graph framework that SASE would operate itself.
3. **SASE-native canonical memory** with optional adapters to Zep/Graphiti.

## What Zep/Graphiti Does Well

Zep's current model is a temporal context graph. It ingests chat, business data, documents, and events, extracts
entities and relationships, and assembles token-efficient context blocks. Zep docs describe the Context Graph as a
memory unit where nodes are entities and edges are facts/relationships that can be invalidated while preserving history.

Graphiti is the open-source engine underneath this style of memory. The docs emphasize:

- temporal graph construction from unstructured and structured data;
- episodic ingestion with provenance;
- facts with `valid_at` and `invalid_at`;
- hybrid retrieval over semantic similarity, BM25 full-text search, and graph traversal;
- optional graph distance reranking;
- custom entity and edge types;
- pluggable graph backends such as Neo4j, FalkorDB, and Amazon Neptune;
- LLM and embedding provider integrations.

This is genuinely relevant to SASE. Agent work changes over time, old facts become invalid, and retrieval often needs
relationships such as "this retry fixed that failure" or "this memory was promoted from this episode."

## Where Zep/Graphiti Fits Poorly

### 1. Zep Cloud is the wrong canonical store for SASE

SASE memory is repo-adjacent and user-auditable. Canonical memory must survive offline work, branch/workspace churn,
local review, and potentially private project state. Moving canonical memory into Zep Cloud would make SASE dependent on
an external service for its own operating instructions and project evidence.

Cloud memory also creates portability and governance problems:

- How does a user diff memory changes in git?
- How does an agent prove which source produced a retrieved fact?
- How does a user review, edit, reject, or revert a proposed memory without leaving SASE?
- How does SASE keep behavior deterministic across machines and ephemeral workspaces?
- How does SASE avoid leaking private repo, chat, or artifact content to a hosted service by default?

These are core SASE requirements, not edge cases.

### 2. Graphiti is a framework, not SASE's governance layer

Graphiti gives temporal graph mechanics, but SASE would still need to build:

- local canonical schemas;
- proposal and review UX;
- source hashing and verification;
- filesystem and git integration;
- read/write audit logs;
- workspace-aware identity;
- memory security policies;
- rebuild and migration tooling;
- CLI/TUI/mobile/editor API contracts.

That is most of the SASE memory system. If Graphiti is adopted too early, SASE risks coupling its product semantics to a
graph library before its own memory contract is stable.

### 3. Runtime and dependency cost is high

Graphiti normally adds a graph database and model-provider dependency. Its repo and docs show Neo4j/FalkorDB/Neptune
style backends, Docker Compose setup, LLM clients, embedders, and optional rerankers. That is reasonable for a hosted
assistant application, but heavy for a local-first development tool whose memory must work in arbitrary repos and
ephemeral agent workspaces.

SASE's current deterministic lexical recall is limited, but it is cheap, inspectable, testable, and works without an
LLM or graph server.

### 4. Automatic memory consolidation is a real safety risk

Recent memory research argues against eager LLM consolidation. The 2026 "Useful Memories Become Faulty..." paper found
that continuously rewritten memory can degrade below no-memory baselines, while raw episodic retention remains
competitive. Its practical recommendation is to treat raw episodes as first-class evidence and gate consolidation.

That supports SASE's existing direction: keep episodes canonical, then promote durable lessons through review.

OWASP's Agent Memory Guard frames persistent memory as a runtime-writeable attack surface. It specifically calls for
integrity checks, policies on reads/writes, snapshots, anomaly detection, and rollback. SASE's proposal/review/audit
model maps better to that threat model than an opaque auto-updating memory bank.

## Decision Matrix

| Option | Strengths | Weaknesses | Fit |
| --- | --- | --- | --- |
| Use Zep Cloud as core memory | Mature managed retrieval, context assembly, enterprise features, low-latency hosted graph | External dependency, privacy risk, cloud lock-in, poor git/local audit fit, CE deprecated | Poor |
| Use Graphiti as core memory | Strong temporal graph model, OSS, hybrid retrieval, custom entities, provenance-oriented episodes | Operate graph DB + LLM/embedding stack, still need SASE governance, harder deterministic rebuilds | Medium |
| Build SASE-native core, borrow Zep ideas | Local-first, reviewable, deterministic, aligned with existing SASE CLI/TUI/state, easy to test | More custom implementation, weaker retrieval initially | Best |
| Build SASE-native core with optional Graphiti adapter | Keeps canonical contract local, allows high-quality graph retrieval where configured | Adapter complexity, eventual consistency, duplicate indexes | Best future path |

## Recommended Architecture

Build SASE memory in layers:

### Layer 1: Canonical Local Memory

Keep canonical memory as files and append-only ledgers:

- `memory/short/*.md` for always-loaded project instructions.
- `memory/long/*.md` for reviewed durable semantic/procedural memory.
- `~/.sase/projects/<project>/memory_reads.jsonl` for audited reads.
- `~/.sase/projects/<project>/memory_proposals.jsonl` for write/review events.
- `~/.sase/projects/<project>/episodes/<episode-id>/episode.json` for private evidence.
- Future curated event records only after review.

Do not store canonical truth in a vector DB, Graphiti DB, or Zep Cloud.

### Layer 2: SASE Memory Contract

Define the durable contract in SASE terms before choosing retrieval engines:

```yaml
id: mem-20260611-example
kind: semantic | procedural | episodic | observation | fact
scope: home | project | sibling | changespec | agent_family
trust: canonical | proposed | derived | untrusted_evidence
subject:
  entities: []
  files: []
  commands: []
valid_at: null
invalid_at: null
supersedes: []
evidence:
  - kind: episode
    path: ~/.sase/projects/sase/episodes/...
retrieval:
  keywords: []
  embedding_text: ""
```

This contract should live where shared frontends can use it. Per the repo's core-boundary guidance, behavior needed by
CLI, TUI, mobile, editor integrations, or sibling repos belongs in `sase-core` with thin Python adapters.

### Layer 3: Rebuildable Local Indexes

Start with deterministic, local indexes:

- SQLite FTS5 or Tantivy for BM25-style lexical recall.
- Explicit entity extraction for high-signal SASE entities: paths, symbols, commands, agents, ChangeSpecs, beads,
  sibling repos, branch names, memory ids, episode ids.
- Simple graph edges derived from existing evidence:
  - episode cites source;
  - episode produced proposal;
  - memory promoted from proposal;
  - fact supersedes fact;
  - agent retried/forked/resumed agent;
  - ChangeSpec/bead/file weak refs.

Only after that should SASE add embeddings. Most SASE queries contain exact anchors, so lexical and structured entity
search should be a strong baseline.

### Layer 4: Optional Graphiti Adapter

If local lexical/entity retrieval is not enough, add a Graphiti adapter as a derived backend:

- Feed SASE episodes, canonical memories, proposals, and events into a Graphiti graph.
- Use SASE ids as external ids.
- Store SASE source paths/hashes in episode metadata.
- Treat Graphiti facts/observations as derived search results, not canonical truth.
- Route any durable memory update through `sase memory write` and human review.
- Allow disabling the adapter without losing memory.

The adapter should be behind a capability boundary such as:

```text
sase memory index rebuild --backend local
sase memory index rebuild --backend graphiti
sase memory search --backend auto
sase memory search --backend local
sase memory search --backend graphiti
```

### Layer 5: Context Assembly

Expose retrieval as bounded, cited context:

- return result type, trust level, score, source path, source hash, and excerpt;
- include "why matched" terms/entities/edges;
- keep unreviewed or transcript-derived content clearly marked as untrusted;
- never inject retrieved memory as system-level instruction unless it is canonical reviewed memory.

This copies the useful part of Zep context blocks without adopting Zep as the source of truth.

## Concrete Near-Term Recommendation

1. Keep current `memory/short`, `memory/long`, audited reads, proposals, and episodes as the canonical memory system.
2. Add a `sase memory search` MVP over local canonical memory and episodes using SQLite FTS5 or Tantivy plus explicit
   SASE entity extraction.
3. Add temporal fields and supersession/retraction semantics to proposals/events before adding LLM extraction.
4. Add a background "memory candidate" generator that can propose facts/observations, but require `sase memory review`
   before anything becomes canonical.
5. Add a Graphiti proof-of-concept only after the local search API and result schema are stable. The POC should index a
   small project subset and compare retrieval quality, latency, setup cost, and explainability against local search.

## Final Recommendation

**Implement SASE's memory system from scratch as a SASE-native, local-first, review-gated memory contract. Do not use Zep
as the core memory system. Use Graphiti/Zep as design input and, later, as an optional derived retrieval backend.**

This gives SASE the properties it actually needs: deterministic local operation, transparent review, source-linked
evidence, git-friendly canonical files, and portable behavior across SASE frontends. Zep/Graphiti is excellent prior art
for temporal graph retrieval, but adopting it as the core would outsource the wrong layer.
