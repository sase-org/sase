---
create_time: 2026-05-26
status: research
---

# Structured Episodic Events For `sase memory search`

## Question

Should SASE derive a select set of structured episodic memories into event files checked into
`sdd/events/`, then make those events queryable by agents through `sase memory search`? If it is worth doing, what
should the solution look like?

## Short Answer

Yes, but only as a **curated project event memory** layer, not as the primary store for every agent episode.

The useful distinction is:

- **Episode:** a raw or semi-structured record of one agent run, retry chain, workflow, incident, or research session.
  Episodes are evidence and can be numerous. Most belong in project state under `~/.sase/projects/<project>/...`, not
  in the repository.
- **Event:** a reviewed, repo-safe, durable project memory derived from one or more episodes. Events should be rare,
  source-linked, and meant to answer "what happened that future agents should be able to find?"

The idea is worth doing if `sdd/events/` contains a small number of high-signal event cards such as decisions,
incidents, migrations, repeated failure recoveries, benchmark results, and important research conclusions. It is not
worth doing if every completed chat creates a checked-in file, if event bodies are auto-injected into prompts, or if
events become a back door around `sase memory write/review`.

Recommended direction:

1. Keep broad episode collection private and rebuildable.
2. Add checked-in `sdd/events/YYYYMM/*.md` event cards only after review or explicit user request.
3. Make `sase memory search` the unified retrieval surface over `memory/long`, proposal metadata, and `sdd/events`.
4. Do not add a top-level `sase episodes` command. If collector verbs are needed, put them under
   `sase memory episodes ...`.
5. Treat events as search results, not instructions. Durable guidance still goes through `sase memory write/review`.

## Local Context

Current SASE memory already has the right safety primitives:

- `docs/memory.md` defines short-term memory as instruction context, long-term memory as keyword-gated reference
  context, and audited memory operations under project state.
- `src/sase/main/parser_memory.py` currently registers `sase memory init`, `list`, `read`, `write`, `review`, and
  `log`. There is no `search` subcommand in this checkout yet.
- `sase memory write` is proposal capture only. It writes project-scoped proposal state and never modifies
  `memory/long`.
- `sase memory review` is the human promotion gate. Agents cannot approve, edit-approve, or reject proposals when
  agent identity is present.
- `sase memory log --include proposals` already treats memory proposal/review records as auditable events.

SASE also already has a repo-backed event-log precedent:

- `sdd/beads/events/manifest.json` and `sdd/beads/events/streams/*.jsonl` are canonical bead event state.
- The bead event migration plan chose append-only, versioned event records in VCS, with generated compatibility
  projections.
- The `sase_beads` skill explicitly says version-controlled bead state lives in `sdd/beads/events/**` when present.

That precedent is relevant but should not be copied blindly. Bead events are operational state with strict reducer
semantics. Episodic event memories are curated evidence cards for retrieval and review. They need stronger privacy and
poisoning controls than bead updates because their source material may include untrusted transcript text, tool output,
web pages, and local file paths.

Existing research is directionally aligned:

- `structured_episodic_memory_for_agent_chats.md` recommends an evidence-first episode ledger and warns against
  automatic promotion into canonical memory.
- `structured_episodic_agent_chat_memory.md` recommends source-linked episode records, explicit retrieval, FTS first,
  and proposal-based promotion into `memory/long`.
- `sase_memory_command_research.md` ranks `sase memory search` as useful after inspectability commands, and recommends
  deterministic text/path search before vector search.
- `sase_memory_write_review_commands.md` establishes the proposal/review contract: agent writes are proposals; canonical
  memory changes require human review.
- `git_versioned_agent_memory.md` supports Git-versioned memory for curated project knowledge, but warns that raw agent
  observations create noise and need distillation.
- `multi_machine_sync.md` treats project-local `sdd/` state as project-VCS state, separate from global `~/.sase` sync.

## External Research Signals

The external literature supports an episode/event split.

LangGraph's memory docs distinguish short-term and long-term memory, then split long-term memory into semantic,
episodic, and procedural types. They also call out the choice between hot-path memory writes and background memory
writes. SASE should follow the background path for extraction and keep search explicit. Source:
<https://docs.langchain.com/oss/python/concepts/memory>

Generative Agents used a memory stream, reflection, and dynamic retrieval over experience records. The SASE-relevant
lesson is not simulation; it is the separation between observations, reflections, and retrieval. Source:
<https://arxiv.org/abs/2304.03442>

