---
create_time: 2026-05-26 18:32:23
status: done
bead_id: sase-45
tier: epic
prompt: sdd/prompts/202605/structured_episodic_memory_mvp.md
---
# Structured Deterministic Episodic Memory MVP

## Problem

SASE already records most of the raw material needed for durable agent memory: agent artifact directories under
`~/.sase/projects/<project>/artifacts/`, chat transcripts under `~/.sase/chats/`, plan paths, QA and feedback logs,
retry lineage, workflow step markers, ChangeSpec metadata, bead metadata, diffs, PDFs, images, notifications, and
audited long-term memory reads.

What is missing is a deterministic project-scoped layer that turns those fragments into a replayable episode: one
coherent lesson with a traceable evidence graph, stable IDs, source hashes, and a command surface that future agents and
UIs can read without reverse-engineering every artifact format.

The MVP should store episodes under:

```text
~/.sase/projects/<project>/episodes/
```

Any command added for this feature must live under:

```text
sase memory episodes
```

not `sase episodes`.

## Research Grounding

This design borrows these ideas, but keeps the write path deterministic and source-grounded:

- Generative Agents stores a complete natural-language record of experience, reflects over it, and retrieves memories
  for later planning. SASE should similarly preserve complete evidence and render a higher-level lesson, but without an
  LLM-only source of truth. https://arxiv.org/abs/2304.03442
- Reflexion uses an episodic memory buffer of verbal lessons from feedback and failures to improve later trials. SASE
  should make feedback, questions, retries, failures, and accepted plans first-class lesson evidence.
  https://arxiv.org/abs/2303.11366
- MemGPT frames memory as tiered context management with explicit movement between short and long-term stores. SASE
  episodes should be a project-scoped long-term store that can later feed deterministic recall into prompts.
  https://arxiv.org/abs/2310.08560
- Voyager shows the value of persistent, compositional learned artifacts and execution-error feedback. SASE episodes
  should connect chats to plans, diffs, files, tests, and artifacts rather than storing chat text alone.
  https://arxiv.org/abs/2305.16291
- Recent surveys organize agent memory as a write-manage-read loop and call out write filtering, provenance,
  contradiction handling, latency budgets, and evaluation. This MVP should treat episodes as a schema-versioned
  derivative of auditable sources, not as an opaque summary blob. https://arxiv.org/abs/2404.13501
  https://arxiv.org/abs/2603.07670

## Product Contract

An episode is a deterministic, rebuildable project-scoped record with:

- A stable `episode_id` derived from project name, root source identity, and canonical source refs, not from wall-clock
  generation time.
- A structured graph of source nodes and edges: `agent_run`, `chat`, `plan`, `question`, `feedback`, `artifact`,
  `changespec`, `bead`, `commit`, `memory_read`, `dynamic_memory`, `retry`, and `workflow_step`.
- A sorted timeline of events derived from artifact timestamps, marker timestamps, chat timestamps, plan approval
  timestamps, and terminal markers.
- Source refs with path, kind, size, and SHA-256 where the source is a file.
- Deterministic lesson records. No LLM call should be required to build or verify an MVP episode.
- A rendered `lesson.md` that is useful to agents and humans while preserving source links back to chats/artifacts.
- A machine-readable `episode.json` that is the canonical data format.
- A project-level `index.jsonl` for fast list/show/recall operations.

Episode storage layout:

```text
~/.sase/projects/<project>/episodes/
  index.jsonl
  index.lock
  <episode_id>/
    episode.json
    lesson.md
    sources.jsonl
```

`episode.json` is canonical. `lesson.md`, `sources.jsonl`, and `index.jsonl` are deterministic render/index projections
that can be rebuilt from `episode.json` and the current source tree.

## Determinism Rules

- Sort every collection by stable keys before serialization.
- Serialize canonical JSON with stable key order and a trailing newline.
- Do not include current wall-clock time in `episode_id` or deterministic content hashes. If a build time is useful,
  place it in a non-identity field and do not use it for equality tests.
- Prefer source timestamps over filesystem mtimes for chronology.
- Never infer a lesson that lacks explicit evidence. Store each lesson with `evidence_ids`.
- Preserve missing/deleted sources as refs with `exists=false`; verification should report drift, not silently rewrite
  history.
- Avoid copying full chat transcripts into episodes for the MVP. Store hashes, bounded excerpts, parsed turns, and
  source paths. Add full source snapshots later only behind an explicit flag.

## Episode Builder Inputs

Use as much existing SASE metadata as possible:

