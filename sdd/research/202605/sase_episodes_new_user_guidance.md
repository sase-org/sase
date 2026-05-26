---
create_time: 2026-05-26
status: research
bead_id: sase-45
---

# SASE Episodes New User Guidance Research

## TL;DR For A New User

If a reader only sees the first screen, they should leave with these five points:

1. Episodes are deterministic, source-linked case files of prior SASE work. They live in
   `~/.sase/projects/<project>/episodes/`, not in the repo.
2. The command surface is `sase memory episodes {build,list,show,verify,recall}`. It is not available in this checkout
   yet; only the Rust/Python wire (Phase 1) has landed.
3. Read `lesson.md` first. `episode.json` is for tools; `sources.jsonl` is for provenance review.
4. Episodes do not silently become rules. Promote a useful lesson with `sase memory write` and approve it with
   `sase memory review`.
5. If `verify` reports drift, treat the episode as historical evidence — re-open the cited sources before relying on it.

The "first 30 minutes" recommended path, once the MVP lands:

```bash
sase memory episodes build -n <agent> --dry-run   # preview
sase memory episodes build -n <agent>             # store
sase memory episodes show <episode-id>            # read lesson.md
sase memory episodes verify <episode-id>          # check drift
sase memory episodes recall -q "<topic>"          # find related prior work
```

Everything else in this file expands on those five points.

## Question

How should SASE guide a new user through episodes, given the `sase-45` Structured Deterministic Episodic Memory MVP?

## Short Answer

Teach episodes as **evidence-backed project history**, not as magic memory and not as instructions.

A new user should learn this mental model first:

- **Chats and artifacts** are the raw source of truth.
- **Episodes** are deterministic, rebuildable records that connect chats, artifacts, plans, beads, ChangeSpecs, retries,
  questions, feedback, memory reads, and outcomes into one inspectable story.
- **Episode recall** is a way to ask "what happened before?" with evidence links.
- **Long-term memory** is still the human-reviewed place for durable guidance. Episodes can provide evidence for
  `sase memory write`, but they should not bypass `sase memory review`.

The first user-facing documentation should avoid agent-memory theory. It should show a small loop:

1. Build an episode from a recent agent run.
2. Inspect the rendered lesson and source graph.
3. Verify whether source evidence has drifted.
4. Recall prior episodes before starting similar work.
5. Promote only reviewed, reusable lessons into long-term memory.

There is an important current-state caveat: in this workspace, `sase memory episodes` is designed in
`sdd/epics/202605/structured_episodic_memory_mvp.md`, and the core wire schema exists, but the CLI is not wired into the
current `sase memory` parser yet. `sase memory --help` currently lists only `init`, `list`, `log`, `read`, `review`, and
`write`; `sase memory episodes --help` currently fails as an invalid subcommand.

## Current Implementation State

As of 2026-05-26, `sase-45` is open:

- `sase-45.1` is closed: core episode schema and canonicalization.
- `sase-45.2` through `sase-45.8` are in progress.

Current code in this checkout confirms only the Phase 1 boundary is present:

- `src/sase/core/episode_wire.py` defines `EpisodeWire`, source refs, nodes, edges, events, lessons, build reports,
  storage index rows, and verify reports.
- `src/sase/core/episode_facade.py` exposes Rust-backed helpers for schema version, canonical JSON, source IDs,
  episode IDs, and source verification.
- `tests/test_core_episode_wire.py` proves canonical serialization sorts sources/nodes/evidence IDs, episode IDs are
  stable across source order, and source verification reports missing/changed evidence.
- `src/sase/main/parser_memory.py` and `src/sase/main/memory_handler.py` currently expose `sase memory init`, `list`,
  `read`, `write`, `review`, and `log`; no `episodes` subcommand exists yet in this workspace.

The current codebase does not yet have the user-facing episode workflow:

- No `src/sase/memory/episodes/` package exists in this workspace.
- No `src/sase/memory/cli_episodes.py` exists.
- `src/sase/main/parser_memory.py` does not register an `episodes` subparser.
- `src/sase/main/memory_handler.py` does not dispatch `episodes`.

That means any public guide should be explicit: `sase memory episodes ...` is the intended command surface from the
epic, not a command available in this checkout yet.

## Product Boundary To Teach

Episodes belong under:

```text
sase memory episodes
```

not:

```text
sase episodes
```

The reason matters for onboarding. SASE already teaches memory as a family of audited operations:

- `sase memory list` shows visible memory context.
- `sase memory read` is an audited agent-side long-memory read.
- `sase memory write` creates a proposal only.
- `sase memory review` is the human promotion gate.
- `sase memory log` audits reads and proposal/review events.

Episodes should fit that story. They are a memory inspection and recall surface, not a separate product competing with
the memory command group.

## Beginner Explanation

Use this as the plain-language explanation:

> An episode is a source-linked summary of a piece of SASE work. It does not replace the chat transcript or artifacts.
> It gives you a compact lesson, timeline, and evidence list so you can understand what happened without rereading every
> raw file.

For a new user, the useful analogy is not "AI memory"; it is "a buildable case file":

- the prompt is the goal;
- the agent chat is testimony;
- artifacts and diffs are exhibits;
- plan feedback, questions, and retries are decision points;
- `episode.json` is the canonical record;
- `lesson.md` is the readable case summary;
- `sources.jsonl` is the evidence inventory;
- `index.jsonl` lets SASE list and recall prior cases.

The simplest task-level explanation is:

> Use episodes when you want SASE to answer, with citations, "what happened in that prior agent run or workflow?"

## Memory Taxonomy New Users Should Learn First

Borrowed from CoALA and the cognitive-science framing already cited in the structured-episodic-memory research, the
useful split for SASE is:

| Memory kind | What it stores | Where in SASE today |
| --- | --- | --- |
| **Semantic** | Facts about the project, codebase, or domain | `memory/long/*.md` (with `keywords` frontmatter) |
| **Episodic** | What happened in specific runs | `~/.sase/projects/<project>/episodes/` (after Phase 4) |
| **Procedural** | Rules/instructions for how to act | `memory/short/*.md` reached from `AGENTS.md` |

Episodes are the **episodic** tier. They are not procedural rules and they are not project-wide facts. The most common
new-user confusion is "I learned X in an episode — should I save it as memory?" The answer is: only if X is reusable
**semantic** (`memory/long`) or **procedural** (`memory/short`) content; otherwise the lesson belongs only in its
episode where the evidence keeps it honest.

