---
create_time: 2026-05-23
status: research
---

# Dream Chop Agent Chat Distillation

## Question

What is the best way to implement a SASE "dream" chop that distills agent chats into summaries with a recency gradient:
recent activity stays detailed, older activity becomes increasingly compressed, and durable lessons can feed future
memory?

The user's initial sketch was a set of sections for `4 hours`, `24 hours`, `1 day`, `7 days`, `1 month`, `6 months`,
and `3 years`. This research treats those as a useful intuition, not as fixed requirements.

Related local research:

- [`sdd/research/202605/sase_dreams_design.md`](sase_dreams_design.md) — prior dreams architecture
- [`sdd/research/202605/zettel_sase_shared_memory.md`](zettel_sase_shared_memory.md) — atomic-note model and promotion gate
- [`sdd/research/202605/sase_memory_command_research.md`](sase_memory_command_research.md) — memory observability commands
- [`sdd/research/202605/sase_memory_command_subcommands.md`](sase_memory_command_subcommands.md) — CLI verbs for memory I/O
- [`sdd/research/202605/multi_machine_sync.md`](multi_machine_sync.md) — per-domain sync classes for `~/.sase`
- [`sdd/research/202605/manus_vs_sase_lessons.md`](manus_vs_sase_lessons.md) — background-memory lessons from competing systems

## Relationship To Prior Dreams Research

[`sase_dreams_design.md`](sase_dreams_design.md) already established the substrate: `~/.sase/dreams/` layout, NREM/REM-style staged distillation, artifact-first discovery via `done.json`, checkpoint via `state.json`, and inbox-only writes guarded by provenance. This note does **not** restate that design. It adds the pieces that file is intentionally light on:

- Time-band rollup semantics and the "do not repeat across bands" rule.
- An importance/decay score so the filter can be tuned rather than hand-coded.
- An on-demand reflect/search agent so old detail stays reachable without bloating context.
- A concrete `sase dreams` CLI surface aligned with the planned [`sase memory`](sase_memory_command_subcommands.md) verbs.
- Multi-machine sync behavior consistent with [`multi_machine_sync.md`](multi_machine_sync.md).
- Failure-mode and schema-migration handling for `state.json` and rollups.
- TUI review surface for the inbox so the promotion gate has a real interface.

Where this note disagrees with the prior file, the disagreement is explicit and called out inline.

## Recommendation

Build the dream chop as a **rolling distillation pipeline**, not as a single markdown summary that is regenerated from
all old chats.

The key design should be:

1. Keep raw chat transcripts and completed-run artifacts as immutable episodic evidence.
2. Distill coherent work episodes into compact "episode cards" with provenance.
3. Roll episode cards into time-banded and workstream-banded summaries.
4. Propose durable memory candidates into an inbox, but do not write directly to `memory/short` or `memory/long`.
5. Keep a reflect/search escape hatch so old details remain reachable without staying in prompt context.

For the time bands, use a smaller and less redundant default set than the initial sketch:

| Band | Purpose | Default detail target |
| --- | --- | --- |
| Hot: last 4 hours | Current working context and handoff details | Full episode cards, newest first |
| Warm: last 24 hours | What changed today, blockers, decisions, files touched | Detailed daily rollup |
| Recent: last 7 days | Workstream outcomes and recurring issues | Per-project/per-CL summaries |
| Medium: last 30 days | Important decisions, conventions, unresolved threads | Theme rollup |
| Long: last 6 months | Durable architecture/process patterns | Sparse index plus memory candidates |
| Archive: older | Searchable evidence only | No default loading; reflect/search path |

Do not include both `24 hours` and `1 day`; they are the same operational window. Do not make `3 years` a default
loaded section for SASE v1. For multi-year history, keep searchable source and curated durable memories, not a giant
evergreen rollup.

The implementation should make time bands **materialized views** over a more stable episode store. The source of truth
is not "the 7-day section"; it is a set of episode distillations plus rollup manifests that record which source
episodes each rollup covers. That prevents duplicate facts from being re-summarized differently at each horizon.