- Rust-backed agent scan records from `sase.core.agent_scan_facade.scan_agent_artifacts` / `query_agent_artifact_index`.
- `agent_meta.json`: name, family, role suffix, parent timestamps, plan chain flags, model/provider, bead IDs,
  ChangeSpec name, SDD prompt/plan paths, retry fields, question fields, wait fields, sibling repo data.
- `done.json`: outcome, finished time, response path, plan/diff paths, images, PDF paths, output path, error/traceback,
  retry links.
- `workflow_state.json` and `prompt_step_*.json`: embedded workflow step structure and child chat paths.
- `raw_xprompt.md`, `submitted_xprompt.md`, `followup_prompt*.md`.
- `plan_path.json`, plan files, SDD prompt/plan files.
- `plan_feedback.jsonl`, `qa_log.jsonl`, pending/response question artifacts.
- `dynamic_memory.json` and audited `memory_reads.jsonl`.
- `~/.sase/chats/**.md`, including `## Linked Chats` and `#fork` / `#fork_by_chat` references.
- ChangeSpec `.sase`/`.gp` current and archive files, including COMMITS drawer chat lines.
- Bead issue/event data when bead IDs are present in agent metadata.
- Explicit/default artifacts indexed through `sase.core.agent_artifact_*`.

## Lesson Shape

`lesson.md` should be rendered from structured fields, not hand-written by the builder:

```markdown
# <Episode Title>

## Summary

<deterministic one-paragraph summary from goal, agents, and outcome>

## Goal

- Prompt: <source-linked prompt excerpt>
- ChangeSpec: <name/status if known>
- Plan/Bead: <ids or links if known>

## Timeline

- <timestamp> <event> [evidence]

## Decisions And Feedback

- <plan approval / user feedback / Q&A fact> [evidence]

## Work Performed

- Files/artifacts/diffs/plans touched [evidence]

## Outcome

- Status, tests/checks mentioned, errors, retry result [evidence]

## Lessons

- <deterministic observation with evidence ids>

## Sources

- <chat/artifact/plan/diff refs with hashes>
```

Lesson records in `episode.json` should include at least:

- `id`
- `kind`: `goal`, `decision`, `feedback`, `question_answer`, `implementation`, `verification`, `failure`, `retry`,
  `artifact`, `memory_context`, `open_question`
- `text`
- `evidence_ids`
- `source_confidence`: initially always `"deterministic"`

## Phase 1 - Core Episode Schema And Canonicalization

Owner: one agent instance.

Write scope:

- `../sase-core/crates/sase_core/src/episode/*`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/episode_wire*.py`
- `src/sase/core/episode_facade.py`
- Core/Python wire parity tests.

Tasks:

1. Add Rust wire structs for episode nodes, edges, events, lessons, source refs, build requests, build reports, storage
   index rows, and verify reports.
2. Add canonical serialization and hash helpers that produce stable source IDs and episode IDs from ordered source refs.
3. Expose PyO3 functions for:
   - canonical episode JSON serialization
   - source/episode ID generation
   - lightweight verification helpers
4. Mirror the wire dataclasses in Python, following existing `agent_scan_wire` and `*_wire_conversion.py` patterns.
5. Add parity tests in `sase-core` and Python so schema drift fails loudly.

Exit criteria:

- Rust tests pass for the new episode module.
- Python tests can round-trip a fixture episode through Rust/Python JSON.
- No CLI or storage behavior yet.

## Phase 2 - Source Graph Collector

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/collector.py`
- `src/sase/memory/episodes/chat_parse.py`
- `src/sase/memory/episodes/source_refs.py`
- focused tests under `tests/test_memory_episodes_*`.

Tasks:

1. Build a collector that starts from one of:
   - named agent
   - artifact directory
   - ChangeSpec name
   - chat path/basename
   - date range/project scan
2. Resolve the connected component using deterministic edges:
   - agent family/root/role suffix
   - parent timestamps and retry links
   - `done.response_path` / `agent_meta.chat_path`
   - `prompt_step_*.json.response_path`
   - chat `## Linked Chats`
   - `#fork` and `#fork_by_chat` references
   - plan/QA/feedback/source artifacts
   - ChangeSpec COMMITS chat refs
   - bead IDs from metadata
3. Parse chat transcripts with the existing chat parser where possible, but return structured turn refs and bounded
   excerpts rather than full bodies.
4. Record source refs for every file touched by the graph with SHA-256, byte count, existence, and kind.
5. Produce an in-memory `EpisodeDraft`/wire object, but do not persist it.

Exit criteria:

- Tests cover plan-chain chats, feedback rounds, Q&A rounds, retry chains, deleted/missing sources, and ChangeSpec chat
  refs.
- Collector output is byte-for-byte stable across two runs on the same fixture.

## Phase 3 - Deterministic Lesson Builder And Renderer

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/builder.py`
- `src/sase/memory/episodes/render.py`
- `src/sase/memory/episodes/title.py`
- `src/sase/memory/episodes/verify.py`
- renderer/builder tests.

Tasks:

1. Convert collector graphs into canonical `EpisodeWire` records.
2. Derive title, summary, timeline, and lesson records using deterministic rules only:
   - goal from earliest submitted/raw prompt or plan title
   - decisions from plan approval state, feedback logs, Q&A, and plan action
   - implementation from diff/plan/artifact refs
   - verification from recognized commands/results in chats/output when explicit
   - failures/retries from done marker error fields and retry lineage
   - memory context from dynamic memory and audited memory reads
3. Render `lesson.md` from `EpisodeWire`.
4. Add verification that recomputes source hashes and reports missing/changed sources without mutating the episode.
5. Keep renderer resilient: missing optional sections are omitted; evidence links remain valid for missing sources.

Exit criteria:

- Golden tests for `episode.json` and `lesson.md` pass.
- No nondeterministic fields appear in golden snapshots.
- Lessons always carry evidence IDs.

## Phase 4 - Project Episode Storage

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/storage.py`
- `src/sase/memory/episodes/index.py`
- `src/sase/memory/episodes/locks.py` if needed, or reuse `sase.memory.locks`
- storage tests.

Tasks:

1. Implement atomic writes under `~/.sase/projects/<project>/episodes/<episode_id>/`.
2. Write `episode.json`, `lesson.md`, and `sources.jsonl`.
3. Maintain `episodes/index.jsonl` under a lock. Index rows should include `episode_id`, title, project, root agents,
   ChangeSpec, bead IDs, outcome, first/last event timestamps, source count, lesson path, and content hash.
4. Support idempotent rebuilds:
   - identical source graph rewrites the same directory with identical content
   - changed sources update the same episode if the root identity is unchanged
   - conflicting roots produce distinct episode IDs
5. Add storage GC helpers only for clearly corrupt temp dirs; do not delete user-visible episode dirs in MVP.

Exit criteria:

- Concurrent write tests validate locking and atomicity.
- Rebuilding a fixture twice produces the same files and index row.

## Phase 5 - `sase memory episodes` CLI

Owner: one agent instance.

Write scope:

- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- `src/sase/memory/cli_episodes.py`
- CLI tests.

Tasks:

1. Add nested command group `sase memory episodes`.
2. MVP subcommands:
   - `build`: build one or more episodes from selectors.
   - `list`: list stored episodes.
   - `show`: show `lesson`, `json`, `sources`, or `timeline`.
   - `verify`: verify source hashes/existence for one episode or all.
   - `recall`: deterministic keyword/query recall over stored lesson text and structured lesson records.
3. Ensure every option has both long and short names.
4. Suggested option surface:
   - `build -p|--project PROJECT`
   - `build -n|--agent AGENT`
   - `build -a|--artifact-dir DIR`
   - `build -c|--changespec NAME`
   - `build -C|--chat CHAT`
   - `build -s|--since DATE`
   - `build -u|--until DATE`
   - `build -l|--limit N`
   - `build -D|--dry-run`
   - `build -f|--force`
   - all relevant subcommands: `-j|--json`
5. Pretty output should be concise and script output should be stable JSON.
6. The command must not modify canonical `memory/short` or `memory/long` files.

Exit criteria:

- `sase memory episodes --help` shows the nested group.
- `sase memory episodes build -n <agent> -j` emits deterministic JSON and writes the episode unless `--dry-run` is set.
- `list`, `show`, `verify`, and `recall` work on fixture data.

## Phase 6 - Write-Path Metadata Hints

Owner: one agent instance.

Write scope:

- `src/sase/axe/run_agent_exec_finalize.py`
- `src/sase/axe/run_agent_exec_plan.py`
- `src/sase/axe/run_agent_helpers_artifacts.py`
- `src/sase/axe/run_agent_helpers_handoff.py`
- marker/update tests.

Tasks:

1. Add an optional lightweight `episode_trace.json` marker in each agent artifact dir. It should duplicate only stable
   linking hints that are hard to recover later:
   - artifact timestamp
   - agent name/family/role
   - parent/root timestamps
   - current chat path
   - plan path
   - feedback/QA artifacts
   - retry parent/child pointers
   - source ChangeSpec/bead IDs
