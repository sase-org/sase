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
- `sdd/epics/202605/structured_episodic_memory_mvp.md` Phase 5-8 (flag surface, exit criteria, non-goals)
- `sdd/research/202605/sase_memory_command_research.md` (memory CLI conventions, `doctor`, output shapes)
- `sdd/research/202605/sase_memory_write_review_research.md` (promotion path from evidence to durable memory)
- `src/sase/ace/` (grep confirms no TUI surface for episodes in MVP)
