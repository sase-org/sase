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
  must be treated as a security-relevant state, not just helpful stored text.
  Sources: <https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/> and
  <https://owasp.org/www-project-agent-memory-guard/>

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

## Recommended Event Card Format

Use markdown with strict YAML frontmatter first. It is readable in code review, works with SDD conventions, and can be
indexed deterministically.

Recommended path:

```text
sdd/events/YYYYMM/<YYYYMMDD>-<slug>.md
```

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
- `temporal.superseded_by` lets search hide stale events by default while preserving history.

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