## Why Fixed Time Sections Are Not Enough

Time-gradient memory is the right shape, but fixed calendar buckets alone are a weak organizer for SASE.

SASE work naturally clusters around:

- root agent/workflow entries;
- retry chains;
- ChangeSpecs, beads, plans, legends, and epics;
- project/workspace boundaries;
- prompt-step artifacts such as plans, questions, diffs, and generated files.

A "last 7 days" section can contain unrelated work from five projects, while a single important retry chain may span
two calendar windows. If the dream chop summarizes only by time, it will either mix unrelated topics or duplicate the
same fact in every age bucket.

The better model is two-dimensional:

- **Episode/workstream axis:** what happened and what it belongs to.
- **Recency/detail axis:** how much detail should remain visible by default.

Time bands are still useful as query and display views. They should not be the primary identity of a memory item.

## Local Context

The previous dreams research already found the relevant SASE primitives:

- `src/sase/history/chat.py` writes chat transcripts under `~/.sase/chats/YYYYMM/*.md`.
- `src/sase/history/chat_catalog.py` can list and resolve sharded chat files.
- Completed agent artifacts under `~/.sase/projects/*/artifacts/ace-run/*/done.json` are a richer primary index than
  raw chat files because they link `response_path`, `diff_path`, `plan_path`, outcomes, project/workspace metadata,
  agent names, and retry-chain fields.
- AXE lumberjacks and chops already provide the scheduling substrate. `src/sase/axe/config.py` supports per-chop
  `run_every`, `timeout`, `env`, and agent chops via the `agent`/`xprompt` field.
- `src/sase/axe/chop_runner.py` already dedupes live script chops and agent chops and records run history.
- Dynamic memory already projects `memory/long/*.md` into `.sase/memory/` based on prompt keyword matches.

That means the dream system should not invent a separate daemon or a separate canonical memory mechanism. It should use
AXE to schedule work, use artifact-first discovery to avoid scanning every transcript every time, and produce reviewable
outputs that can later feed existing dynamic memory.

## External Prior Art

### Sanity Nuum

