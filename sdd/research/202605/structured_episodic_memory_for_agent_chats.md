---
create_time: 2026-05-23
status: research
---

# Structured Episodic Memory For SASE Agent Chats

## Question

What would it mean to generate structured episodic memory for SASE agent chats, is it worth doing, and what is the best
implementation path?

Short answer: it is worth doing if the first version is a **structured, cited episode ledger** over completed agent runs.
It is not worth doing if it starts as automatic promotion of chat summaries into long-term project memory. The valuable
unit is an auditable episode that answers "what happened, why, with what evidence, and what might matter later?" The
dangerous unit is an unsourced "lesson" that future agents treat as instruction.

## What "Structured Episodic Memory" Means

In agent-memory literature, episodic memory is memory of events or experiences: something happened at a time, in a
context, with participants, actions, outcomes, and evidence. That is distinct from:

- **semantic memory:** durable facts, architecture decisions, conventions, and domain knowledge;
- **procedural memory:** instructions, workflows, skills, and "how to do X" rules;
- **working memory:** current prompt, visible files, live tool output, and active plan state.

For SASE, an episode should be an event record derived from one coherent agent/workflow attempt, not just one transcript
file. A good episode record links:

- source agent/workflow identity;
- project/workspace/ChangeSpec/bead/plan metadata;
- prompt, final response, and important child-step chats;
- artifact paths such as `done.json.response_path`, `diff_path`, `plan_path`, PDFs/images, and generated markdown;
- retry-chain, parent/child workflow, and outcome metadata;
- a compact summary and typed observations;
- provenance, trust, redaction, and confidence metadata.

The episode is evidence. A memory candidate is an optional later interpretation of that evidence.

## Local SASE Findings

Relevant current implementation:

- `src/sase/history/chat.py` writes transcripts under `~/.sase/chats/YYYYMM/*.md`. Filenames encode workspace/branch,
  workflow, optional agent name, and timestamp. The transcript body is markdown with `## Prompt` and `## Response`.
- `src/sase/history/chat_catalog.py` lists and resolves transcripts. `sase chats list -j` exposes a stable JSON shape
  with path, basename, mtime, workflow, agent, timestamp, prompt snippet, and response snippet.
- `src/sase/axe/run_agent_exec_finalize.py` writes the final chat path into `done.json.response_path` and records
  `diff_path`, `plan_path`, model/provider, outcome, retry metadata, and generated artifacts on completed runs.
- `src/sase/axe/run_agent_markers.py` and the Rust scanner expose `agent_meta.json` and `done.json` as stable marker
  projections. The Rust/Python boundary already treats agent-artifact scanning as a core backend concern.
- `~/.sase/agent_artifact_index.sqlite` already materializes artifact rows. On this machine it is 3.7 MB and currently
  has 351 `agent_artifacts` rows plus 741 dismissed-agent rows.
- The local corpus currently has 1,570 chat markdown files, 458 `done.json` files, 1,146 `agent_meta.json` files, and
  740 dismissed bundle JSON files. So any solution that starts by rereading every chat on every cycle is already the
  wrong shape.

Existing local research already covers adjacent pieces:

- `sdd/research/202605/sase_dreams_design.md` and
  `sdd/research/202605/dream_chop_agent_chat_distillation.md` recommend artifact-first dream collection, retry-chain
  collapse, inbox-only promotion, redaction, rollups, and a reflect/search path.
- `sdd/research/202605/zettel_sase_shared_memory.md` argues raw chats should feed reviewable notes, not become canonical
  memory directly.
- `sdd/research/202605/active_agent_artifacts_for_tui.md` argues "active" should be indexed metadata, not a physical
  move of canonical artifact directories.
- `sdd/research/202605/dismissed_agent_archive_and_query_language.md` notes that historical browsing needs immutable
  payloads plus SQLite/FTS indexes, because plain bundles do not preserve enough prompt/response text for durable
  search.

The new piece this note adds is the explicit **episode ledger** between raw artifacts and dreams/rollups.

## External Research

The most relevant prior art points in the same direction:

