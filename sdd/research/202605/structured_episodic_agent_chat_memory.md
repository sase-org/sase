# Structured Episodic Memory for SASE Agent Chats

Date: 2026-05-23

## Question

SASE already saves agent chat transcripts and has an agent-facing memory system. The question is whether it should also generate structured episodic memory from agent chats, what that should mean, and what implementation is most likely to help rather than create a noisy second memory system.

## Short Answer

It is worth doing, but only if "episodic memory" is treated as a searchable, source-linked record of what happened in an agent run, not as automatically trusted long-term guidance.

The valuable version is:

- keep raw chat markdown and artifacts as source of truth;
- generate compact structured episode records after runs complete;
- index those records for retrieval, triage, and future planning;
- promote durable lessons into `memory/long/*.md` only through the existing human-reviewed `sase memory write/review` flow.

The risky version is:

- let every agent write permanent memory directly;
- inject generated memories into every future prompt;
- collapse one-off run facts, inferred project rules, and reusable procedures into the same blob.

That risky version would likely make agents more confident but less reliable.

## What "Episodic Memory" Means Here

In cognitive-science-inspired agent architecture, memory is commonly split into:

- **Semantic memory:** facts and concepts.
- **Episodic memory:** experiences or events.
- **Procedural memory:** rules or ways to act.

LangGraph's memory docs use this exact distinction and describe episodic memory as past events/actions that can help an agent remember how a task was accomplished. They also distinguish short-term thread memory from long-term memory and call out update-time tradeoffs between hot-path and background memory writes. Source: <https://docs.langchain.com/oss/python/concepts/memory>

For SASE, an episode should be one completed agent run or workflow step:

- the user's goal;
- the agent identity and runtime metadata;
- the chat and artifact paths;
- what files, specs, beads, or sibling repos were touched;
- decisions made;
- blockers, errors, and tests;
- outcome;
- follow-up work;
- compact lessons that might be reusable, but are not yet canonical project memory.

An episode is not the raw transcript, and it is not a permanent instruction. It is a structured index card that points back to the evidence.

## Relevant External Research

The "Generative Agents" paper is the clean historical reference for memory-stream based agents: it stores experience records, synthesizes higher-level reflections, and retrieves memories dynamically for planning. The useful SASE lesson is not the social-simulation framing; it is the separation between observation, reflection, and planning, with raw experiences preserved below generated reflections. Source: <https://arxiv.org/abs/2304.03442>

MemGPT argues for hierarchical memory management: limited context should be treated as a managed tier, backed by larger external storage. It is relevant because SASE chats already exceed what should be blindly inserted into future prompts. Episodic memory should be retrieved selectively, not pasted wholesale. Source: <https://arxiv.org/abs/2310.08560>

Reflexion is directly relevant for coding agents: it stores verbal reflections from prior trials in an episodic memory buffer and uses them to improve future attempts without model weight updates. The SASE lesson is that reflections can help, but they must be tied to feedback/outcomes; otherwise they become ungrounded self-commentary. Source: <https://arxiv.org/abs/2303.11366>

CoALA gives the architectural framing: language agents should have modular memory components, a structured action space for interacting with memory and the external environment, and a decision loop. The SASE lesson is to keep chat episodes, semantic project memory, and procedural instructions separate. Source: <https://arxiv.org/abs/2309.02427>

A 2025 position paper argues that episodic memory is central for long-term LLM agents because it supports single-shot learning of instance-specific context. That supports building this, but it also implies that retrieval quality matters: a bad episode retrieved at the wrong time can mislead just as easily as help. Source: <https://arxiv.org/abs/2502.06975>

A 2026 survey describes agent memory as a write-manage-read loop and identifies practical engineering concerns: write-path filtering, contradictions, latency budgets, privacy, trustworthy reflection, and learned forgetting. Those concerns map almost exactly to SASE's risk surface. Source: <https://arxiv.org/abs/2603.07670>

