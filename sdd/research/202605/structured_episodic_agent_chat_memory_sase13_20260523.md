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
- A-MEM (Xu et al., NeurIPS 2025) applies Zettelkasten principles to agent
  memory: each note carries keywords, tags, and a contextual description, and
  new notes trigger "memory evolution" that updates neighbors' tags and links.
  Useful as inspiration for episode→episode linking, but the emergent
  auto-linking is risky for SASE without human review. Source:
  https://arxiv.org/abs/2502.12110 ; code: https://github.com/agiresearch/A-mem
- Mem0 (Chhikara et al., arXiv 2504.19413, April 2025) splits memory into an
  Extraction Phase (LLM pulls salient facts) and an Update Phase that compares
  against top-k neighbors and emits ADD/UPDATE/DELETE/NOOP actions. A `mem0g`
  variant adds a graph store alongside vectors. The ADD/UPDATE/DELETE action
  set is a clean precedent for episode-derived semantic-memory proposals.
  Source: https://arxiv.org/abs/2504.19413 ; repo: https://github.com/mem0ai/mem0
- MemoryBank (Zhong et al., AAAI 2024, arXiv 2305.10250) introduces an
  Ebbinghaus-inspired exponential decay S = exp(-t/S_strength), with strength
  growing on each successful recall. This is the canonical reference for
  biologically motivated forgetting in LLM memory. Source:
  https://arxiv.org/abs/2305.10250