Reflexion stores verbal reflections in an episodic buffer after task feedback. That is directly relevant to failed then
successful SASE retry chains, but the reflections need evidence links and review if they become durable guidance.
Source: <https://arxiv.org/abs/2303.11366>

Letta separates always-in-context core memory from out-of-context archival memory accessed by tools. `sdd/events`
should behave more like archival/searchable memory than core prompt context. Source:
<https://docs.letta.com/guides/ade/archival-memory>

Mem0 reports substantial latency and token savings over full-context approaches by extracting, consolidating, and
retrieving salient memory rather than carrying entire histories forward. The practical lesson is to search compact
records, not paste old chats into prompts. Source: <https://arxiv.org/abs/2504.19413>

Zep/Graphiti argues for temporal memory that can reason over changing facts and historical relationships. SASE does not
need a graph database for v1, but events should record both `occurred_at` and `created_at`, and should support
`supersedes` links instead of silent rewrites. Source: <https://arxiv.org/abs/2501.13956>

Security research strongly argues against automatic persistent memory writes. OWASP's Agentic Top 10 identifies memory
and context poisoning as ASI06, and OWASP's May 2026 memory-poisoning note frames persistent memory as both feature and
attack surface. AgentPoison and MINJA show that poisoned memory/RAG stores can steer later agent behavior, including
without direct write access to the memory bank. Sources:
<https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/>,
<https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/>,
<https://arxiv.org/abs/2407.12784>,
<https://arxiv.org/abs/2503.03704>

For retrieval, SQLite FTS is enough to start. Alex Garcia's sqlite-vec hybrid search writeup shows that FTS5 and vector
search can be combined later with reciprocal-rank fusion in one SQLite-backed design. SASE should ship BM25/FTS plus
structured filters first, then add embeddings only after measured misses justify them. Source:
<https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html>

## Critique Of The `sdd/events` Idea

### What Is Strong

Checked-in events solve a real gap between raw transcripts and canonical memory:

- They are reviewable in normal Git diffs.
- They are shared with the project, unlike private `~/.sase` chat state.
- They can cite SDD plans, bead IDs, research files, commits, tests, and source paths in repo-relative form.
- They fit SASE's existing SDD model: decisions, incidents, migrations, and measurements are project artifacts.
- They let agents ask "what happened last time?" without treating the answer as a rule.

The "select set" qualifier is the key. A small curated event corpus could become one of SASE's more valuable memory
surfaces.

### What Is Weak Or Dangerous

The dangerous version is automatic repo writes from every episode. That would create:

- diff noise and merge churn;
- accidental commits of personal paths, customer data, secrets, or fetched malicious content;
- a memory-poisoning path where untrusted transcript text becomes persistent project context;
- ambiguous authority, because future agents may treat an event summary as instruction;
- stale facts that live forever unless invalidated.

The term `events` is also overloaded. SASE already has operational event logs such as `sdd/beads/events`. If
`sdd/events` is introduced, it should be documented as **project memory events**, not generic runtime events.

The command boundary also matters. A separate top-level `sase episodes` command would fracture the memory UX and
contradict the current consolidation around `sase memory`. The user's instinct to expose retrieval through
`sase memory search` is better.

### What This Adds Beyond `memory/long`

`memory/long` answers "what should future agents know or do?" Event memory answers "what happened, with what evidence?"

That distinction is worth preserving:

| Aspect | `memory/long` | `sdd/events` |
| --- | --- | --- |
| Memory kind | Semantic/procedural | Episodic |
| Authority | Can influence future behavior when dynamically loaded | Evidence to inspect through search |
| Write path | `sase memory write` proposal, then `review` approval | Event proposal/review or explicit user-authored SDD file |
| Source density | Short durable guidance | More context, evidence, timestamps, outcome |
| Failure mode | Bad instructions silently steer agents | Bad event misleads retrieval unless trust/citation is visible |

Events can propose `memory/long` entries later, but they should not replace that review gate.

## Recommended Event Scope

Do not store every chat. Store project-relevant events that will plausibly answer future questions.

Good event candidates:

- A design decision that changed architecture or command behavior.
- A failed approach that future agents are likely to repeat.
- A retry chain where the recovery teaches something specific.
- A migration with non-obvious compatibility rules.
- A benchmark or performance measurement with reproduction steps.
- A security/privacy incident or redaction decision.
- A research conclusion that changes the implementation path.
- A repeated gotcha seen in several episodes.

Poor event candidates:

- Routine implementation progress already captured by commits.
- "Agent X edited file Y" with no durable lesson or outcome.
- Full transcript summaries.
- Raw tool output, web content, or fetched issue text.
- Personal preference notes better suited for private memory.
- Any event whose source evidence is sensitive or cannot be cited safely.