Letta's current docs distinguish archival memory from conversation search: archival memory is intentional long-term storage, while conversation search recalls what was said in past messages. That is a useful distinction for SASE: structured episodes should start closer to conversation search plus metadata, not as always-visible core memory. Source: <https://docs.letta.com/guides/core-concepts/memory/archival-memory>

### Additional Prior Art (2024–2026)

These weren't covered above and each maps to a concrete SASE design decision.

**Raw episode vs synthesized lesson** — A-MEM (Zettelkasten-style auto-linking; arXiv:2502.12110), ExpeL (AAAI 2024; trajectory pool + extracted insights as separate tables; arXiv:2308.10144), MemoryBank (raw dialog + summarized memories at separate tiers; arXiv:2305.10250), RAISE (dual scratchpad + retrieved-examples bolted onto ReAct; arXiv:2401.02777). The pattern is consistent: store raw experience, derive a separate "lesson" layer that can be regenerated and challenged.

**Memory update / contradiction handling** — Mem0 (LLM emits explicit ADD/UPDATE/DELETE/NOOP against semantically-similar existing memories; +26% over OpenAI memory on LOCOMO; arXiv:2504.19413). Zep/Graphiti use a bi-temporal knowledge graph: facts get `t_valid` and `t_invalid` rather than being overwritten, preserving history (arXiv:2501.13956; <https://blog.getzep.com/zep-a-temporal-knowledge-graph-architecture-for-agent-memory/>).

**Forgetting / decay** — MemoryBank operationalizes an Ebbinghaus-style decay `R = e^(-t/S)` with strength `S` boosted on each recall. Reflective Memory Management (arXiv:2503.08026) uses usage-based retention with periodic LLM reflection to prune and merge.

**Coding-agent benchmarks** — SWE-Bench-CL repackages SWE-Bench Verified into chronological streams to measure knowledge transfer and catastrophic forgetting (arXiv:2507.00014). MemGovern reports +4.65% on SWE-bench from a curated experience-card store (arXiv:2601.06789). These let episode-memory wins be measured rather than asserted.

**Memory poisoning** — OWASP GenAI Top-10 2025 LLM01 covers indirect injection through retrieved content (<https://genai.owasp.org/llmrisk/llm01-prompt-injection/>). NIST AI 100-2 (March 2025) explicitly enumerates agent memory poisoning. AgentPoison (NeurIPS 2024, arXiv:2407.12784) and MINJA (arXiv:2503.03704; >95% success against ReAct agents via query-only injection) demonstrate the attack class. Unit 42 documented an end-to-end indirect-injection write through long-term memory across sessions (<https://unit42.paloaltonetworks.com/indirect-prompt-injection-poisons-ai-longterm-memory/>).

**Embeddings for code+chat** — voyage-code-3 (+13.8% over text-embedding-3-large across 32 code-retrieval datasets, Matryoshka + int8/binary; <https://blog.voyageai.com/2024/12/04/voyage-code-3/>) and BGE-M3 (open weights, dense+sparse+ColBERT in one model) are the practical 2025–2026 picks for short technical text.

**Hybrid retrieval on SQLite** — sqlite-vec author Alex Garcia documents an FTS5+vec recipe with reciprocal-rank fusion that beats either alone for sub-100K-document corpora (<https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html>; Simon Willison summary: <https://simonwillison.net/2024/Oct/4/hybrid-full-text-search-and-vector-search-with-sqlite/>). The relevant point for SASE: episode corpora will sit in the thousands for a long time, so FTS5-first is rational and a vec column can be added without changing the storage layer.

**Production schemas** — concrete fields stored per memory in shipping systems:

- Mem0: `{id, memory (markdown), hash, user_id|agent_id|app_id|run_id, metadata (≤2KB JSON), categories, created_at, updated_at, embedding}` (<https://docs.mem0.ai/core-concepts/memory-types>).
- Letta archival passage: `{id, text, embedding, timestamp, metadata}`, surfaced via `archival_memory_insert` / `archival_memory_search` tools.
- Zep/Graphiti edge: `{source_node, target_node, fact, t_valid, t_invalid, created_at, episodes[]}` bi-temporal model (<https://github.com/getzep/graphiti>).

Common across all three: a stable id, a short human-readable text payload, owner/scope keys, a timestamp pair, and a small metadata bag. SASE's schema should not be wider than this without justification.

## Existing SASE Surfaces

Current local code has most of the raw material:

- `src/sase/history/chat.py` writes markdown transcripts under `~/.sase/chats/YYYYMM/`, parses prompt/response turns, resolves chat paths, and flattens chats for `#fork` / resume.
- `src/sase/history/chat_catalog.py` lists transcripts with bounded snippets and resolves by agent, path, or basename.
- `src/sase/chats/cli_list.py` and `src/sase/chats/cli_show.py` expose `sase chats list/show`.
- `src/sase/axe/run_agent_exec_finalize.py` saves the chat after each run and then builds done markers and default artifacts.
- `src/sase/axe/run_agent_exec.py` predicts `SASE_AGENT_CHAT_PATH` before completion.
- `agent_meta.json["chat_path"]` and `done.json["response_path"]` already connect agents to saved transcripts.
- `src/sase/memory/read_log.py` has agent-attributed audited memory reads.
- `src/sase/memory/proposals.py` has human-reviewed long-term memory proposals with evidence records, prompt-injection warnings, and project-scoped JSONL ledgers.
- `sase-core` already owns shared agent artifact scanning/indexing. `crates/sase_core/src/agent_scan/index.rs` uses SQLite as a materialized view over artifact directories while keeping the artifact tree as source of truth.

This suggests a natural shape: episode generation belongs near chat finalization/backfill in Python, while durable schema/index/query logic should move into `sase-core` if it will be shared by TUI, CLI, mobile gateway, and editor integrations.

### Concrete attachment points in current code

- `src/sase/axe/run_agent_exec_finalize.py:380` (`_save_chat_history`) and `:432` (`write_done_marker_and_update_index`) are the natural enqueue points. There is no formal post-finalize hook framework today, so episode generation either runs inline after `write_done_marker_and_update_index` or is enqueued for a background worker fed by `done.json` mtime.
- `done.json` already carries `response_path`, `step_output`, `diff_path`, `plan_path`, `markdown_pdf_paths`, `image_paths`, `default_artifacts_persisted`, and `retry_metadata` (`retry_count`, `retry_errors`, `used_fallback`, `fallback_model`, `retried_as_timestamp`, `retry_chain_root_timestamp`, `retry_error_category`) — every field an episode would need for outcome/retry/artifact provenance is already on disk.
- `agent_meta.json` carries `pid`, `workspace_dir`, `name`, `model`, `llm_provider`, `vcs_provider`, `tag`, `sibling_repos`, `run_started_at`, `stopped_at` — enough for agent identity and family scoping without re-parsing the transcript.
- `src/sase/history/chat_catalog.py` already does bounded transcript reads (first 64 KiB) and section snippet extraction — reuse it for deterministic episode fields rather than re-implementing markdown slicing.
- `src/sase/memory/proposals.py:32` defines `EvidenceKind = Literal["path", "chat", "url", "note"]`. Both `path` (the episode JSON sidecar) and `chat` (with `chat_id`) are already accepted as proposal evidence, so the bridge from episode to human-reviewed long-term memory exists without schema changes.
- No token/cost telemetry is recorded today. Episode generation is a natural place to introduce a `usage` subobject — but only when the runtime actually surfaces token counts; do not fabricate them.

## Critique: Reasons Not To Do It

Do not build this if the main goal is only "summarize old chats." `sase chats show --format response`, chat snippets, and editor access already cover much of that.

Do not build it as automatic long-term memory. Generated summaries can be wrong, stale, overbroad, or contaminated by prompt-injection text inside transcripts. If those summaries are injected into future prompts as truth, the system will slowly accumulate plausible but unverified rules.

Do not build it if it will run synchronously in the agent's critical path. The external literature and SASE's own UX constraints both point toward background generation. Chat saving should remain cheap and reliable.

Do not build vector search first. It will be tempting, but the first hard problem is not semantic similarity; it is deciding what the episode schema means, preserving provenance, making generation idempotent, and proving retrieval is useful.

## Why It Is Still Worth Doing

It is worth doing because SASE has a specific, recurring problem that raw transcripts do not solve well: agents need to answer "what happened last time?" without rereading a long markdown transcript or guessing from snippets.

Structured episode records would help with:

- finding previous runs that touched a file, bead, changespec, sibling repo, model, or workflow;
- understanding why a previous agent chose a plan;
- preventing repeated failed approaches;
- surfacing unresolved follow-ups from completed chats;
- feeding planner context with concise, source-linked prior work;
- creating better evidence for human-reviewed `memory/long` proposals;
- supporting mobile and TUI views without parsing full transcript markdown.

The value is high because SASE already has durable chat artifacts, agent metadata, and a memory review system. The implementation can be incremental rather than a new platform.

## Recommended Episode Schema

Use a versioned JSON object. Keep the generated text compact and evidence-linked.

```json
{
  "schema_version": 1,
  "episode_id": "ep_<stable_hash>",
  "project": "sase_27",
  "generated_at": "2026-05-23T00:00:00Z",
  "source": {
    "chat_path": "~/.sase/chats/202605/example.md",
    "chat_sha256": "...",
    "artifacts_dir": "~/.sase/projects/.../artifacts/ace-run/...",
    "done_path": ".../done.json",
    "agent_meta_path": ".../agent_meta.json"
  },
  "agent": {
    "name": "sase-27.x",
    "family": "sase-27",
    "workflow": "ace-run",
    "model": "codex/gpt-5.5",
    "llm_provider": "codex"
  },
  "lineage": {
    "parent_episode_id": null,
    "root_episode_id": "ep_<root>",
    "retry_of_episode_id": null,
    "retry_chain_root_timestamp": null,
    "sibling_episode_ids": []
  },
  "temporal": {
    "t_valid": "2026-05-23T00:00:00Z",
    "t_invalid": null,
    "last_recalled_at": null,
    "recall_count": 0,
    "strength": 1.0
  },
  "usage": {
    "tokens_in": null,
    "tokens_out": null,
    "model_cost_usd": null,
    "wall_seconds": null
  },
  "task": {
    "title": "Fix prompt history for multi-agent xprompts",
    "goal": "Make original multi-prompt history persist instead of fanout children.",
    "repos": ["sase"],
    "files": ["src/sase/..."],
    "beads": ["sase-..."],
    "changespec": null
  },
  "outcome": {
    "status": "completed",
    "summary": "Implemented ...",
    "tests": ["just test tests/..."],
    "artifacts": ["..."],
    "commit": null
  },
  "experience": {
    "decisions": [
      "Used the original prompt as history source before multi-agent fanout."
    ],
    "problems": [
      "Existing per-child launch path wrote each fanout prompt independently."
    ],
    "failed_attempts": [],
    "followups": [],
    "reusable_lessons": [
      "Prompt-history changes must cover both xprompt and plain --- fanout paths."
    ]
  },
  "retrieval": {
    "tags": ["prompt-history", "multi-agent", "xprompt"],
    "keywords": ["fanout", "history", "xprompt"],
    "embedding_text": "Compact text used for lexical/vector retrieval.",
    "confidence": "medium"
  },
  "safety": {
    "generated_by": "sase-episode-extractor@1",
    "prompt_injection_flags": [],
    "contains_generated_claims": true,
    "private": false,
    "redactions": []
  }
}
```

Key rule: the episode can summarize and classify, but it must not replace the transcript. Every important claim needs a path back to the source chat or artifact.

The added blocks have explicit purposes. `lineage` lets a parent agent's episode reach its fanout children and retry chain without a side table — both are already present in `agent_meta.json` (`sibling_repos`) and `done.json` (`retry_chain_root_timestamp`, `retried_as_timestamp`). `temporal` borrows Zep's `t_valid`/`t_invalid` and MemoryBank's recall counter so consolidation and decay can run later without a schema break. `usage` is nullable on purpose — agents that don't surface token counts should leave it null rather than guess. `safety.private` is a hard opt-out for retrieval ("this run touched a credential / a personal artifact, do not surface").

## Memory Update Semantics

The risky failure mode is not "we summarized a chat badly." It is "we wrote a confident lesson that contradicts what we already knew." Episodes-as-evidence sidesteps this for now, but the moment SASE starts retrieving episodes into prompts, the system needs an explicit policy for contradictions and near-duplicates.

Two patterns from production memory systems are worth copying:

- **Mem0-style explicit transitions.** When a new episode arrives, retrieve the top-k most similar existing episodes and ask an LLM to emit one of `ADD`, `UPDATE`, `DELETE`, `NOOP` per neighbor, with a short rationale. Updates and deletes must cite the new episode's `episode_id` as the cause. This keeps the merge logic auditable and reversible from the sidecar trail.
- **Zep-style bi-temporal invalidation.** Never delete in place. When a fact in an old episode is contradicted, write the new episode and set the old one's `temporal.t_invalid` to the new episode's `generated_at`. Retrieval defaults to `t_invalid is null`, but history queries can still see superseded episodes.

Recommendation for SASE phase 1: defer consolidation entirely. Phase 2: add `t_invalid` plumbing and Mem0-style transition prompts behind a feature flag, gated on episodes being retrieved into prompts at all.

## Forgetting & Decay

SASE chats accumulate under `~/.sase/chats/YYYYMM/` with no current GC. Episodes will inherit that growth. Three policies, from cheap to ambitious:

1. **Time-windowed FTS rebuild.** The SQLite index can default to the last N months and require an explicit flag to search older episodes. The sidecar JSON is never deleted; just less reachable.
2. **Recency + recall weighting.** Score episodes at retrieval time by a recency factor times a recall counter (incremented when an episode is actually used). This is cheap, transparent, and survives index rebuilds.
3. **Ebbinghaus-style strength.** MemoryBank's `R = e^(-t/S)` with `S` boosted on each recall is the most-cited version. It is overkill for an evidence store; only adopt it if episodes start feeding prompts directly.

Whatever is chosen, the policy must be a query-time scoring layer, not a destructive prune. The sidecar tree is cheap to store and expensive to regenerate.

## Security: Memory Poisoning and Indirect Prompt Injection

Chat transcripts contain user prompts, tool outputs, fetched web content, and pasted error logs. All of these can carry adversarial instructions. The risk class is well-documented: OWASP GenAI Top-10 2025 LLM01 (indirect injection), NIST AI 100-2 (agent memory poisoning as a named threat), AgentPoison (arXiv:2407.12784), MINJA (arXiv:2503.03704; query-only injection succeeds >95% of the time against ReAct agents), and Unit 42's documented end-to-end persistence of an injection through long-term memory.

`src/sase/memory/proposals.py:39` already flags a small set of prompt-injection patterns on proposal bodies. Episode generation should extend the same checks to:

- the raw transcript before it is fed to the extractor LLM (mark `safety.prompt_injection_flags`, do not refuse to generate);
- the generated episode body before it is written to disk (refuse the write if generated text contains exfiltration-style imperatives that did not appear in the source);
- the retrieval path (an injected episode is dangerous only when it is read back into a prompt — so retrieval should display source paths and never auto-quote episode body into another agent's context without provenance markers).

The hard rule: episodes never get promoted into `memory/long/*.md` without going through `sase memory write` and a human review. That gate is the actual defense; injection flags are a defense-in-depth signal, not authorization.

## Multi-Agent and Retry Episodes

`agent_meta.json` carries `sibling_repos` and `tag`; `done.json` carries `retried_as_timestamp` and `retry_chain_root_timestamp`. The fanout/family relationships are in the glossary (root vs child agents, agent family by name prefix). Episodes need to honor these:

- **Fanout children.** One episode per concrete agent run, with `lineage.parent_episode_id` set to the root agent's episode. The root agent gets its own episode covering the dispatch and aggregation, not a synthesized super-episode that hides the children's evidence.
- **Retry chains.** One episode per attempt, with `lineage.retry_of_episode_id` linking to the previous attempt and `retry_chain_root_timestamp` mirrored from `done.json`. Retrieval defaults can hide superseded retries (the chain root carries the surfaceable summary) but the per-attempt episodes remain queryable for failure-pattern analysis.
- **Workflow steps.** Treat each step that produces its own chat as a separate episode under the workflow root. Steps that are pure scripted python/bash do not need episodes — their artifacts already speak for themselves.

This is consistent with the boundary memory note: shared family/retry relationships belong in `sase-core` (other frontends must see the same lineage), while the Python side owns the extractor and the orchestration around `finalize_loop`.

## Embeddings and Hybrid Search

Start with SQLite FTS5. The corpus will sit in the low thousands of episodes for a long time, FTS5 is built into Python's stdlib `sqlite3` and into `rusqlite` on the core side, and lexical recall on agent-generated structured text is already strong. The ZeroClaw benchmark and Garcia's sqlite-vec hybrid recipe both confirm that lexical-only is competitive at this corpus size.

Add a `vec` column only when one of these triggers fires:

- corpus crosses ~5K episodes and lexical recall starts missing paraphrases;
- retrieval is feeding prompt context directly (not just CLI/TUI display);
- evaluation shows concrete misses that hybrid retrieval fixes.

When that happens, the practical model picks as of 2026 are voyage-code-3 (paid, +13.8% over `text-embedding-3-large` on 32 code-retrieval datasets, Matryoshka + int8/binary storage) and BGE-M3 (open weights, dense+sparse+ColBERT in one model). Either one fits in sqlite-vec without architectural change. Do not commit to an embedding column in the v1 schema — it belongs in the index, not the canonical sidecar.

## Storage Recommendation

Use two layers:

1. **Canonical sidecar records:** `~/.sase/projects/<project>/episodes/YYYYMM/<chat-basename>.json`
2. **Materialized SQLite index:** `~/.sase/projects/<project>/episodes.sqlite`

The sidecar JSON makes each episode inspectable, easy to delete/regenerate, and stable under backfills. The SQLite index makes CLI/TUI/mobile queries fast. This mirrors the artifact-index pattern in `sase-core`: the filesystem records remain source of truth, while SQLite is a rebuildable query accelerator.

Avoid a single append-only JSONL ledger as the only store. It is good for audit trails but awkward for idempotent regeneration, correction, and per-chat deletion. If an audit log is needed, add it later as `episode_events.jsonl`.

## Generation Pipeline

Phase 1 should be background and idempotent:

1. Hook after chat save/finalization to enqueue or opportunistically generate an episode.
2. Add `sase episodes build --since ...`, `--chat ...`, and `--all` for backfill.
3. Parse transcript with existing `sase.history.chat` helpers.
4. Read `agent_meta.json`, `done.json`, plan path, diff path, step output, and default artifacts when available.
5. Generate a conservative structured summary.
6. Validate JSON against a strict schema.
7. Write sidecar atomically.
8. Upsert the SQLite index.

The first extractor can be mostly deterministic plus a small LLM-generated summary. If the LLM fails, write a partial episode with `confidence: "low"` and deterministic metadata rather than blocking chat finalization.

## Retrieval UX

Add a CLI first:

- `sase episodes list --query <text> --agent <name> --tag <tag> --limit 20`
- `sase episodes show <episode-id|chat-basename> --json`
- `sase episodes rebuild-index`
- `sase episodes generate --chat <path>`

Then expose it to agents as a skill or xprompt:

- `sase episodes search -j -q "prompt history fanout"`
- agent receives compact episode rows, not raw transcripts;
- agent can explicitly open source chats with `/sase_chats` when evidence is needed.

Do not automatically inject episode memories into every prompt. Start with explicit retrieval. Later, dynamic memory can include top episodes only when a prompt strongly matches tags/keywords and the payload stays small.

## Relationship To Existing SASE Memory

Episodes should be evidence, not canonical memory.

When an episode reveals durable guidance, use the existing `sase memory write` proposal flow:

- evidence can include `chat:<basename>` and `path:<episode-json>`;
- the proposal body becomes a curated semantic/procedural memory;
- a human reviewer approves it into `memory/long/*.md`.

This preserves the current policy that agents do not directly modify memory files without approval.

## Core Boundary

Per project memory, shared backend behavior should live in `sase-core` when another frontend must observe the same results.

Recommended split:

- Python repo:
  - transcript parsing orchestration;
  - LLM extraction prompt;
  - CLI command wiring;
  - post-run enqueue/integration.
- `sase-core`:
  - episode wire structs;
  - sidecar validation helpers if practical;
  - SQLite index schema and query;
  - stable JSON output shape used by CLI/TUI/mobile.

This avoids a Python-only index that mobile or editor integrations later have to reimplement.

## Evaluation Plan

Do not judge this by "does it produce nice summaries?" Judge it by whether retrieved episodes improve future agent work.

Suggested checks:

- Backfill 50 recent chats and inspect extraction precision manually.
- For 10 real follow-up prompts, compare retrieved episodes against what a human would pick.
- Track whether episodes cite existing source paths and avoid unsupported claims.
- Verify generation never blocks chat finalization.
- Measure index query latency with hundreds/thousands of episodes.
- Add regression fixtures for transcript formats: plain chat, previous conversation, plan feedback, failed run, killed run, retry, multi-agent workflow step, and missing metadata.

## Recommended Solution

Build a small, source-linked episodic memory layer:

1. Define `EpisodeWire` schema in `sase-core`, including `lineage`, `temporal`, `usage`, and `safety.private`. Reserve `temporal.t_invalid` and `recall_count` now even if unused in phase 1; adding them later is a wire break.
2. Store canonical per-chat JSON sidecars under `~/.sase/projects/<project>/episodes/YYYYMM/`. Never delete; supersede via `t_invalid`.
3. Add a rebuildable SQLite FTS5 index under `~/.sase/projects/<project>/episodes.sqlite`. Defer embeddings and `sqlite-vec` until a concrete retrieval-quality gap shows up.
4. Generate episodes in the background after `write_done_marker_and_update_index` in `src/sase/axe/run_agent_exec_finalize.py`, plus an explicit `sase episodes build` backfill. Generation must never block chat finalization; on extractor failure, write a deterministic-only partial episode with `confidence: "low"`.
5. Honor multi-agent and retry lineage: one episode per concrete run, parent/retry pointers in `lineage`, mirroring fields already in `agent_meta.json` and `done.json`.
6. Keep retrieval explicit at first through `sase episodes` and an agent skill. Do not auto-inject episode bodies into prompts. If a later phase does inject, gate it on tag/keyword match, a small payload budget, and Mem0-style ADD/UPDATE/DELETE/NOOP consolidation on write.
7. Run the existing prompt-injection patterns from `src/sase/memory/proposals.py:39` on both the source transcript and the generated body. Flag, don't refuse, on the source side; refuse the write on the generated side if it introduces unsupported imperatives.
8. Use generated episodes only as evidence for existing human-reviewed long-term memory proposals (`sase memory write` already accepts `chat` and `path` evidence — no schema change needed).
9. Measure with a SWE-Bench-CL-shaped evaluation: take real follow-up SASE prompts, compare retrieved episodes to a human pick, and track whether prompts informed by episodes change agent behavior. "Nice summaries" is not the metric.

This is the highest-value version because it makes prior agent work discoverable without weakening SASE's current memory safety model, and it leaves room for consolidation, decay, and hybrid retrieval to land later without a schema migration.
