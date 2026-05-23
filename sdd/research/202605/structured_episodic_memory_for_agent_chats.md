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
>
> **Revision (2026-05-23, third pass):** Third pass closes remaining gaps without overturning prior conclusions. New
> material covers: an explicit importance/selection scoring function so the LLM-call budget is deterministic; an
> inter-episode link vocabulary (`supersedes`, `refutes`, `see_also`, `parent_of`, `forked_from`) so episodes can form
> an auditable causal graph; a redaction-at-source design that reuses `src/sase/ace/tui/repro/redact.py` and the
> existing `_PROMPT_INJECTION_PATTERNS` rather than inventing parallel scrubbers; pre-embedding ranking signals
> (recency decay, success weight, agent-family match, file overlap, repo locality); a concrete backfill plan for the
> existing ~1,570 chats and ~458 `done.json` records; TUI and mobile surfaces including a `sase ace` "Episodes" tab and
> Telegram digest format; a comparison row for current commercial memory products (Claude memory tool, ChatGPT memory,
> Cursor "Memories", Continue/Cline rule files, Letta archival memory); explicit trigger points (post-finalizer hook,
> retry-chain close, dismissal) and a uniform-runtime constraint; observability metrics the collector and distiller
> must emit; a forgetting/decay policy; and an anti-patterns list that calls out the failure modes most likely to
> appear under implementation pressure. None of these reverse the earlier recommendation that episodes are evidence,
> not instructions; they harden the seams where that line is easy to cross by accident.

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

## Importance Scoring And Episode Selection

Phase 1 must produce an importance score deterministically so Phase 2 can pick which episodes get LLM distillation
without invoking a model just to decide. The earlier `selection.importance: 0.73` field needs a defined source.

Recommended scoring function, computed from already-indexed metadata only:

```
importance = clamp01(
    0.25 * outcome_signal       # +1 retry-chain success after failure, +0.5 first-try success, 0 noop, -0.5 dismissed
  + 0.15 * artifact_signal      # +1 if diff_path | plan_path | commit, +0.5 if generated artifacts, else 0
  + 0.15 * scope_signal         # 1.0 if ChangeSpec/bead/sdd_prompt_path present, 0.5 if just project, 0 unscoped
  + 0.15 * retry_signal         # 1.0 for chains of len>=3 ending in success, 0.5 for len==2, 0 for len==1
  + 0.10 * duration_signal      # log10(seconds)/4 capped at 1.0 -- short runs are rarely worth distilling
  + 0.10 * model_signal         # 1.0 if model is Opus/Sonnet-class, 0.5 Haiku, 0 unknown -- a proxy for stake
  + 0.10 * recency_signal       # exp(-age_days/30); recent failures matter more than ancient ones
)
```

Episodes with `importance >= 0.55` enter the distillation queue. Episodes between `0.30` and `0.55` enter only on
explicit `sase episodes distill --include-medium`. Below `0.30`, the deterministic manifest is enough.

Three hard overrides bypass the score:

1. **User-flagged**: any episode where the user prompt contains `#flag` or a `sase episodes flag ep_...` call.
2. **Failure-recovery**: any retry chain that ended with success after at least one failure (Reflexion's high-value
   case).
3. **Research/postmortem**: episodes whose root prompt path is under `sdd/research/` or `sdd/postmortems/`.

This keeps token spend predictable: at ~60 episodes/day peak with selection rate ~40%, distillation is bounded at
24/day even if every score were a coin flip. The thresholds are tunable per project via `~/.sase/episodes.yml`.

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

## Inter-Episode Links

Episodes acquire most of their long-term value once they reference each other. Borrow A-MEM's typed-link idea but
restrict the vocabulary to keep audit cheap. The link block is a top-level array, not buried in `summary`:

```json
"links": [
  {"kind": "parent_of",   "episode_id": "ep_abc", "reason": "child workflow step"},
  {"kind": "forked_from", "episode_id": "ep_def", "reason": "/fork from chat path"},
  {"kind": "supersedes",  "episode_id": "ep_ghi", "reason": "later attempt fixed earlier regression"},
  {"kind": "refutes",     "episode_id": "ep_jkl", "reason": "earlier 'lesson' was wrong, see chat L42"},
  {"kind": "see_also",    "episode_id": "ep_mno", "reason": "same ChangeSpec, adjacent in time"}
]
```

Rules:

- **Links are append-only.** Adding a `supersedes` edge does not delete the predecessor; the index just deranks it for
  default queries. The predecessor stays as evidence.