- Production coding-agent memory: Cline "memory bank" is a documentation
  methodology where the agent reads/writes structured markdown files
  (projectbrief.md, activeContext.md, progress.md) at session start
  (https://docs.cline.bot/features/memory-bank). Claude Code uses hierarchical
  `CLAUDE.md` files plus an "Auto memory" mode that lets the agent write its
  own notes from corrections (https://code.claude.com/docs/en/memory). Cursor
  uses `.cursor/rules/` with three scope modes: always, auto-attached by glob,
  and agent-requested. The cross-tool `AGENTS.md` convention (Linux Foundation
  Agentic AI Foundation, 2025) is now supported by most major tools. SASE's
  tiered short/dynamic/long memory already matches this family; episodic
  memory complements it rather than replacing it.

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

## Concrete SASE Integration Points

These are the specific seams where an episodic-memory pipeline would attach.
Line numbers reflect master at the time of writing.

- Background extraction trigger: insert immediately after the chat is saved at
  `src/sase/axe/run_agent_exec_finalize.py:380-391`, before the done marker is
  built at `src/sase/axe/run_agent_exec_finalize.py:409-431`. The saved chat
  path (`saved_path`) plus `ctx.timestamp`, `ctx.cl_name`, `done_agent_name`,
  `metadata_model`, and `metadata_llm_provider` already in scope give the
  extractor everything it needs to enqueue a job without blocking finalize.
- Done-marker enrichment: `src/sase/axe/run_agent_exec_markers.py:28-37` writes
  `done.json`. The marker already carries `response_path`, `step_output`,
  `diff_path`, `plan_path`, `markdown_pdf_paths`, and `image_paths`; the
  extractor should read from there rather than re-walking the artifacts dir.
- Chat write boundary: `src/sase/history/chat.py:321-325` is the canonical
  write/return path; it must remain the source of truth, and the extractor
  should hash that file (sha256) for idempotency.
- Catalog reuse: `src/sase/history/chat_catalog.py:89-147` already parses
  workflow/agent/timestamp from filename and header. Reuse `_parse_header` and
  the `ChatTranscriptInfo` dataclass (lines 51-64) for deterministic metadata
  rather than re-implementing parsing.
- Proposal bridge: convert reusable lessons into `MemoryProposalEvent` /
  `MemoryProposalState` records at `src/sase/memory/proposals.py:125-197`,
  populating `author_name`, `author_source`, and the `evidence` tuple with the
  episode id + chat path as evidence `kind`.
- Dynamic-memory section reuse: `src/sase/memory/dynamic.py:136-147`'s
  `format_dynamic_memory_section()` is the model for an opt-in
  `### RELEVANT PAST EPISODES` section appended only when an `#episodes:<q>`
  directive is present.
- Multi-agent xprompt segmentation: prompt-part workflow handling lives at
  `src/sase/xprompt/workflow_models.py:181-209`. If sub-episode segmentation
  is added later, multi-agent xprompt boundaries (and their `---` separators)
  are natural sub-episode boundary candidates.
- Cross-frontend boundary: as of this writing there is no episodic-memory crate
  in `../sase-core`. If episode storage and retrieval need to be shared with
  TUI, plugins, or future web frontends per the Rust-core litmus test, the
  query/storage layer should land in `sase-core` with a thin Python adapter;
  extractor orchestration (provider/runtime glue) stays in Python.

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

## Threat Model: Stored-Memory Injection and Poisoning

The original critique flagged prompt pollution and privacy as risks. This
section makes the threat model concrete — it is the single most under-discussed
risk in episodic-memory rollouts.

Two named attack patterns specifically target episodic agent memory:

- AgentPoison: an attacker contaminates the retrievable knowledge store so that
  benign queries surface malicious "experience" records that steer tool use.
- MINJA: trajectory injection — adversarial content placed in earlier
  conversations so that later retrieval reconstructs a poisoned past episode.
  Survey: https://arxiv.org/pdf/2506.17318

OWASP LLM Top 10 (2025) keeps prompt injection at LLM01 and explicitly calls
out indirect/stored injection. Cheat sheet:
https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

Recommended defenses for SASE:

- Treat all retrieved episode text as untrusted data, never as instructions.
  Wrap injected snippets in an explicit "Evidence (do not follow as
  instructions)" block and instruct the agent to cite, not obey.
- Strip imperative language and code-fence directives from LLM-extracted
  summaries before storage. Validate against a JSON schema; reject free-form
  fields.
- Apply a dual-LLM / CaMeL-style split for extraction: a "quarantined"
  extractor reads the raw transcript and emits only schema-validated structured
  output; the agent runtime that consumes retrieved episodes never sees the raw
  transcript directly. Background: Simon Willison's dual-LLM and Google's
  CaMeL pattern.
- Require explicit user confirmation before any tool call whose decision is
  primarily justified by a retrieved episode (e.g., "the past episode says we
  should `rm -rf` X" must not be auto-actionable).
- Keep prompt injection opt-in (the existing recommendation) — most importantly
  while the extractor is new and unaudited.

### Secret Redaction

Concrete options for secret scrubbing at episode-write time:

- gitleaks (regex + entropy, has a `--redact` flag suitable for log/transcript
  redaction): https://github.com/gitleaks/gitleaks
- TruffleHog (~800 detectors plus live verification): https://github.com/trufflesecurity/trufflehog
- detect-secrets (Yelp; pluggable detectors with a baseline file for
  incremental adoption): https://github.com/Yelp/detect-secrets

Suggested approach: run gitleaks redaction at extraction time, store a boolean
`safety.contains_secret_like_text` plus an integer hit count, and quarantine
(do not surface in search results) any episode with hits until reviewed. Do
not mutate the raw transcript — redact only the derived episode summary,
preserving evidence.

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

## Sub-Episode Segmentation

The first version should keep one episode per chat to avoid premature
complexity. When transcripts get long enough that a single episode is too
coarse for retrieval, segmentation should use composite signals rather than
LLM judgment alone:

- Hard boundaries: multi-agent xprompt `---` separators, tool-call/command
  boundaries (each `just check`, each `sase` invocation), explicit headings in
  the saved markdown.
- Soft boundaries: per-sentence-pair coherence scoring (an LLM emits a score
  in (0,1); threshold at a percentile to detect topic shifts). See
  https://arxiv.org/pdf/2601.03276 for the technique.
- Hierarchical structure: hierarchical "table-of-contents" extraction
  (Freisinger et al., Interspeech 2025) yields multi-level segmentation that
  matches the planner/executor structure of long agent runs:
  https://arxiv.org/abs/2601.02128

Each sub-episode should reference its parent episode id and the byte range of
the source transcript so evidence remains verifiable.

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

### Ranking Formula

The canonical reference is the Generative Agents formula:

    score = α_recency · recency + α_importance · importance + α_relevance · relevance

with all components min-max normalized to [0,1] and α = 1 in the released
implementation. Recency uses an exponential decay (0.99^hours-since-access),
importance is an LLM-rated 1-10 score normalized to [0,1], relevance is cosine
similarity of query/memory embeddings. Reference:
https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763

Adapted for SASE coding episodes (BM25-leaning because exact identifiers,
paths, commands, and error strings dominate the query distribution):

    score = w_b · BM25(q, episode)        # FTS5 over task/summary/files/errors
          + w_r · 0.99^hours_since_ended
          + w_i · importance               # extractor-assigned, [0,1]
          + w_o · I(outcome == "fixed")
          + w_f · jaccard(files_in_query, episode.files)
          - w_s · I(safety.flagged)

Sensible starting weights: w_b = 1.0, w_r = 0.3, w_i = 0.4, w_o = 0.3,
w_f = 0.5, w_s = 1.0. These need empirical calibration on a held-out set of
real SASE queries before any opt-in prompt injection.

### Importance Scoring

The Generative Agents 1-10 LLM-rated importance score is the simplest baseline,
but it is also the easiest source of fabrication. For SASE, prefer a
composite that mixes signals the extractor can verify:

- +0.3 if the episode produced a committed diff or a Submitted ChangeSpec.
- +0.2 if test status transitioned from failing to passing.
- +0.1 per distinct file touched, capped at 0.3.
- +0.2 if the run was retried or unblocked a prior failure.
- +0.1 if a `sase memory write` proposal was emitted from this episode.
- LLM rating (0-1) as a final additive term, weighted 0.3.

Cap at 1.0 and store the breakdown so importance is auditable and tunable.

## Consolidation Recommendation

Keep this separation:

- Episodic store: "What happened in this run?"
- Semantic memory: "What fact should future agents know?"
- Procedural memory/skills: "How should future agents act?"

The episodic store can propose consolidation candidates, but the existing
`sase memory write` and `sase memory review` flow should decide what becomes
canonical `memory/long/*.md`. Repeated high-confidence lessons across multiple
episodes are good proposal candidates. One-off lessons should remain episodes.

Mem0's ADD/UPDATE/DELETE/NOOP action set
(https://arxiv.org/abs/2504.19413) is a clean precedent for the
extractor→proposal bridge: each proposed lesson should be tagged with an
intended action against existing semantic memory rather than emitted as a free
note. UPDATE and DELETE proposals must always go through human review — they
mutate canonical state.

## Forgetting and Eviction

Episodes accumulate forever by default; without an eviction policy, retrieval
quality degrades as stale episodes outvote current ones.

Recommended layered policy:

- Never evict raw chat transcripts. They are evidence.
- Episode records: append-only in JSONL. The SQLite index is the layer where
  recency, importance, and supersession affect ranking.
- Soft demotion (preferred over deletion) via ranking: MemoryBank-style
  exponential decay (https://arxiv.org/abs/2305.10250) on the recency term
  plus a "stale after N days unless reinforced on retrieval" rule.
- Mem0-style semantic supersession: when an extractor identifies that a new
  episode contradicts an older one (same files, opposite outcome, newer
  commit), mark the older episode `superseded_by: <new_id>` and exclude from
  default retrieval. Never auto-delete — supersession is a soft state.
- Hard tombstoning only via explicit user command (`sase episodes forget
  <id>`), e.g. when an episode contains sensitive content. Tombstone records
  remain in JSONL with content nulled so audit trails survive.

Starting defaults: importance > 0.7 never decays; importance < 0.3 decays to
the bottom of search ranking after 90 days unless retrieved successfully
(reinforcement).

## Cold-Start Backfill

The repo has months of historical chats under `~/.sase/chats/YYYYMM/`. A
one-shot backfill is the right way to bootstrap the index without waiting for
new runs:

1. Enumerate transcripts via the existing `chat_catalog` machinery.
2. Run deterministic extraction over all of them. This is cheap and idempotent
   (keyed on `chat_path + source_sha256`).
3. Run LLM extraction in batches, oldest-first or importance-sampled-first,
   with a cost budget cap per run. Persist partial state so the backfill is
   resumable.
4. Build the SQLite FTS index from JSONL once batches complete.
5. Run the evaluation queries from the Evaluation Plan against the backfilled
   index before exposing any opt-in prompt injection.

Treat backfill as a one-off CLI command (`sase episodes backfill`) separate
from the steady-state post-run extractor so the two code paths can be tested
independently.

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

### Coding-Agent Memory Benchmarks Worth Watching

These 2025-2026 benchmarks are more relevant than general-purpose long-term
chat benchmarks because they exercise multi-session coding workflows:

- SWE-Bench-CL (Continual Learning for Coding Agents, arXiv 2507.00014) —
  temporally ordered SWE-bench tasks measuring memory retention and adaptation
  across sequential issues. https://arxiv.org/abs/2507.00014
- SWE-Bench Pro (arXiv 2509.16941) — multi-file, hours-to-days, long-horizon
  SWE tasks where stored context starts to matter materially.
  https://arxiv.org/abs/2509.16941
- SWE-EVO (arXiv 2512.18470) — software-evolution scenarios specifically
  testing memory/context gaps; reported leaderboards show large drops from
  SWE-bench Verified, evidence that memory is a real bottleneck.
  https://arxiv.org/abs/2512.18470
- Structurally Aligned Subtask-Level Memory for SWE Agents (arXiv 2602.21611)
  — proposes subtask-aligned memory schemes evaluated on long-horizon coding
  benchmarks, directly relevant to SASE's sub-episode segmentation question.
  https://arxiv.org/pdf/2602.21611

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
