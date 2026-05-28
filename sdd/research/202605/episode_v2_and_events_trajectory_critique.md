---
create_time: 2026-05-28
status: research
bead_id: sase-48
---

# Critique: Episode V2 Trajectory And `sdd/events/` Plans

## Question

What is the current state and trajectory of SASE memory episodes (per the `sase-48` epic), are there concerning
architectural problems, and are the plans for `sdd/events/` sound?

## Scope And Method

This is a critique, not a design. It reviews the `sase-48` epic, the three governing research notes, and the actual code
state as of 2026-05-28. Where the planning docs make load-bearing claims, I verified them against the checkout rather
than trusting the prose.

## Verified Current State

The verification matters because several planning docs describe state that has since changed.

- **Epic:** `sase-48` (`sdd/epics/202605/episode_v2_explorer.md`) has 9 phases. Only Phase 1 (`sase-48.1`) has landed
  (`010721231 feat: add episode v2 Python wire compatibility`). Phases 2-9 are open/in-progress and strictly ordered.
- **Phase 1 is real and respects the Rust boundary.** `../sase-core/crates/sase_core/src/episode/wire.rs` is at
  `EPISODE_WIRE_SCHEMA_VERSION = 2` with `component_key`, `status`, `importance_score`, `importance_band`,
  `importance_factors`, `safety`, and `weak_refs`. `mod.rs` exposes `stable_v2_episode_id(project, component_key)`. The
  Python side mirrors this in `src/sase/core/episode_wire.py` and binds through `episode_facade.generate_v2_episode_id`.
  (Note: a sibling workspace other than `sase-core_13` may show a stale tree with no `episode/` module — confirm against
  the workspace number matching this primary repo before concluding the schema is missing.)
- **Everything else is still v1.** `src/sase/memory/episodes/` has the v1 collector/builder/storage/recall (20 files).
  `components.py`, `importance.py`, `auto_build.py`, and `views.py` do not exist yet. The CLI
  (`cli_episodes.py` + `parser_memory_episodes.py`) exposes only `build`, `list`, `show`, `verify`, `recall`. No `auto`,
  `status`, `doctor`, or `export`.
- **`sdd/events/` does not exist** and the epic explicitly forbids creating it. The plans for it live entirely in three
  research notes.
- **`sase memory search` does not exist.** There is no `search` subcommand in `parser_memory.py`.

So the trajectory is: the cross-repo wire was bumped to v2 first (correct sequencing), but the system still produces
v1-shaped episodes. The v2 fields currently serialize as defaults on every episode the builder writes.

## What Is Solid

Stated up front so the concerns below are read as targeted, not wholesale.

- **The core insight is correct.** Episodes as deterministic connected components over *strong lineage edges*, with
  ChangeSpec/bead/family/path as *weak metadata only*, is the right fix for the real "one `project_scan` bag" bug. It
  matches the conversation-segment-before-summarize pattern from the prior-art survey.
- **The deterministic, no-LLM episode layer is the right call.** Reproducible IDs, no per-token cost, and a much smaller
  attack surface than LLM-summarized episodes. The one LLM step (the dreamer) is correctly isolated to event promotion.
- **Non-destructive migration.** Additive schema, v1 freeze, alias rows instead of rewrites. This is the right posture
  and is backed by the cited 2026 "memories become faulty when continuously updated" finding.
- **Strong prior-art and threat grounding.** CoALA, Reflexion, Generative Agents, Zep, OWASP ASI06, AgentPoison/MINJA are
  cited and actually shape decisions (background writes, importance×content separation, human promotion gate).

## Architectural Concerns

### 1. Schema landed far ahead of its only producer

Phase 1 added eight semantic fields to `EpisodeWire` plus index-row fields, but nothing populates them until Phase 4
(importance/safety) and Phase 2 (`component_key`). Today every newly built episode stores `importance_score = 0`,
`importance_band = "unknown"`, empty `safety`, empty `weak_refs`. `band = "unknown"` is a usable sentinel; `score = 0`
is **not** — once Phase 4 lands, nothing distinguishes "scored and genuinely zero" from "written before scoring
existed." Recommendation: treat `importance_band = "unknown"` as the authoritative "unscored" marker and never rank or
filter on `importance_score` when the band is unknown, or add an explicit `scored: bool`/nullable score. Decide this now,
before any v2 episodes with default-zero scores accumulate on disk.

### 2. The identity/merge layer (Phase 3) is the riskiest work and sits mid-stack

