# SASE Episodes New User Guidance Research

Research date: 2026-05-26

## Question

How should SASE guide a new user through using episodes?

Short answer: present episodes as a source-grounded "what happened last time?" layer under `sase memory`, not as a new
top-level product and not as automatic long-term memory. A new user should learn to build or inspect episodes only when
they need evidence about prior work, then promote durable lessons through the existing reviewed memory flow when a
lesson should affect future agents.

There is an important current-state caveat: in this workspace, `sase memory episodes` is designed in
`sdd/epics/202605/structured_episodic_memory_mvp.md`, and the core wire schema exists, but the CLI is not wired into the
current `sase memory` parser yet. `sase memory --help` currently lists only `init`, `list`, `log`, `read`, `review`, and
`write`; `sase memory episodes --help` currently fails as an invalid subcommand.

## Mental Model For New Users

An episode is not a chat transcript. It is a compact, deterministic record derived from chats, agent metadata, plans,
diffs, questions, feedback, artifacts, beads, and ChangeSpecs.

An episode is not canonical project memory. It is evidence. If the user wants a lesson to become durable guidance for
future agents, the lesson should go through `sase memory write` and `sase memory review`, with the episode and source
chat as evidence.

An episode is not a separate command family. The intended surface is:

```bash
sase memory episodes ...
```

not:

```bash
sase episodes ...
```

The simplest explanation for a new user is:

> Use episodes when you want SASE to answer, with citations, "what happened in that prior agent run or workflow?"

## Current Implementation Findings

The current codebase has Phase 1 foundations:

- `src/sase/core/episode_wire.py` defines `EpisodeWire`, `EpisodeSourceRefWire`, graph nodes/edges, timeline events,
  deterministic lessons, build reports, storage index rows, and source verification reports.
- `src/sase/core/episode_facade.py` exposes Rust-backed helpers for schema version, canonical JSON, source IDs, episode
  IDs, and source verification.
- `tests/test_core_episode_wire.py` verifies stable canonical serialization, stable episode IDs across source order, and
  source drift reporting.

The current codebase does not yet have the user-facing episode workflow:

- No `src/sase/memory/episodes/` package exists in this workspace.
- No `src/sase/memory/cli_episodes.py` exists.
- `src/sase/main/parser_memory.py` does not register an `episodes` subparser.
- `src/sase/main/memory_handler.py` does not dispatch `episodes`.

The SDD epic defines the intended storage and command contract:

```text
~/.sase/projects/<project>/episodes/
  index.jsonl
  index.lock
  <episode_id>/
    episode.json
    lesson.md
    sources.jsonl
```

`episode.json` is canonical. `lesson.md`, `sources.jsonl`, and `index.jsonl` are deterministic projections.

## Why New Users Need A Different Guide Than Implementers

The existing research is implementation-heavy: storage layout, deterministic IDs, source graphs, build phases, and
retrieval architecture. A new user guide should instead answer five practical questions:

1. When should I use episodes?
2. Which selector should I start from?
3. How do I read an episode?
4. How do I decide whether to trust it?
5. How do I turn a useful lesson into durable memory?

Do not start the docs with the schema. Put the schema behind "what gets saved" or "how verification works."

## Recommended First-Run Flow

Once the CLI exists, the first-run guide should use a single prior agent name because that is the easiest selector to
understand:

```bash
sase memory episodes build -n <agent-name>
sase memory episodes list
sase memory episodes show <episode-id>
sase memory episodes verify <episode-id>
```

Then introduce recall:

```bash
sase memory episodes recall -q "what did we learn about prompt history?"
```

The guide should tell users to read `lesson.md` first. `episode.json` is for tools, debugging, and deterministic tests;
`sources.jsonl` is for provenance review; `verify` is for deciding whether source files still match the episode record.

## Selector Guidance

New users should choose selectors in this order:

| User knows | Recommended selector | Why |
| --- | --- | --- |
| Agent name | `build -n|--agent <agent>` | Best first example; maps to visible ACE agent rows. |
| Artifact directory | `build -a|--artifact-dir <dir>` | Most precise when debugging a known run. |
| ChangeSpec | `build -c|--changespec <name>` | Best for PR/CL-oriented work with multiple agents. |
| Chat file or basename | `build -C|--chat <chat>` | Good when starting from `sase chats list/show`. |
| Date range | `build -s|--since <date> -u|--until <date>` | Useful for backfill, but should be taught later because it can produce many candidates. |

For documentation examples, avoid starting with project-wide or date-range builds. They are powerful but make the first
experience feel like data management instead of recall.

## Suggested Beginner Recipes

### Recall A Prior Fix

Use this when the user remembers the agent or task:

```bash
sase memory episodes build -n <agent-name>
sase memory episodes show <episode-id>
```

Expected behavior: show a human-readable lesson with goal, timeline, decisions, work performed, outcome, lessons, and
source links.

### Check Whether An Episode Is Still Trustworthy

Use this before relying on an old episode for current work:

```bash
sase memory episodes verify <episode-id>
```

Expected behavior: report whether source paths still exist and whether file sizes/hashes match. Changed or missing
sources do not invalidate the whole episode automatically; they tell the user to treat the lesson as historical evidence
that may need rereading.

### Find Related Prior Work

Use this when the user knows the topic but not the agent:

```bash
sase memory episodes recall -q "retry chain prompt feedback"
```

Expected behavior: return compact cards with `episode_id`, title, matching lesson text, and evidence links. Recall
should be explicit, not automatically injected into every future prompt until prompt augmentation is separately proven.

### Promote A Durable Lesson

Use this only after the user decides an episode contains a reusable rule:

```bash
sase memory write \
  --title "Prompt history fanout rule" \
  --slug prompt_history_fanout \
  --evidence ~/.sase/projects/<project>/episodes/<episode-id>/episode.json \
  --evidence chat:<chat-id> \
  --body "..."

sase memory review --list
```

The exact evidence syntax may need CLI polish, but the principle should remain: durable memories are reviewed proposals,
not automatic episode side effects.

## What To Tell Users Not To Do

Do not edit `episode.json` by hand. Rebuild from sources instead.

Do not treat an episode lesson as a rule for all future work. It is a grounded observation from one run.

Do not commit raw generated episodes to the repo. Prior research recommends keeping broad episode collection in project
state under `~/.sase/projects/<project>/episodes/` and committing only curated, reviewed event/memory artifacts when
they are explicitly useful to the project.

Do not expect `sase episodes`. The command should stay under `sase memory episodes` so memory, recall, review, and
promotion remain one product surface.

Do not use episodes as a replacement for `sase chats show`, SDD research, ChangeSpecs, or beads. Episodes are an index
and lesson layer over those sources.

## Trust And Safety Guidance

The user guide should make provenance visible early:

- Every lesson should cite evidence IDs.
- `show` should default to `lesson.md`, but the output should expose the source list or a clear command to inspect it.
- `verify` should be part of the first-page workflow, not an advanced appendix.
- Prompt-injection and untrusted transcript content should remain evidence, not instructions.
- Episode recall should return citations and snippets, not silently rewrite future prompts.

For new users, the practical rule is:

> If an episode says something important, open the evidence before turning it into memory.

## Recommended CLI Help Shape

The `sase memory episodes --help` text should be task-oriented:

```text
Build, inspect, verify, and recall source-grounded records of prior SASE work.

Episodes are deterministic evidence records under ~/.sase/projects/<project>/episodes/.
They do not modify memory/short or memory/long. Use `sase memory write` to propose
durable memory from an episode.

examples:
  sase memory episodes build -n <agent>
  sase memory episodes list
  sase memory episodes show <episode-id>
  sase memory episodes verify <episode-id>
  sase memory episodes recall -q "what did we learn about retries?"
```

Avoid help text that starts with implementation details such as source refs, graph edges, or canonical JSON. Those are
important, but they belong in `show --format json`, `verify`, or developer docs.