## How Episodes Relate To Existing Memory Commands

A new user already sees five memory subcommands. Episodes add a sixth, and they should fit the existing mental model
rather than replace any of it:

| User intent | Old command | New episode command |
| --- | --- | --- |
| "What context is loaded right now?" | `sase memory list` | unchanged |
| "Let an agent read a long-memory file with attribution" | `sase memory read` | unchanged |
| "Propose a durable lesson" | `sase memory write` | unchanged; `--evidence path:<episode.json>` cites an episode |
| "Approve / reject a proposal" | `sase memory review` | unchanged |
| "Audit memory reads and proposals" | `sase memory log` | unchanged |
| "Initialize / refresh AGENTS.md wiring" | `sase memory init` | unchanged; episodes need no init step |
| "What happened in a prior run?" | (none) | `sase memory episodes show / list / verify` |
| "Find prior work on a topic" | `sase memory log` (audit only) | `sase memory episodes recall` |

The distinction the docs should hammer: `log` answers "what did agents read or propose?", `recall` answers "what
happened in prior runs, by topic?" They are not interchangeable.

## Comparison: Episodes vs Adjacent Surfaces

New users mostly fail to choose between four similar-feeling surfaces. A direct table beats prose here:

| Surface | What it is | Source of truth? | Indexed for recall? | Committed to repo? | Right for |
| --- | --- | --- | --- | --- | --- |
| `~/.sase/chats/` | Raw agent transcripts | yes | no (basename/agent filter only) | no | reading the exact dialogue |
| `~/.sase/projects/<p>/artifacts/<agent>/` | Agent run artifacts (done.json, diff, plan, feedback) | yes | partial (Rust scan) | no | debugging a specific run |
| `~/.sase/projects/<p>/episodes/` | Source-linked lessons over chats+artifacts | no (derivative) | yes (lexical) | no | "what happened, with citations" |
| `memory/long/*.md` | Reviewed semantic facts/references | yes | yes (dynamic memory keywords) | yes | rules that should apply forever |
| `memory/short/*.md` | Loaded instructions via `AGENTS.md` | yes | n/a (always loaded) | yes | rules that should apply to every prompt |
| `sdd/research/YYYYMM/` | Exploratory notes (this file!) | yes | no | yes | options, prior art, recommendations |
| `sdd/events/YYYYMM/` (proposed) | Reviewed cross-machine event cards | yes | no | yes | very rare promoted episodes |

The single rule: **episodes are derivative**. If the underlying chat or artifact disappears, the episode survives but
`verify` will mark it drifted. Episodes are never the right place to store ground truth.

## Why New Users Need A Different Guide Than Implementers

The existing research is implementation-heavy: storage layout, deterministic IDs, source graphs, build phases, and
retrieval architecture. A new user guide should instead answer five practical questions:

1. When should I use episodes?
2. Which selector should I start from?
3. How do I read an episode?
4. How do I decide whether to trust it?
5. How do I turn a useful lesson into durable memory?

Do not start the docs with the schema. Put the schema behind "what gets saved" or "how verification works."

## Suggested New User Flow

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

The first guide should prefer one happy-path selector before introducing all selectors. Suggested ordering:

```bash
# Start here
sase memory episodes build -n <agent-name>

# Then learn alternatives
sase memory episodes build -a ~/.sase/projects/sase/artifacts/.../<agent-dir>
sase memory episodes build -c <changespec-name>
sase memory episodes build -C ~/.sase/chats/202605/<chat>.md
sase memory episodes build -s 2026-05-01 -u 2026-05-26 -l 20
```

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

## What Users Should Do Today

Until Phases 2-8 land, users cannot rely on `sase memory episodes` in this checkout. The near-term guidance should be:

- use `sase chats list/show` for raw transcript inspection;
- use ACE or artifact paths for run artifacts;
- use `sase memory log --include proposals` for audited memory activity;
- use `sase memory write --evidence ...` when a durable lesson should be proposed for review;
- do not write `memory/short` or `memory/long` directly through episode work.

This is not equivalent to episodes, but it preserves the same safety model: inspect source evidence first, then propose
durable memory through review. When episode CLI work lands, the docs should explicitly replace the "start from chat"
path with "build/show/verify an episode, then propose memory from the cited lesson."

## What An Episode Is Good For

Episodes should be recommended when the user is asking:

- "What happened in that agent run?"
- "Why did the previous agent choose this approach?"
- "Did we already try this and fail?"
- "Which files, plans, beads, or ChangeSpecs were involved?"
- "Was there user feedback or a question answer that changed the plan?"
- "What evidence supports this lesson?"
- "Did the source evidence drift since the episode was built?"

Episodes should be especially useful before:

- planning work on an old bead or ChangeSpec;
- retrying a failed agent run;
- touching a subsystem that recently had a migration or benchmark;
- proposing long-term memory from prior work;
- writing docs that summarize implementation history.

## What Episodes Are Not For

The guide should be blunt about non-goals:

- Episodes are not canonical project instructions.
- Episodes are not automatically loaded into every prompt.
- Episodes are not a replacement for `memory/long`.
- Episodes are not a way for agents to silently edit memory.
- Episodes are not raw transcript storage.
- Episodes are not a vector database requirement.
- Episodes are not a reason to delete old chats or artifacts.

Do not edit `episode.json` by hand. Rebuild from sources instead.

Do not commit raw generated episodes to the repo. Prior research recommends keeping broad episode collection in project
state under `~/.sase/projects/<project>/episodes/` and committing only curated, reviewed event/memory artifacts when
they are explicitly useful to the project.

Do not expect `sase episodes`. The command should stay under `sase memory episodes` so memory, recall, review, and
promotion remain one product surface.

Do not use episodes as a replacement for `sase chats show`, SDD research, ChangeSpecs, or beads. Episodes are an index
and lesson layer over those sources.

## Common User Mistakes (Anti-Patterns)

The existing "Episodes are not for" section lists feature non-goals. New users still make these specific mistakes that
deserve their own list:

- **Reading `episode.json` directly.** It is canonical for tools, not humans. Use `show --format lesson`.
- **`grep`-ing the episodes directory.** Use `recall -q` so lexical scoring, recency, and outcome tie-breakers apply.
- **Pasting a `lesson.md` excerpt into `memory/long/*.md` by hand.** Skips the review gate and loses the evidence link.
  Use `sase memory write --evidence path:<episode.json> ...`.
- **Building the same episode repeatedly with `--force`.** If sources have not changed, rebuild is a no-op; if they
  have, prefer rerunning `verify` and rebuilding only when the new content is what you want.
- **Deleting `index.lock` to "unstick" a build.** The lock is held by a real writer; deleting it can leave a half-written
  index row. Wait or retry.
- **Treating `recall` as semantic search.** MVP scoring is lexical with tie-breakers. Phrase queries the way the lesson
  text would phrase them.
- **Expecting episodes on another machine.** Episodes are local project state. Use long-term memory to share lessons.
- **Filing an episode under a ChangeSpec name that does not exist yet.** Build with the agent name first; ChangeSpec
  selectors collapse multi-agent runs after the spec has been written.
- **Looking for episodes in ACE.** No TUI surface exists in MVP; the CLI is the only entry point.

Each item should be a callout in the docs, not a paragraph; new users will skim.

## Memory Poisoning In Plain Terms

The Trust And Safety section below is short. New users benefit from naming the attack class explicitly:

- An agent chat can contain text from the open web, repo files, issue bodies, PR comments, or sibling repos. That text
  is **input**, not instructions. If it ends up inside an episode, it is still input — episodes do not sanitize it.
- The attack class is "indirect prompt injection through retrieved content" (OWASP GenAI LLM01-2025) and "agent memory
  poisoning" (NIST AI 100-2, March 2025). Research demonstrations include AgentPoison (NeurIPS 2024) and MINJA
  (>95% success against ReAct agents). These are not hypothetical.
- Recall results that look like a user instruction are still untrusted text. The CLI must show them with citations so
  the reader can attribute the source before acting.
- Prompt augmentation (Phase 7) must therefore stay opt-in. The new-user guide should explain that turning it on means
  past chat text starts to influence future prompts, which is the exact surface the attacks target.

For new users, the practical rule:

> Read the cited source before adopting a lesson into memory. If you cannot find the source, do not adopt the lesson.

## Trust And Safety Guidance

New users need a trust model because episode summaries can feel authoritative.

Recommended framing:

- Trust the **evidence links** first.
- Treat the **lesson text** as a deterministic summary of available evidence, not as a universal rule.
- Use `verify` when an episode matters for a new decision.
- Promote durable lessons through `sase memory write` and human `sase memory review`.
- Prefer recent, verified, source-rich episodes over old or drifted episodes.
- If two episodes disagree, inspect their sources and timestamps rather than merging their lesson text mentally.

The docs should show a warning box near `recall`: recall results answer "what did prior work record?" not "what is true
now?"

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

## Output Shape To Optimize For

For new users, the most important display is `show` with the rendered lesson. The ideal first screen should contain:

- title;
- one-paragraph summary;
- goal;
- timeline;
- decisions and feedback;
- work performed;
- outcome;
- lessons with evidence IDs;
- sources.

The command should then make the evidence graph discoverable without requiring users to read JSON:

```bash
sase memory episodes show <episode-id> --timeline
sase memory episodes show <episode-id> --sources
sase memory episodes show <episode-id> --json
```

`--json` should be positioned as script/automation output. Human onboarding should show the markdown lesson first.

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

## Storage Contract To Explain Late

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

`episode.json` is canonical. `lesson.md`, `sources.jsonl`, and `index.jsonl` are deterministic projections. Do not lead
with this structure in beginner docs; introduce it only after the user understands the build/show/verify loop.

## Discoverability For A New User

A new user will not find episodes by accident. `docs/memory.md` in this checkout has 177 lines and does not mention
episodes; `sase memory --help` does not list them yet. Phase 8 should land at least four discoverability surfaces:

1. **`sase memory --help`**: an `episodes` line under the subcommand list with a one-sentence description.
2. **`docs/memory.md`**: a new top-level section titled "Episodes" inserted after "Review TUI" and before any
   troubleshooting subsection. The section should be ~40-60 lines and link to the dedicated `docs/episodes.md` page.
3. **`docs/index.md`**: a one-line entry pointing at the episodes page next to the existing memory entry.
4. **`sase init` output**: a single line such as "Run `sase memory episodes list` to inspect prior agent work" only
   when the project already has at least one finalized agent run. New empty projects should not see this hint.

The `docs/memory.md` splice should use the existing tone (terse, declarative, second person discouraged) and link to
the dedicated `docs/episodes.md` for deep content.

## Empty State And First-Run UX

The first thing a new user does is run `list` or `recall` with nothing stored. The MVP must handle this gracefully or
adoption stalls:

- `sase memory episodes list`: print "No episodes stored yet under `~/.sase/projects/<project>/episodes/`. Build one
  with `sase memory episodes build -n <agent>`." Exit 0, not 1.
- `sase memory episodes list -j|--json`: emit `{"episodes": [], "project": "<project>"}` and exit 0.
- `sase memory episodes recall -q "..."`: print "No matching episodes. Try `list` to see what is stored, or `build` from
  an agent name first." Exit 0.
- `sase memory episodes show <bad-id>`: print "No episode found for id `<bad-id>`. Available ids: `list`." Exit 1.
- `sase memory episodes verify <bad-id>`: same shape as `show`. Exit 1.
- `sase memory episodes build -n <unknown-agent>`: print "No agent named `<unknown-agent>` in project `<project>`.
  Confirm with `sase chats list` or pass `-a|--artifact-dir`." Exit 1.

The empty-state strings should name the next command. "No results" without a next step is the most common docs failure
in CLIs and is easy to avoid here.

## First-Run Walkthrough (Narrative Form)

The earlier "Suggested New User Flow" section gives commands. For onboarding, a narrative is more sticky. Suggested
docs section:

> You finished an agent run named `planner.coder` and want to know what happened.
>
> 1. List recent agents with `sase chats list` and confirm the agent name.
> 2. Build the episode: `sase memory episodes build -n planner.coder`. You should see a single line: the new
>    episode ID, the lesson path, and a source count.
> 3. Read the lesson: `sase memory episodes show <episode-id>`. Skim the timeline and lessons; cited evidence IDs
>    point at chats and artifacts you can open.
> 4. Trust check: `sase memory episodes verify <episode-id>`. If it says `0 missing, 0 drift`, the cited sources still
>    exist and match. If anything drifted, open those sources before relying on the lesson.
> 5. Find related prior work: `sase memory episodes recall -q "retry feedback"` to see if other episodes already
>    learned the same thing.
> 6. (Optional) Promote a durable rule: if the lesson is a reusable project rule, run `sase memory write
>    --title "..." --slug ... --evidence path:~/.sase/projects/<project>/episodes/<episode-id>/episode.json --body ...`
>    and approve it with `sase memory review`.

Six steps, single agent, no flags beyond the necessary ones. Reserve `-p|--project`, `-a|--artifact-dir`,
`-c|--changespec`, and date-range selectors for a second walkthrough.

## Documentation Placement

Recommended docs/pages after implementation:

1. A short `docs/episodes.md` or `docs/memory.md` subsection titled "Episodes".
2. CLI examples in `sase memory episodes --help`.
3. A "Promote a lesson to memory" subsection that points to `sase memory write/review`.
4. A troubleshooting subsection for "no episode found", "source changed", and "recall found stale evidence".

Troubleshooting should cover:

- no episode found for selector;
- source file missing;
- source hash changed;
- command is unavailable in pre-MVP builds;
- recall returns stale or irrelevant results;
- private paths appear in output.

Do not bury episodes only inside the structured memory epic. The epic is correct for implementers but too deep for
first-use learning.

## Relationship To `sdd/events`

Prior research separates private/generated **episodes** from reviewed, repo-checked **events**:

- Episodes are operational, rebuildable, and stored under `~/.sase/projects/<project>/episodes/`.
- Event cards, if added later, should be rare reviewed project memories under `sdd/events/YYYYMM/`.

This distinction should not be introduced on day one unless the user asks about Git storage. The beginner guide should
only say: "Episodes are local project state. Durable instructions still go through reviewed memory."

## Documentation Copy Candidates

### One-Line Definition

SASE episodes are source-linked records of prior agent work that help you inspect, verify, and recall what happened.

### First Paragraph

Use episodes when you need history with evidence. An episode ties together the agent prompt, chat, artifacts, plan,
feedback, retries, beads, ChangeSpecs, memory reads, and outcome into a deterministic record. It gives humans and agents
a compact lesson without replacing the raw transcript.

### Warning Box

Episodes are evidence, not instructions. If an episode contains a lesson that should guide future agents, propose it
with `sase memory write` and approve it with `sase memory review`.

### First Workflow

```bash
# Preview what would be built from an agent run.
sase memory episodes build -n <agent> --dry-run

# Build and store the episode.
sase memory episodes build -n <agent>

# Read the lesson and evidence.
sase memory episodes show <episode-id>

# Check whether the cited evidence still matches.
sase memory episodes verify <episode-id>
```

## Open Questions

- Should `build` default to writing, or should the first documented command use `--dry-run`? The epic says it writes
  unless `--dry-run`; user onboarding may still want a first example that builds for real because the storage location is
  outside the repo.
- Should `show` accept partial episode ID prefixes? New users will expect this if memory proposal review already accepts
  unambiguous prefixes.
- Should `list` default to the current project only? It should, unless `-p|--project` explicitly names another project.
- Should `recall` search private episodes only, curated events only, or both? For first release, keep it to stored
  project episodes and make any later `sdd/events` bridge explicit.
- Should `recall` search only verified episodes by default? Research recommendation: include drift status in results,
  but do not silently hide drifted episodes until users can understand why results disappeared.
- Should docs call them "episode lessons" or "lesson cards"? Use "episode" for the whole record and "lesson" for the
  human-readable projection to avoid conflating data and presentation.
- Should episode IDs be visible in beginner docs? Yes, because every recall result and evidence link needs a stable
  handle.
- Should auto-build happen during agent finalization? Not for initial onboarding. Users should learn explicit builds
  before background generation is enabled.

## Failure Modes And Error Recovery

The first-run guide should name the failures a new user will actually hit. Each one should map to a single recovery
sentence, not a generic "see logs" pointer.

| Failure | Likely cause | Recovery |
| --- | --- | --- |
| `no episodes matched selector` | Wrong agent name, typo, project mismatch | Re-run with `-p|--project` and confirm with `sase chats list`. |
| `source not found` during `verify` | Artifact dir was cleaned or chat was renamed | Treat the episode as historical evidence; rebuild from a fresh selector if a new run exists. |
| `source hash mismatch` during `verify` | Chat or artifact was edited after build | Open the cited source and decide whether to rebuild (`build -f|--force`) or keep the prior episode as a snapshot. |
| `index locked` during `build` | Another `sase memory episodes` write is in flight | Retry; do not delete `index.lock` manually. |
| `schema_version higher than supported` | Episode was produced by a newer SASE binary | Upgrade SASE in this workspace; do not hand-edit `episode.json`. |
| `episode already exists; use --force` | Deterministic ID collision because sources are unchanged | Either skip or pass `-f|--force` to overwrite the projection files (`lesson.md`, `sources.jsonl`). |

The user guide should also state plainly: a `verify` failure does not delete the episode and does not block recall. It
flags the record as "evidence drift" so the user can decide whether to trust the lesson.

## Privacy And Secrets Handling

Episodes inherit content from agent chats, plan files, diffs, and artifacts. Those sources may contain API keys, tokens,
or other secrets that the agent transcript captured. A new user must understand three rules:

1. Treat an unbuilt episode like a chat: it can contain anything the agent saw.
2. Read `lesson.md` before promoting any lesson to long-term memory; do not paste source snippets into
   `sase memory write --body` without review.
3. If a source contains a real secret, rotate the secret. Removing it from the chat does not remove it from any episode
   that already captured the hash and offset of that line.

The epic schedules a secret-scrub helper (`episodes/scrub_secrets.py` in the structured-episodic-memory research). Until
it lands, the user guide should explicitly say "episodes are not redacted" rather than imply automatic safety.

Pair this with the existing memory-poisoning guidance: untrusted transcript text inside an episode is evidence, not
instructions. The `recall` command must return citations and snippets that the user reads, never auto-applied rules.

## Lifecycle, Retention, And Garbage Collection

The MVP does not garbage-collect user-visible episode directories. A new user should know:

- Episodes live in `~/.sase/projects/<project>/episodes/` indefinitely.
- The MVP storage GC only cleans clearly corrupt temp directories; it does not prune by age, count, or outcome.
- Deleting an episode directory by hand is acceptable but will leave a dangling `index.jsonl` row. The user should
  instead use `sase memory episodes build -f|--force` to regenerate or wait for a future `episodes prune` subcommand.
- Episodes survive workspace rebuilds because they live under `~/.sase`, not under `sase_<N>/`.
- Episodes do not auto-delete when the underlying chat or artifact is removed; they become "drifted" instead and
  `verify` will report it.

A practical onboarding line: "Episodes are write-mostly. If your project state feels large, archive whole project
directories under `~/.sase/projects/`; don't try to surgically prune individual episodes."

## Multi-Agent And Multi-Project Workflows

The earlier draft only shows single-agent selectors. Real SASE work usually involves an agent family, retries, and
parent/child agents. The new-user guide should add three points:

1. `build -n <agent>` follows the source graph through parent/root timestamps, retry links, `done.response_path`,
   `agent_meta.chat_path`, `prompt_step_*.json.response_path`, chat `## Linked Chats`, and `#fork`/`#fork_by_chat`
   references. One selector can produce one episode spanning multiple chats.
2. To group an episode by a whole workflow, prefer `build -c|--changespec <name>`. ChangeSpec selectors collapse all
   agents whose commits land on the same spec into one episode if the source graph connects them.
3. Cross-project work stays separated. `~/.sase/projects/<project>/episodes/` is per-project. There is no MVP "merge
   episodes across projects" operation; users who need a cross-project lesson should promote it to long-term memory via
   `sase memory write`.

The guide should also distinguish "one episode per agent family run" (the common case) from "one episode per chat" (a
debugging case reachable through `-C|--chat`).

## Schema Versioning And Upgrade Behavior

`schema_version` is the only mutable surface in the episode record. The user-facing implications:

- New optional fields can appear in `episode.json` after a SASE upgrade and old episodes will still load.
- A binary will refuse to read an episode whose `schema_version` exceeds the binary's known maximum, rather than
  silently dropping fields.
- Episode IDs are deterministic from canonical source content, not from `schema_version`. Re-running `build` after a
  schema bump should not change the ID unless the sources or canonical projection rules changed.
- The user should never hand-edit `schema_version`. Rebuild instead.

The new-user guide should say: "If `show` or `verify` refuses an episode after an upgrade, upgrade SASE everywhere you
use that project."

## Concurrency And Locking

The storage layout includes `index.lock` because multiple agents and CLI invocations can race on the index. New users
should know:

- It is safe to run `build` while agents are running. Locking is at the index/episode level, not at the project level.
- Concurrent `build` invocations serialize on `index.lock`; one will wait briefly, none should fail outright in the
  common case.
- `list`, `show`, `verify`, and `recall` are read-only and do not take the write lock.
- If `index.lock` is stuck (process killed mid-write), the recovery is to wait for the lock TTL or re-run; the lock
  should not be deleted by hand because partial index rows must be reconciled by the writer.

Auto-build during agent finalization is intentionally not on by default. The MVP requires latency and lock-contention
measurements first. A new user should not assume episodes appear automatically after every run.

## Cross-Machine Sync Expectations

Episodes are local project state, not repo state. Concretely:

- Episodes are not committed to the project's git repo.
- Switching machines does not bring your episodes along unless you sync `~/.sase/projects/<project>/episodes/` yourself.
- Long-term memory under `memory/long/` (created via `sase memory write` + `review`) is the supported way to share an
  episode-derived lesson across machines and collaborators.
- Source verification across machines depends on the chats and artifacts also being present. If the original artifact
  dir does not exist on the second machine, `verify` will report missing sources even though the episode is intact.

The single-sentence rule: "Episodes are local evidence; long-term memory is the portable lesson."

## Confirmed Flag Surface From The Epic

The epic pins the following surface for Phase 5, which the user guide should quote rather than paraphrase:

```text
build -p|--project PROJECT
build -n|--agent AGENT
build -a|--artifact-dir DIR
build -c|--changespec NAME
build -C|--chat CHAT
build -s|--since DATE
build -u|--until DATE
build -l|--limit N
build -D|--dry-run
build -f|--force
all subcommands: -j|--json
```

`show` formats are `lesson`, `json`, `sources`, and `timeline`. The exact short option for the format selector is not
fixed in the epic; the repo convention ("all options need a short and long form") means the implementer should pick a
stable short, with `-F|--format` as the natural choice. Recall's `-q|--query` and `-l|--limit` are pinned in Phase 7.

`recall` does not have a pinned short option for project scope yet; the user guide should not show one until Phase 5
lands.

## TUI / ACE Integration (Current Status)

There is no TUI surface for episodes in the current workspace. A grep of `src/sase/ace/` for `episode` only matches the
unrelated "idle episode" counter in `activity_log.py`. The MVP is CLI-only.

A new user should be told this directly:

- Browse episodes with `sase memory episodes list`, not from the Agents tab.
- Open an episode with `sase memory episodes show <id>`, not from a row keymap.
- Future TUI integration (opening an episode from an agent row, filtering by outcome) is plausible but explicitly out
  of MVP scope.

If users expect a TUI tab, the docs should say "CLI-only for MVP; TUI integration is a future enhancement."

## Sample Outputs A New User Will See

The earlier draft describes output shape in prose. New users learn faster from concrete examples. The docs should
include at least one example of each command's default output.

`list` (recent episodes, current project):

```text
EPISODE ID             TITLE                                ROOT AGENT       OUTCOME    SOURCES   WHEN
ep_20260524_1f9a3c     Retry chain prompt feedback fix      planner.coder    success    14        2d ago
ep_20260522_7b21d0     Bead JSONL merge conflicts triage    bead.fixer       partial    9         4d ago
ep_20260520_4e88a1     ACE startup regression bisect        perf.bisect      success    22        6d ago
```

`show <id>` (default lesson):

```markdown
# Retry chain prompt feedback fix
- Goal: stop dropping feedback on retried chains.
- Outcome: success; landed in changespec retry_feedback_chain.
- Timeline: 14 events across planner.coder + planner.coder.1.
- Lessons:
  1. Retry edges must carry the parent feedback ref or it gets garbage-collected.
  2. The fork_by_chat tag is the reliable join key, not chat path.
- Evidence:
  - chat:planner.coder.20260524.103200
  - artifact:.../planner.coder.20260524.103200/feedback.json
  - changespec:retry_feedback_chain
```