Moving from content-set IDs to component-root-key IDs, plus `members.jsonl` + `aliases.jsonl` + alias resolution
threaded through `show`/`list`/`verify`/`recall` + v1 freeze, is the single most failure-prone phase. Union-find with a
root-key priority list is sound, but the "late bridge between two existing episodes" case is genuinely hard: it mutates
identity for already-stored records. If this lands buggy, it corrupts the stable handles every later phase (and the TUI)
depends on. The ordering is right (before UI), but the phase deserves the most fixture coverage and probably a
dedicated property test for "rebuild is idempotent and order-independent."

### 3. Cross-machine canonical-ID selection is hand-waved

The connected-components note asserts "no CRDT is required" because each machine walks forward from its checkpoint. But
canonical-ID choice on a late bridge is **order-dependent**: if machine A and machine B independently merge the same two
components in different orders, they can pick different canonical IDs and write mutually-pointing alias rows — an alias
cycle or a two-canonical conflict that "union by append" does not resolve. The fix is cheap but must be explicit:
make the canonical ID a pure deterministic function of the component (e.g. the lexicographically-minimal qualifying
root key), so any machine reaches the same canonical regardless of processing order. Without this rule, `aliases.jsonl`
sync is not actually conflict-free.

### 4. Importance weights are hardcoded, and that contradicts the project's own prior art

The weight table (+18 retry_recovered, -14 hidden chop, ...) will live in `importance.py`. Deterministic is good, but
these are guesses that will rot, and `memory_system_prior_art.md` and `structured_episodic_events_for_memory_search.md`
both explicitly recommend putting ranking/scoring weights in a TOML config (`memory_search.toml`) with an `--explain`
flag, precisely so tuning is not a code change and ranking debates become evidence. The episode importance design drops
that lesson. Recommendation: externalize the weights to project-state config from day one and add `--explain` to
`show`/`list`, matching the search-ranking design rather than diverging from it.

### 5. Long, serial critical path with little re-validation until Phase 9

Nine strictly-ordered single-agent phases rebuild the entire subsystem before the pilot (Phase 9) re-checks user value.
The whole time, v1 and v2 coexist with migration/alias complexity. There is no intermediate "is this actually better for
a user" gate until the end. Recommendation: pull a lightweight pilot forward — after Phase 5 (split build + inventory),
run the "does split produce multiple episodes where v1 produced one bag, with a non-degenerate importance histogram"
check from the Phase 9 acceptance list. If the distribution is degenerate or split is noisy, that is far cheaper to
learn before Phases 6-8 than after.

### 6. The TUI explorer (Phase 7) lands in a subsystem with a documented perf history

This repo has a long trail of ACE perf research (startup profiles, j/k latency baselines, progressive-slowdown
debugging, full-refresh elimination). Adding a time-window inventory + graph/timeline drill-down risks regressions. The
plan does say "avoid expensive filesystem scans on the event loop; use a worker/cached read path" — good awareness — but
given the history this needs a hard rule: the explorer reads only `index.jsonl`/cached projections on the event loop and
never opens per-episode `episode.json` or re-hashes sources synchronously. The visual-snapshot and no-event-loop-block
acceptance criteria should be treated as gating, not nice-to-have.

## Concerns Specific To The `sdd/events/` Plans

### 7. The three notes disagree on event storage shape, and it is unreconciled

This is the most concerning inconsistency in the trajectory.

- `structured_episodic_events_for_memory_search.md` and `git_versioned_episodic_events.md` both specify **one markdown
  file per event** — `sdd/events/YYYYMM/<id>.md` — with rich frontmatter (`event_type`, `scope`, `retrieval`,
  `temporal`, `evidence`, `safety`) and an explicit "avoid a per-month index / avoid JSONL streams" rule.
- `memory_episode_connected_components_and_events.md` (the newest, and the one the epic cites as authoritative) instead
  specifies **a directory per event** — `sdd/events/YYYYMM/<event_id>/lesson.md` — and even says the earlier events
  research is "not authoritative ... especially where this note changes the storage shape."

These layouts are incompatible (file-per-event vs dir-per-event), and the frontmatter schemas are a third variant that
only partially overlaps the earlier two (`event_type: gotcha`, `episode_ids`, `aggregate_importance_score`,
`trust: reviewed`, `privacy: repo_safe` vs the earlier `retrieval`/`temporal`/`scope` blocks). Before any `sdd/events/`
code is written, these must be reconciled into one schema and one layout. Right now "the plan for `sdd/events/`" is
actually three plans.

### 8. Reusing the name `lesson.md` for events while removing it from episodes is confusing

