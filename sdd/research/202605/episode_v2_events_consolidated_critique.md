---
create_time: 2026-05-28
status: research
bead_id: sase-48
---

# Consolidated Critique: Episode V2 And `sdd/events/`

## Question

What is the current state and trajectory of SASE memory episodes, using the `sase-48` epic bead as the breadcrumb? Are
there concerning architectural problems? Are the plans for `sdd/events/` sound?

## Scope

This consolidates the two prior research drafts produced from these agent transcripts:

- `~/.sase/chats/202605/sase-ace_run-260528_175938.md`
- `~/.sase/chats/202605/sase-ace_run-260528_175939.md`

The prior drafts were useful, but they were already stale in one important way: Phase 2 has now landed. This note
re-verified the current checkout, the `sase-48` bead state, the governing episode/events research, and the code paths
before making recommendations.

## Short Answer

The direction is right: keep high-volume private episodes as deterministic source-linked evidence, then promote only a
small reviewed subset into portable project memory under `sdd/events/`. The architectural risk is not the destination;
it is the transition state.

As of this checkout, SASE has:

- v2 Rust/Python wire compatibility from Phase 1;
- a new Python connected-component planner from Phase 2;
- the old user-facing build/storage/recall path still writing one aggregate episode with `lesson.md`;
- no member/alias identity layer yet;
- no v2 no-lesson storage path yet;
- no `sdd/events/` directory and no `sase memory search`.

The most concerning new finding is that the landed Phase 2 component keys still include normalized absolute artifact or
chat paths. That is acceptable for an internal planning key, but not for the durable `component_key` that feeds
`stable_v2_episode_id(project, component_key)`. If persistent v2 episodes are written before this is fixed, IDs can be
machine-, home-dir-, or workspace-root-dependent.

## Verified Current State

`sase bead show sase-48` now reports:

- `sase-48.1` closed: v2 wire contract and compatibility;
- `sase-48.2` closed: connected component planner;
- `sase-48.3` through `sase-48.9` in progress.

The local git history agrees that Phase 2 exists: `df403f3c8 feat: add episode component planner (sase-48.2)`. The bead
notes currently say `COMMIT: 92c9e9f0e`, which is not a valid object in this checkout. That looks like stale or
workspace-local bead metadata, not an episode architecture problem, but it is worth correcting because the bead is the
breadcrumb for this work.

The matching Rust core workspace is `sase-core_12`, opened via `sase workspace open -p sase-core 12`. It contains
`123f0a7 feat: add episode v2 wire contract (sase-48.1)`. `crates/sase_core/src/episode/wire.rs` has
`EPISODE_WIRE_SCHEMA_VERSION = 2`, v2 fields such as `component_key`, `status`, `importance_score`, `importance_band`,
`importance_factors`, `safety`, and `weak_refs`, plus `stable_v2_episode_id(project, component_key)` in `mod.rs`.

The Phase 2 planner exists in `src/sase/memory/episodes/components.py`. Its tests prove the two most important initial
properties:

- unrelated same-date records with the same ChangeSpec, bead, and agent family split into separate component plans;
- a date-window seed pulls an out-of-window parent/fork through strong lineage.

The active CLI is still v1-shaped:

- `sase memory episodes build` still calls `collect_episode_draft(...)`, `build_episode(...)`,
  `render_lesson_markdown(...)`, and `write_project_episode(...)` once per invocation.
- The parser still exposes only `build`, `list`, `show`, `verify`, and `recall`; there is no `--split`, `auto`,
  `status`, `doctor`, inventory, graph view, or export path yet.
- `storage.write_project_episode` always writes `episode.json`, `lesson.md`, and `sources.jsonl`.
- `recall` still reads `lesson_path`/`lesson.md` and searches lesson text.
- `sase memory search` is not registered under `sase memory`.
- `sdd/events/` does not exist.

So "schema v2" currently means "v2-capable wire," not "the product is producing v2 semantic episodes."

## What Is Solid

The core model should stay:

- Date windows should select seeds only. Strong runtime lineage should define episode membership.
- ChangeSpec, bead, family, touched path, and date co-occurrence should be weak metadata, not merge criteria.
- Private episodes should be deterministic evidence, not LLM-authored lessons or instructions.
- Curated `sdd/events/` should be rare, reviewed, repo-safe project memory.
- Durable procedural guidance should still go through `sase memory write` and `sase memory review`, with events serving
  as evidence rather than bypassing the memory gate.

Phase 2 is also a real step forward. The planner is not just a design note now; it has a DTO, strong-edge extraction,
weak refs, component-scoped draft collection, byte-stability tests, and the right initial split behavior.

