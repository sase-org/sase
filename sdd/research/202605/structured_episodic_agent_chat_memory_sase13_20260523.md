# Structured Episodic Memory for SASE Agent Chats

Date: 2026-05-23

## Research Question

What would it mean for SASE to generate structured episodic memory from agent
chats, is that worth doing, and what implementation path fits the current SASE
architecture?

Constraint honored during this research: existing research markdown files under
`sdd/research/` were not opened. I inspected local source, docs, and current
external references.

## Short Answer

It is worth doing, but only if "episodic memory" means a reviewable,
queryable, evidence-linked index of past agent episodes. It is not worth doing
if the first version automatically rewrites `memory/long/*.md`, injects
LLM-generated lessons into every prompt, or treats raw chat transcripts as
memory.

For SASE, the right first implementation is:

- Keep raw transcripts as the source of truth in `~/.sase/chats/YYYYMM/*.md`.
- Add a project-scoped structured episode ledger plus derived search index under
  `~/.sase/projects/<project>/`.
- Generate episodes asynchronously after an agent run completes.
- Use deterministic metadata extraction first, LLM structured extraction only
  for summaries and lessons.
- Keep prompt injection opt-in until retrieval quality is evaluated.
- Convert durable lessons into existing `sase memory write` proposals, not
  direct writes to canonical long-term memory.

## What "Structured Episodic Memory" Means

In cognitive and agent-memory literature, episodic memory is memory of specific
events and experiences, not just facts. For SASE agent chats, an episode should
capture a bounded agent run or sub-run with enough context to answer:

- What task was attempted?
- In what project, workspace, branch, ChangeSpec, and agent context?
- What actions, commands, files, decisions, failures, and outcomes occurred?
- What should a future agent retrieve from this past experience?
- What transcript or artifact evidence supports the extracted memory?

This differs from:

- Raw chat history: complete prompt/response text, useful as evidence but too
  verbose and weakly indexed.
- Semantic memory: stable facts, project rules, or user preferences.
- Procedural memory: reusable instructions, workflows, and skills.

The 2025 position paper "Episodic Memory is the Missing Piece for Long-Term LLM
Agents" frames episodic memory around five properties: long-term storage,
explicit reasoning, single-shot learning, instance-specific content, and
contextual relations such as when, why, and in what broader context an event
occurred. That maps well onto SASE chat runs because an agent run is naturally
single-shot, timestamped, artifact-backed, and often valuable precisely because
of its specific context.

## External Research Notes

The most relevant pattern is not "summarize all chat logs." It is an
encode-retrieve-consolidate loop:

- CoALA ("Cognitive Architectures for Language Agents") organizes language
  agents around modular memory, structured actions, and decision making. It is a
  useful taxonomy for separating episodic, semantic, and procedural memory.
  Source: https://arxiv.org/abs/2309.02427
- "Episodic Memory is the Missing Piece for Long-Term LLM Agents" argues that
  current long-context, RAG, graph, and parametric approaches each cover only
  part of episodic memory. It recommends focusing on encoding, retrieval,
  consolidation, and benchmarks. Source: https://arxiv.org/abs/2502.06975 and
  HTML: https://ar5iv.labs.arxiv.org/html/2502.06975v1
- "Generative Agents" used a memory stream of natural-language observations,
  retrieval by relevance/recency/importance, reflection into higher-level
  inferences, and planning. It also found failures from bad retrieval and
  fabricated embellishments, which is directly relevant to SASE risk. Source:
  https://arxiv.org/abs/2304.03442 and HTML:
  https://ar5iv.labs.arxiv.org/html/2304.03442
- "Reflexion" improved agents by storing verbal reflections in an episodic
  memory buffer for later trials rather than fine-tuning model weights. This is
  close to SASE's "learn from failed/repeated agent work" use case, but SASE
  should store evidence-linked lessons rather than free-floating self-advice.
  Source: https://arxiv.org/abs/2303.11366
- LangGraph's current memory guide separates short-term thread state from
  long-term memory, distinguishes semantic/episodic/procedural memory, and
  explicitly calls out the latency and quality tradeoff between hot-path memory
  writing and background memory writing. Source:
  https://docs.langchain.com/oss/python/concepts/memory
- LongMemEval evaluates long-term chat memory using information extraction,
  multi-session reasoning, temporal reasoning, knowledge updates, and
  abstention. Those abilities make a good evaluation checklist for SASE.
  Source: https://huggingface.co/papers/2410.10813
- Zep's temporal knowledge graph work is useful as a warning and future path:
  enterprise agent memory often needs dynamic knowledge integration and
  temporal relationships, not just static document retrieval. Source:
  https://arxiv.org/abs/2501.13956
- Letta/MemGPT-style systems separate in-context core memory from archival or
  external memory and let agents retrieve older messages after compaction. SASE
  can borrow the hierarchy without adopting the whole runtime. Sources:
  https://docs.letta.com/guides/core-concepts/stateful-agents and
  https://docs.letta.com/guides/core-concepts/memory/context-hierarchy/

## Current SASE Fit

Relevant local architecture:

- `src/sase/history/chat.py` writes central markdown transcripts using
  sanitized branch/workflow/agent/timestamp basenames, sharded under
  `~/.sase/chats/YYYYMM/`. The saved transcript includes timestamp, optional
  model/agent metadata, extra sections, prompt, and response.
- `src/sase/history/chat_catalog.py` lists sharded and legacy transcripts,
  reads only a bounded head for search/snippets, and exposes a stable JSON
  shape for `sase chats list -j`.
- `src/sase/chats/cli_show.py` can show raw transcript markdown, flattened
  resume turns, or the latest parsed response.
- `src/sase/axe/run_agent_exec_finalize.py` saves the final `ace-run` chat with
  agent/model/provider metadata and then persists related artifacts into the
  done marker.
- `src/sase/memory/dynamic.py` already turns keyword-tagged `memory/long/*.md`
  into prompt-local `.sase/memory/long-*.md` files and appends a
  `### DYNAMIC MEMORY` section.
- `src/sase/memory/proposals.py` already supports attributable,
  evidence-backed, human-reviewable proposals for canonical long-term memory.
  Agents can propose; humans approve or reject.

The local gap is clear: SASE has raw chat evidence and curated semantic memory,
but not structured, searchable, project-scoped episodes that connect the two.

## Critique: Is This Worth Doing?

Yes, with a narrow first scope.

It is worth doing because SASE creates the exact data that episodic memory needs:
timestamped agent runs, artifacts, plans, questions, diffs, commits, statuses,
and final outcomes. A structured episode index would help answer questions like:

- "Have we tried this approach before?"
- "Which agent last touched this file and what went wrong?"
- "What test failure pattern did prior agents resolve?"
- "What did the planner decide and why?"
- "Which chat should I fork from?"

It also fits SASE's existing philosophy: memory should be attributable,
inspectable, and backed by evidence. The proposal workflow is already the right
gate for turning a one-off episode into durable project memory.

The plan is not worth doing if the goal is ambient self-improving memory that
silently changes future prompts. Main risks:

- Prompt pollution: low-quality summaries become instructions by accident.
- Staleness: an old workaround can become actively wrong after code changes.
- Hallucinated extraction: LLM summaries may invent decisions or outcomes.
- Privacy/security: chat logs can contain secrets, personal data, or sensitive
  customer/project details.
- Retrieval harm: irrelevant retrieved memories can distract agents more than
  no memory.
- Cost and latency: hot-path extraction adds delay and duplicates work.
- Governance drift: direct writes to `memory/long` would bypass the existing
  human-review contract.

So the value is high only if SASE treats episodes as an evidence index and
retrieval substrate first, then separately promotes durable lessons through
review.

## Recommended Data Model

Use one episode per completed agent chat in the first version. Later, segment
large transcripts into sub-episodes such as "plan", "failed attempt",
"successful fix", or "review finding".

Suggested schema:

```json
{
  "schema_version": 1,
  "episode_id": "ep-20260523-153012-8f2a91bc",
  "project": "sase",
  "workspace": "sase_13",
  "branch_or_changespec": "example-cl",
  "workflow": "ace-run",
  "agent_name": "planner.foo",
  "agent_family": "planner",
  "runtime": "codex",
  "model": "gpt-5.4",
  "status": "completed",
  "outcome": "fixed|noop|failed|blocked|unknown",
  "started_at": "2026-05-23T15:30:12-04:00",
  "ended_at": "2026-05-23T15:37:44-04:00",
  "chat_path": "~/.sase/chats/202605/example-ace-run-260523_153012.md",
  "artifacts_dir": "~/.sase/projects/sase/artifacts/ace-run/260523_153012",
  "diff_path": "~/.sase/diffs/202605/example.diff",
  "plan_path": "sdd/plans/...",
  "source_sha256": "hash-of-chat-file",
  "task": "Short task statement",
  "summary": "What happened in 3-6 sentences.",
  "files": ["src/sase/history/chat.py"],
  "commands": [
    {"command": "just check", "outcome": "passed"}
  ],
  "decisions": [
    {"text": "Chose FTS before embeddings", "evidence": "chat:# Response"}
  ],
  "errors": [
    {"text": "Parser failed on nested headings", "resolved": true}
  ],
  "reusable_lessons": [
    {
      "text": "Prefer background extraction; do not write canonical memory directly.",
      "type": "procedural_candidate",
      "confidence": 0.83
    }
  ],
  "tags": ["memory", "chat-history", "retrieval"],
  "keywords": ["episodic memory", "sase chats"],
  "importance": 0.0,
  "extracted_by": {
    "method": "deterministic+llm",
    "model": "configured-small-model",
    "prompt_version": "episode-extract-v1"
  },
  "safety": {
    "redacted": true,
    "contains_secret_like_text": false,
    "contains_prompt_injection_like_text": false
  }
}
```

Store pointers and evidence, not full transcript copies. Raw chat remains the
source of truth.

## Storage Recommendation

Use two layers:

1. Canonical append-only JSONL ledger:
   `~/.sase/projects/<project>/episodic_memory/episodes.jsonl`
