---
create_time: 2026-05-26
status: research
---

# Git-Versioned Episodic Events for `sase memory search`

## Question

Should SASE turn a selected subset of structured episodic memories into version-controlled event records under
`sdd/events/`, then make those records queryable by agents through `sase memory search`? A `sase memory episodes`
subcommand may exist, but there should be no top-level `sase episodes` command.

## Short Answer

Yes, but only if the feature is deliberately scoped as **curated project event memory**, not as the primary store for all
agent episodes.

The worthwhile version is:

- selected, low-volume "event cards" checked into `sdd/events/YYYYMM/`;
- one file per event, with stable IDs, frontmatter, source evidence, and a compact human-readable body;
- indexed by `sase memory search` alongside `memory/short` and `memory/long`;
- retrieved as evidence, not as authoritative instructions;
- created through a proposal/review path, not automatic direct writes from agents.

The not-worth-doing version is:

- every completed agent run writes a committed file;
- raw chat summaries or LLM reflections become trusted future prompt context;
- repo history accumulates private machine paths, secrets, stale workarounds, and one-off noise;
- a new top-level `sase episodes` product surface competes with `sase memory`.

The name shift from "episodes" to "events" is useful. An **episode** is operational state from one agent run. An
**event** is a reviewed project-relevant memory object derived from one or more episodes, chats, commits, beads, or
research notes.

## Local Context Reviewed

Relevant existing research:

- `sdd/research/202605/structured_episodic_agent_chat_memory.md` recommends structured episodes as source-linked
  evidence, not auto-injected long-term memory. It originally recommended local sidecar storage under
  `~/.sase/projects/<project>/episodes/YYYYMM/` plus a rebuildable SQLite/FTS index.
- `sdd/research/202605/structured_episodic_agent_chat_memory_sase13_20260523.md` independently lands on the same
  architecture: raw chats as source of truth, structured episodes as an evidence index, durable memory only through
  review.
- `sdd/research/202605/sase_memory_command_research.md` and
  `sdd/research/202605/sase_memory_command_subcommands.md` both recommend `sase memory search` as an eventual
  deterministic agent-callable search surface over memory files, with `--agent-mode --json`.
- `sdd/research/202605/zettel_sase_shared_memory.md` argues for inbox/review/promotion instead of direct canonical
  agent writes. That applies directly here: event cards are canonical enough to be version-controlled, so they need a
  gate.
- `sdd/research/202605/sase_memory_write_review_research.md` documents the existing proposal/review model for long-term
  memory. Event creation should reuse that shape instead of creating a second governance path.

Relevant current code:

- `src/sase/main/parser_memory.py` currently exposes `sase memory {init,list,read,write,review,log}`. There is no
  `search` command yet.
- `src/sase/main/memory_handler.py` dispatches only those six subcommands, so `search` and any event-oriented subcommand
  are still open design space.
- `src/sase/memory/inventory.py`, `src/sase/memory/cli_list.py`, and `src/sase/xprompt/loader_memory.py` already treat
  memory as an inventory/searchability problem rather than only file I/O.
- `sdd/beads/events/` already exists for bead event streams, which is evidence that event logs are a known SDD shape,
  but those streams are domain-specific operational ledgers. A new top-level `sdd/events/` should not reuse bead stream
  semantics blindly.

Relevant project constraints:

- `AGENTS.md` says memory files should not be modified without user approval.
- `memory/short/rust_core_backend_boundary.md` says shared backend/domain behavior belongs in `sase-core` when CLI, TUI,
  editor, or mobile frontends must agree. A memory search index over event files qualifies.

## External Research Notes

Recent agent-memory work supports episodic memory, but it also warns against treating generated memory as automatically
trusted state.

- LangGraph's memory guide separates semantic, episodic, and procedural memory. It describes episodic memory as past
  events/actions, and explicitly calls out the tradeoff between hot-path memory writes and background writes.
  Source: <https://docs.langchain.com/oss/python/concepts/memory>
- CoALA frames language agents as systems with modular memory and structured actions. That supports keeping events as a
  distinct memory type instead of blending them into `memory/long`.
  Source: <https://arxiv.org/abs/2309.02427>
