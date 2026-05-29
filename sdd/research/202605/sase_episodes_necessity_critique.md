---
create_time: 2026-05-29
tier: research
status: draft
topic: Do we need SASE episodes if the real goal is committing curated events/lessons to sdd/events/?
---

# Critique: Are SASE Episodes Necessary for `sdd/events/`?

## The question, stated precisely

You like the idea of committing **events / lessons** to `sdd/events/YYYYMM/<event_id>/lesson.md`: rare,
human-reviewed, git-versioned distillations of what agents learned. You are unsure whether the **episodes** layer is a
necessary precondition for that.

This note critiques episodes *specifically against that goal*. It is not asking "are episodes well built?" (they are —
see below). It asks "does the thing you actually want require them?"

## What each layer is (as currently designed)

| Layer | Where | Who writes | Lifetime | Role |
|---|---|---|---|---|
| Raw artifacts / chats | agent artifact dirs, chat transcripts | runtime | ephemeral-ish, can drift/disappear | source of truth |
| **Episodes** | `~/.sase/projects/<project>/episodes/` (NOT git) | machine (build/auto) | persistent, auto-maintained | deterministic connected-component **evidence index** |
| **Events** | `sdd/events/YYYYMM/<id>/lesson.md` (git) | human-curated | durable, reviewed | the **lesson** you actually keep |

Episodes are explicitly "evidence, not instruction." They never write `memory/short` / `memory/long`. The epic
(`sdd/epics/202605/episode_v2_explorer.md`) is emphatic that events are a separate, later, non-goal — episodes only
"carry enough structured metadata for future event selection."

So architecturally, episodes are an **intermediate, machine-generated, non-git cache** sitting between noisy raw
evidence and the rare curated lesson.

## The honest case *for* episodes

These are real and shouldn't be dismissed:

1. **Provenance graph-walking is genuinely hard by hand.** A single "work episode" is scattered across retries, forks,
   `#resume`, parent agents, workflow steps, and multiple chats. The union-find connected-component planner reconstructs
   that automatically. A human curating an event would otherwise hunt across artifact dirs to answer "what actually
   happened here." This is the strongest argument.
2. **Triage / discovery funnel.** You cannot curate a lesson from work you can't find. `list` + importance bands let you
   surface candidate work for a week without reading every chat. Events are supposed to be *rare*, which means the hard
   part is *selecting* the rare 2% — and that selection needs an inventory to select from.
3. **Determinism + verification.** Source hashing and `verify` let you detect when an event's cited evidence has rotted.
4. **Volume compression.** chats (huge, noisy) → episodes (structured) → events (wisdom). Each layer reduces volume.

## The case *against* episodes being necessary

### 1. The consumer is explicitly *rare* — the weakest case for a materialized cache
Episodes are a **cache/index of something recomputable** from raw artifacts. You materialize and auto-maintain a cache
when query cost × query frequency is high. But events are designed to be **rare, reviewed artifacts**. Rare consumption
is the *weakest* justification for a persistent, auto-built, checkpointed, alias-tracked, metric-emitting store. You
build caches for hot paths; event curation is a cold path by design. This is the central tension: the heavy machinery's
cost is continuous, but its consumer fires occasionally.

### 2. Episodes store rot-prone *references*, not durable *content* — so they don't solve the durability problem
The one scenario that would strongly justify a persistent layer is: *raw artifacts get pruned, so we need to snapshot
provenance before it disappears.* But episodes store **source refs + SHA-256 hashes**, not the source content. `verify`
only *detects* drift; it does not *preserve* the evidence. If a chat is deleted, the episode tells you it's gone — it
does not give you the text back. For a git-committed lesson you actually want the relevant evidence **inlined into the
lesson.md at curation time** (where git makes it durable), which episodes do not do. So episodes don't deliver the
durability guarantee that would most justify them.

