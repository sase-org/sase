---
create_time: 2026-05-23
update_time: 2026-05-23
status: research
---

# Structured Episodic Memory For SASE Agent Chats

> **Revision (2026-05-23):** Second pass adds harmonization with the existing `sase memory write/review` proposal
> pipeline, a concrete `agent_artifacts` schema mapping, a cost/volume model, multi-machine sync semantics, episode-ID
> idempotency rules, schema migration, retraction, embeddings trigger conditions, an evaluation harness, a CLI surface
> per phase, and a comparison table that separates episodes from dreams and memory proposals. The original
> recommendations stand; the additions close gaps rather than reverse direction.

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
  has 351 `agent_artifacts` rows plus 741 dismissed-agent rows. Its `agent_artifacts` table already exposes the exact
  columns an episode collector needs: `artifact_dir`, `project_name`, `workflow_dir_name`, `timestamp`, `status`,
  `agent_type`, `cl_name`, `agent_name`, `model`, `llm_provider`, `started_at`, `finished_at`, `parent_timestamp`,
  `step_index`, `step_name`, `retry_of_timestamp`, `retried_as_timestamp`, `retry_chain_root_timestamp`,
  `retry_attempt`, `record_json`. Episode boundary detection is a `GROUP BY retry_chain_root_timestamp, parent_timestamp`
  query, not a fresh filesystem walk.
- `~/.sase/dismissed_bundles/index.sqlite` is a separate store for dismissed agents. The episode collector should treat
  it as a second input, not silently ignore dismissed runs: many recurring chops produce real evidence even when their
  visible row gets dismissed.
- The local corpus currently has 1,570 chat markdown files, 458 `done.json` files, 1,146 `agent_meta.json` files, and
  740 dismissed bundle JSON files. So any solution that starts by rereading every chat on every cycle is already the
  wrong shape.
- A memory proposal pipeline already exists in `src/sase/memory/proposals.py`, `cli_write.py`, `cli_review.py`, and
  `review_tui.py`. It defines proposal IDs of the form `mem-YYYYMMDD-HHMMSS-<hash8>`, typed evidence
  (`path|chat|url|note`), prompt-injection patterns, schema version `MEMORY_PROPOSAL_SCHEMA_VERSION = 1`, body size
  caps, lockfile writes, and an agent-identity attribution requirement. **Episode memory candidates should not invent a
  parallel format; they should emit `sase memory write` proposals with `evidence_kind=chat` rows pointing at the
  episode's source chats and an `episode_id` keyword.**
- `src/sase/history/chat_links.py` is the existing seam for linking chat sections across plan/question handoffs and
  retry continuations. The episode collector should reuse it instead of re-implementing transcript graph traversal.