2. Write/update the marker wherever chats are saved and follow-up artifact dirs are created.
3. Extend the Rust scanner/Python wire only if the collector needs this marker for efficient future scans. If not needed
   for MVP, let the collector read it directly and keep scan schema untouched until Phase 7.
4. Do not auto-build episodes in the runner yet unless the earlier phases make that safe and fast. Prefer recording
   hints first; auto-build can be gated by config later.

Exit criteria:

- Existing finalization tests still pass.
- New tests prove the collector prefers `episode_trace.json` when present and falls back to old artifacts when absent.
- No runtime-specific branching.

## Phase 7 - Deterministic Recall Integration

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/recall.py`
- `src/sase/memory/dynamic.py`
- `src/sase/axe/run_agent_runner_setup.py` if prompt injection is added
- tests for recall and prompt augmentation.

Tasks:

1. Implement `sase memory episodes recall -q|--query QUERY -l|--limit N`.
2. Use deterministic lexical scoring first:
   - token overlap with title, summary, lesson text, source labels, ChangeSpec, bead IDs, file paths, and tags
   - recency and outcome as tie-breakers only after lexical score
3. Return compact lesson cards with evidence links and episode IDs.
4. Optionally add prompt augmentation behind config/env only after CLI recall is stable. Keep default behavior unchanged
   for the MVP unless explicitly enabled.
5. If dynamic memory integration is enabled, write an artifact recording which episodes were injected.

Exit criteria:

- Recall output is stable across runs.
- Prompt augmentation is opt-in and recorded as an artifact.

## Phase 8 - End-To-End Fixtures, Docs, And Validation

Owner: one agent instance.

Write scope:

- `tests/fixtures/memory_episodes/**`
- `tests/test_memory_episodes_e2e.py`
- `sdd/tales/202605/structured_episodic_memory_mvp.md` or equivalent SDD artifact if the implementation workflow
  requires it
- README/help text updates where appropriate.

Tasks:

1. Build a fixture with:
   - planner chat
   - feedback round
   - questions round
   - coder chat
   - retry/failure variant
   - plan file
   - diff artifact
   - ChangeSpec with COMMITS chat refs
   - bead metadata
   - dynamic memory and audited memory read rows
2. Add end-to-end tests:
   - build episode from agent
   - build episode from ChangeSpec
   - build episode from chat
   - list/show/verify/recall
   - deleted source verification
3. Update CLI help/docs with examples.
4. Run `just install` and `just check` in this repo after implementation file changes. If any phase touches `sase-core`,
   also run the relevant Rust tests there before returning.

Exit criteria:

- The whole MVP can be demonstrated with:

```bash
sase memory episodes build -n <agent>
sase memory episodes list
sase memory episodes show <episode-id>
sase memory episodes verify <episode-id>
sase memory episodes recall -q "what did we learn about <topic>"
```

## Suggested Implementation Order

1. Phase 1 and Phase 2 should happen before any CLI work. The data contract and collector determine every later surface.
2. Phase 3 and Phase 4 can run after Phase 2, but should coordinate on the exact `EpisodeWire` shape from Phase 1.
3. Phase 5 depends on Phases 2-4.
4. Phase 6 can run after Phase 2; it should not block the MVP because the collector must support historical artifacts.
5. Phase 7 depends on persisted lessons from Phase 4 and CLI plumbing from Phase 5.
6. Phase 8 should run last and may adjust small gaps in earlier phases, but should not change the core schema without
   looping back to Phase 1 tests.

## Non-Goals For The MVP

- No LLM-generated summaries as canonical episode state.
- No automatic writes to `memory/short` or `memory/long`.
- No top-level `sase episodes` command.
- No mandatory auto-build during every agent finalization until latency and lock contention are measured.
- No vector database dependency.
- No deletion of existing chats/artifacts as part of episode GC.
- No runtime-specific behavior for Claude/Gemini/Codex/Qwen/OpenCode.

## Risk Notes

- Chat transcript parsing has historical formats and sharding. Reuse `sase.history.chat` and `sase.history.chat_catalog`
  where possible, then add compatibility tests instead of broad rewrites.
- The artifact scanner is Rust-backed and shared by the TUI. Schema changes must update both `sase-core` and Python wire
  mirrors in lockstep.
- Episodes are derivative, but they will become trusted memory. Every lesson must be source-grounded with evidence IDs
  and verification status.
- Large source graphs can be expensive. Start with bounded traversal from explicit selectors, then add project-wide
  batch builds after indexing is proven.
- The repo memory says to run `just install` before `just check` after implementation changes in this workspace.