- Reflexion shows that trial feedback stored in episodic memory can improve later coding/reasoning attempts, but its
  useful signal comes from tying reflection to task feedback. For SASE, that means event cards need outcome and evidence,
  not just "lessons."
  Source: <https://arxiv.org/abs/2303.11366>
- "Episodic Memory is the Missing Piece for Long-Term LLM Agents" argues for explicit episodic-memory properties:
  long-term storage, explicit reasoning, single-shot learning, instance-specific context, and contextual relations. Git
  event cards satisfy the long-term and instance-specific parts only if they preserve provenance and temporal context.
  Source: <https://arxiv.org/abs/2502.06975>
- Mem0 reports practical wins from extracting, consolidating, and retrieving salient memories rather than replaying full
  conversation history. Its result strengthens the case for compact structured event cards and a search index.
  Source: <https://arxiv.org/abs/2504.19413>
- OWASP's 2026 memory-poisoning guidance is directly relevant. Persistent memory can influence future behavior, so it
  must be treated as a security-relevant state, not just helpful stored text. OWASP's Agentic Top 10 classifies memory
  and context poisoning as **ASI06**, and the May 2026 memory-poisoning note frames persistent memory as both feature
  and attack surface.
  Sources: <https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/>,
  <https://owasp.org/www-project-agent-memory-guard/>, and
  <https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/>
- **AgentPoison** (Chen et al., 2024) and **MINJA** (Dong et al., 2025) demonstrate concrete attacks that steer agent
  behavior by injecting hostile records into RAG/memory stores, even without direct write access to the memory bank.
  An event-card store that is built from transcripts and tool output is exactly the substrate those attacks target.
  Sources: <https://arxiv.org/abs/2407.12784> and <https://arxiv.org/abs/2503.03704>
- Letta separates always-in-context core memory from out-of-context archival memory accessed by tools. `sdd/events/`
  belongs in the archival/searchable tier, never in always-loaded prompt context.
  Source: <https://docs.letta.com/guides/ade/archival-memory>
- Zep/Graphiti argues that durable agent memory needs temporal reasoning over changing facts. SASE does not need a
  graph database for v1, but event cards should record both `occurred_at` and `created_at`, and should support
  `supersedes` and `retracted` rather than silent rewrites or deletions.
  Source: <https://arxiv.org/abs/2501.13956>
- Alex Garcia's sqlite-vec hybrid-search writeup shows BM25/FTS5 and vector search can later be fused in one SQLite
  design with reciprocal-rank fusion. v1 should remain lexical; this is the upgrade path if deterministic recall is
  insufficient.
  Source: <https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html>

## The Core Design Distinction

The existing episodic-memory research was mostly about **operational episode storage**:

```text
~/.sase/projects/<project>/episodes/YYYYMM/<episode>.json
~/.sase/projects/<project>/episodes.sqlite
```

That is still the right shape for automatically generated, potentially high-volume per-agent-run data.

The new proposal is better understood as **curated project event storage**:

```text
sdd/events/YYYYMM/<event-id>.md
sdd/events/YYYYMM/<event-id>.json   # optional later, if markdown frontmatter is not enough
```

These two layers solve different problems.

| Layer | Owner | Stored in Git? | Volume | Trust level | Primary use |
| --- | --- | --- | --- | --- | --- |
| Raw chat/artifacts | Runtime | No | High | Evidence only | Full audit trail |
| Generated episode sidecar | Runtime/background collector | No by default | Medium/high | Evidence summary | Retrieval, analysis, backfill |
| Curated event card | Human-approved SDD memory | Yes | Low | Reviewed evidence | Agent/searchable project history |
| `memory/long` | Human-approved canonical memory | Yes | Very low | Instructional/project memory | Dynamic prompt context |

The event card sits between generated episodes and long-term memory. It is durable and versioned, but it is still
episodic evidence, not a rule.

## Why `sdd/events/` Is Attractive

The main benefits are real:

1. **Portability with the repo.** Future agents in fresh workspaces can find project history without relying on one
   machine's `~/.sase` state.