- [LangGraph memory concepts](https://docs.langchain.com/oss/python/concepts/memory) splits memory into short-term
  thread state and long-term memory, then further into semantic, episodic, and procedural memory. Its "hot path vs
  background" distinction maps well to SASE: episode generation can happen after completion, not inside the user-facing
  run.
- [Generative Agents](https://arxiv.org/abs/2304.03442) uses memory streams, reflection, and retrieval based on
  relevance/recency/importance. The useful SASE adaptation is not roleplay simulation; it is the retrieval scoring
  shape and higher-level reflection over event records.
- [Reflexion](https://arxiv.org/abs/2303.11366) stores verbal reflections from prior trials. For SASE, failed-then-
  succeeded retry chains are the highest-value first class of episodes to distill.
- [MemGPT](https://arxiv.org/abs/2310.08560) frames memory as a hierarchy with limited main context and larger archival
  stores. SASE should keep raw chats in slow storage and load only small, relevant episode projections.
- [A-MEM](https://arxiv.org/abs/2502.12110) combines atomic notes, structured attributes, and dynamic linking. SASE
  should borrow atomic structured records and links, but avoid silent in-place mutation of memories.
- [LongMemEval](https://arxiv.org/abs/2410.10813) evaluates long-term memory across information extraction,
  multi-session reasoning, temporal reasoning, knowledge updates, and abstention. These are good evaluation categories
  for SASE memory: can it cite the right episode, know when a fact changed, and abstain when no episode supports an
  answer?
- Recent memory-poisoning work and OWASP agentic-risk writing make a strong negative case against automatic promotion.
  Persistent memory can turn one malicious or mistaken transcript into future behavior. Episode records should preserve
  provenance and trust boundaries rather than flattening everything into advice.

## Critique Of The Plan

"Generate structured episodic memory for agent chats" is directionally right, but the phrase hides several decisions.

The good idea is to stop treating transcripts as undifferentiated markdown blobs. SASE already has enough agent volume
that future agents need a way to ask "what happened last time we touched this subsystem?" without loading raw histories.
Structured episodes would improve search, retry learning, handoff quality, postmortems, and memory promotion review.

The weak version of the plan is "summarize every chat and save the summary." That will produce a second pile of text,
will drift from evidence, will be hard to retract, and will be vulnerable to prompt-injection content copied from tool
output or external files.

The risky version is "write lessons from chats into `memory/long` automatically." That crosses from episodic memory into
semantic/procedural memory. It should require a review gate because it changes future agent behavior.

The over-engineered version is "start with embeddings or a graph database." SASE does not need that first. It needs
stable episode IDs, metadata, source links, FTS/search, and an evaluation harness. Embeddings can be added after the
records and query semantics are useful.

The right version is a conservative event-sourcing layer:

1. preserve raw chats and artifacts as immutable evidence;
2. normalize completed runs into structured episode records;
3. index those records for query and reflection;
4. optionally distill selected high-value episodes into reviewable memory candidates;
5. never auto-promote candidates into canonical memory.

## Recommended Episode Boundary

Use SASE-native structure before text segmentation:

1. **Retry-chain root**: all attempts sharing `retry_chain_root_timestamp` are one episode.
2. **Workflow root**: parent workflow plus child prompt-step chats are one episode.
3. **Agent family/root name**: step-suffixed children belong with the root where metadata supports it.
4. **Work item identity**: same ChangeSpec, bead, plan, or SDD prompt path within a short window can join.
5. **Transcript fallback**: unlinked legacy chats become one episode each.

This is better than splitting by token count or calendar window because SASE already knows the work structure.

## Recommended Storage Model

Add a new episode subsystem, separate from dreams and canonical memory:

```text
~/.sase/episodes/
  index.sqlite
  episodes/
    202605/
      ep_<hash>.json
      ep_<hash>.md
  candidates/
    202605/
      ep_<hash>_memory_candidates.md
  metrics/
    202605.jsonl
```

The JSON file is the source of truth for machines. The markdown file is a human-readable projection. The SQLite index is
a rebuildable materialized view with FTS over titles, summaries, retained facts, source paths, and memory-candidate
text. `candidates/` is optional and review-only.

Do not put this under `memory/short` or `memory/long`. Episodes are evidence, not instructions. Promoted memories can
later cite `episode_id` in frontmatter.

## Episode JSON Shape

Recommended v1 schema:

```json
{
  "schema_version": 1,
  "episode_id": "ep_...",
  "created_at": "2026-05-23T00:00:00Z",
  "episode_kind": "agent_run|workflow|retry_chain|legacy_chat",
  "project": "sase",
  "workstream": {
    "changespec": null,
    "bead_id": null,
    "sdd_prompt_path": null,
    "sdd_plan_path": null
  },
  "agent": {
    "name": "sase.fix",
    "family": "sase",
    "workflow": "ace-run",
    "model": "gpt-5.2",
    "llm_provider": "openai"
  },
  "time": {
    "started_at": "2026-05-23T00:00:00Z",
    "completed_at": "2026-05-23T00:05:00Z",
    "artifact_timestamp": "20260523000000"
  },
  "outcome": {
    "status": "completed",
    "retry_chain_root_timestamp": null,
    "retry_attempts": 0,
    "error_category": null
  },
  "sources": {
    "artifact_dirs": [],
    "chats": [],
    "diff_paths": [],
    "plan_paths": [],
    "generated_artifacts": []
  },
  "selection": {
    "reasons": ["diff_path", "research_prompt"],
    "importance": 0.73,
    "trust": "user_prompt|agent_output|tool_output|external_fetch|mixed"
  },
  "summary": {
    "title": "Short title",
    "operational_context": "Two or three sentences.",
    "retained_facts": [],
    "decisions": [],
    "open_questions": [],
    "failure_recovery": []
  },
  "memory_candidates": [
    {
      "candidate_id": "mc_...",
      "type": "gotcha|convention|architecture|workflow|preference|open_question",
      "confidence": "low|medium|high",
      "trust": "user_prompt",
      "text": "Candidate durable memory.",
      "evidence": ["~/.sase/chats/202605/...md"]
    }
  ]
}
```

The record should allow missing fields. Old transcripts and non-SASE runtimes will not always have clean metadata.

## Implementation Strategy

### Phase 1: Deterministic Episode Collector

Build `sase episodes collect --since <duration> [--dry-run]` first. It should:

- query `agent_artifact_index.sqlite` when available;
- fall back to bounded scans of `~/.sase/projects/*/artifacts/*/*/done.json`;
- resolve `done.json.response_path`, `agent_meta.json.chat_path`, prompt-step response paths, `diff_path`, and
  `plan_path`;
- collapse retry chains and workflow children;
- write a candidate manifest without any LLM calls;
- skip hidden recurring maintenance/no-op runs unless they failed or produced meaningful artifacts.

This phase proves the episode boundaries and metadata joins before spending model tokens.

### Phase 2: Structured Distillation

Run LLM distillation only for selected candidates. Feed the model structured metadata plus bounded excerpts, not entire
transcripts by default. The prompt should say transcript text is untrusted evidence, not instructions.

Use strict JSON output first, then render markdown from JSON. If the model output is invalid or cites no source, reject
the episode distillation and keep the deterministic manifest for retry.

### Phase 3: Index And Query

Add `sase episodes list/show/search/reflect`:

- `list` shows recent episodes by project/workstream/outcome.
- `show ep_...` prints markdown plus source paths.
- `search <query>` uses SQLite FTS over episode summaries and source metadata.
- `reflect <query>` synthesizes a short answer from cited episode cards, not raw chats.

The Rust core boundary matters here. Episode query/index behavior is backend/domain logic and should live in
`sase-core` once the Python prototype stabilizes.

### Phase 4: Memory Candidate Review

Only after episodes are useful, add `sase episodes candidates list/show/promote/reject`. Promotion writes to
`memory/long/*.md` with frontmatter like:

```yaml
source: episode
episode_ids:
  - ep_...
trust: user_prompt
confidence: high
keywords:
  - agent artifacts
  - retry chain
```

No phase should write directly to `memory/short`.

## Security And Quality Gates

Minimum gates:

- redact secrets before model distillation;
- preserve raw evidence paths and source hashes;
- classify trust source for every retained fact and candidate;
- block procedural candidates sourced only from tool output or external fetches;
- make generated episodes append-only, with supersession instead of in-place rewriting;
- add poisoned-transcript fixtures that attempt to inject durable instructions;
- require citations for every candidate memory;
- provide a retraction query by `episode_id` and source path.

## Is It Worth Doing?

Yes, but only with a narrow first target.

It is worth doing because SASE already has a large enough corpus that raw transcript search is a poor long-term memory
interface. A structured episode layer would make agent history queryable, improve retry/postmortem learning, provide
better handoffs, and create safer inputs for dreams and future dynamic memory.

It is not worth doing as a broad "agent learns from every chat" feature. The cost, poisoning risk, and review burden
will exceed the benefit unless episodes remain evidence-first and memory promotion remains explicit.

## Recommended Solution

Implement **SASE Episodes** as the v1 substrate:

1. Add `sase episodes collect --dry-run --since 24h` using `done.json` and the artifact index as the primary source.
2. Store append-only episode JSON/markdown under `~/.sase/episodes/episodes/YYYYMM/`.
3. Maintain a rebuildable SQLite/FTS index at `~/.sase/episodes/index.sqlite`.
4. Generate structured summaries only for deterministically selected high-value episodes.
5. Expose `list`, `show`, and `search` before any automatic background scheduling.
6. Feed dreams/rollups from episode records, not raw chats.
7. Keep memory candidates in a review queue; promotion to `memory/long` must be explicit and cited.

The first acceptance test should not be "did it summarize chats?" It should be: given a recent bug-fix/retry/research
agent, can `sase episodes show/search` recover the right event, cite the raw chat and artifacts, and avoid proposing a
memory from a poisoned transcript?