- **`refutes` requires a citation.** The episode JSON must carry `refutes_evidence: [{episode_id, chat_path,
  excerpt_sha256}]`. Without that, the link is rejected at validation. This is the only way an episode is allowed to
  contradict another.
- **`supersedes`/`refutes` cascade to memory proposals.** If an episode that produced an approved `mem-*` memory is
  refuted or superseded, the index flags that memory for human re-review and writes a row to a `memory_invalidations`
  table. The memory file itself is not edited automatically.
- **Link creation is local-deterministic where possible.** `parent_of` and `forked_from` come from `agent_meta.json`
  and `chat_links.py`. `supersedes` is inferred from retry-chain root + outcome flip. `refutes` and `see_also` are
  the only kinds that may be proposed by an LLM, and only with citations.

The link graph is a useful retrieval signal: `reflect "<query>"` should prefer episodes whose closest neighbors in the
link graph also score well, breaking ties before recency.

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

## Redaction At The Source: Secret And PII Scrubbing

The collector must scrub before any text leaves the immediate evidence layer. Two existing seams should be reused
rather than duplicated:

1. **`src/sase/ace/tui/repro/redact.py`** already scrubs reproduction captures of paths, tokens, and identifiers. The
   episode collector should call the same redactor on excerpts before they enter the JSON `summary.*` arrays or are
   shipped to the distiller. New scrub rules belong in that module so repro captures benefit from the same fixes.
2. **`src/sase/memory/_proposal_validation.py::_PROMPT_INJECTION_PATTERNS`** already detects classic injection strings.
   The collector should run those patterns over any excerpt it considers including, and on hit it must:
   - set `selection.trust = "tool_output"` for the source segment;
   - drop the segment from `summary.retained_facts` and `memory_candidates`;
   - record the matching pattern code in `safety.prompt_injection_flags`.

Concrete scrub layers, applied in order:

| Layer | What it catches | Where it runs |
| --- | --- | --- |
| Path/identity redactor (existing) | `$HOME`, machine name, workspace number, absolute paths | `redact.py` |
| Secret regex pack | AWS/GCP/Anthropic/OpenAI/GH keys, JWTs, RSA blocks, `Bearer <token>` | new `episodes/scrub_secrets.py` |
| PII regex pack | emails (except the configured user email), phone numbers, IP addresses | new `episodes/scrub_pii.py` |
| Injection screen (existing) | `ignore previous instructions`, `system:`, `</prompt>`, etc. | `_proposal_validation.py` |
| Length cap | head + tail + retry-delta only, ≤16 KB per episode total | collector |

The secret/PII regex packs should be lifted as-is from well-known sources (`gitleaks`, `trufflehog`, `detect-secrets`)
rather than hand-written; SASE does not need to invent a new pattern set. A single fixtures file
`tests/episodes/fixtures/poisoned/` should contain one chat per pattern class so regressions are caught immediately.

Important: scrubbing is for *excerpts*, not for raw chat files. Raw chat redaction is a separate, opt-in flow
(`sase chats redact <path>`) because removing evidence from the canonical record has stronger implications than
redacting a projection. The episode collector must treat the raw chat as immutable input.

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

## Search Ranking Signals Before Embeddings

FTS by itself ranks on lexical overlap. Coding-agent retrieval needs more. The recommended `sase episodes search`
ranker combines BM25 with five cheap structural signals, all computed at query time from the index:

```
score = bm25
      + 0.6 * recency_decay        # exp(-age_days / 60)
      + 0.4 * outcome_weight       # +1 success, +0.7 noop, +0.3 failure, 0 unknown
      + 0.4 * importance           # cached from selection.importance
      + 0.3 * scope_match          # 1 if query mentions same ChangeSpec / bead / file / repo
      + 0.2 * agent_family_match   # 1 if query mentions the same agent family
```

Rationale per signal:

- **recency_decay (60-day half-life)**: coding-agent context rots faster than general knowledge. A six-month-old
  episode about the same file is usually less useful than a one-week-old episode about a neighboring file.
- **outcome_weight**: a successful retry chain is a better template than a failed one for "what should I try?", but
  failures should not be excluded — they are essential for "what did we try and rule out?". A small positive weight
  on failure (`0.3`) keeps them in the top-k without dominating.
- **importance**: re-uses the deterministic Phase-1 score; no extra cost.
- **scope_match**: extracted from the query at search time by matching against known ChangeSpec names, bead IDs, and
  repo-relative file paths (cheap because those identifiers have rigid shapes).
- **agent_family_match**: a fix-family episode is usually a better match for a fix-family query than a research-family
  one, even when the words overlap.