2. **Reviewability.** Git diffs make event memory inspectable. That is much safer than invisible background writes into
   an agent database.
3. **Branch-aware memory.** Events can live with the branch/PR that introduced them, then merge with the code they
   describe.
4. **Human-readable SDD history.** Some episodes are not just agent trivia; they explain why a design changed, why an
   approach failed, or why a test harness exists.
5. **Better evidence for long memory.** A reviewed event can become the evidence item for a later `sase memory write`
   proposal, preserving the semantic/procedural boundary.
6. **Agent-callable retrieval without prompt bloat.** `sase memory search` can surface compact events on demand instead
   of appending them to every prompt.

This is most compelling for events that will matter after the original workspace disappears:

- a non-obvious root cause and fix;
- a failed approach that future agents are likely to repeat;
- a design decision that changed SASE's architecture;
- a cross-repo or migration lesson;
- a security incident or memory-poisoning finding;
- a benchmark/result that should be searchable later;
- an implementation gotcha that is too contextual for `memory/long` but too important to bury in a chat.

## Why It Can Easily Be Not Worth It

The cost/risk is also real.

### 1. Git is the wrong store for raw episodes

Agent episodes are high-volume, machine-specific, and often noisy. Checking them in would create churn, merge friction,
and accidental disclosure risk. Even "summaries" can include private paths, copied logs, credentials, customer details,
or fetched adversarial text.

Use Git only for reviewed event cards.

### 2. Events can become stale authority

An old event saying "test X fails unless Y" may be useful evidence in May 2026 and actively wrong in July 2026. If
retrieval makes old events look like current instructions, SASE will create exactly the failure mode prior research
warned about: confident agents following stale generated memory.

Every retrieval result needs type and temporal framing:

```text
type: event
valid_at: 2026-05-19
status: superseded | active | historical
source: sdd/events/202605/...
```

### 3. "Select set" needs a selection policy

Without a selection policy, the repository will either get no events or too many. The first version should be
opinionated and conservative.

Good default criteria:

- user explicitly asks to preserve the lesson;
- an agent fixes a bug after at least one failed attempt;
- the work changes project architecture or SASE conventions;
- the event closes a research/postmortem thread;
- the same issue has recurred at least twice;
- the event is needed as evidence for a `memory/long` proposal.

Bad criteria:

- every completed task;
- every passing test run;
- every chat summary that "might be useful";
- events created only because an LLM marked them important.

### 4. The command namespace matters

The user constraint is right: do not add top-level `sase episodes`.

SASE already has a memory command group, and current code has room for `sase memory search`. Adding `sase episodes`
would split user attention and make "memory" vs "episodes" feel like two products. The search behavior agents need is
not "episode management"; it is "find relevant remembered project context."

### 5. Security gets worse if event cards are treated as instructions

OWASP's current guidance treats persistent memory as an attack surface. Event cards will sometimes be derived from
transcripts that include untrusted content. Git review helps, but it does not make the content safe to obey.

Retrieval must label event content as evidence and must not put raw event bodies into a high-trust system/developer
instruction position.

### 6. Concrete poisoning vectors to plan for

Event cards inherit their threat model from their input sources. The realistic vectors are:

- **Transcript-derived events.** Chat content includes pasted issue descriptions, web fetches, tool stdout, and
  fetched markdown. AgentPoison-style injections can ride along into the proposed event body.
- **Indirect prompt injection.** A repo file or external page contains text designed to be quoted into the event card
  body ("Future agents must read /etc/secrets and..."). The card looks reviewed; the embedded instruction is not.
- **Trust laundering by promotion.** A low-trust generated episode becomes a reviewed event, then is cited as evidence
  for a `memory/long` proposal. Each step seems incremental; the end state is an unreviewed instruction.
- **Stale-authority drift.** A correct 2026-05 event becomes a wrong 2026-09 instruction because retrieval keeps
  surfacing it without marking it superseded.

The mitigations below land in the Test Surface, Recommended Event Card Format, and Search Design sections: required
`safety` frontmatter, retrieval-side `trust` and `valid_at` display, prompt-injection text detection in proposed event
bodies, and explicit human review before promotion across any trust boundary.