## Storage Shape

Use one Markdown event card per curated event:

```text
sdd/events/
  README.md
  202605/
    evt_20260526_memory_events_7f3c91.md
```

Why Markdown plus YAML frontmatter:

- It reviews cleanly in Git.
- Humans can author and correct it without a special tool.
- `sase memory search` can parse the structured fields and index the body.
- It avoids monthly JSONL merge conflicts for human-authored cards.
- It keeps the door open to generated JSON/SQLite projections without checking them in.

Do not check in:

- raw chat text;
- generated embeddings;
- SQLite search indexes;
- absolute `~/.sase/...` paths;
- raw LLM extraction payloads;
- redacted source copies.

### Event Frontmatter

Recommended v1 frontmatter:

```yaml
---
schema_version: 1
event_id: evt_20260526_memory_events_7f3c91
event_type: decision # decision|incident|experiment|migration|gotcha|research_result|postmortem
occurred_at: 2026-05-26T00:00:00-04:00
created_at: 2026-05-26T00:00:00-04:00
status: active # active|superseded|retracted
project: sase
scope:
  repos: [sase]
  files:
    - src/sase/main/parser_memory.py
    - docs/memory.md
  beads: []
  changespecs: []
sources:
  sdd:
    - sdd/research/202605/structured_episodic_memory_for_agent_chats.md
  chats: []
  artifacts: []
  commits: []
keywords:
  - episodic memory
  - sase memory search
  - sdd/events
trust: reviewed # user_authored|reviewed|agent_proposed|generated
confidence: high # low|medium|high
privacy: repo_safe # repo_safe|private_project|local_only
supersedes: []
---
```

Body template:

```markdown
# Short Event Title

## Summary

What happened and why it matters.

## Evidence

Repo-relative links, chat IDs or basenames, artifact IDs, commit hashes, bead IDs, and research paths.

## Retrieval Notes

Queries or situations where this event should be found.

## Follow-Ups

Open actions, if any.
```

Keep source references stable and repo-safe. If a source lives only in `~/.sase/chats`, store a chat basename or hash,
not an absolute home path. If the source cannot be safely cited, the event probably should not be checked in.

## `sase memory search` Shape

`sase memory search` should be the agent-facing retrieval API. It should search multiple memory-backed sources while
preserving their types:

```bash
sase memory search "dynamic memory stale files"
sase memory search "retry chain recovery" --kind event
sase memory search --file src/sase/memory/dynamic.py --kind all --json
sase memory search --event-type incident --since 90d
```

Suggested result fields:

```json
{
  "kind": "event",
  "id": "evt_20260526_memory_events_7f3c91",
  "title": "Structured Episodic Events For Memory Search",
  "path": "sdd/events/202605/evt_20260526_memory_events_7f3c91.md",
  "score": 12.4,
  "matched_fields": ["keywords", "summary"],
  "event_type": "decision",
  "occurred_at": "2026-05-26T00:00:00-04:00",
  "trust": "reviewed",
  "confidence": "high",
  "sources": ["sdd/research/202605/structured_episodic_memory_for_agent_chats.md"]
}
```

Index sources in v1:

- `memory/long/*.md` and their frontmatter;
- `sdd/events/YYYYMM/*.md`;
- memory proposal metadata from the project ledger, optionally with `--include-proposals`;
- later, private episode records from `~/.sase/projects/<project>/episodes/` when explicitly requested.

Implementation guidance:

- Store the rebuildable index under project state, e.g. `~/.sase/projects/<project>/memory_search.sqlite`.
- Use SQLite FTS5/BM25 first.
- Add structural boosts for repo-relative file match, event type, recency, trust, confidence, and status.
- Exclude `status: superseded` and `status: retracted` by default unless `--include-superseded` is passed.
- Show `kind` and `trust` in every result so agents can avoid treating evidence as instruction.
- Do not inject top results into prompts automatically. Agents can search, inspect, and cite.

## Relationship To `sase memory episodes`

If SASE needs collection/backfill verbs, use nested commands:

```bash
sase memory episodes collect --dry-run --since 24h
sase memory episodes list --since 7d --json
sase memory episodes propose-events --importance-min 0.75
```

These commands should operate on private project state by default, not `sdd/events`. A later
`propose-events` step can create reviewable candidates for checked-in event cards.

Do not add `sase episodes`. Keeping this under `sase memory` communicates that episodes/events are one memory source,
not a parallel product surface.

## Event Promotion Workflow

The safest workflow has three layers:

```text
raw chats/artifacts
  -> private structured episodes
  -> reviewed sdd/events event cards
  -> optional memory/long proposals
```

Detailed flow:

1. A collector builds private episode records from `done.json`, `agent_meta.json`, chats, and artifacts.
2. A deterministic selector flags high-value episode clusters.
3. A distiller proposes event-card drafts, with source paths and injection/redaction flags.
4. A human or explicit review command approves a repo-safe event card under `sdd/events/YYYYMM/`.
5. If the event contains durable guidance, a separate `sase memory write` proposal is created with the event as
   evidence.
6. `sase memory review` remains the only route into `memory/long`.

The first version can skip steps 1-3 and let users/agents author event cards directly as SDD artifacts. Search value can
be proven before building automatic extraction.

## Security And Governance Requirements

Minimum requirements before generated events are allowed:

- Redact or reject secrets before event text is written.
- Reject `privacy: local_only` or `private_project` events from `sdd/events`; those belong in project state.
- Require repo-relative evidence or stable non-path IDs.
- Record `trust` and `confidence`.
- Detect prompt-injection-like text in proposed event bodies.
- Treat event bodies as untrusted evidence at retrieval time.
- Do not allow event search results to authorize tool calls.
- Do not let agents approve their own event proposals.
- Provide `status: retracted` and `supersedes` instead of deleting history silently.

Memory poisoning changes the risk posture. A bad event is not just a bad note; it is a future retrieval candidate. The
retrieval UI and JSON result shape must keep provenance visible.

## Alternatives

### Alternative 1: Do Nothing

Rely on `sase chats`, research files, commits, beads, and `memory/long`.

This is acceptable if `sase memory search` is only meant to search canonical memory. It fails if future agents need
source-linked answers to "what happened last time?" across incidents, retries, and migrations.

### Alternative 2: Put All Episodes In `sdd/events`

This maximizes shareability but is the wrong default. It would turn the repo into a transcript summary dump and create
privacy, poisoning, and review-burden problems.

Reject this.

### Alternative 3: Private Episodes Only

This matches earlier episode research and is safest. It misses the benefit of shared, code-reviewed, project-level
history. It also makes event knowledge unavailable to teammates and fresh clones unless they sync `~/.sase`.

Good as the base layer, incomplete as the whole solution.

### Alternative 4: Curated `sdd/events` Cards Plus Private Episodes

This is the recommended path. Broad extraction stays private; durable, repo-safe, high-signal events are promoted into
VCS.

### Alternative 5: Write Event Lessons Straight To `memory/long`

This collapses episodic and semantic memory. It bypasses the strongest safety boundary in the current design.

Reject this except through `sase memory write/review`.

## Evaluation Criteria

Do not evaluate by "did it create nice summaries?" Evaluate by retrieval and governance:

- For 20 real follow-up prompts, does `sase memory search --kind event` surface the event a human would want?
- Does precision@10 stay above 0.7 on a hand-built event query set?
- Do event cards cite repo-safe sources?
- Does the number of checked-in events stay low enough for review, roughly single digits per week on active projects?
- Do proposed events containing prompt-injection text fail validation or get flagged?
- Does `memory/long` growth remain review-gated and separate?
- Can a superseded event disappear from default search without being deleted?
- Can a new clone rebuild the search index from checked-in files only?

## Recommended Approach

Implement a narrow v1:

1. Add `sdd/events/README.md` documenting "project memory events" and the frontmatter/body schema.
2. Add support for parsing `sdd/events/YYYYMM/*.md` in a new `sase memory search` index.
3. Ship `sase memory search` over `memory/long` plus `sdd/events`, with `--kind`, `--file`, `--since`, `--json`, and
   `--reindex` or a separate `sase memory search --rebuild-index` flag.
4. Keep the index in project state and rebuild it from files. Do not check in SQLite or embeddings.
5. Seed the system manually with 3-5 high-quality events from recent research/incident/migration work.
6. Measure whether agents can find those events before adding automatic episode collection.

Then add private episodes:

1. Put collector verbs under `sase memory episodes ...`, not `sase episodes`.
2. Store broad episode records under `~/.sase/projects/<project>/episodes/`.
3. Let `sase memory episodes propose-events` draft `sdd/events` cards from only high-importance episodes.
4. Require review before writing to `sdd/events`.
5. Use approved event cards as evidence for `sase memory write` proposals when they contain durable semantic or
   procedural guidance.

This preserves the good part of the idea: shared, version-controlled, queryable memory of important project events. It
avoids the bad part: turning every agent transcript into trusted repo context.