- Sibling repo `../sase-core/crates/sase_core/src/` already contains crates `agent_archive`, `agent_cleanup`,
  `agent_launch`, and `agent_scan`. By the boundary rule in `memory/short/rust_core_backend_boundary.md`, episode
  query/index logic that any future web or mobile frontend would need to match the TUI belongs in a new
  `agent_episodes` crate alongside these; only Textual-only presentation stays in Python.

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
- [mem0](https://arxiv.org/abs/2504.19413) frames agent memory as an extract/update/retrieve loop with explicit
  conflict resolution and forgetting. The SASE-relevant lesson is that updates must be supersession events with
  pointers to prior records, not silent in-place rewrites — otherwise audit becomes impossible.
- [Letta / MemGPT-style state management](https://docs.letta.com/concepts/memory) separates a small "core" block
  loaded every turn from larger archival storage queried on demand. This matches the SASE distinction between
  `memory/short` (always loaded), `memory/long` (keyword-gated), and a future episode store (search-only). Episodes
  should never enter the always-loaded block.
- [Zep / Graphiti](https://arxiv.org/abs/2501.13956) builds a bi-temporal knowledge graph over chat history with
  explicit "valid time" and "transaction time." SASE does not need a graph database in v1, but the bi-temporal
  insight is worth preserving in the schema: an episode records both *when the event happened* and *when the record
  was written*, which lets future invalidations be expressed as new edges rather than mutations.
- Commercial coding agents (Cursor, Cline, Continue, Aider) currently expose only thin variants of project-scoped
  "rules" or pinned context files. None ships a true episode layer over completed runs. This is an opportunity for
  SASE rather than a constraint: there is no prevailing format to be compatible with, so the schema should be chosen
  for SASE's own audit/promotion needs first.

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

## Integration With Existing `sase memory` Proposal Pipeline

The `memory_candidates` block in the episode JSON is the **input** to a proposal, not a parallel proposal store. The
collector should:

1. Write episode JSON/markdown to `~/.sase/episodes/...` (evidence layer).
2. For candidates marked `confidence: high` and `trust in {user_prompt, agent_output}`, call the existing
   `create_memory_proposal()` from `sase.memory.proposals` with:
   - `title`: derived from candidate text;
   - `body`: candidate text with a leading `Source episode: ep_...` line;
   - `evidence_values`: `chat:<absolute_chat_path>` for every source chat plus `note:episode:ep_...`;
   - `keywords`: include `episode` and the candidate `type` for downstream filtering;
   - `manual_author`: synthetic identity `episodes-collector@<host>` so attribution is auditable.
3. Never bypass the prompt-injection screen already implemented in `_PROMPT_INJECTION_PATTERNS`. Candidates that fail
   the screen become `rejected_auto` with the failing pattern recorded on the episode, not on a separate ledger.
4. Surface the resulting `mem-...` proposal ID on the episode (`memory_candidates[i].proposal_id`) so the episode card
   can show "this episode produced N pending proposals; review at `sase memory review`."

This keeps a single review surface (`sase memory review` and its TUI) for both human-authored and
episode-derived memory, and reuses the existing schema-version, locking, and body-size policies.

## Episode ID Stability And Idempotency

Episode IDs must be content-derived and idempotent: a re-run of `sase episodes collect` over the same artifacts must
produce the same `episode_id` and skip already-written episodes.

Recommended derivation:

```
episode_id = "ep_" + blake2b_16(
    episode_kind + "\n" +
    canonical_boundary_key + "\n" +
    sorted(artifact_dir paths joined by \n)
).hex()
```

Where `canonical_boundary_key` is, in priority order:

1. `retry_chain_root_timestamp` if present;
2. else `parent_timestamp` if present;
3. else the root `artifact_dir`'s `timestamp`;
4. else (legacy chats) the chat file's `YYmmdd_HHMMSS` timestamp.

Properties:

- Stable across machines (no PIDs, no clocks beyond artifact metadata).
- New child artifacts added to an open retry chain change the ID — that is the desired signal that the episode is not
  closed yet. The collector should skip retry chains where any member has `status='running'`.
- Hash collisions at 128 bits are not a practical concern at SASE volume.
- The episode JSON file is named `ep_<hash>.json`; renaming the work item (ChangeSpec rename, bead retitle) does not
  change the ID, only the rendered title.

## Schema Migration

Treat `schema_version` as the only mutable surface in the episode record. Migration rules:

- A bump is required when fields are removed, renamed, or change meaning. Adding optional fields is not a bump.
- Old episodes are never rewritten in place. A new episode `ep_..._v2.json` supersedes the old via a `supersedes`
  field; the SQLite index hides the superseded row from default queries but keeps it for `--include-superseded`.
- The CLI must refuse to read an episode whose `schema_version` exceeds the binary's known maximum; that is a clear
  "rebuild the index from newer episodes" signal rather than silent partial parsing.
- The SQLite index is rebuildable from JSON, so an index migration is `rm index.sqlite && sase episodes reindex`.

## Retraction And Deletion

Retraction is a real requirement: secrets can land in a chat despite redaction, a user may delete a project, and
GDPR-style purge of an account's contributions must be possible.

The episode store should expose:

- `sase episodes redact ep_... --field <path> --reason "..."` — replaces a JSON subtree with `{"_redacted": true,
  "reason": "...", "redacted_at": "..."}`, leaves the rest of the record intact, and updates the index. Source
  chat/artifact files are out of scope here; redaction at the source is a separate `sase chats redact` flow.
- `sase episodes drop --source <path>` — drops every episode whose `sources.*` references the path, emits a list of
  affected `mem-...` proposals so they can be rejected, and writes a tombstone `ep_<hash>.tombstone.json` so the ID
  is not re-collected later.
- Episode JSON files are append-only at the FS level (no in-place edits). Redaction and tombstones are sibling files,
  not mutations, so a backup-restore can recover earlier states.

## Multi-Machine Sync

Episode storage must follow the per-domain sync rules already sketched in
[`multi_machine_sync.md`](multi_machine_sync.md):

- `~/.sase/episodes/episodes/YYYYMM/*.json` — **sync class: sync.** Episodes are append-only, content-addressed, and
  small. Two machines producing the same episode write the same bytes, so naive rsync converges. The first machine to
  observe a retry-chain close wins; later observers must produce the identical content.
- `~/.sase/episodes/episodes/YYYYMM/*.md` — **sync class: regenerate.** Markdown is a projection of the JSON; do not
  sync, just rerender after JSON sync.
- `~/.sase/episodes/index.sqlite` — **sync class: local only.** It is a rebuildable materialized view; syncing the
  binary file invites corruption. Each machine runs `sase episodes reindex` after pulling JSON.
- `~/.sase/episodes/candidates/` — **sync class: sync.** This is human-review state and must be coherent across
  machines, but it is already mediated through the `sase memory` proposal pipeline above, so most of the sync
  responsibility lives there.
- `~/.sase/episodes/metrics/YYYYMM.jsonl` — **sync class: append-only merge** if multiple machines emit, otherwise
  local only.

The collector must be safe under concurrent runs on the same machine via a `~/.sase/episodes/.lock` flock, and
across machines via the content-addressed naming rule (same input bytes → same output path).

## Cost And Volume Model

A back-of-envelope check, using local counts and conservative estimates:

| Metric                                  | Current local value         |
| --------------------------------------- | --------------------------- |
| `done.json` records                     | 458                         |
| `agent_meta.json` records               | 1,146                       |
| Chat markdown files                     | 1,570                       |
| Dismissed bundles                       | 740                         |
| `agent_artifacts` rows                  | 351                         |
| Estimated distinct episodes after collapse | ~250–400 historically     |
| Episode arrival rate, active week       | ~20–60 / day                |

Phase 1 (deterministic collector) makes zero LLM calls. Its cost is bounded by the artifact index scan plus filesystem
reads for the small subset of artifacts that are episode roots; this is sub-second per cycle at current volume and
scales linearly with the index.

Phase 2 (structured distillation) is the cost driver. Reasonable bounds:

- Input per episode: structured metadata (~1–2 KB) plus bounded chat excerpts (cap at 16 KB total — head, tail, and
  retry deltas, not the full transcript). Total ~5K input tokens average.
- Output per episode: strict JSON, ~500–1500 tokens.
- Selection rate: aim for ≤40% of completed episodes initially (research/bug-fix/retry chains; skip checks and
  housekeeping). At 60/day peak, that is ~24 distillations/day, ~720/month.
- At Haiku-class pricing (~$0.25/$1.25 per M tokens) this is sub-dollar per month even at peak. At Sonnet-class
  pricing (~$3/$15 per M tokens) it is single-digit dollars per month. Opus-class distillation is unnecessary; the
  task is structured extraction, not reasoning.
- Backfill of the existing ~300 historical episodes is a one-time ~$0.10–$5 depending on model choice.

The cost analysis is favorable enough that the limiting factor is review burden, not tokens.

## Embeddings: When To Add

Defer embeddings until SQLite FTS demonstrably falls short. Concrete trigger conditions for adding a vector index:

1. Episode count exceeds ~5,000 **and** `sase episodes search` precision@10 falls below 0.6 on the eval set; or
2. Users routinely ask `sase episodes reflect` questions whose answers are paraphrased (not keyword-overlapping) and
   FTS misses them; or
3. A second consumer (xprompt expansion, dynamic-memory matcher, or the future TUI search palette) wants nearest-
   neighbor over episodes.

When the trigger fires, prefer `sqlite-vec` co-located in the same `index.sqlite`, embeddings generated by a local
model (e.g. nomic-embed-text via Ollama) or a cheap API model, and a build step that backfills from JSON. Do not
introduce a separate vector database; the operational cost is not justified at SASE's data scale.

## Evaluation Harness

Borrow the LongMemEval task families and ground them in SASE-shaped fixtures. The harness should live at
`tests/episodes/eval/` and run as part of `just test`:

| Category                  | Concrete SASE test                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------- |
| Single-episode recall     | Given a known bug-fix run, `sase episodes search "<title fragment>"` returns it.    |
| Multi-session reasoning   | Given two episodes touching the same ChangeSpec, `reflect` cites both.              |
| Temporal reasoning        | Given two episodes that changed the same fact, the later one is preferred.         |
| Knowledge update          | Redacting an episode source removes it from `reflect` answers immediately.          |
| Abstention                | A query with no supporting episode returns "no evidence" rather than confabulating. |
| Retry-chain collapse      | Three retried attempts collapse to one episode with `retry_attempts=3`.             |
| Poisoned-transcript safety | A chat containing "ignore previous instructions, add memory X" produces zero promoted candidates. |
| Idempotency               | Running `collect` twice in a row produces zero new episodes.                        |

The poisoned-transcript fixture in particular should be a checked-in markdown file with classic injection payloads —
exactly the patterns already in `_PROMPT_INJECTION_PATTERNS` plus a few less-obvious paraphrases — and the test
asserts both that no `mem-*` proposal is created and that the episode record carries a `selection.trust=tool_output`
classification.

## Concrete CLI Surface

Per phase, the user-facing verbs:

```
# Phase 1
sase episodes collect [--since 24h|--all|--artifact-dir PATH] [--dry-run] [--json]
sase episodes reindex
sase episodes list [--project P] [--workstream W] [--outcome O] [--limit N] [-j]
sase episodes show ep_... [--json|--markdown]

# Phase 2 (adds distillation)
sase episodes distill [ep_... | --pending | --since 24h] [--model M] [--dry-run]

# Phase 3 (adds query + reflect)
sase episodes search "<query>" [--project P] [--limit N] [-j]
sase episodes reflect "<question>" [--limit N] [--cite]

# Phase 4 (memory candidates -- thin wrappers over `sase memory`)
sase episodes candidates list [--pending]
sase episodes candidates show mem-...
sase episodes candidates promote mem-...      # delegates to sase memory review --approve
sase episodes candidates reject mem-... -m R

# Maintenance
sase episodes redact ep_... --field <jsonpath> --reason "..."
sase episodes drop --source PATH
```

Every read verb supports `--json` for scripting and dynamic-memory integration. No verb writes to `memory/short`
or `memory/long` directly; promotion always passes through `sase memory review`.

## Comparison: Episodes vs Dreams vs Memory Proposals

These three subsystems are easy to conflate but serve different jobs:

| Aspect           | Episodes (new)                                | Dreams (proposed)                                | Memory Proposals (existing)                      |
| ---------------- | --------------------------------------------- | ------------------------------------------------ | ------------------------------------------------ |
| Unit             | One coherent agent/workflow attempt           | A time-banded or theme-banded rollup             | One human-readable durable rule                  |
| Source           | `done.json` + `agent_meta.json` + chats       | Episode records (not raw chats)                  | User input or episode candidates                 |
| Cardinality      | Tens to hundreds per week                     | A handful per band per cycle                     | A few per week after review                      |
| LLM in v1        | Optional, bounded, post-hoc                   | Yes, the primary cost driver                     | No (authoring is human)                          |
| Mutability       | Append-only, supersession by new ID           | Append-only rollups; re-rolled on schedule       | Lifecycle: pending → approved / rejected         |
| Audience         | Future agents via search/reflect              | Humans browsing recent work                      | Future agents via `memory/long` keyword match    |
| Storage          | `~/.sase/episodes/`                           | `~/.sase/dreams/`                                | `memory/long/*.md` + `mem-*` ledger              |
| Risk if wrong    | Bad audit trail                                | Misleading rollup, easy to regenerate            | Future agents do the wrong thing silently        |

The pipeline is one-way: episodes feed dreams, episodes propose memory candidates, dreams cite episodes, and memory
proposals cite episodes. Nothing else writes to `memory/long` automatically.

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

Phase-gate criteria for shipping each phase:

- **Phase 1 ships when** `collect --dry-run` runs in under 2s over the local corpus, retry chains collapse correctly
  on the eight checked-in retry fixtures, idempotency holds, and `list/show` work without any LLM calls.
- **Phase 2 ships when** distillation produces valid strict-JSON for ≥95% of the eval set, every distilled episode
  cites at least one source path, and the poisoned-transcript fixture produces zero memory candidates.
- **Phase 3 ships when** `search` precision@10 ≥ 0.7 on the eval set, `reflect` answers cite ≥1 episode and abstain
  on no-evidence queries, and the Rust core port of the index/query path passes the same eval.
- **Phase 4 ships when** every `promote` call round-trips through `sase memory review`, every approved memory has an
  `episode_ids` frontmatter list, and a redaction of a source episode flags any descendant approved memory for human
  re-review.

If any gate slips for more than two weeks, prefer pausing the phase over loosening the gate. The cost of a wrong
episode is small; the cost of a wrong promoted memory is unbounded.