2. Rebuildable SQLite index:
   `~/.sase/projects/<project>/episodic_memory/index.sqlite`

The JSONL ledger gives auditability, easy sync/debugging, and rollback. SQLite
gives fast filters, FTS5/BM25 text search, and later optional vector columns or
sidecar embeddings. If the index is corrupt, rebuild it from JSONL and raw chat
paths.

If this becomes a cross-frontend capability for CLI, TUI, mobile, and plugins,
the storage/query core belongs in `../sase-core` with Python as a thin adapter,
per the repo's Rust-core boundary. The LLM extraction orchestration can remain
in Python because it is provider/runtime glue.

## Extraction Pipeline

Run extraction in the background after a chat is saved and the done marker is
available.

Do deterministic extraction first:

- Parse filename, timestamp, workflow, agent, model/provider metadata.
- Resolve `done.json`, `agent_meta.json`, diff, plan, markdown/PDF/image
  artifacts, and final status.
- Hash the raw transcript and artifacts referenced by the episode.
- Extract file paths, commands, test statuses, and explicit error sections when
  present.

Then run optional LLM extraction for fields that need judgment:

- Task summary.
- Decisions.
- Failure causes.
- Outcome.
- Reusable lessons.
- Candidate semantic/procedural memory proposals.
- Importance score and tags.

Use strict JSON schema validation and make extraction idempotent by keying on
`chat_path + source_sha256 + extractor_version`. On extraction failure, store a
diagnostic record or skip; never block the agent finalizer.

## Retrieval Recommendation

Start with deterministic search:

- SQLite FTS over `task`, `summary`, `files`, `errors`, `decisions`, `tags`,
  and `reusable_lessons`.
- Filters for project, date range, workflow, agent family, status/outcome, file,
  ChangeSpec, and model/provider.
- Scoring that combines BM25, recency, importance, and successful outcome.

Add embeddings only after a lexical baseline exists. Coding-agent memory often
depends on exact identifiers, file paths, commands, and error strings where
BM25/FTS is strong and predictable.

Initial surfaces:

- `sase episodes index --since ...`
- `sase episodes search <query> --file ... --outcome ... --json`
- `sase episodes show <episode-id>`
- `sase episodes propose-memory <episode-id> --target long/<slug>.md`

Do not auto-inject retrieved episodes into every prompt in version 1. Add an
opt-in xprompt later, for example `#episodes:<query>` or a prompt directive that
adds a short "Relevant Past Episodes" section with episode IDs, paths, and
compact summaries.

## Consolidation Recommendation

Keep this separation:

- Episodic store: "What happened in this run?"
- Semantic memory: "What fact should future agents know?"
- Procedural memory/skills: "How should future agents act?"

The episodic store can propose consolidation candidates, but the existing
`sase memory write` and `sase memory review` flow should decide what becomes
canonical `memory/long/*.md`. Repeated high-confidence lessons across multiple
episodes are good proposal candidates. One-off lessons should remain episodes.

## Evaluation Plan

Use shadow mode first: build the index and CLI, but do not feed retrieved
episodes to agents by default.

Evaluate:

- Retrieval precision@k on hand-written queries from recent SASE work.
- Whether the top result answers "what happened last time?" without opening the
  raw transcript.
- Temporal reasoning: can it distinguish old superseded outcomes from current
  outcomes?
- Abstention: does search avoid fabricating an answer when no episode matches?
- Agent impact: on repeated tasks, does opt-in episode retrieval reduce repeated
  failures or time-to-fix?
- Cost and latency: background extraction should not affect agent completion.
- Safety: sampled episodes should avoid secrets and prompt-injection text in
  summaries.

LongMemEval's categories are a useful checklist, but SASE should build its own
small benchmark from real, non-sensitive development episodes.

## Implementation Phases

1. Define schema and index contract.
   Add versioned dataclasses/wire records, validation, and JSONL/SQLite storage.

2. Build an offline indexer.
   Read existing chat catalog entries, parse metadata, create deterministic
   episode records, and populate SQLite FTS.

3. Add background post-run extraction.
   Trigger after `save_chat_history`/done marker finalization. Keep it best
   effort and idempotent.

4. Add CLI inspection.
   Implement `index`, `search`, and `show` before any prompt-injection feature.

5. Add LLM structured extraction.
   Gate behind config. Store extractor version/model and validate all outputs.

6. Add proposal bridge.
   Convert selected lessons into `sase memory write` proposals with episode/chat
   evidence.

7. Add opt-in prompt retrieval.
   Only after search quality is good, provide an explicit xprompt or directive
   that retrieves compact cited episodes.

## Recommended Solution

Build structured episodic memory as a project-scoped, evidence-linked episode
index over SASE agent chats, not as automatic long-term memory mutation.

The first useful system should be a background extractor plus
`sase episodes search/show` over an append-only JSONL ledger and rebuildable
SQLite FTS index. It should preserve raw chats as source evidence, extract
structured run metadata deterministically, use LLMs only for schema-validated
summaries/lessons, and route durable lessons through the existing
`sase memory write` human-review workflow. After the index proves useful in
shadow mode, add opt-in prompt retrieval with compact, cited episode snippets.