`verify <id>` (concise default):

```text
ep_20260524_1f9a3c: 14 sources, 14 verified, 0 missing, 0 drift  OK
```

`verify <id> -j` (script-friendly):

```json
{
  "episode_id": "ep_20260524_1f9a3c",
  "verified": 14,
  "missing": [],
  "drift": [],
  "schema_version": "1.0.0",
  "status": "ok"
}
```

`recall -q "retry feedback"`:

```text
ep_20260524_1f9a3c  Retry chain prompt feedback fix       score=0.84  changespec=retry_feedback_chain
  ...feedback ref or it gets garbage-collected. The fork_by_chat tag is the reliable join key...
ep_20260403_3c2a99  Feedback artifact loss on retry        score=0.71  changespec=feedback_artifact_retry
  ...partial feedback propagation when retry parent had no fork tag...
```

These are illustrative, not literal. The doc should reproduce real outputs once Phase 8 fixtures exist, but the shapes
should match.

The illustrative `ep_YYYYMMDD_xxxxxx` IDs above should not be read as a spec. The epic's determinism rules
(`sdd/epics/202605/structured_episodic_memory_mvp.md` Determinism Rules) require `episode_id` to be derived from project
name, root source identity, and canonical source refs, not from wall-clock time. The user guide should describe IDs as
"a short opaque handle" and show a real format only after Phase 1/2 fixtures pin it. Embedding the build date in the
visible ID would make rebuilds appear to "change" the episode even when sources are unchanged, which is the opposite of
the contract.

## Onboarding And `sase init`

Episodes should not require an explicit `sase memory episodes init` step. The build path should create
`~/.sase/projects/<project>/episodes/` and `index.jsonl` on first use. The new-user guide should say:

- No setup required. The first `build` creates the storage layout.
- `sase init` should not mention episodes prominently. Mentioning the storage location once in the memory docs is
  enough.
- If the project's `~/.sase/projects/<project>/` directory does not exist yet, `build` should create it with the same
  permissions as the rest of the project state.

The directory bootstrap should be silent. Surface a one-line "wrote ~/.sase/projects/<project>/episodes/index.jsonl"
only on the very first run.

## FAQ For New Users

Short, direct answers belong in the docs:

- "Where are episodes stored?" `~/.sase/projects/<project>/episodes/`. Not in your repo.
- "Do episodes get committed?" No. Long-term memories created from episodes do.
- "Will agents read my episodes automatically?" No. Recall is explicit until prompt augmentation is opted in.
- "Can I delete an episode?" Yes, by removing its directory. The index row becomes a dangling reference until a future
  `prune` lands; prefer `build -f|--force` to regenerate.
- "Does an episode change when I edit a chat?" No. `verify` will flag drift, but the stored `episode.json` is
  immutable until rebuilt.
- "Can two machines share episodes?" Only if you sync `~/.sase/projects/<project>/episodes/` yourself. Use long-term
  memory for portable lessons.
- "What if I have secrets in a chat?" Assume the episode captured them. Rotate the secret and rebuild if needed.
- "Is there a TUI for episodes?" Not in MVP. CLI only.
- "Will the schema change?" Yes, additively. `schema_version` is the only mutable surface; binaries refuse newer
  versions instead of silently dropping fields.

## Recommendation

Build the new-user guide around a small loop:

1. Build from a known agent.
2. Show the lesson.
3. Verify the evidence.
4. Recall by topic when the agent is unknown.
5. Promote only reviewed, reusable lessons into long-term memory.

Keep the wording disciplined: episodes are evidence records, not memory rules; `lesson.md` is the human view, not the
source of truth; `episode.json` is canonical; and the command belongs under `sase memory episodes`.

## Determinism Guarantees To Teach New Users

The epic's determinism rules matter for onboarding because they are unusual relative to vendor "AI memory" products. The
guide should state plainly:

- No LLM call is required to build, render, verify, or recall an MVP episode. `build` is deterministic source
  collection and rendering. `recall` is deterministic lexical scoring. The user is never paying a per-token cost to make
  an episode appear or to find one.
- The same sources always produce the same `episode_id`, the same `lesson.md` bytes, and the same `sources.jsonl`. If a
  rebuild changes either projection, the sources or the SASE binary changed; the episode itself did not "drift" of its
  own accord.
- Wall-clock time is not part of identity. `build_time` may appear in non-identity fields, but two rebuilds an hour or a
  month apart should hash identically when the underlying sources are unchanged.
- Source timestamps come from artifact and chat content, not from filesystem mtimes. Touching a file (mtime bump with no
  content change) should not invalidate an episode.
- Missing or deleted sources are preserved as refs with `exists=false`. `verify` reports drift; it never rewrites
  history.

For new users, the practical implication is: episodes are reproducible artifacts, not stochastic summaries. If a
teammate sees a different lesson than you do for the same `episode_id`, the SASE binary, project name, or source content
differs on one side. Treat that as a bug, not as expected variance.

## Recall Scoring Semantics

`recall` is deterministic lexical scoring, not embedding search. The new user guide must say this up front because most
people arrive expecting semantic retrieval like ChatGPT memory or a vector store. Per the epic Phase 7 contract, recall
uses:

1. Token overlap with title, summary, lesson text, source labels, ChangeSpec name, bead IDs, file paths, and tags.
2. Recency and outcome only as tie-breakers after lexical score, never as primary signals.

Practical consequences a new user should know:

- Synonyms do not match. "retry" does not retrieve "rerun". Phrase queries with the words the lesson would actually use.
- Code identifiers, ChangeSpec slugs, and bead IDs are first-class query terms. `recall -q "sase-45 storage"` is often
  better than `recall -q "episode storage design"`.
- Results are stable across runs on the same machine and across machines with the same episode store. There is no
  randomness, no LLM reranker, and no per-user personalization in the MVP.
- An empty result usually means "rephrase" or "build more episodes first", not "no prior work exists". The guide should
  show a quick recovery: try `sase chats list` or `sase memory list`, then build an episode from the relevant agent.

If a future release adds embedding-based recall, it should ship as an opt-in flag so the deterministic default is
preserved.