### 3. The thing you value needs ~none of this infrastructure
A committed event is a markdown file written with human/curatorial judgment. The decision "is this a reusable lesson?"
is inherently editorial and cannot be delegated to a deterministic importance score. Everything load-bearing about
`sdd/events/` — the judgment, the writing, the review, the git history — exists with zero episode code.

### 4. Importance scoring is deterministic, not correct
Determinism is being used as a proxy for trust, but a deterministic heuristic that mis-ranks is just *consistently*
wrong. The real importance signal is "a human/agent found something reusable here" — exactly the editorial judgment that
event curation already requires. The score can help *sort* candidates, but it cannot make the call, so it can't be the
justification for the layer.

### 5. Cost and gravity
The episodes Python package is ~9.7k LOC across 43 modules, plus the Rust `sase_core` wire schema, PyO3 bindings, an ACE
TUI explorer, a checkpointed auto-builder with status/doctor/metrics, member/alias indexes, and a 9-phase epic — **all
shipped before a single event exists.** That is a large speculative foundation poured before the building it's meant to
support is designed. The risk is not that episodes are bad; it's that the intermediate layer accrues its own gravity
(beads, TUI, auto-builder) and becomes the de-facto product while events — the actual goal — stay perpetually "later."

### 6. The valuable 20% is cheap to extract
The genuinely hard, valuable part (argument #1: lineage reconstruction) could be delivered by a single on-demand command
— "given this agent/chat, walk strong lineage and print the connected artifacts" — feeding directly into event
authoring. That is a small fraction of the current surface. You do not need stored `episode.json` + `sources.jsonl` +
`index.jsonl` + `members.jsonl` + `aliases.jsonl` + metrics + auto-build + a TUI to answer "show me everything connected
to this work" at curation time.

## The decision hinges on two questions

**Q1 — Do raw agent artifacts/chats persist, or are they pruned?**
- If **pruned**: there is a real preservation argument, *but only if episodes inline content* (today they store refs, so
  this argument currently fails — see #2). Fixing that is cheaper than the full layer.
- If **permanent**: episodes are a recomputable index, and on-demand recomputation at curation time is sufficient.

**Q2 — Is candidate triage across a period actually a bottleneck?**
- If you routinely scan a week of work to pick lessons and that is painful: the inventory + importance funnel earns its
  keep (a *lean* version of it).
- If lessons are obvious in the moment ("that retry-recovery was worth recording, write it now"): the funnel solves a
  problem you don't have, and you can author events inline as work happens.

## Recommendation

Lead with **events first, episodes as a thin on-demand helper** — not the other way around. Concretely:

1. Define and ship `sdd/events/` and the lesson format now. Author 5–10 real events by hand from recent May 2026 work.
   This is the only way to learn what evidence a good lesson actually needs.
2. Replace the heavyweight always-on episode store, at least initially, with **one on-demand command** that does
   lineage reconstruction (the valuable 20%) and **inlines** the connected evidence so an author can paste it into a
   lesson. That captures provenance durably in git, where you want it.
3. Only invest in *persistent, auto-built* episodes if authoring those real events proves that (a) artifacts disappear
   before you can curate them, or (b) triage across many candidates is a recurring bottleneck. Let the pain justify the
   layer, rather than building the layer in anticipation of pain.

In short: the episodes work is good engineering, but it is a sophisticated **cache built ahead of its consumer**, it
preserves references rather than content, and its consumer is rare by design. None of `sdd/events/`'s core value
(judgment, durable git-versioned lessons) depends on it. Keep the *idea* of connected-component provenance — it's the
genuinely hard part — but extract it as a thin on-demand tool and let real events tell you whether the heavy version is
worth it.

## Open items to resolve before deciding
- Confirm the retention policy of raw agent artifacts and chats (answers Q1).
- Sanity-check how often you'd actually run a week-scale triage (answers Q2).
- If you keep episodes, decide whether they should **inline** key evidence so git-committed events are self-contained.