## Recommended Output Defaults

`build` should print the episode ID, title, lesson path, source count, lesson count, and whether it wrote or reused an
existing episode. JSON output should remain stable for automation.

`list` should show recent episodes with title, outcome, root agent, ChangeSpec/bead if known, first/last event time, and
source count. It should not dump source paths by default.

`show` should default to `lesson`, with explicit formats:

```bash
sase memory episodes show <episode-id> --format lesson
sase memory episodes show <episode-id> --format timeline
sase memory episodes show <episode-id> --format sources
sase memory episodes show <episode-id> --format json
```

The epic mentions `show` formats but not the exact option spelling. Use a single option such as `-F|--format` and keep
values stable.

`verify` should be concise by default and detailed under `-j|--json` or a future verbose flag.

`recall` should return enough context to decide whether to open the episode, not enough to replace opening it.

## Product Positioning

For onboarding, episodes should sit between chats and memory:

```text
raw chats/artifacts -> episodes -> recall cards -> reviewed memory proposals
```

This positioning solves a specific user problem:

- Raw chats are too long and fragmented.
- Long-term memory is too important to write automatically.
- Episodes provide searchable, source-linked intermediate evidence.

That is the core message for a new user.

## Documentation Placement

Recommended docs/pages after implementation:

1. A short `docs/episodes.md` or README section titled "Episodes".
2. CLI examples in `sase memory episodes --help`.
3. A "Promote a lesson to memory" subsection that points to `sase memory write/review`.
4. A troubleshooting subsection for "no episode found", "source changed", and "recall found stale evidence".

Do not bury episodes only inside the structured memory epic. The epic is correct for implementers but too deep for
first-use learning.

## Current-State Guidance Until The CLI Lands

Because the CLI is not available in this workspace yet, a new user today should use the existing lower-level surfaces:

```bash
sase chats list
sase chats show <chat-id-or-path>
sase memory write --title "..." --slug ... --evidence chat:<chat-id> --body "..."
sase memory review --list
```

This is not equivalent to episodes, but it preserves the same safety model: inspect source evidence first, then propose
durable memory through review.

When episode CLI work lands, the docs should explicitly replace the "start from chat" path with "build/show/verify an
episode, then propose memory from the cited lesson."

## Open Questions

- Should `build` default to writing, or should the first documented command use `--dry-run`? The epic says it writes
  unless `--dry-run`; user onboarding may still want a first example that builds for real because the storage location is
  outside the repo.
- Should `show` accept partial episode ID prefixes? New users will expect this if memory proposal review already accepts
  unambiguous prefixes.
- Should `list` default to the current project only? It should, unless `-p|--project` explicitly names another project.
- Should `recall` search private episodes only, curated events only, or both? For first release, keep it to stored
  project episodes and make any later `sdd/events` bridge explicit.
- Should docs call them "episode lessons" or "lesson cards"? Use "episode" for the whole record and "lesson" for the
  human-readable projection to avoid conflating data and presentation.

## Recommendation

Build the new-user guide around a small loop:

1. Build from a known agent.
2. Show the lesson.
3. Verify the evidence.
4. Recall by topic when the agent is unknown.
5. Promote only reviewed, reusable lessons into long-term memory.

Keep the wording disciplined: episodes are evidence records, not memory rules; `lesson.md` is the human view, not the
source of truth; `episode.json` is canonical; and the command belongs under `sase memory episodes`.

## Evidence Reviewed

- `sdd/epics/202605/structured_episodic_memory_mvp.md`
- `sdd/research/202605/structured_episodic_agent_chat_memory.md`
- `sdd/research/202605/structured_episodic_memory_for_agent_chats.md`
- `sdd/research/202605/structured_episodic_events_for_memory_search.md`
- `sdd/research/202605/git_versioned_episodic_events.md`
- `src/sase/core/episode_wire.py`
- `src/sase/core/episode_facade.py`
- `tests/test_core_episode_wire.py`
- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
