---
create_time: 2026-05-29
status: research
---

# Are SASE Episodes Necessary For `sdd/events/`?

## Question

Should SASE require `sase memory episodes` before committing curated events or lessons to `sdd/events/`, or can
`sdd/events/` stand on its own as a reviewed project-memory layer?

## Short Answer

Episodes are useful, but they should not be mandatory for the first `sdd/events/` design.

For hand-curated lessons, postmortems, decisions, and event cards, direct `sdd/events/YYYYMM/*.md` files are enough if
they have a validator, explicit evidence refs, safety metadata, and a search path. Episodes become necessary when SASE
wants to mine noisy raw agent history automatically or semi-automatically: backfills, dream/chop proposals, duplicate
collapse, source-hash verification, and event-readiness exports.

The clean architecture is:

```text
raw chats/artifacts
  -> private project episodes in ~/.sase/projects/<project>/episodes/
  -> bounded read-only event candidate export
  -> reviewed event proposal
  -> committed sdd/events/YYYYMM/*.md card
  -> optional memory/long proposal when the event contains durable rules
```

But the direct path should also exist:

```text
human or agent-reviewed insight
  -> committed sdd/events/YYYYMM/*.md card with raw evidence refs
```

That means `sdd/events/` should accept episode evidence when available, not depend on it as the only source.

## Current Local State

The current checkout has moved beyond the earlier episode-v2 critique:

- `docs/episodes.md` defines episodes as deterministic source-linked evidence under
  `~/.sase/projects/<project>/episodes/`, not active instructions.
- `sase memory episodes build --split` now builds one component-backed v2 episode per connected component.
- V2 component episodes have `lessons=[]` and storage omits `lesson.md`; legacy aggregate episodes still use
  `lesson.md`.
- `src/sase/memory/episodes/storage.py` now has member and alias indexes, canonical-id resolution, and late-bridge
  aliasing.
- `src/sase/memory/episodes/export.py` is explicitly read-only and returns `writes_events: false`.
- `sase memory episodes auto/status/doctor` exist in the parser and tests, so there is now a checkpointed automatic
  builder surface.
- `sdd/research/202605/episode_v2_phase9_pilot.md` shows a May 2026 pilot: stored inventory was still one legacy
  aggregate episode, but dry-run split produced 27 v2 component episodes and demonstrated useful event-readiness data.

There is still no top-level `sdd/events/` directory in this checkout. The existing `sdd/beads/events/` tree is a bead
event store, which is operational issue-state history, not curated project memory. A future `sdd/events/` needs naming
and docs that keep those concepts separate.

## What Episodes Are Good For

Episodes solve problems that direct event cards do not solve well.

1. **Evidence normalization.** Episodes connect chats, artifact dirs, plan files, QA, feedback, ChangeSpecs, beads,
   diffs, dynamic memory inputs, and memory-read audit rows into one inspectable record.
2. **Boundary detection.** The v2 planner uses strong runtime edges for membership and keeps ChangeSpec, bead, family,
   touched path, and date proximity as weak refs. That is the right split for avoiding giant same-ChangeSpec blobs.
3. **Verification and drift.** Source refs carry existence, byte size, and hashes. `verify` can show when evidence has
   changed without silently rewriting the episode.
4. **Search and review input.** `recall`, `list`, and `export` provide bounded evidence cards. This is the right input
   shape for future event review.
5. **Private high-volume storage.** Episodes can contain local paths, missing-source warnings, safety flags, and noisy
   metadata that should not be committed to the repo by default.

Those are real advantages if the goal is to mine agent history at scale.

## What Episodes Cost

Episodes also add a lot of machinery before any curated event exists.

1. **Complexity.** The system now has a wire schema, collector, component planner, builder, storage/index layer,
   aliases/members, recall, export, auto-builder state, metrics, doctor, and TUI-facing views.
2. **Identity fragility.** `src/sase/memory/episodes/components.py` still builds durable-looking `component_key` values
   from normalized absolute artifact/chat paths, and `identity.py` uses absolute paths for chat/artifact member keys.
   That is acceptable for local verification, but weak for cross-machine or repo-portable identity.
3. **Trust-boundary confusion.** The docs say episodes are evidence, not instructions. That is correct. But legacy
   aggregate episodes still write `lesson.md`, and the name "lesson" tempts downstream code to treat generated text as
   guidance.
4. **Operational state.** Automatic episodes introduce checkpoints and metrics under the project episode store. Tests
   cover lock contention and failed writes, but the feature still creates another background state machine.
5. **Review burden remains.** Episodes can prepare evidence, but they cannot decide what should be committed as durable
   project memory. A review gate is still required.