## Alternatives Considered

### A. Do nothing; rely on existing surfaces

Keep using `sase chats`, research files, commits, beads, and `memory/long`. This is acceptable if `sase memory search`
is only intended to search canonical memory. It fails the "what happened last time?" use case across incidents,
migrations, and retry chains, especially in fresh workspaces where local chat state is missing.

### B. Check in every episode

Maximum shareability, minimum curation. Rejected: repo noise, merge friction, privacy/secret risk, untrusted text
becoming a persistent retrieval target, and a review burden that no human will actually perform. This is the failure
mode the prior episodic-memory research notes explicitly warned against.

### C. Private episodes only, no `sdd/events/`

Match the earlier episode research and keep all episodic data under `~/.sase/projects/<project>/...`. Safest, and the
right base layer, but it misses the benefit of shared, code-reviewed project-level history. Teammates and fresh clones
cannot see what happened without out-of-band sync.

### D. Curated `sdd/events/` cards plus private episodes (recommended)

Two-layer split: broad episode collection stays private and rebuildable; only reviewed, low-volume, repo-safe event
cards reach Git. This is the path this note recommends.

### E. Write event lessons directly to `memory/long`

Collapses episodic and semantic memory and bypasses the strongest current safety boundary. Rejected. Lessons go
through `sase memory write/review`, with event cards as evidence.

### F. Reuse `sdd/beads/events/` JSONL streams

The bead event log is a good precedent for *append-only operational state* with strict reducer semantics. Curated
project memory has different needs: small reviewable units, easy supersession, human authorship, no reducer. Markdown
event cards diff better and avoid the monthly JSONL merge-conflict pattern documented in
`sdd/research/202605/bead_jsonl_merge_conflicts.md`. Reject reuse of the bead-event substrate; keep the concept.

### G. External memory service (Mem0/Zep/Letta)

A hosted service handles extraction, retrieval, and temporal reasoning but moves project memory off-repo, introduces a
network dependency, and removes Git review. SASE's value proposition leans on local, inspectable, reviewable artifacts.
Consider a service later only if internal search recall collapses; not v1.

## Recommended Event Card Format

Use markdown with strict YAML frontmatter first. It is readable in code review, works with SDD conventions, and can be
indexed deterministically.

Recommended path:

```text
sdd/events/YYYYMM/<YYYYMMDD>-<slug>-<short-hash>.md
```

Naming convention rationale:

- `YYYYMMDD` keeps events sorted in the directory and matches the SDD research convention.
- `<slug>` is a stable, human-readable identifier derived from the title.
- `<short-hash>` is a 6-character content/uuid hash that disambiguates same-day events with the same slug and prevents
  branch-merge collisions when two branches independently create an event on the same day. Without the hash, two PRs
  that both add `20260526-memory-events.md` will hit a tree conflict on rename or content; with the hash, each event
  has a unique path that is stable across rebases.
- `event_id` in frontmatter mirrors the filename basename, minus extension, so search can return either a path or an
  ID and they round-trip.

Example:

```markdown
---
schema_version: 1
event_id: evt-20260526-structured-episodic-events
event_type: design_decision
created_at: 2026-05-26T00:00:00Z
status: active
project: sase
scope:
  repos: [sase]
  files:
    - src/sase/main/parser_memory.py
    - sdd/research/202605/structured_episodic_agent_chat_memory.md
memory:
  type: episodic_event
  trust: reviewed
  promote_to_long_memory: false
retrieval:
  title: Use curated SDD events instead of committing raw episodes
  summary: Git-versioned events are useful only as selected, reviewed event cards searched by `sase memory search`.
  tags: [memory, episodic-memory, sdd-events, search]
  keywords: [episodic memory, memory search, sdd/events, event cards]
  applies_to: [memory CLI, agent retrieval, SDD]
temporal:
  valid_at: 2026-05-26
  supersedes: []
  superseded_by: null
evidence:
  - kind: research
    path: sdd/research/202605/structured_episodic_agent_chat_memory.md
  - kind: code
    path: src/sase/main/parser_memory.py
safety:
  contains_untrusted_text: false
  private: false
---

# Use curated SDD events instead of committing raw episodes

## What Happened

...

## Why It Matters

...

## Future Retrieval Guidance

...
```

