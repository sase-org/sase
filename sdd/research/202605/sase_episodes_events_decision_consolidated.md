---
create_time: 2026-05-29
status: research
bead_id: sase-48
---

# Critique: SASE Episodes And `sdd/events/`

## Question

The user likes committing events or lessons to `sdd/events/`, but is uncertain whether SASE episodes are necessary for
that. This note consolidates two independent research drafts identified from these completed-agent transcripts:

- `~/.sase/chats/202605/sase-ace_run-260529_093252.md`
- `~/.sase/chats/202605/sase-ace_run-260529_093253.md`

The intermediate draft files, removed after this consolidation, were:

- `sdd/research/202605/sase_episodes_for_sdd_events_decision_critique.md`
- `sdd/research/202605/episodes_necessity_for_sdd_events_critique.md`

It re-checks their claims against the current checkout and focuses on the decision: are episodes load-bearing for a
curated, repo-committed event memory layer?

## Short Answer

No: episodes should not be mandatory for the first `sdd/events/` design.

Episodes are valuable as private, source-linked evidence and as infrastructure for automatic or retroactive lesson
mining. But the user's stated goal is a reviewed project-memory layer: event cards committed to the repo so future
agents can search and inspect what happened. That layer can stand on its own if it has a small event spec, validation,
safe evidence references, and a retrieval path.

The better decision frame is not "episodes yes/no." It is authoring mode:

| Authoring mode | Are episodes necessary? | Reason |
| --- | --- | --- |
| Push model: user or finishing agent writes a lesson as work completes | No | The author already knows the work boundary and can cite plans, research, commits, chats, or ChangeSpecs directly. |
| Pull model: background dreamer mines lessons from a backlog of chats | Yes | Raw agent history needs segmentation, dedupe, ranking, hashes, and poisoning/redaction signals before an LLM can safely propose durable memory. |
| Recall/debugging: "what happened last time?" | Useful, but separate | Episodes can justify themselves as local evidence/search even if events do not depend on them. |

Recommendation: build `sdd/events/` first as a standalone curated layer. Let episodes be optional evidence refs and a
future event-candidate feed, not a prerequisite.

## Verified Current State

The two drafts mostly agree, but one conflict needed resolution: the older phase critique was stale. The current checkout
has moved beyond the earlier "only phase 2 exists" state.

Verified now:

- `docs/episodes.md` defines episodes as deterministic, source-linked evidence under
  `~/.sase/projects/<project>/episodes/`, not active instructions or direct writes to `memory/short`/`memory/long`.
- `sase memory episodes build --split` is registered and builds one v2 component episode per connected component.
- V2 component episodes have `lessons=[]`; storage omits `lesson.md` for component episodes and removes stale
  `lesson.md` projections.
- Legacy aggregate episodes still render and store `lesson.md` for compatibility.
- Member and alias indexes exist in `src/sase/memory/episodes/identity.py` and
  `src/sase/memory/episodes/storage.py`.
- `sase memory episodes export` is read-only and returns `writes_events: false`.
- `sase memory episodes auto`, `status`, and `doctor` exist in parser/CLI/tests, though `docs/episodes.md` does not yet
  document them.
- `sdd/research/202605/episode_v2_phase9_pilot.md` reports a read-only May 2026 pilot: stored inventory was still one
  legacy aggregate episode, while dry-run split build produced 27 v2 component episodes with no lessons.
- There is no top-level `sdd/events/` directory in this checkout. `sdd/beads/events/` is operational bead state, not the
  proposed curated project-memory event layer.
- `sase memory search` is still not registered under `sase memory`, so the event retrieval surface remains future work.

The remaining serious episode risk is identity. `src/sase/memory/episodes/components.py` still builds durable-looking
component keys from normalized absolute artifact/chat paths, and member keys also use normalized source paths. That is
acceptable for local evidence and drift checks, but weak as repo-portable or cross-machine identity.

## What Episodes Buy

The pro-episode case is strong when the system needs to mine history at scale.

Episodes provide:

- **Segmentation.** Connected-component planning separates unrelated work while keeping retry, fork, parent, chat, and
  workflow lineage together. Date ranges select seeds; they should not define episode boundaries.
- **Provenance.** Source refs carry existence, size, and SHA-256 hashes. `verify` can detect source drift without
  silently rewriting the episode.
- **Selection signal.** Importance scoring and bands help a downstream reviewer or dreamer decide which work is worth
  inspecting.
- **Safety metadata.** Episodes can flag untrusted transcript text, injection-like content, redaction hits, missing
  sources, and other promotion hazards.
- **Private high-volume storage.** Episodes can safely contain local paths, noisy metadata, missing-source warnings, and
  runtime details that should not be committed to the repo.
- **Recall independent of events.** Stored episodes can answer operational questions about a prior agent run even when
  no durable lesson exists.

Those are real advantages. They are just not the same as "required before any event card can exist."

## What Episodes Cost

Episodes are not a cheap prerequisite.

- **Large maintenance surface.** The feature now spans collector, connected-component planner, builder, storage,
  identity indexes, recall, export, auto-build state, metrics, doctor checks, CLI, tests, and TUI-facing views.
- **Identity fragility.** Absolute-path-derived component/member keys are fine for local source refs but should not leak
  into committed event identity or be treated as portable evidence keys.