## When To Use Recall Versus Other Search Tools

Episodes are not the only way to search SASE history. The new user guide should give an explicit decision rule rather
than leaving users to guess:

| Question | Best tool | Why |
| --- | --- | --- |
| "What did the agent literally say in turn N?" | `sase chats show <chat>` | Episodes summarize; chats are the raw transcript. |
| "Which agent worked on bead X?" | `sase agents` filters or `sase bead show X` | Episodes are not the agent index. |
| "What was decided across several runs on this PR?" | `sase memory episodes show` from a `-c|--changespec` build | Episode spans agents within a ChangeSpec. |
| "Have we ever learned something about topic T?" | `sase memory episodes recall -q T` | Recall is the topic-to-episode bridge. |
| "What durable rules apply to this project?" | `sase memory list` and `memory/long/` | Episodes are evidence, memory is rules. |
| "Which long-memory proposals are open for review?" | `sase memory review --list` | Episodes do not bypass review. |

The rule of thumb: reach for episodes when you want a compact, source-linked story; reach for chats/agents/beads when
you want raw state; reach for memory when you want durable instructions.

## Empty-State And Discoverability

A new user who runs `sase memory episodes list` on a fresh project will see an empty store. The guide should treat that
as a normal first encounter, not a failure:

- The first run of `list` on an empty store should print a one-line empty state plus a hint pointing at `build`. It
  should not print an error or a stack trace.
- The first `build` should silently create `~/.sase/projects/<project>/episodes/` and `index.jsonl`, then print exactly
  the episode ID, title, lesson path, source count, and lesson count.
- `sase memory --help` should mention `episodes` as a subcommand once Phase 5 lands. Until then, the guide should
  explicitly tell users that `sase memory episodes` will fail in pre-MVP builds and link to the epic.
- The guide should mention that `sase memory log --include episodes` (or the equivalent filter once Phase 5/6 land) is
  the audit trail for builds, verifies, and recall calls. Until that filter exists, the user can grep `~/.sase/logs/`
  for `episode` events.

The single sentence to put in the onboarding doc: "Episodes appear when you build them. SASE does not create them
silently in the background until you opt into auto-build."

## Mental-Model Contrast With Vendor "AI Memory"

New users almost always arrive with one of three priors:

1. **ChatGPT-style memory** — a profile blob the model reads automatically.
2. **Vector store / RAG** — embedded chunks with semantic similarity retrieval.
3. **Notion/Obsidian notes** — human-curated documents the user reads.

SASE episodes are none of these. The mental model that fits is closer to a deterministic build artifact (think Bazel
output or a reproducible PDF): given the same sources and binary, you get the same bytes. The guide should call this
out directly:

- Unlike ChatGPT memory, episodes are not auto-injected. Recall is explicit until a user opts into prompt augmentation.
- Unlike a vector store, recall is lexical and deterministic. Same query, same store, same ranking.
- Unlike free-form notes, episodes have a canonical machine-readable form (`episode.json`) and a derived human view
  (`lesson.md`). Editing the human view by hand does not change the canonical record; rebuild instead.

This framing also explains why episodes live under `~/.sase/projects/<project>/episodes/` rather than in the repo:
they are project-local build outputs, not curated documentation.

## Day-One Tutorial Script

Once the CLI ships, the onboarding doc should include a single linear script a new user can paste. This is what the
research recommends:

```bash
# 1. Pick a recent agent to anchor the first episode.
sase agents --status done --limit 5

# 2. Preview the episode SASE would build, without writing anything.
sase memory episodes build -n <agent> -D

# 3. Build for real. Note the printed episode ID.
sase memory episodes build -n <agent>

# 4. Read the lesson first; it is the human view.
sase memory episodes show <episode-id>

# 5. Confirm the cited evidence is still on disk and unchanged.
sase memory episodes verify <episode-id>

# 6. Search for related prior work by topic.
sase memory episodes recall -q "<short phrase from the lesson>"

# 7. If a lesson is reusable across future agents, propose it as durable memory.
sase memory write \
  --title "<one-line rule>" \
  --slug <kebab_slug> \
  --evidence ~/.sase/projects/<project>/episodes/<episode-id>/episode.json \
  --body "<the rule, in plain English>"

# 8. Promote it through human review.
sase memory review --list
sase memory review --approve <slug>
```

The tutorial deliberately ends in `sase memory review`, not at `recall`, so the user finishes with the correct mental
model: episodes feed reviewed memory, they do not replace it.

## Glossary For The Episodes Surface

Beginner docs should define these terms once, near the top:

- **Episode** — a deterministic record of prior SASE work for a project. Includes source refs, a timeline, decisions,
  and lessons. Lives under `~/.sase/projects/<project>/episodes/<episode-id>/`.
- **Episode ID** — a short opaque handle derived from the project name, root source identity, and canonical source refs.
  Stable across rebuilds when sources are unchanged.
- **Lesson** — a single source-linked claim with one or more `evidence_ids`. The episode's rendered `lesson.md` is a
  human projection of the canonical lesson records inside `episode.json`.
- **Source ref** — a pointer to a chat, artifact, plan, diff, ChangeSpec, bead, or commit, with path, kind, size, and
  SHA-256 where applicable.
- **Evidence ID** — a stable identifier inside an episode that lessons cite. Used to anchor a lesson to specific source
  refs.
- **Drift** — the state of an episode when one or more sources are missing or hashed differently from build time.
  Reported by `verify`; does not delete the episode.
- **Canonical projection** — a derived file (`lesson.md`, `sources.jsonl`, or an `index.jsonl` row) that can be
  regenerated from `episode.json` and the current source tree without re-running the collector.
- **Selector** — the build flag that picks which sources start the source graph: `-n|--agent`, `-a|--artifact-dir`,
  `-c|--changespec`, `-C|--chat`, or `-s|--since`/`-u|--until`.
- **Source graph** — the directed graph of agent_run, chat, plan, question, feedback, artifact, changespec, bead,
  commit, memory_read, dynamic_memory, retry, and workflow_step nodes that a single episode records.
- **Recall** — deterministic lexical search across stored lessons. Returns cards with episode IDs, scores, and evidence
  links. Does not modify the episode store.

## Performance And Scale Expectations

The epic does not pin numeric SLAs, but the determinism contract and storage layout imply rough budgets the user guide
should set expectations against:

- `build` is dominated by source collection (chat file reads, artifact directory walks, SHA-256 hashing) rather than
  rendering. A typical single-agent run should complete in well under a second; a ChangeSpec spanning many agents may
  take longer because it hashes more files.
- `list` reads `index.jsonl` and should return in tens of milliseconds for projects with hundreds of episodes. It
  should not open per-episode `episode.json` files.
- `show` opens one episode directory and renders `lesson.md` directly when available; it is read-only and fast.
- `verify` is the only operation that re-hashes sources by default. On a large source set it can be the slowest
  read-only command and may dominate latency. The guide should suggest running `verify` selectively, not on every list
  view.
- `recall` over a few thousand episodes should remain interactive because scoring is lexical and bounded by lesson and
  index sizes, not by transcript size.

Scale guidance for the onboarding doc: a single project with several hundred episodes is well within the MVP envelope.
Tens of thousands of episodes is out of scope for MVP measurement and should be flagged as needing benchmarking before
auto-build is enabled by default.

## Related Research Cross-Links

The new-user guide should not stand alone. The most useful adjacent reads, all in this directory, are:

- `sase_memory_command_research.md` — overall `sase memory` CLI shape and audit semantics.
- `sase_memory_write_review_research.md` — how an episode-derived lesson becomes a reviewed long-term memory.
- `sase_memory_read_agent_usefulness.md` — when an agent should call `sase memory read` versus rely on dynamic memory.
- `structured_episodic_memory_for_agent_chats.md` and `structured_episodic_agent_chat_memory.md` — the design history
  behind the current epic.
- `structured_episodic_events_for_memory_search.md` and `git_versioned_episodic_events.md` — the distinction between
  private episodes (local project state) and curated events (`sdd/events/`, repo-checked).
- `dream_chop_agent_chat_distillation.md` and `zettel_sase_shared_memory.md` — older summarization approaches that
  episodes intentionally replace with a deterministic build.
- `manus_vs_sase_lessons.md` and `openhands_vs_sase.md` — comparisons with vendor agent-memory designs that motivate
  SASE's no-LLM, source-grounded default.

Beginner docs should link to at most two of these (memory write/review and the epic) and treat the rest as deep dives.

## Reuse Of Rust Core Boundary

The repo's `rust_core_backend_boundary.md` guidance applies to episodes: schema, canonical serialization, source IDs,
and episode IDs already live in `sase-core` and `sase_core_rs`. The Python collector, builder, renderer, and storage
layer (Phases 2-4) are Python-side because they orchestrate filesystem reads against existing Python parsers
(`sase.history.chat`, `agent_scan_facade`). The user-facing docs should not mention this split, but maintainers should
treat any change to canonical episode shape as a Rust-first change with Python wire updates in lockstep.

## Memory Proposal Evidence Format

The existing `sase memory write` evidence kinds (`path`, `chat`, `url`, `note`) already accept an episode reference
without schema changes: `--evidence path:~/.sase/projects/<project>/episodes/<id>/episode.json`. The new-user docs
should show this exact form, and the implementer should not invent a new `episode:` evidence kind unless review surfaces
a real need. Reusing `path:` keeps the proposal ledger backward compatible and means existing review TUIs render
episode-derived proposals without changes.

If a future iteration wants a first-class `episode:<id>` evidence kind, that should be a separate proposal with
review-side changes, not bundled into the MVP.

## Evidence Reviewed

- `sase bead show sase-45`
- `sdd/epics/202605/structured_episodic_memory_mvp.md`
- `sdd/prompts/202605/structured_episodic_memory_mvp.md`
- `sdd/research/202605/structured_episodic_agent_chat_memory.md`
- `sdd/research/202605/structured_episodic_memory_for_agent_chats.md`
- `sdd/research/202605/structured_episodic_events_for_memory_search.md`
- `sdd/research/202605/git_versioned_episodic_events.md`
- `src/sase/core/episode_wire.py`
- `src/sase/core/episode_facade.py`
- `tests/test_core_episode_wire.py`
- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- `docs/memory.md`
- `docs/configuration.md`
- `sdd/epics/202605/structured_episodic_memory_mvp.md` Phase 5-8 (flag surface, exit criteria, non-goals)
- `sdd/research/202605/sase_memory_command_research.md` (memory CLI conventions, `doctor`, output shapes)
- `sdd/research/202605/sase_memory_write_review_research.md` (promotion path from evidence to durable memory)
- `src/sase/ace/` (grep confirms no TUI surface for episodes in MVP)
- `sdd/epics/202605/structured_episodic_memory_mvp.md` Phase 7 (deterministic lexical recall, no embeddings)
- `sdd/epics/202605/structured_episodic_memory_mvp.md` Determinism Rules (episode_id derivation, no wall-clock)
- `sdd/research/202605/README.md` (research directory convention)
- `sdd/research/202605/dream_chop_agent_chat_distillation.md`, `zettel_sase_shared_memory.md`,
  `manus_vs_sase_lessons.md`, `openhands_vs_sase.md` (mental-model contrast and prior approaches)
- `docs/memory.md` (confirmed: 177 lines, no episodes mention as of 2026-05-26)
- `docs/` directory listing (no `episodes.md` exists; no docs mention `episode` outside an unrelated infographic critique)
- `sase bead show sase-45` and `sase bead show sase-45.5` (confirmed Phase 5 in progress, depends on Phases 2-4, blocks Phase 7)
- `src/sase/memory/proposals.py` evidence kinds (`path`, `chat`, `url`, `note`) — confirmed episodes can be cited as `path:<episode.json>` without schema changes
- `memory/short/rust_core_backend_boundary.md` (boundary guidance applied to episode schema/canonicalization living in `sase-core`)
- OWASP GenAI Top-10 2025 LLM01 indirect prompt injection (cited via `structured_episodic_memory_for_agent_chats.md`)
- NIST AI 100-2 (March 2025) agent memory poisoning (cited via `structured_episodic_memory_for_agent_chats.md`)
- AgentPoison (NeurIPS 2024) and MINJA (>95% success against ReAct agents) attack demonstrations (cited via `structured_episodic_memory_for_agent_chats.md`)
- CoALA modular memory framing (semantic/episodic/procedural split, cited via `structured_episodic_agent_chat_memory.md`)