When embeddings are added later, they replace `bm25` as the lexical term; the structural signals stay. This makes the
upgrade additive and revertible (drop the `sqlite-vec` extension load, and ranking falls back to FTS+structural).

The TUI's "Episodes" tab (described below) should expose the contribution of each signal as a debug overlay (`E`
keymap) so ranking regressions are diagnosable without a full eval rerun.

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

## Backfill Plan For The Existing Corpus

The local SASE state already contains 1,570 chat markdown files, 458 `done.json`s, 1,146 `agent_meta.json`s, and 740
dismissed bundles. A naïve "distill them all" backfill is the wrong shape; a tiered backfill is right.

Recommended ordering:

1. **Tier A — index only, no LLM.** Run `sase episodes collect --all` against the artifact index and the chat
   catalog. Goal: every chat with usable metadata gets a deterministic episode record with `importance`, links, and
   sources populated. Expected output: ~300–400 episodes after retry-chain and workflow collapse. Cost: zero LLM
   tokens, sub-minute on a warm SQLite index.
2. **Tier B — distill top decile.** Run `sase episodes distill --pending --importance-min 0.7 --limit 50` to spend
   tokens on the clearly-valuable episodes first. Manually spot-check 10 of those to validate the prompt before
   widening the queue.
3. **Tier C — widen to retry chains + research/postmortem.** Distill anything matching the hard overrides regardless
   of score. Expected total: ~80–120 distilled episodes after Tier B + C combined.
4. **Tier D — opt-in widening.** Leave the remaining ~70% of episodes as deterministic-only records. They are still
   searchable and citable; they just lack an LLM-written summary. The collector can revisit them later if
   `sase episodes search` precision falls.

Pre-backfill guards:

- Run the secret/PII scrub on a 10-chat sample before any distillation. If the scrubber finds matches, fix the
  patterns before running at full scale.
- Cap the backfill rate (e.g. `--max-rps 0.5`) so a runaway loop does not produce thousands of proposals overnight.
- Backfill produces episodes only; it does **not** auto-create `mem-*` proposals. Proposal creation is gated by
  `sase episodes promote-candidates --since 1d` so a human can pace the review queue.

Dismissed-bundle backfill is opt-in via `--include-dismissed`. Many dismissed bundles are legitimate work that was
manually hidden from the TUI but still valuable as evidence; some are noise. The collector should mark every such
episode `episode_kind: "agent_run"` with a `selection.reasons` entry of `"dismissed_recovered"` so the source is
obvious in `show`.

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

## TUI And Mobile Surfaces

CLI is enough for v1, but the value of episodes shows up at review time, and review is mostly visual.

**`sase ace` TUI: "Episodes" tab.** Add a fourth tab next to Agents, Chats, and Memory. Rows show `episode_id`,
title, project, workstream, outcome glyph, agent family, `importance`, distilled-yes/no, and pending-proposal count.
Keymaps:

- `Enter`: open the episode markdown projection in the right pane.
- `o`: open the underlying chat in the existing Chats tab.
- `c`: open the candidate proposals (if any) in the existing Memory tab.
- `l`: jump to the linked predecessor (`supersedes`/`forked_from`/`parent_of`).
- `/`: open a search palette using the same FTS+structural ranker as `sase episodes search`.
- `E`: toggle the ranking-signal debug overlay described earlier.
- `R`: redact the highlighted field (calls `sase episodes redact`).

The Episodes tab is presentation-only and stays in Python, per the Rust-core boundary. The data it renders comes from
the new `agent_episodes` crate's stable wire format.

**Mobile / web surfaces.** Use the same wire format for the future mobile app and the `textual-serve` web shell.
Episodes are smaller than chats, and their structure is fixed, so they render well on small screens. A mobile
"timeline" view should list episodes in reverse-chronological order, grouped by ChangeSpec or bead, with the title
plus a 1-line outcome line — no excerpt scrolling required.

**Telegram digest (via `sase-telegram`).** A daily/weekly `sase episodes digest --telegram` command produces a
Markdown-V2 message with: top 5 episodes by importance, count of failed-then-succeeded retry chains, count of pending
memory proposals, and a deep-link path per episode. The message body is bounded at 4096 characters; episodes beyond
the cap roll into a "+N more" line. The Telegram bridge sends but does not store; the canonical record stays under
`~/.sase/episodes/`.

**Neovim (`sase-nvim`).** A `:SaseEpisodes <pattern>` command opens a quickfix list scoped to the current file or
ChangeSpec. This is mostly a thin wrapper around `sase episodes search -j --file <path>`, but it makes the "what did
I or another agent do here last time?" question answerable from the editor without context-switching.

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

