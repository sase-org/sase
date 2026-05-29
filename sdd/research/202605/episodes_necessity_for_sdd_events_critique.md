---
create_time: 2026-05-29
status: research
bead_id: sase-48
---

# Critique: Are SASE Episodes Necessary For `sdd/events/`?

## Question

The user likes the idea of committing events/lessons to `sdd/events/` but is uncertain whether the SASE *episodes*
subsystem is necessary to support that. This note critiques episodes specifically against that goal: not "are episodes
good?" but "are episodes load-bearing for a curated `sdd/events/` lesson layer, or are they a heavy detour?"

## Short Answer

Episodes are **not necessary** for the `sdd/events/` goal as the user has framed it. They become necessary only if you
also want the *other* half of the design — a background **dreamer** that mines lessons automatically and retroactively
from a large backlog of past agent runs with no human in the authoring loop.

So the real decision is not "episodes yes/no." It is **how events get authored**:

- **Push model** (forward-looking, low-volume, human- or finishing-agent-authored): the agent that just did notable
  work — or you — writes `sdd/events/YYYYMM/<id>.md` and it lands through normal review. Episodes add almost nothing
  here. You need a spec, a validator, and search; not an evidence store, an importance scorer, an identity index, an
  auto-build worker, and a TUI explorer.
- **Pull model** (retroactive, high-volume, LLM-mined): a dreamer scans thousands of past transcripts and proposes
  events. Here episodes earn their keep, because you cannot point an LLM at raw transcripts safely or coherently — it
  needs bounded, segmented, deduplicated, safety-gated, importance-ranked input. That is exactly what episodes provide.

If you only want the push model, episodes are optional infrastructure you can defer or skip. If you want the pull model,
episodes are the architectural hinge and you should keep them.

## What Episodes Actually Buy You (Steelman)

The design (`docs/episodes.md`, `sdd/research/202605/memory_episode_connected_components_and_events.md`) gives episodes
six real jobs. Taken on their own terms these are sound:

1. **Segmentation.** A "lesson" needs a unit of work to be about. Episodes deterministically partition agent/chat
   lineage into connected components (union-find over strong retry/fork/parent/workflow edges), so a date-bounded scan
   of unrelated work becomes N episodes instead of one undifferentiated bag.
2. **Provenance.** Each episode is source-linked with SHA-256 hashes; `verify` recomputes existence/size/hash and flags
   drift. A claim becomes traceable evidence rather than an assertion.
3. **Determinism vs LLM rot.** The cited 2026 prior art ("Useful Memories Become Faulty When Continuously Updated by
   LLMs") argues raw episodes should stay first-class and the LLM layer should be read-only over them. Episodes are the
   immutable, rebuildable substrate; events are the regenerable pitch on top.
4. **Selection signal.** Deterministic importance scoring (retry-recovery, SDD writes, plan/feedback, verification, etc.)
   tells a downstream consumer *which* work is worth a lesson, instead of treating all work equally.
5. **Safety boundary.** Episodes carry `safety` metadata (untrusted-transcript text, injection-phrase hits, redaction
   hits) that gates promotion. This is the mitigation for OWASP ASI06 / AgentPoison-style memory poisoning.
6. **Recall/debugging value independent of events.** "What did agent X do, what was its retry chain, what did it touch"
   is answerable from episodes regardless of whether any event is ever written.

Point 6 matters for fairness: even if episodes are unnecessary *for events*, they may justify themselves on recall
alone. "Necessary for events" and "useful at all" are different questions, and the answer to the first can be no while
the answer to the second is yes.

## Where That Value Is Real vs. Speculative Right Now

The catch is that five of those six jobs (everything except recall) exist to feed a consumer that does not yet exist.

- The episodes→events pipeline's only authoring consumer is the **dreamer**, and the dreamer is unbuilt (Phase 5+ in
  the design; `sdd/events/` does not exist in this checkout).
- The companion critique (`sdd/research/202605/episode_v2_events_consolidated_critique.md`) states plainly that "schema
  v2 currently means v2-capable wire, not the product is producing v2 semantic episodes," and warns of a "dangerous
  middle state": v2 fields and a component planner exist, but the active product still behaves like v1, component keys
  are not yet machine-independent, and `lesson.md` is a "zombie contract."
- Eight phases are reportedly closed (wire, planner, identity, importance, split build, drill-down, TUI explorer,
  auto-build). That is a large, multi-repo investment (Rust core wire + Python collector/builder/storage/identity +
  auto-build worker + TUI modal + CLI surface) whose payoff — curated lessons you can actually read — is still zero
  files on disk.

So the honest framing of the sunk cost: episodes are *mostly built*, but "already built" is not the same as
"load-bearing for the events goal." The events layer has not consumed a single episode yet.

## The Simpler Alternative: Events Without Episodes

The repo already contains the pattern an events layer would ride on. `sdd/research/`, `sdd/tales/`, and `sdd/prompts/`
are durable markdown with YAML frontmatter, organized in `YYYYMM/`, committed to the repo, human-reviewed via normal
PR, and searchable with ripgrep and git. An events track can be exactly that:

```text
sdd/events/YYYYMM/<YYYYMMDD>-<slug>-<shorthash>.md
```

with frontmatter (`event_id`, `status`, `keywords`, `episode_ids` or `chat_paths`, `sources`, `trust`, `privacy`,
`supersedes`) and a body that is the lesson + evidence + "what not to infer."

What that buys you without any episode machinery:

- **Authoring** is done by the agent that just finished notable work (it already has full transcript context and knows
  the work boundary), or by you at review time. No retroactive mining needed.
- **Provenance** is frontmatter citing chat paths, commit hashes, and ChangeSpec names. For a human-reviewed doc that
  someone read before approving, that is enough traceability — hash-verified source projections are overkill.
- **Selection** is human judgment ("this was worth a lesson"), which is the same gate the design ultimately requires
  anyway via the review boundary.
- **Safety** is the PR review itself plus an injection-phrase validator on the body, which you would want regardless.
- **Search** is `sase memory search` over `sdd/events/**/*.md` (which the consolidated critique already recommends
  building first, recommendation #8: "Start the events track with a spec, validator, and search, not with
  dreamer-generated repo writes").

Notably, the existing critique already half-endorses this path — it just doesn't frame it as "and therefore episodes
are optional for the events goal," which is the point this note is making explicit.

## Which Pro-Episode Arguments Survive The Simpler Alternative?

Testing the six jobs against the push model:

| Episode job | Survives without episodes? | Why |
| --- | --- | --- |
| Segmentation | Mostly not needed | The finishing agent/human already knows the work boundary. Connected-component partitioning matters for *retroactive bulk backfill* of thousands of artifacts — a pull-model concern, not "commit a lesson going forward." |
| Provenance (hashed) | Weakened | Frontmatter citations suffice for a reviewed doc. Drift detection is valuable for an *automated* evidence store, marginal for a curated lesson a human approved. |
| Determinism vs LLM rot | Conditional | This argument bites only if an LLM is continuously rewriting memory. If humans/agents author events deliberately and supersede rather than rewrite, the rot risk is already controlled. |
| Selection (importance) | Not needed | Human judgment replaces the scorer. The scorer's purpose is to rank input for an LLM that has no judgment. |
| Safety metadata | Partially needed | You still want an injection-phrase validator on event bodies. But you don't need per-episode safety projections; you need one validator at the `sdd/events/` boundary. |
| Recall/debugging | Independent | Survives, but is unrelated to events. Judge it on its own merits. |

The one argument that genuinely *requires* episodes is segmentation-at-scale — and only for retroactive, automated
mining. Every other pro-episode argument either collapses to "human review" or shrinks to "one validator at the
boundary" under the push model.

## Decision Framing

Ask yourself which of these is the real goal:

1. **"I want to capture lessons as I go, in the repo, reviewed."** → Build `sdd/events/` directly: a `README.md` spec, a
   frontmatter validator, an injection scan, and `sase memory search`. Optionally a skill or finalize-hook that drafts
   an event from a completed agent for your review. Episodes are not required. This is days of work, not phases.
2. **"I want lessons mined automatically from everything agents do, including the backlog, without me authoring them."**
   → You need episodes (segmentation + importance + safety + dreamer). This is the full multi-phase program, and the
   consolidated critique's gates (path-independent component keys, canonical-ID selection, kill the zombie `lesson.md`
   contract, settle the events format) must hold first or you will "turn noisy generated summaries into repo-backed
   false confidence."
3. **Middle path (recommended if undecided).** Build the `sdd/events/` layer first under the push model. Author events
   manually / agent-assisted. Only invest further in episodes-as-event-feedstock if and when manual authoring demonstrably
   fails to keep up — i.e., let the pull model earn its complexity with evidence, not anticipation. Episodes that already
   exist can keep serving recall in the meantime, so the prior work is not wasted.

A useful tell: if you find yourself unwilling to *manually* write a lesson for a given piece of work, that work probably
was not lesson-worthy — which is precisely the "most batches should be zero" property the dreamer design itself
asserts. That property is an argument *for* human authoring being sufficient, not for automating the authoring.

## Risks Of Keeping Episodes On The Critical Path For Events

- **Speculative coupling.** The events format, validator, and search are blocked behind a much larger system whose
  consumer is unbuilt. You can ship events value today; coupling them to episodes defers it.
- **Two `lesson.md` contracts.** The design removes `lesson.md` from private episodes but reintroduces it for events.
  Reusing the same filename across a trust boundary (untrusted episode evidence vs. reviewed event) invites confusion
  unless the event format is rigidly distinct. A flat `sdd/events/.../<slug>.md` card avoids re-creating the contract.
- **Identity fragility.** Persistent v2 episode IDs currently derive from normalized absolute paths, which are machine-
  and workspace-dependent. If events cite episode IDs, a wrong ID scheme propagates into committed repo artifacts.
- **Maintenance surface.** Auto-build worker, locks, checkpoints, doctor, metrics, member/alias index, TUI explorer —
  all must keep working for the pull model to pay off. The push model has none of that surface.

## Bottom Line

Episodes are a well-designed *evidence-and-mining* substrate, but they are infrastructure for **automatic, retroactive,
LLM-mined** lessons. The user's stated goal — committing curated events/lessons to `sdd/events/` — is a **push-model,
human-reviewed** artifact that the repo's existing `sdd/*` + frontmatter + PR-review pattern already supports without
any episode machinery.

Recommendation: decouple the decisions. Build `sdd/events/` first as a standalone curated layer (spec, validator,
search, optional draft-from-agent helper). Treat episodes as a *separate* bet justified by recall/debugging value and by
a later, explicit decision to automate lesson mining — not as a prerequisite for having events at all. If automatic
mining never proves its worth, you still have the events layer; if it does, episodes are ready to feed it.