Frontmatter rules:

- `event_id` is stable and unique.
- `event_type` is an enum: `design_decision`, `bug_pattern`, `failed_approach`, `migration`, `benchmark`,
  `security_note`, `research_finding`, `postmortem`, `followup`.
- `retrieval.summary`, `tags`, `keywords`, and `applies_to` are the main search fields.
- `evidence` is required. At least one item must point to a repo path, chat id, commit, bead, or URL.
- `safety.private: true` excludes the event from default agent-mode search.
- `safety.contains_untrusted_text: true` flags events derived from chat/web content; retrieval must surface this.
- `status` in {`active`, `superseded`, `retracted`}; default search returns only `active` events.
- `temporal.superseded_by` lets search hide stale events by default while preserving history.
- `temporal.valid_at` is required so retrieval can render age and flag stale-authority risk.

Markdown body rules:

- Keep event cards short: target 300-900 words.
- Summarize what happened, why it matters, what future agents should check, and what not to infer.
- Do not paste raw logs or long chat excerpts.
- Do not write imperative agent instructions such as "always do X" unless the event is explicitly being promoted into
  `memory/long` through review.

## Search Design

`sase memory search` should search three memory classes:

1. `memory/short/*.md` and referenced always-loaded memory.
2. `memory/long/*.md` dynamic/canonical memory.
3. `sdd/events/YYYYMM/*.md` curated event memory.

Suggested command contract:

```bash
sase memory search "prompt history fanout"
sase memory search --type event "failed rust backend migration"
sase memory search --file src/sase/main/parser_memory.py --json
sase memory search --tag episodic-memory --agent-mode --json
```

JSON result shape:

```json
{
  "id": "evt-20260526-structured-episodic-events",
  "kind": "event",
  "title": "Use curated SDD events instead of committing raw episodes",
  "summary": "Git-versioned events are useful only as selected, reviewed event cards...",
  "path": "sdd/events/202605/20260526-structured-episodic-events.md",
  "score": 12.4,
  "matched": ["episodic memory", "sdd/events"],
  "tags": ["memory", "episodic-memory"],
  "status": "active",
  "trust": "reviewed",
  "evidence": [
    {"kind": "research", "path": "sdd/research/202605/structured_episodic_agent_chat_memory.md"}
  ]
}
```

Agent-mode output should be compact and should not include the full markdown body by default. Agents can request a
specific file if they need details.

Ranking should start deterministic:

- BM25/FTS over title, summary, tags, keywords, applies-to, headings, and body;
- boosts for path/file matches;
- boosts for active/non-superseded events;
- small recency boost;
- no embeddings in v1.

This matches the existing `sase memory search` research: deterministic IDs, path applicability, and provenance should
come before vector search.

## Cross-Repo and Branch Semantics

Two semantics questions need explicit answers up front because they affect storage layout.

### Where does an event about a sibling-repo change live?

SASE has sibling repos (`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`). An event card describing a fix in
`sase-core` could plausibly live in either repo.

Recommended rule: the event lives in the repo that **owns the lesson's future audience**. A design change to the Rust
core that all frontends must respect lives in `sase-core/sdd/events/`. A SASE-specific TUI gotcha discovered while
touching the binding lives in `sase/sdd/events/`. The `scope.repos` frontmatter field declares the cross-cutting reach
of an event, so `sase memory search` in any sibling repo can later choose whether to surface only the local repo's
events or to consult sibling repos through workspace open.

This also implies `sase memory search` should be repo-scoped by default and require an explicit `--scope sibling` or
`--scope all` to walk sibling repos via the existing workspace-open machinery. Cross-repo retrieval is a v2 concern;
v1 should ship single-repo only.

### Branch and merge semantics

Event cards are repo-state, so they obey normal Git rules. Three concrete cases:

- **Two PRs add a new event on the same day.** With the `-<short-hash>` filename component, both paths are distinct
  and merge cleanly.