## Comparison With Current Commercial Memory Products

The commercial landscape as of 2026 helps locate SASE's design. None of these products targets the "audit completed
agent runs in a coding workspace" niche directly; each makes a different tradeoff that SASE should learn from but not
copy.

| Product | Unit of memory | Promotion | Provenance | Why SASE differs |
| --- | --- | --- | --- | --- |
| ChatGPT memory (OpenAI) | Free-text facts about the user | Automatic, with a "Saved" notice | Weak: shown in a settings page, not cited inline | SASE needs per-episode citation back to chats/artifacts; account-level facts are the wrong unit |
| Claude memory tool (Anthropic API) | Developer-defined documents stored via a tool call | Tool-mediated, app controls writes | Whatever the app records | Closest in spirit to SASE's `memory/long` writes via review; SASE's contribution is the *episode layer below it* |
| Cursor "Memories" | Editor-scoped rules learned from interactions | Auto-proposed; user accepts/rejects in UI | Linked to the originating chat | Cursor proposes rules but does not expose episode evidence; SASE's review surface stays the same place a human would audit |
| Continue / Cline rule files | Pinned markdown files in the repo | Manual edit only | The file itself | No episode layer; SASE adds one without disturbing the rule-file model |
| Aider conventions | Static markdown loaded into the prompt | Manual | Filename | Same shape as `memory/long`; SASE differs by having an episode index below it |
| Letta archival memory | Vector-indexed text blocks with explicit `archival_insert` | Agent-mediated, no review by default | Insertion timestamp | SASE rejects "agent-mediated insert without review" for `memory/long`; episodes are SASE's substitute for ad-hoc archival writes |
| Zep / Graphiti | Bi-temporal knowledge graph over conversations | Automatic edge creation | Strong: nodes carry valid/transaction time | Useful schema lesson (bi-temporal fields) but SQLite + JSON is enough for SASE volume; a graph DB is not justified |
| mem0 | Extract/update/retrieve loop with conflict resolution | Automatic merge | Per-claim source | SASE's `supersedes`/`refutes` link kinds capture the conflict-resolution idea without silent in-place mutation |
| Generative Agents memory stream | Time-stamped observations + reflections | Importance score + retrieval | Embedded in stream | SASE borrows the importance score, drops the always-on retrieval injection |

Two takeaways:

1. The market direction is toward *some* automatic memory, but every product that exposes it conservatively (Cursor's
   accept/reject, Claude's tool-mediated writes) does better than products that promote silently. SASE's review-gated
   promotion path matches the safer pattern.
2. No current product publishes an "episode card" with full evidence links. That is the SASE-specific niche: a record
   that future agents (and humans during postmortem) can cite without trusting it as instruction.

## Implementation Strategy

### Trigger Points And Hook Integration

The collector should not poll on a schedule. SASE already emits the events it needs:

- **Post-finalizer**: `src/sase/axe/run_agent_exec_finalize.py` is the single place where `done.json` becomes complete.
  Add a best-effort, non-blocking call to `episodes.collect_for_artifact(artifact_dir)` at the end of that function.
  Failure must not affect the agent's user-visible outcome; log to `~/.sase/episodes/collector.log` and continue.
- **Retry-chain close**: when `retry_chain_root_timestamp` gains a successful terminal member, re-collect the chain
  (the episode ID changes when the chain extends, per the idempotency rules). This is detectable at finalize time.
- **Dismissal**: `~/.sase/dismissed_bundles/` writes are an explicit user action. Subscribe via a filesystem watcher
  or, simpler, re-scan on the next collector invocation; either way, never lose the evidence.
- **Manual**: `sase episodes collect [--since|--all|--artifact-dir]` for backfill and reruns.

The post-finalizer hook is the only one that needs to be online during normal use. Everything else is recoverable on
the next `collect` call. This keeps the agent critical path unaffected.

### Cross-Runtime Parity

By the "Uniform Agent Runtimes" rule in `memory/short/gotchas.md`, the collector must not branch on runtime. Claude,
Codex, Gemini, Qwen, and any future runtime produce the same `done.json` and `agent_meta.json`. The episode collector
reads those, not runtime-specific transcript dialects. Two practical consequences:

1. Distillation prompts should be runtime-neutral. The prompt should describe the *input shape* (structured metadata
   + bounded excerpts) without mentioning a specific runtime's transcript format.
2. The eval harness must include at least one fixture per supported runtime so a runtime-specific regression is
   caught immediately. Fixtures should live under `tests/episodes/fixtures/runtimes/{claude,codex,gemini,qwen}/`.

If a runtime produces malformed `agent_meta.json` (older Codex versions, for example), the deterministic collector
still produces an episode — fields just go missing — rather than failing or branching on runtime.

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

## Observability And Metrics

The collector and distiller must publish enough state that a regression is debuggable without re-running them. Append
JSONL rows to `~/.sase/episodes/metrics/YYYYMM.jsonl` for every run with the following fields:

```json
{"ts": "...", "phase": "collect|distill|reindex",
 "episodes_seen": 0, "episodes_written": 0, "episodes_skipped_idempotent": 0,
 "candidates_produced": 0, "candidates_rejected_injection": 0, "candidates_rejected_low_confidence": 0,
 "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "wall_seconds": 0.0,
 "errors": [{"path": "...", "kind": "...", "message": "..."}]}
```

A small `sase episodes stats --since 30d` command should aggregate these. Key alarms worth surfacing:

- distillation rejection rate (poison-screen hits / candidates) — sustained spikes mean a new injection pattern is in
  the wild;
- LLM output JSON-validation failure rate — sustained spikes mean the distillation prompt drifted;
- p95 collector wall time — sustained growth means the artifact index needs maintenance;
- candidate-to-promoted ratio — if approval rate falls below ~30%, the selection threshold is too generous.

These metrics are local-only; they should not be synced. Each machine's view is independent.

## Forgetting And Decay Policy

Episodes are append-only on disk, but they are not equally visible forever. The index applies three decay rules:

1. **Visibility decay**: default queries (`list`, `search`, `reflect`) attenuate episodes older than 180 days by 50%
   in the ranker. `--include-old` disables the attenuation. Nothing is deleted.
2. **Superseded archival**: episodes with at least one inbound `supersedes` edge drop out of default queries entirely
   but remain reachable via `show` and `--include-superseded`.
3. **Tombstone semantics**: dropped sources (via `sase episodes drop`) leave a `.tombstone.json` so the same episode
   cannot be re-collected later; the tombstone is the forgetting record.

Hard deletion is reserved for retraction and is always explicit. Nothing decays to deletion silently. This matters
because the episode store will eventually be the longest-lived artifact in SASE, and silent decay would make
postmortems impossible.

The decay coefficients should be tunable via `~/.sase/episodes.yml` so different projects can move faster or slower
based on how quickly their code churns.

## Anti-Patterns

The following are the failure modes most likely to appear under implementation pressure. Naming them up front:

1. **"Just inject the top episode into every prompt."** This collapses the episodic/semantic boundary. Top-k episode
   injection should require an explicit `#episodes:<query>` directive, never an always-on prefix.
2. **"Write the lesson straight to `memory/long`."** This bypasses `sase memory review`. The collector must always
   round-trip through `create_memory_proposal()` so prompt-injection screens and human review apply.
3. **"Distill everything; we'll filter later."** This makes token spend grow with corpus size, and creates a review
   backlog that drowns useful signal. The importance scorer exists to prevent this.
4. **"Vector search first; FTS later."** This inverts the right ordering. FTS + structural ranker shipped first is
   cheap and debuggable; embeddings retro-fit cleanly when the trigger conditions hit.
5. **"Use full transcripts as distillation input."** This wastes tokens, multiplies prompt-injection surface, and
   defeats the redaction budget. Use head + tail + retry-delta only, capped at 16 KB.
6. **"Mutate episodes in place when we learn more."** This destroys audit. New information becomes a new episode
   linked via `supersedes`/`refutes`; the predecessor stays untouched.
7. **"Sync the SQLite index across machines."** Binary index sync invites corruption. Sync JSON only and rebuild.
8. **"One episode per chat file."** Retry chains, parent/child workflows, and forks would produce duplicate or
   conflicting episodes. The boundary rule (retry-chain root, workflow root, then transcript fallback) exists
   precisely to avoid this.
9. **"Branch on runtime."** Violates the uniform-runtime rule. All runtimes produce the same `done.json` schema;
   episodes never need a runtime switch.
10. **"Hide dismissed runs entirely."** Dismissal is a UI hint, not evidence deletion. The collector must still see
    dismissed bundles (opt-in via `--include-dismissed` in v1, default on in v2).
11. **"Auto-cleanup old episodes after N days."** The decay policy attenuates visibility; it does not delete. Deletion
    is always explicit. Auto-cleanup would conflict with multi-machine sync semantics.
12. **"Add an LLM judge for poison screening."** The deterministic `_PROMPT_INJECTION_PATTERNS` set is sufficient,
    cheap, and auditable. Adding an LLM judge introduces a new attack surface (the judge prompt) and a new failure
    mode (silent flakiness).

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