## Architectural Concerns

### 1. Durable Component Keys Are Not Durable Enough Yet

The current `_component_root(...)` builds component keys like:

```text
component/artifact/<project>/<timestamp>/<normalized absolute artifact path>
component/chat/<normalized absolute chat path>
```

Those paths come from `normalize_source_path(...)`, which resolves to an absolute path. That makes sense for verifying a
local source file, but it is not safe as the durable identity input to `stable_v2_episode_id`. Two machines, home
directories, project-state roots, or restored artifacts can compute different IDs for the same logical episode.

This should be fixed before Phase 3 or Phase 4 writes persistent v2 episodes. Component keys should use stable logical
member keys such as project name, workflow dir, timestamp, runtime-written retry/workflow/root identifiers, and chat
basenames or content hashes. Absolute paths can remain source refs and evidence, but not identity.

Tests should prove:

- component keys are independent of `projects_root`;
- the same fixture under two temp roots yields the same `component_key` and v2 episode ID;
- chat-only components do not use absolute chat paths as canonical roots.

### 2. V2 Wire And Planner Exist, But Product Semantics Are Still V1

The code can now create v2-ish episodes if a caller supplies `component_key` metadata: `build_episode(...)` will use
`generate_v2_episode_id(...)`. But the public build command does not call the planner, and storage still writes a
lesson. A downstream surface could see `schema_version = 2` and assume it has a connected, no-lesson, importance-scored
episode when it is really an aggregate v1-style record with v2 default fields.

Consumers need an explicit semantic contract, not just a schema version:

- component-backed episode;
- stable path-independent `component_key`;
- `lessons=[]`;
- no v2 `lesson.md`;
- non-unknown importance only after scoring runs;
- alias/member resolution available.

Until then, "schema 2" should be treated as a compatibility envelope only.

### 3. The Identity/Alias Layer Is Still The Hardest Phase

Phase 3 is where the design either becomes stable or gets expensive to repair. It must handle member indexes,
aliases, late bridges, v1 freeze, prefix resolution, and read-path alias resolution before UI or automatic worker code
relies on IDs.

The prior drafts correctly flagged cross-machine canonical selection. The rule should be explicit: canonical ID
selection must be a pure deterministic function of the logical component, not write order. Otherwise two synced
machines can choose different winners for the same late bridge and produce alias cycles.

The Phase 2 planner currently chooses the earliest artifact path/timestamp as the root. That is deterministic for a full
component, but it is not the root-priority policy described in the research: retry root, workflow root, parent/fork
target, artifact timestamp, then chat-only fallback. Phase 3 should own this rule and add order-independence property
tests.

### 4. `lesson.md` Is Still A Zombie Contract

The v2 design says private episodes should stop owning `lesson.md`. The current storage/index/recall/show path still
centers it:

- `write_project_episode` always writes `lesson.md`;
- index rows always contain `lesson_path`;
- recall reads lesson text;
- `show` defaults to the lesson projection when present.

This is fine for v1 compatibility, but dangerous as a convenience contract. New v2 tests should fail if a component
episode writes `lesson.md`, and v2 read paths should search title, summary, timeline, source labels, weak refs, safety,
and importance factors instead of lesson text.

The same concern applies to events: reusing `lesson.md` for `sdd/events` while deleting it from private episodes will
confuse trust boundaries unless the event format is very explicit.

### 5. Importance Defaults And Ranking Weights Need A Contract

The v2 wire defaults `importance_score` to `0` and `importance_band` to `unknown`. `unknown` is a good sentinel; `0`
is ambiguous once scoring exists. Search, listing, and worker logic should never rank on score when band is `unknown`,
or the schema should use a nullable score / explicit `scored` flag.

The proposed importance weights are deterministic, which is good, but they should not become magic constants. Existing
memory-search research recommends configurable ranking weights plus `--explain`. Episode importance should follow that
pattern so tuning does not require code changes and users can audit why an episode was ranked high.

### 6. The Rust Core Boundary Is Only Partially Satisfied

Phase 1 correctly put shared wire and ID helpers in `sase-core`. Phase 2 put component planning in Python. That may be
pragmatic while the planner is close to Python artifact scanning and chat parsing, but the stable semantics are shared
backend behavior: strong-edge classification, weak-ref classification, canonical root selection, component-key
normalization, and event frontmatter validation/search should not drift across CLI, TUI, editor, mobile, and future web
frontends.

The immediate fix does not have to be "rewrite the planner in Rust." A reasonable intermediate gate is to move pure
identity normalization helpers into `sase-core`, or at least pin cross-language/golden fixtures for component keys and
canonical IDs before writing persistent v2 records.