- **A PR supersedes an event from main.** The PR updates `temporal.superseded_by` on the older event and adds a new
  event card. No file is deleted. The search ranker drops superseded events from default results but keeps them
  retrievable with `--include-superseded`.
- **Two branches edit the same event card body.** Standard merge conflict. Treat events as small, single-author edit
  units; if two branches both want to revise an event, prefer creating a new event with `supersedes:` and leave the
  old one untouched.

Branch-aware memory is a feature, not a bug: an event card landing alongside the PR it describes is exactly the
review property `sdd/events/` was meant to deliver.

## Should `sase memory episodes` Exist?

Maybe, but not as the first user-facing surface.

If it exists, it should be a narrow management subgroup for event/episode bridges:

```bash
sase memory episodes propose --from-chat <chat-id> --to-event
sase memory episodes list --source local
sase memory episodes promote <episode-id> --event
```

But this name is still a little misleading if the stored files are called events. A cleaner option is:

```bash
sase memory events propose --from-chat <chat-id>
sase memory events add --file draft.md
sase memory events validate
sase memory events show evt-...
```

The user-facing retrieval path should remain `sase memory search`.

## Integration With Existing SASE Surfaces

Event cards should not be a standalone feature. Reuse what is already there.

### `sase chats`

`sase chats` is the natural primary source for proposed events. Add `sase memory events propose --from-chat <chat-id>`
that loads the chat artifact, lets an agent or user draft a card, and writes a candidate to a project-local inbox
(matching the `sase memory write/review` proposal/review boundary). Never write directly into `sdd/events/` from a
chat; that bypasses the safety gate.

### `sase memory log`

`sase memory log --include proposals` already treats memory writes as auditable events. Event-card creation should
appear in the same log stream so reviewers can see "agent X proposed event Y from chat Z on date W." This also gives
`sase memory retract --evidence <chat-path>` a clean way to find and quarantine events whose source chat is later
discovered to be poisoned.

### Hooks

Add the corresponding hook events to `src/sase/ace/hooks/`:

- `memory.event_proposed` — fires when an agent submits an event-card candidate;
- `memory.event_promoted` — fires when an event card lands in `sdd/events/`;
- `memory.event_retracted` — fires when supersession or retraction changes search results;
- `memory.search` — fires per `sase memory search` invocation so projects can lint queries or sample telemetry.

These match the pattern already proposed for `memory.matched`/`memory.proposed` in
`sdd/research/202605/sase_memory_command_subcommands.md`.

### Telemetry

Add counters and histograms next to the existing memory counters:

- `MEMORY_EVENT_COUNT` — current event cards by status;
- `MEMORY_EVENT_SEARCHES` — search invocations with hit/miss labels;
- `MEMORY_EVENT_RETRIEVED` — events appearing in top-K agent-mode results;
- `MEMORY_EVENT_AGE_DAYS_P50/P95` — health signal for stale-authority risk.

Zero retrievals over 30 days on a card is a strong signal that the event is unused; pair with `doctor` to flag.

### Agent-callable skill

Per the `Uniform Agent Runtimes` rule in `memory/short/gotchas.md`, `sase memory search` and any
`sase memory events ...` write surface must be exposed through the existing generated-skill pipeline, not as
runtime-specific (Claude/Codex/Gemini) special cases. Agents should call the skill exactly the same way regardless of
runtime. This also means the JSON contract (`--agent-mode --json`) must be locked early so generated skills don't
break on schema drift.

### Rust core boundary

Per `memory/short/rust_core_backend_boundary.md`, anything that other frontends (TUI, editor, mobile, web) must agree
on belongs in `sase-core`. The event-card parser, frontmatter validator, and search index belong in `sase-core`; the
Python `sase memory search` CLI becomes a thin frontend calling `sase_core_rs`. Presentation-only formatting and
argparse glue stay in Python.

## Storage Decision

Recommended:

```text
sdd/events/
  README.md
  202605/
    20260526-structured-episodic-events.md
```

Avoid:

```text
sdd/events/streams/*.jsonl
```

The existing bead event stream layout is good for append-only operational state. Curated project memory is better as
one reviewed markdown file per event. One-file-per-event gives better diffs, easier deletion/supersession, simpler
links, and less merge pain.