- **Trust-boundary confusion.** The docs correctly say episodes are evidence, not instructions. Legacy `lesson.md`
  still exists, and reusing "lesson" terminology across private generated evidence and reviewed repo memory invites
  misuse.
- **Operational state.** Auto-building episodes adds locks, checkpoints, metrics, and recovery behavior under project
  state. That is justified for pull-model mining, not for a simple reviewed event card.
- **Review burden remains.** Episodes can prepare evidence, but they cannot decide what should become durable project
  memory. A review gate is still required.

The sunk cost should be evaluated honestly: episode infrastructure is useful and increasingly mature, but `sdd/events/`
has not consumed it yet. "Already built" is not the same as "load-bearing for the events goal."

## Direct `sdd/events/` Path

A v1 event layer can be much simpler than the episode subsystem:

```text
sdd/events/
  README.md
  202605/
    20260529-episodes-events-decision.md
```

Use one reviewed Markdown card per event. Avoid directory-per-event `lesson.md` unless v1 truly needs sibling artifacts;
one file is easier to diff, search, link, validate, and mentally separate from private episode `lesson.md` projections.

Minimum frontmatter should cover:

```yaml
schema_version: 1
event_id: evt_20260529_episodes_events_decision
event_type: lesson # decision|incident|gotcha|postmortem|research_result|migration
occurred_at: 2026-05-29T00:00:00-04:00
created_at: 2026-05-29T00:00:00-04:00
status: active # active|superseded|retracted
project: sase
trust: reviewed
privacy: repo_safe
sources:
  sdd: []
  commits: []
  chats: []      # use basename/hash, not absolute home paths
  episodes: []   # optional local evidence refs
supersedes: []
keywords: []
```

Suggested body:

```markdown
## Event

What happened.

## Lesson

What future agents should be able to find, phrased as evidence rather than command authority.

## Evidence

Repo-relative SDD paths, commit hashes, ChangeSpecs, bead IDs, chat basenames, or optional episode IDs.

## Caveats

When this lesson may be stale, incomplete, local-only, or unsafe to apply automatically.
```

This gives `sdd/events/` value before episode promotion exists. An event can cite an episode when one is useful, but it
can also cite an SDD research file, a commit, a plan, a ChangeSpec, a bead, or a chat basename directly.

## Decision Matrix

| Use case | Recommended source | Episode dependency |
| --- | --- | --- |
| Recording a design decision from an approved plan | `sdd/events` card citing the plan/research | None |
| Capturing a lesson after a bug fix | Finishing agent/user writes a reviewed event card | None |
| Turning a research conclusion into durable project history | Event card citing `sdd/research/...` | None |
| Preserving "do not repeat this failed approach" | Event card, optionally followed by `sase memory write` if it is procedural guidance | None |
| Backfilling lessons from months of chats | Episode export feeding proposals | Strong |
| Dream/chop-generated candidate lessons | Episode export plus validator/review inbox | Strong |
| Debugging a prior agent run | `sase memory episodes recall/show/verify` | Episodes are the right tool |
| Repo-portable memory for future agents | `sdd/events` and `memory/long`, not private episode IDs | Episodes optional as evidence |
| Automatic prompt injection as guidance | Neither directly | Use reviewed `memory/long` or explicit retrieval framing |

## Gates Before Episode-Driven Events

If episodes later feed event proposals, hold these gates first:

1. Define `sdd/events/README.md` before promotion code: path, frontmatter, status, evidence, privacy, supersession, and
   retraction rules.
2. Add an event validator before automation: schema validation, repo-safe source refs, no absolute local paths, injection
   scan, redaction/privacy flags, and clear trust labels.
3. Keep export/proposals read-only with respect to Git. Episode export should feed a reviewable proposal inbox, not write
   `sdd/events/` directly.
4. Fix or quarantine path-dependent episode identity. Event files should not depend on absolute-path component keys as
   durable, portable IDs.
5. Keep event retrieval framed as evidence. Events should not be injected as high-trust instructions; durable procedural
   rules still go through `sase memory write` and `sase memory review`.
6. Document the now-existing `auto`, `status`, and `doctor` episode commands so operators understand the background
   state they are relying on.

## Practical Pilot

The fastest way to decide is not more episode infrastructure. It is a small event pilot:

1. Add `sdd/events/README.md` and 5 to 10 hand-curated event cards from existing research/tales.
2. Allow direct evidence refs first: SDD paths, commits, ChangeSpecs, bead IDs, chat basenames, and optional episode IDs.
3. Implement or prototype search over those cards with structured filters and lexical text search.
4. Separately run `sase memory episodes build --split -D -j` plus `export` over the same period and compare whether
   episode export finds better, safer, or meaningfully different event candidates.

If manual event cards are easy and useful, episodes are an accelerator, not a prerequisite. If reviewers repeatedly need
to reconstruct source graphs from scattered chats and artifacts, episodes have earned the role of event-candidate
substrate.

## Bottom Line

Separate the decisions.

Build `sdd/events/` for reviewed, repo-portable project memory. Keep episodes for private, source-linked historical
evidence and for future pull-model mining. Connect them through optional evidence refs and reviewed promotion, not a
hard dependency or direct writes.

Events answer: what reviewed lesson should travel with the project?

Episodes answer: what actually happened, and what evidence supports it?