v1 episodes own `lesson.md` (a deterministic human summary). The v2 plan deletes `lesson.md` from episodes and
*reassigns the same filename* to events, where it now means "the dreamer's LLM-written pitch for a reusable lesson."
Same filename, opposite trust level (deterministic projection → LLM-authored argument) and opposite location (private
state → repo). This will mislead anyone who learned the v1 model. The earlier events research used richly-named
frontmatter cards, not a file literally called `lesson.md`. Recommendation: do not call the event body `lesson.md`; use
the event-card convention from the earlier notes so the name signals "reviewed event card," not "episode lesson."

### 9. `sdd/events/` collides with the existing `sdd/beads/events/` namespace

SASE already has `sdd/beads/events/` (operational bead event streams with reducer semantics). A top-level `sdd/events/`
for "curated project memory events" is a different concept with a near-identical path. Both earlier notes flag this and
recommend documenting it as "project memory events," but the epic doesn't resolve it. At minimum the `sdd/events/README.md`
must draw the distinction explicitly; consider whether a less-collidey name (`sdd/memory_events/`, `sdd/lessons/`) is
worth it before the directory is created and becomes hard to rename.

### 10. The retrieval surface the events plan depends on does not exist and is not in the epic

Every events note frames `sase memory search` as *the* agent-facing retrieval path for events. It does not exist today,
and `sase-48` does not build it (Phase 9 adds a one-shot `export`, not search). So `sdd/events/` as currently planned
would be a checked-in corpus with no query path — exactly the "looks tidy, doesn't help the next prompt" failure the
notes themselves warn against. The dependency should be made explicit: either `sase memory search` is a prerequisite for
the events track, or the events track must ship its own retrieval. This sequencing gap is currently invisible because
events live in a separate (unplanned-as-beads) track.

### 11. The one LLM component is the safety-critical one and is furthest out / least executable

The dreamer is the sole LLM step and the sole path by which untrusted transcript text becomes repo-checked content. The
threat model for it is genuinely thorough (evidence-not-instructions framing, injection scanning, redaction, no
self-promotion, propagating `contains_untrusted_text`, human promotion gate). But it lives in the *events* track, which
`sase-48` explicitly excludes, so the most security-sensitive piece is the least specified in executable form and has no
bead. That is defensible (ship the deterministic base first), but the risk is that events get built under schedule
pressure later with the safety controls treated as optional polish. Recommendation: when the events epic is created,
make the validator/redactor/injection-scan an early phase with its own acceptance tests, not a trailing one.

## Recommendations

1. **Resolve the `sdd/events/` storage shape and frontmatter into a single canonical spec before writing any event
   code.** This is the highest-leverage cleanup; three contradictory plans is worse than one imperfect one.
2. **Decide the "unscored" representation now** (concern 1) so default-zero importance scores don't become permanent
   ambiguity on disk.
3. **Make canonical-ID selection a pure deterministic function of the component** (concern 3) so cross-machine alias
   sync is genuinely conflict-free, and write the order-independence property test in Phase 3.
4. **Externalize importance weights to project-state config with `--explain`** (concern 4), matching the search-ranking
   design instead of diverging from it.
5. **Pull a minimal pilot forward to after Phase 5** (concern 5) to validate split quality and the importance
   distribution before investing in Phases 6-8.
6. **Rename the event body away from `lesson.md`** and resolve the `sdd/events/` vs `sdd/beads/events/` namespace
   collision in the events README (concerns 8-9).
7. **Make `sase memory search` an explicit prerequisite of the events track** (concern 10), or scope retrieval into it.

## Evidence Reviewed

- `sdd/epics/202605/episode_v2_explorer.md` (sase-48, 9 phases)
- `sdd/research/202605/memory_episode_connected_components_and_events.md` (authoritative v2 design)
- `sdd/research/202605/structured_episodic_events_for_memory_search.md`
- `sdd/research/202605/git_versioned_episodic_events.md`
- `sdd/research/202605/sase_episodes_new_user_guidance.md`
- `sdd/research/202605/memory_system_prior_art.md`
- `src/sase/memory/episodes/` (v1 implementation, 20 files; no components/importance/auto_build/views)
- `src/sase/memory/cli_episodes.py`, `src/sase/main/parser_memory_episodes.py` (build/list/show/verify/recall only)
- `src/sase/core/episode_wire.py`, `src/sase/core/episode_facade.py` (v2 fields + `generate_v2_episode_id`)
- `../sase-core/crates/sase_core/src/episode/wire.rs` + `mod.rs` (schema v2, `stable_v2_episode_id`) — verified in
  `sase-core_13`
- `src/sase/main/parser_memory.py` (confirmed no `search` subcommand)
- `git log` (only `sase-48.1` landed; `sdd/events/` absent)