### 7. Parallel Phase State Still Creates Contract Risk

The epic preclaimed all phases and still shows phases 3-9 in progress. The dependencies are linear. If agents are
actually implementing downstream phases before Phase 3 and Phase 4 settle, expect churn around JSON shapes, ID
resolution, index rows, and UI assumptions.

If "in progress" only means "preclaimed by the epic runner," add that to bead notes. If downstream agents are really
working concurrently, gate merges so Phase 5+ cannot depend on provisional component IDs, lesson paths, or missing alias
semantics.

### 8. Worker And TUI Plans Need Hard Performance/Transaction Gates

The background worker will mutate shared project state under `~/.sase/projects/<project>/episodes/` from many ephemeral
workspaces. The existing lock/atomic-write pattern is good, but Phase 8 needs one transaction boundary covering episode
upsert, members, aliases, index, and checkpoint advancement. A checkpoint that advances without durable member/alias
state can permanently skip seeds.

The TUI explorer should read cached projections/index rows on the event loop. It must not synchronously open and parse
every `episode.json`, hash source files, or traverse chat graphs while rendering. This repo has enough TUI performance
history that "no event-loop filesystem scan" should be a gating acceptance criterion.

## `sdd/events/` Assessment

The `sdd/events/` idea is worth keeping if it remains a curated project memory layer:

```text
raw chats/artifacts
  -> private connected episodes
  -> reviewed project memory events under sdd/events/
  -> optional memory/long proposal using the event as evidence
```

The unresolved problem is that the current notes define multiple incompatible event formats.

Two earlier notes recommend one markdown file per event:

```text
sdd/events/YYYYMM/<YYYYMMDD>-<slug>-<short-hash>.md
```

The newer connected-components note changes that to a directory per event:

```text
sdd/events/YYYYMM/<event_id>/lesson.md
```

It also changes the frontmatter shape. This is not just bikeshedding. The parser, validator, search index, promotion
workflow, Git merge behavior, and user mental model all depend on the path contract.

My recommendation is to start with one reviewed markdown card per event. It is easier to diff, easier to search, easier
to link, and less likely to recreate the confusing `lesson.md` contract. Use directory-per-event only if v1 will
actually store sibling artifacts such as redaction reports, validation reports, or source manifests.

Before any event code lands:

- write `sdd/events/README.md` with the canonical path and frontmatter contract;
- make clear that `sdd/events/` means "curated project memory events," not operational event streams like
  `sdd/beads/events/`;
- implement parser/validator/search before promotion automation;
- make `sase memory search` the retrieval path, since it does not exist today;
- keep event proposals in project state until review;
- require safety fields for untrusted transcript text, injection hits, redaction hits, privacy, and evidence;
- never auto-inject event bodies into prompts as instructions.

The dreamer should remain a later, gated producer of proposals only. It is the only LLM step and the security-critical
step, so the validator/redactor/injection-scan should be an early phase of the events epic, not cleanup work after event
promotion already exists.

## Recommended Next Moves

1. Fix Phase 2 component-key identity before persistent v2 writes. Remove absolute paths from durable `component_key`
   values and add project-root-independence tests.
2. In Phase 3, define canonical winner selection as a pure component function and add order-independence tests for late
   bridges and aliases.
3. Treat schema v2 as a compatibility envelope until component-backed, alias-aware, no-lesson writes exist. Add tests
   for this semantic distinction.
4. Keep the public build path aggregate-compatible until `--split` has stable IDs; then expose split builds with JSON
   that returns multiple component build reports.
5. Decide the unscored representation before scoring lands. Do not let `importance_score = 0` mean both unknown and
   genuinely zero.
6. Externalize importance weights and add `--explain` output for ranking/scoring decisions.
7. Pull a small pilot forward after Phase 5: split a real May 2026 date window, inspect component quality, and confirm
   the importance histogram is not degenerate before investing further in TUI/worker work.
8. Start the events track with a spec, validator, and `sase memory search`, not with dreamer-generated repo writes.
9. Correct the `sase-48.2` bead note to point at the actual landed commit, or at least remove the invalid commit hash.

## Bottom Line

The episode v2 architecture is on the right track, and Phase 2 materially improves the foundation. The system is still
in a dangerous middle state: v2 fields exist, component planning exists, but the active product still behaves like v1
and the newly landed component keys are not yet safe durable IDs.

Fix identity before storage, remove the lesson contract before recall/export/UI depend on it, and settle the
`sdd/events/` format before building promotion machinery. If those gates hold, `sdd/events/` can become useful curated
memory. If they do not, it will turn noisy generated summaries into repo-backed false confidence.