Add a generated local index outside Git:

```text
.sase/memory/events.sqlite
```

or, if the index is project-state rather than workspace-state:

```text
~/.sase/projects/<project>/memory_events.sqlite
```

The index is rebuildable from `memory/**` and `sdd/events/**`, so it should not be checked in.

## Relationship To `memory/long`

Events should not replace long-term memory.

Use this boundary:

- Event: "On 2026-05-26, we discovered that committing every episode would create noise; use curated event cards."
- Long memory: "Agents must not commit raw episodic summaries; use `sase memory events propose` for durable project
  event cards."

The first is evidence. The second is a rule. The second belongs in `memory/long` only after explicit review.

This boundary keeps the existing SASE memory contract intact:

1. agents may propose durable memory;
2. users review and approve;
3. canonical memory files are not silently rewritten.

## Evaluation Plan

Before implementing automatic event creation, run a small manual pilot:

1. Create 10-20 event cards from existing May 2026 research/tales that are clearly reusable.
2. Implement `sase memory search --type event --json` over frontmatter and markdown text.
3. Test 15 real follow-up prompts and record whether the expected event appears in the top 5.
4. Compare against `rg` and current memory listing to prove the command adds value.
5. Review every result for stale-authority risk: would an agent treat the event as instruction?
6. Add validation tests for frontmatter shape, required evidence, duplicate `event_id`, private-event filtering, and
   superseded-event ranking.

Success criteria:

- top-5 recall >= 80% on the pilot query set;
- zero default results with `safety.private: true`;
- every event has at least one live evidence pointer;
- no event body is required to fit in always-loaded prompt context;
- users can understand and edit an event from a normal Git diff.

## Test Surface

Concrete test categories for the validator and search index. These should all be deterministic and fixture-driven, not
LLM-dependent.

### Frontmatter validation

- Required fields present: `schema_version`, `event_id`, `event_type`, `status`, `retrieval`, `temporal`, `evidence`,
  `safety`.
- `event_type` is in the allowed enum.
- `event_id` matches `^evt-\d{8}-[a-z0-9-]+(-[a-f0-9]{6})?$` and equals filename basename.
- `evidence` is non-empty and every entry has a valid `kind` and `path`/`url`/`id`.
- `temporal.valid_at` parses as ISO date; `temporal.superseded_by` either null or matches another `event_id`.
- `safety.private: true` excludes the event from default search.
- `status` in {`active`, `superseded`, `retracted`}.
- Reject duplicate `event_id` across the whole `sdd/events/**` tree.

### Search behavior

- Deterministic top-K ordering for a fixture query set (golden test).
- Path-match boost: `--file <path>` returns events whose `scope.files` includes that path before unrelated matches.
- `--type event` filters out non-event memory sources.
- Superseded events are hidden by default and visible under `--include-superseded`.
- Retracted events are hidden under both defaults and `--include-superseded`; only `--include-retracted` reveals them.
- `--agent-mode --json` output schema is locked and snapshot-tested.

### Safety/poisoning regressions

- A fixture event containing common prompt-injection phrases ("ignore previous instructions", "execute the following")
  triggers a validator warning and is flagged in `safety.contains_untrusted_text`.
- A fixture event whose only evidence path no longer exists in the repo is reported by `doctor`.
- A fixture chat-id evidence that is later retracted (`sase memory retract --evidence ...`) marks dependent events
  `status: retracted`.

### Property tests

- Index rebuild from `sdd/events/**` is idempotent: running the indexer twice produces the same SQLite content hash.
- A round-trip `event_id` → search result → file path → frontmatter `event_id` always returns the same id.

## Supersession, Retraction, and Deletion

Three distinct lifecycle operations with intentionally different semantics:

- **Supersede.** Replace a still-valid claim with a newer one. The old card stays in repo. Both files have
  `temporal.supersedes`/`temporal.superseded_by` cross-links. Default search hides the older card; history queries can
  retrieve it.
