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
    "contains_generated_claims": true
  }
}
```

Key rule: the episode can summarize and classify, but it must not replace the transcript. Every important claim needs a path back to the source chat or artifact.

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

1. Define `EpisodeWire` schema in `sase-core`.
2. Store canonical per-chat JSON sidecars under `~/.sase/projects/<project>/episodes/YYYYMM/`.
3. Add a rebuildable SQLite FTS index under `~/.sase/projects/<project>/episodes.sqlite`.
4. Generate episodes in the background after chat finalization and through an explicit backfill CLI.
5. Keep retrieval explicit at first through `sase episodes` and an agent skill.
6. Use generated episodes only as evidence for existing human-reviewed long-term memory proposals.

This is the highest-value version because it makes prior agent work discoverable without weakening SASE's current memory safety model.