The Sanity article ["How we solved the agent memory problem"](https://www.sanity.io/blog/how-we-solved-the-agent-memory-problem)
is the best match for the user's idea. Nuum separates memory into:

- raw temporal history;
- distilled compressed history;
- long-term knowledge curated separately.

The most useful ideas to borrow:

- A background distillation worker compresses older messages when context pressure rises.
- It finds coherent conversation segments before summarizing, instead of compressing arbitrary token spans.
- Each segment produces two outputs: short operational narrative and retained facts.
- Distillations can be recursively distilled into meta-distillations.
- A separate reflection/search agent can drill into the raw history when precise details are needed.

The most important adaptation for SASE: Nuum is optimizing one long-running agent's context window. SASE has many agent
runs and completed artifacts, so the natural segment boundary is usually an agent episode or retry chain, not a raw
message range.

### Letta And Sleep-Time Compute

Letta's sleep-time compute work argues for moving reasoning about persistent context into asynchronous background work.
The Letta blog frames this as transforming raw context into learned context during idle time, and the paper reports
roughly 5x lower test-time compute for the same accuracy on their stateful tasks, plus benefits when multiple future
queries reuse the same context:

- [Letta sleep-time compute blog](https://www.letta.com/blog/sleep-time-compute)
- [Sleep-time Compute: Beyond Inference Scaling at Test-time](https://arxiv.org/abs/2504.13171)

The useful SASE lesson is not "always run more background LLM calls." It is: background work pays off only when the
result is likely to be reused. Dream outputs should therefore include **anticipated questions** and retrieval keywords,
so dynamic memory can later decide whether a distilled item is actually relevant.

Letta also separates the primary agent from the sleep-time memory agent. That maps well to SASE: normal coding agents
should not block on memory work, and dream agents should be hidden/background agents with a narrower contract.

### LangGraph Memory Types

LangGraph's current memory overview splits memory by scope and type: short-term thread state versus long-term memory,
and semantic, episodic, and procedural memory types. It also explicitly calls out hot-path versus background memory
writes:

- [LangGraph memory overview](https://docs.langchain.com/oss/python/concepts/memory)

The SASE mapping:

- Raw chats and `done.json` records are **episodic** memory.
- Distilled decisions, conventions, gotchas, and user preferences are **semantic** memory candidates.
- Agent instructions, skills, and workflow rules are **procedural** memory and need stricter promotion.

This distinction matters because a dream chop should not turn every episode into a rule. Most episodes should remain
evidence. Only repeated, high-confidence, or user-confirmed patterns should become semantic or procedural memory.

### Zep And Temporal Knowledge Graphs

Zep's memory docs and paper emphasize adding chat history continuously, building a user-level graph, retrieving
relevant context, and combining long-term context with the last few raw messages:

- [Zep Memory API docs](https://help.getzep.com/v2/memory)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)

The lesson for SASE is temporal validity and source granularity. Dream outputs should record when a fact was learned,
what evidence supports it, and when it appears superseded. A flat markdown paragraph without source IDs will be hard to
retract or update.

SASE does not need to adopt a graph database in v1. It can get most of the benefit by storing structured metadata in
JSON manifests alongside markdown rollups.

### Reflexion, Generative Agents, MemGPT, And A-MEM

Several older and adjacent systems reinforce the same pattern:

- [Reflexion](https://arxiv.org/abs/2303.11366) stores verbal reflections in episodic memory so later attempts can
  improve without model fine-tuning. For SASE, failed-then-succeeded retry chains are prime dream material.
- [Generative Agents](https://arxiv.org/abs/2304.03442) store experiences, synthesize higher-level reflections, and
  retrieve them dynamically. For SASE, the reflection trigger should be deterministic and budgeted.
- [MemGPT](https://arxiv.org/abs/2310.08560) models LLM context as a hierarchy with paging between limited context and
  larger stores. For SASE, raw chats stay in slow storage; only distilled, relevant projections enter prompts.
- [A-MEM](https://arxiv.org/abs/2502.12110) applies Zettelkasten-like atomic notes, structured attributes, dynamic
  linking, and memory evolution. For SASE, adopt atomic proposed notes and links, but use append-and-supersede instead
  of silent in-place mutation.

### Recent Cautions

Two 2026 results are especially relevant because they argue against naive continuous consolidation:

- [Useful Memories Become Faulty When Continuously Updated by LLMs](https://arxiv.org/abs/2605.12978) reports that
  consolidation itself can degrade memory utility and recommends preserving raw episodes as first-class evidence.
- [When Stored Evidence Stops Being Usable](https://arxiv.org/abs/2605.07313) evaluates memory as irrelevant sessions
  accumulate and finds that usable reliability depends on agent, interface, scale range, and interaction budget.

These both support a conservative dream architecture: preserve raw evidence, gate consolidation, measure retrieval
quality, and avoid repeatedly rewriting the same memory in place.

Security research also makes automatic promotion dangerous:

- OWASP's 2026 memory/context poisoning discussion treats persistent memory as part of the attack surface:
  [Memory Is a Feature. It Is Also an Attack Surface](https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/).
- [MINJA](https://arxiv.org/abs/2503.03704) shows memory injection via query-only interaction.
- [MemoryGraft](https://arxiv.org/abs/2512.16962) shows poisoned successful experiences can persistently steer later
  behavior.
- [Hidden in Memory](https://arxiv.org/abs/2605.15338) reports delayed memory poisoning where external documents,
  webpages, or repositories cause fabricated memories to be stored and later reused.
- [AgentSys](https://huggingface.co/papers/2602.07398) points toward hierarchical memory isolation and schema-validated
  data flow as a defense against indirect prompt injection.

Dreams are exactly the kind of subsystem that can amplify a one-off poisoned transcript into durable context. Treat all
transcript text as untrusted evidence, not instructions.

## Proposed Architecture

### Source Of Truth

Use an append-mostly dream state tree under `~/.sase/dreams/`:

```text
~/.sase/dreams/
  state.json
  dream.lock
  episodes/
    202605/
      <episode_id>.json
      <episode_id>.md
  rollups/
    current.md
    daily/20260523.md
    weekly/2026-W21.md
    monthly/202605.md
    seasonal/2026-H1.md
  inbox/
    202605/
      <dream_id>_memory_candidates.md
  runs/
    202605/
      <dream_id>.json
      <dream_id>.md
  metrics/
    202605.jsonl
```

`state.json` should track the checkpoint and budget state:

```json
{
  "schema_version": 1,
  "last_successful_dream_id": "20260523040000",
  "last_done_mtime_ns": 1779523200000000000,
  "processed_episode_ids": ["sha256:..."],
  "consecutive_failures": 0,
  "backoff_until": null,
  "daily_token_budget_used": 0
}
```

Episode IDs should be stable hashes over project, artifact directory, root retry-chain timestamp, and response paths.
They should not be hashes of the summary text, because the distillation can improve while the source episode remains
the same.

### Pipeline

The dream chop should split deterministic work from LLM work.

1. **Collect:** walk completed `done.json` records since the last checkpoint, resolve `response_path`, join
   `agent_meta.json`, prompt-step metadata, `diff_path`, `plan_path`, and retry-chain fields.
2. **Normalize episodes:** collapse retry chains, group child steps with parent workflows, resolve project/workstream
   labels, and attach source paths.
3. **Score and select:** choose candidates with deterministic signals before any LLM call.
4. **Redact:** replace secrets and sensitive values in excerpts with stable redaction tokens.
5. **Episode distill:** create one episode card per selected episode.
6. **Roll up:** update hot/warm/recent/medium/long materialized views from episode cards and previous rollups.
7. **Propose memory:** emit durable memory candidates into `inbox/`, with provenance and trust metadata.
8. **Checkpoint:** atomically advance state only after all artifacts are written.

The first implementation can run steps 1-4 as a script chop and launch an agent/xprompt only when there are selected
candidates. That keeps idle cycles cheap and makes dry-run/debugging practical.

### Candidate Scoring

Positive signals:

- `done.json.outcome == "completed"` with a readable response path.
- Has `diff_path`, `plan_path`, generated artifacts, PR/CL references, or SDD file references.
- Agent prompt/name mentions research, design, plan, review, bug fix, architecture, performance, migration, memory,
  xprompt, hooks, tests, release, or failure analysis.
- Retry chain failed then succeeded.
- User explicitly asked for memory/research/documentation or corrected agent behavior.
- Transcript references `memory/`, `AGENTS.md`, `default_config.yml`, `sdd/`, `src/sase/axe/`, or other high-value
  shared surfaces.

Negative signals:

- Hidden recurring maintenance chops unless they failed or changed state.
- Very small/no-op transcripts with no artifacts.
- Pure status checks, polling, stale cleanup, notification plumbing, or digest sends.
- Dream-generated artifacts unless explicitly allow-listed, to avoid recursive self-feeding.
- Transcript content whose only "lesson" comes from untrusted external/web/tool output.

Persist both selected and rejected candidates with reasons. The rejected set is the data needed to tune the filter.

### Importance Score And Decay

The Generative Agents paper uses a weighted blend of importance, recency, and relevance to retrieve memories. The same shape works as a deterministic *selection* gate before any LLM call:

```text
score = w_importance * importance
      + w_recency    * exp(-age_hours / half_life_hours)
      + w_signal     * positive_signal_count
      - w_noise      * negative_signal_count
```

Suggested defaults for v1:

- `w_importance = 1.0` — set from explicit signals (user-corrected, retry-chain recovery, decision/architecture content).
- `w_recency = 0.6`, `half_life_hours = 72` — recent episodes win ties but a strong older episode still surfaces.
- `w_signal = 0.3`, `w_noise = 0.5` — noise is penalized harder than signal is rewarded to keep idle cycles cheap.

Decay belongs in *retrieval*, not in the stored episode card. Cards should never be downgraded or rewritten in place; they should age out of high-detail rollups while remaining searchable. This matches the 2026 "Useful Memories Become Faulty When Continuously Updated by LLMs" finding cited above: avoid lossy in-place edits.

### Episode Boundary Detection

Selecting "what is one episode" deterministically avoids the Sanity-style problem of arbitrary token spans. Use, in priority order:

1. **Retry-chain root timestamp.** If `done.json` records a `retry_chain_root`, all chats sharing that root are one episode.
2. **Parent workflow id.** Workflow steps under the same root agent/workflow entry collapse into one episode card, with child step text quoted as evidence.
3. **ChangeSpec / bead / plan id co-mention.** Chats that touch the same ChangeSpec, bead, or plan within a short window join.
4. **User-prompt boundary.** A new top-level user prompt with no shared retry-chain/workflow/CL link starts a new episode.
5. **Idle gap.** As a last resort, a 60-minute idle gap between chats closes the prior episode.

Rules 1-3 are SASE-specific and should dominate. Rule 5 exists only so unparented one-off chats still get bounded.

## Episode Card Format

An episode card should be compact, cited, and structured enough to roll up later:

```markdown
# Episode: <episode_id>

Source:
- project: <project>
- artifact_dir: <path>
- chats:
  - <response_path>
- retry_chain_root: <timestamp-or-null>
- started_at: <iso>
- completed_at: <iso>

Selection reasons:
- diff_path
- user_requested_research

## Operational Context

Two or three sentences explaining what work happened and why it mattered.

## Retained Facts

- file/path or command-level facts worth preserving
- decisions and rationale
- errors and fixes
- unresolved follow-ups

## Memory Candidates

- type: gotcha | convention | architecture | workflow | preference | open_question
  trust: user_prompt | agent_output | tool_output | external_fetch | mixed
  confidence: low | medium | high
  evidence: <chat path or artifact path>
  text: <candidate durable memory>
```

Keep episode cards small. If the model needs exact detail later, the card points back to raw chats and artifacts.

## Rollup Semantics

Rollups should be summaries of lower-level distillations, not raw chat rereads.

Recommended rules:

- The `current.md` rollup can include detailed episode cards for the last 4 hours.
- The daily rollup summarizes episode cards from the last 24 hours and links to each card.
- The weekly rollup summarizes daily rollups, grouped by project/workstream.
- The monthly rollup summarizes weekly rollups, emphasizing decisions, changed conventions, and unresolved threads.
- Seasonal/long rollups should mostly be an index of durable memory candidates and major project arcs.
- Older raw chats should be search-only unless a reflect query needs them.

Each rollup should include a `Sources covered` section with episode IDs and prior rollup IDs. This is how later runs
avoid summarizing the same evidence twice.

### Suggested `current.md`

For agent-facing use, one compact rolling file is more useful than many overlapping sections:

```markdown
# SASE Dream Current Context

Generated: 2026-05-23T04:00:00-04:00
Coverage: 2026-05-22T04:00:00-04:00 to 2026-05-23T04:00:00-04:00

## Last 4 Hours

High-detail bullets. Include files, commands, decisions, blockers, and active handoffs.

## Last 24 Hours

Daily synthesis. Do not repeat the 4-hour bullets except for active blockers.

## Last 7 Days

Workstream outcomes and repeated patterns. Link to daily rollups.

## Last 30 Days

Important decisions and stale/open threads.

## Durable Memory Candidates

Only items ready for review, with links to inbox files.

## Reflect Index

Pointers to old rollups and raw-chat search terms for deeper recall.
```

The "do not repeat" rule matters. Without it, a prompt that includes the whole file will pay for the same fact in four
forms.

## Scheduling Shape

Recommended AXE config shape for an opt-in v1:

```yaml
axe:
  lumberjacks:
    memory:
      interval: 3600
      chop_timeout: "30m"
      chops:
        - name: dream_collect
          description: "Distill recent agent chats into dream rollups and memory candidates"
          run_every: "6h"
```

`dream_collect` can be a script chop that exits quickly when there are no selected candidates or when a budget/backoff
gate is active. It can launch a hidden agent/xprompt only after it writes a candidate bundle.

If SASE wants to start with an agent chop instead, make the xprompt's first deterministic step collect candidates and
skip the LLM step when empty. Do not launch a long-running dream agent every hour just to discover that no work exists.

## Reflect And Search Agent

A static set of rollups will inevitably miss the detail a future task needs. The Sanity, MemGPT, and Generative Agents systems all converge on the same answer: keep a *reflect* path that can drill back into raw evidence on demand.

For SASE, expose this as a hidden agent and a CLI command sharing one implementation:

- `sase dreams reflect "<query>" [--since <duration>] [--project <name>] [--max-episodes N]`
  Resolves the query against episode cards first (cheap), then rollups, then falls back to raw chats via `chat_catalog`. Returns a structured response with episode IDs, citations, and a short synthesized answer.

- A `dreams.reflect` xprompt argument-hint so a normal coding agent can invoke `#dreams.reflect query="..."` inline. The hint should return episode-card excerpts, never raw transcripts, so injection surface stays small.

Reflect is read-only. It does not write episode cards, rollups, or inbox entries. It is the escape hatch that lets the default `current.md` stay small without losing access to history.

This is also the bridge to **dynamic memory**: a successful reflect query that produced a useful answer is itself a signal that the answered fact deserves to become a memory candidate. Record reflect hits in `metrics/` and feed the top-hit queries back into the dream scorer's positive-signal list.

## CLI Surface

Align with the verbs proposed in [`sase_memory_command_subcommands.md`](sase_memory_command_subcommands.md) so users have one mental model for read/write/promote across both subsystems:

| Verb | Purpose | Phase |
| --- | --- | --- |
| `sase dreams status` | Show last run, checkpoint, backoff, budget used | v1 |
| `sase dreams collect [--dry-run] [--since DUR]` | Build candidate manifest from `done.json` | v1 |
| `sase dreams distill [--budget TOKENS]` | Run LLM stage on selected candidates | v1 |
| `sase dreams rollup [--bands hot,warm,recent,medium,long]` | Refresh materialized views | v1 |
| `sase dreams show [--band BAND] [--episode ID]` | Print current rollup or episode card | v1 |
| `sase dreams reflect "<query>"` | On-demand search across cards, rollups, raw chats | v1 |
| `sase dreams inbox list / show / promote / reject` | Manage memory candidates | v2 |
| `sase dreams retract <memory_id>` | Find and remove memories sourced from a poisoned/bad chat | v2 |
| `sase dreams doctor` | Validate `state.json`, rollups, lock file, schema version | v2 |
| `sase dreams replay --from <dream_id>` | Re-run distillation from a past checkpoint without advancing live state | v2 |

`promote` is the only verb that writes into canonical memory, and it must go through the same review path as `sase memory promote`. Dreams never call `sase memory promote` directly without the user.

## Multi-Machine Sync

[`multi_machine_sync.md`](multi_machine_sync.md) recommends a per-domain hybrid. Dreams should be classified as **write-mostly, append-only, machine-local-by-default**:

- `~/.sase/dreams/episodes/`, `runs/`, `metrics/` are append-only and safe to merge by union. They can sync.
- `~/.sase/dreams/rollups/` are derived. They should be regenerated, not synced. Treat them as a cache.
- `~/.sase/dreams/state.json` is per-machine. Each machine maintains its own checkpoint over the union of episodes it can see.
- `~/.sase/dreams/dream.lock` is per-machine and must never sync. It would deadlock the worker on the other side.
- `~/.sase/dreams/inbox/` should sync, because promotion is a user action that may happen on either machine. Inbox files must be append-only with stable candidate IDs so concurrent edits resolve cleanly.

A second machine reaching a synced episode store simply walks forward from its own checkpoint and skips any episode whose deterministic hash is already in its `processed_episode_ids`. There is no need for a CRDT.

## Failure Modes And Recovery

Treat the dream worker like any other long-running background job. Concrete cases:

- **Crash mid-run.** `dream.lock` files become stale if a process dies. Use a pidfile with a heartbeat in the lock and treat it as expired after `chop_timeout`. `sase dreams doctor` clears stale locks after confirming no live PID.
- **Partial write.** Write episode cards, rollups, and inbox files to a temp path and `rename` into place. Update `state.json` last. If a run dies before the rename, the next run reprocesses cleanly with no duplicate output.
- **Corrupt `state.json`.** Keep `state.json.prev` after every successful checkpoint. Doctor restores from prev if the current file fails schema validation.
- **Schema migration.** `schema_version` bumps require an explicit migration step. Do not silently rewrite old episode cards into new formats; write a new card alongside the old and mark the old as `superseded_by`. This honors the "preserve raw evidence" rule from the 2026 update-degradation paper.
- **Missing source artifacts.** If `response_path` or `diff_path` no longer exists at distill time, mark the episode `evidence_missing` and skip distillation rather than fabricating context.
- **Backoff.** Two consecutive failures should set `backoff_until` to `now + 1h`, capped at `12h`. Surface this in `dreams status` so users notice silent failure.
- **Budget exceeded.** Token budget is a hard gate on the distill stage, not on collect/score. Exceeding it should leave the candidate manifest intact for the next run.

## Dynamic Memory Integration

Promoted candidates need to be retrievable by the existing tier-2 dynamic-memory keyword projection. That means promotion must produce a `memory/long/*.md` file with a `keywords` frontmatter list and a stable filename. Concretely:

```yaml
---
schema_version: 1
source: dream
dream_id: 20260523040000
candidate_id: c_8f7a...
episode_ids:
  - ep_4b21...
trust: user_prompt
confidence: high
promoted_at: 2026-05-24T10:00:00-04:00
keywords:
  - axe lumberjack
  - chop_runner
  - dedupe
---
```

Two important rules:

1. The dream system **proposes** the keywords from the episode card's anticipated-questions section, but the human promoter is allowed to edit them before write. Bad keywords either over-trigger or never trigger.
2. Promoted files write into `memory/long/`, not `memory/short/`. Short-term memory is "always loaded" and is the wrong place for opinions distilled from chats. Long-term memory loads only on keyword match, which matches the conservative, opt-in shape dreams should have.

A retraction path can grep `source: dream` plus `episode_ids:` to find every promoted memory derived from a transcript that later turns out to be bad.

## TUI Review Surface

The inbox-only model only works if review is friction-free. The ACE TUI already has tabs for Agents and related views; the natural addition is a `Dreams` tab (or a new sub-tab under an existing memory tab) that lists pending inbox candidates with:

- candidate type, trust, confidence;
- citing episode link (jumps to the chat or artifact);
- inline `promote` / `reject` / `defer` actions;
- a diff preview of the would-be `memory/long/*.md` write.

Until that lands, a CLI loop (`sase dreams inbox list` then `promote`/`reject` by ID) is enough. The point is that promotion must not require hand-editing files in `memory/long/`. If the only review path is "open the markdown and merge it manually," promotion will not happen and dreams will quietly stop being useful.

## Cost Model

Rough order-of-magnitude budget for a daily dream run, useful for picking the AXE `run_every` and prompt sizes:

- Collect/score: zero LLM cost; bounded by `done.json` count.
- Episode distill: one LLM call per selected episode. With redacted excerpts and a tight system prompt, expect 2-6k input tokens and 300-800 output tokens per card.
- Rollup: one LLM call per band touched per run, but rollups consume cards, not raw chats. Expect 4-12k input tokens at the weekly/monthly bands; less at daily.
- Reflect: paid per user request, not per dream run. Cap individual reflects with `--max-episodes`.

A typical heavy day might process ~10 episode cards and refresh hot/warm/recent rollups: roughly 60-100k input tokens and 5-10k output tokens. Light days are zero. Both numbers should be reported in `metrics/` so the budget is observable, not assumed.

The bigger cost question is not money but *prompt context*: a `current.md` that grows past ~2k tokens will quietly outcompete real working context in every future agent prompt. Track `current.md` size as a first-class metric and hard-cap it in the rollup step.

## Security Requirements

Minimum v1 safeguards:

- Dreams write to `~/.sase/dreams/inbox/`, never directly to `memory/short` or `memory/long`.
- Transcript content is framed as untrusted data in prompts.
- The distillation stage receives redacted excerpts and structured metadata, not unlimited raw transcripts.
- Each candidate records `trust`, `evidence`, `source_kind`, and `review_status`.
- Candidates based only on `tool_output` or `external_fetch` cannot become procedural memory.
- Dream outputs exclude prior dream outputs unless explicitly allow-listed for rollup maintenance.
- Promotion requires a review command or explicit user approval.
- A retraction path can find all promoted memories whose provenance cites a bad chat/artifact.
- Tests include poisoned transcript fixtures that try to smuggle durable instructions into memory.

The safe default is "propose, do not promote."

## Evaluation

Add metrics from the first version:

- candidate count before/after scoring;
- episode cards written;
- rollups updated;
- memory candidates proposed;
- token spend and latency by stage;
- redaction hits;
- rejected candidate reasons;
- promoted/rejected inbox rate;
- dynamic-memory hit rate for promoted items;
- retraction/staleness events.

Add fixture-based tests:

- positive retry chain where the dream should capture the recovery rule;
- design/research agent where it should capture a decision and source;
- no-op/poller transcript where it should produce nothing;
- poisoned transcript where it must not propose a memory;
- contradictory later transcript where it should mark an earlier memory candidate stale instead of overwriting it.

The 2026 memory-evaluation papers make the evaluation point explicit: memory quality must be measured under growing
irrelevant history, not just on a clean small corpus.

## MVP Plan

The smallest useful version:

1. Add `sase dreams collect --dry-run --since <duration>` to build a candidate manifest from `done.json` records.
2. Add a redactor and deterministic scoring layer.
3. Add one xprompt or internal LLM runner that converts selected candidates into episode cards.
4. Write `~/.sase/dreams/rollups/current.md` and `~/.sase/dreams/inbox/YYYYMM/<dream_id>_memory_candidates.md`.
5. Add an opt-in AXE `memory` lumberjack with a `dream_collect` script chop using `run_every: "6h"`.
6. Add tests for checkpoint idempotence, retry-chain collapse, poisoned transcripts, and no-op rejection.

Defer:

- graph database storage;
- automatic memory promotion;
- multi-agent specialized dreamers;
- years-long rollups;
- cross-machine conflict resolution beyond a lock and append-mostly files.

## MVP Plan Addendum

To the v1 list above, add explicit acceptance signals before scheduling dreams to run automatically:

- A user can run `sase dreams collect --dry-run --since 24h` and see a non-empty candidate manifest on a representative day.
- A user can run `sase dreams reflect "<recent topic>"` and get back a citation to the correct episode card without raw transcript text.
- The doctor command catches a hand-corrupted `state.json` and restores from `state.json.prev`.
- A fixture run on the poisoned-transcript test produces no inbox entries.
- `current.md` is under the configured token cap after a synthetic load of 50 episodes.

Only after those signals are green should the AXE chop default to running, and even then only with the existing opt-in lumberjack pattern.

## Open Questions

- Should the dream output be global across all projects or project-scoped first? Project-scoped is safer and easier to
  review, but global rollups help with SASE-wide user preferences.
- Should dream rollups be visible to normal agents by default, or only through dynamic memory matching? The safer v1 is
  dynamic/on-demand.
- Should the CLI expose `sase dreams review` before scheduled dreams ship? If inbox review is the promotion gate, the
  answer is probably yes.
- What token budget is acceptable for a background memory system? The answer should be configurable and visible in
  metrics, not hardcoded into the prompt.