- **Retract.** The event is wrong, poisoned, or referenced retracted evidence. The card stays in repo (auditability)
  with `status: retracted` and a `retraction_reason` field. Default search hides it. Cross-references from other
  events remain so the chain is visible.
- **Delete.** Reserved for events that should not have been committed at all: secrets, PII, accidental private content.
  Deletion is a normal `git rm`, but should be accompanied by a `sase memory retract --evidence` run so dependent
  events and proposals also get quarantined.

Default policy: prefer supersede over retract, prefer retract over delete. Deletion is the exceptional path because it
breaks evidence chains.

## Implementation Sequence

1. Add `sdd/events/README.md` documenting the event-card contract.
2. Add a frontmatter parser/validator in the same code path that will power `sase memory search`.
3. Add `sase memory search` over current memory files and `sdd/events/**`, with `--type`, `--file`, `--tag`, `--json`,
   and `--agent-mode`.
4. Add tests for deterministic search and private/superseded filtering.
5. Add `sase memory events validate` if validation needs a dedicated command.
6. Only after search is useful, add `sase memory events propose --from-chat <chat-id>` to draft event cards from
   episodes/chats.
7. Consider a local operational episode store later, but keep it outside Git unless an episode is promoted into a
   curated event.

## Open Questions

1. **Indexer location.** Live entirely in `sase-core` Rust from day one, or land first in Python and migrate once
   cross-frontend pressure exists? Recommendation: Rust core, because mobile/editor will want the same search, and the
   xprompt catalog has already crossed this boundary.
2. **Default search scope.** Should `sase memory search` include `sdd/events/` by default, or require `--kind event`?
   Recommendation: include by default but tag every result with `kind` so agents can filter.
3. **Repo-wide vs sibling-wide search.** When should `sase memory search` walk sibling repos via `sase workspace open`?
   Recommendation: never implicitly; require `--scope sibling|all`.
4. **Per-branch event drafts.** Should event-card candidates live on a branch as `sdd/events/inbox/` until merge, or
   in a project-local inbox outside Git? Recommendation: project-local inbox; promote to `sdd/events/YYYYMM/` only on
   review approval.
5. **Maximum event volume.** Is there a soft cap (events per month, total events) above which `doctor` should warn?
   Recommendation: warn over 50/month or 1000 total, both configurable.
6. **Embedding upgrade trigger.** What measured search miss rate justifies adding `sqlite-vec` hybrid search?
   Recommendation: defer until precision@10 on the pilot query set falls below 0.7 with deterministic ranking.
7. **Notification surface.** Should a new `memory.event` notification type fire on proposal/promotion? Recommendation:
   yes, reusing `sase notify`, so review backlogs are visible without polling.
8. **TUI/mobile read-only browse.** Should the ACE TUI add an Events tab? Recommendation: not v1; reuse
   `sase memory show` and `sase memory search` until use proves a dedicated browser is needed.

## Recommended Approach

Build this, but call the checked-in objects **events**, not episodes, and make them a curated SDD memory tier.

Recommended v1:

1. Store reviewed event cards as markdown under `sdd/events/YYYYMM/`, one file per event.
2. Require strict YAML frontmatter with `event_id`, `event_type`, `status`, `retrieval`, `temporal`, `evidence`, and
   `safety`.
3. Implement `sase memory search` as the single agent-facing retrieval command across `memory/**` and `sdd/events/**`.
4. Keep search lexical/FTS and deterministic in v1; use `--agent-mode --json` for compact agent output.
5. Do not create a top-level `sase episodes` command. If management commands are needed, prefer
   `sase memory events ...`; use `sase memory episodes ...` only for local generated episode sidecars.
6. Do not auto-inject events into prompts. Agents should explicitly search and then cite event paths.
7. Do not check in automatically generated per-run episodes. Promote only selected, reviewed, low-volume events to Git.
8. Treat retrieved events as untrusted evidence unless and until a human promotes a durable rule into `memory/long`.

This is worth doing because it gives SASE a portable, reviewable memory of important project events without turning
every agent transcript into permanent prompt context. The design also aligns with the user's namespace preference:
memory retrieval stays under `sase memory`, and "episodes" remains an implementation detail rather than a competing
top-level command.