This means episodes are not a cheap prerequisite. They are a serious evidence subsystem.

## Direct `sdd/events/` Without Episodes

A direct event card can work if it is explicitly reviewed and evidence-backed.

Suggested v1 path:

```text
sdd/events/YYYYMM/<YYYYMMDD>-<slug>.md
```

Suggested frontmatter:

```yaml
id: event-20260529-<slug>
status: active
type: lesson | decision | incident | gotcha | postmortem
observed_at: 2026-05-29T00:00:00-04:00
created_at: 2026-05-29T00:00:00-04:00
trust: reviewed-evidence
scope: project
evidence:
  - kind: episode
    ref: ep-...
  - kind: chat
    ref: ~/.sase/chats/202605/example.md
  - kind: sdd
    ref: sdd/research/202605/example.md
supersedes: []
tags: []
safety:
  untrusted_transcript_text: false
  prompt_injection_reviewed: true
  redaction_reviewed: true
```

Suggested body:

```markdown
## Event

What happened.

## Lesson

What should be remembered, in evidence language rather than command language.

## Evidence

Why the lesson is supported.

## Caveats

When this lesson may be stale or inapplicable.
```

This format can cite an episode, but it can also cite a research note, commit, prompt, chat, artifact, or ChangeSpec
directly. That gives `sdd/events/` value before the episode pipeline is fully trusted.

## Decision Matrix

| Use case | Are episodes necessary? | Reason |
| --- | --- | --- |
| Hand-writing a known lesson after a bug fix | No | A reviewed event card can cite the plan, commit, chat, or research note directly. |
| Recording a design decision from an approved plan | No | The SDD plan is already the strongest evidence. |
| Converting a research note into a durable lesson | No | The research note is already curated. |
| Backfilling lessons from months of agent chats | Yes | Raw chats need boundary detection, dedupe, ranking, and source hashes. |
| Dream/chop-generated candidate lessons | Strongly yes | Generated candidates need source-grounded review input and safety flags. |
| Asking "what happened last time this failed?" | Yes | Episodes are better as a historical query layer than curated events. |
| Sharing repo-portable memory with future agents | Events, not episodes | Episodes live in `~/.sase/projects`; events live in repo SDD and can be reviewed in Git. |
| Automatically injecting guidance into prompts | Neither directly | Use reviewed `memory/long` or an explicit retrieval block; retrieved events/episodes should be evidence, not orders. |

## Recommendation

Do not block `sdd/events/` on episodes. Define `sdd/events/` now as a small, reviewed, repo-portable markdown format
with a validator and search path. Make episode IDs optional evidence refs.

Keep developing episodes if they stay in this role:

- private, source-linked historical evidence;
- a local search and recall layer;
- a bounded input to event review;
- a way to audit generated event candidates.

Avoid this role:

- automatic writer to `sdd/events/`;
- automatic writer to `memory/long`;
- canonical source of project guidance;
- repo-portable identity source while component/member keys are path-dependent.

## Gates Before Episode-Driven Events

Before letting episodes feed an event promotion workflow, settle these items:

1. **Path-independent component identity.** Durable `component_key` values should not include absolute artifact or chat
   paths. Absolute paths can remain source refs.
2. **Event spec first.** Add `sdd/events/README.md` with path, frontmatter, status, evidence, safety, supersession, and
   retraction rules before generating any events.
3. **Validator before automation.** A `sase events validate` or `sase memory search` path should reject malformed or
   unsafe cards before a dreamer can propose them.
4. **Proposal inbox.** Episode export should feed reviewable proposals, not write files directly.
5. **Docs sync.** `docs/episodes.md` should include `auto`, `status`, and `doctor` if those are now supported public
   commands.

## A Practical Pilot

The fastest decision aid is a manual pilot:

1. Create `sdd/events/README.md` plus 5 to 10 hand-curated event cards from known research/tales.
2. Allow evidence refs to be raw SDD paths, commits, chats, and optional episode IDs.
3. Try searching and reading those cards from an agent prompt.
4. Separately run `sase memory episodes build --split -D -j` over the same period and compare whether episode export
   would have found better or safer event candidates.

If manual event cards are easy and useful, episodes are an accelerator, not a prerequisite. If reviewers keep needing
to reconstruct source graphs from chats and artifacts, episodes are justified as the event-candidate substrate.

## Bottom Line

`sdd/events/` and episodes should be complementary layers, not a dependency chain where the curated repo memory waits on
the private episode subsystem. Events answer "what reviewed lesson should travel with the project?" Episodes answer
"what actually happened, and what evidence supports it?"

Build `sdd/events/` for the first question. Keep episodes for the second. Connect them through optional evidence refs
and reviewed promotion, not direct writes.
