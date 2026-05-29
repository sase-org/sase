# Episodes

SASE episodes are deterministic, source-linked evidence records for prior agent work. They sit between raw chats and
reviewed memory: an episode ties together prompts, chats, artifacts, plans, feedback, questions, retries, beads,
ChangeSpecs, audited memory reads, dynamic-memory inputs, and outcomes into inspectable evidence records.

Episodes are evidence, not active instructions. They do not write `memory/short` or `memory/long`. If an episode
contains a reusable project rule, propose that rule with `sase memory write` and approve it with `sase memory review`.

## First Workflow

Start from a completed agent name. `build` stores the episode by default, so the later commands have something to read:

```bash
sase memory episodes build -n <agent-name>
sase memory episodes list
sase memory episodes show <episode-id>
sase memory episodes verify <episode-id>
```

Then use recall when the topic is known but the agent name is not. Recall searches stored episodes only:

```bash
sase memory episodes recall -q "retry feedback"
sase memory episodes export -s 2026-05-19 -u 2026-05-20 -b high -j
```

`show` defaults to the human-readable view. Use explicit formats for provenance and automation:

```bash
sase memory episodes show <episode-id> --format overview
sase memory episodes show <episode-id> --format timeline
sase memory episodes show <episode-id> --format graph
sase memory episodes show <episode-id> --format sources
sase memory episodes show <episode-id> --format agent
sase memory episodes show <episode-id> --format json
```

For a day or week of project work, prefer split builds and inventory filters:

```bash
sase memory episodes build -p <project> -s 2026-05-19 -u 2026-05-20 --split
sase memory episodes list -p <project> -s 2026-05-19 -u 2026-05-20 -g day
sase memory episodes list -p <project> -s 2026-05-19 -u 2026-05-20 -b high -j
```

For recurring maintenance, run one checkpointed automatic build cycle and inspect its state:

```bash
sase memory episodes auto -p <project> -l 50
sase memory episodes status -p <project>
sase memory episodes doctor -p <project>
```

`auto` is one pass, not a resident daemon. Put it in your scheduler or configure the installed `memory_episodes` axe
chop when you want repeated maintenance.

## Command Summary

| Command                            | Purpose                                                                                 |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| `sase memory episodes auto`        | Run one checkpointed automatic build cycle over new completed agent markers.            |
| `sase memory episodes build`       | Build aggregate compatibility output or split v2 component episodes.                    |
| `sase memory episodes doctor`      | Inspect automatic builder state and apply safe repairs with `--repair`.                 |
| `sase memory episodes export`      | Emit bounded read-only episode summaries for future event review.                       |
| `sase memory episodes list`        | Inventory stored episodes by event time, status, metadata, and importance.              |
| `sase memory episodes show <id>`   | Show overview, timeline, graph, sources, agent pack, JSON, or legacy lesson.            |
| `sase memory episodes status`      | Show automatic-builder checkpoint, lock, index, and latest metrics state.               |
| `sase memory episodes verify [id]` | Recompute source existence, size, and hash checks for one episode, or all when omitted. |
| `sase memory episodes recall -q Q` | Search stored episode evidence with deterministic keyword scoring.                      |

All subcommands accept `-p|--project <project>` when the project name should not be inferred from the current workspace.

## Build Selectors

Choose the narrowest selector you know. Only one explicit selector can be used per build:

| Selector                                              | Use when                                                                  |
| ----------------------------------------------------- | ------------------------------------------------------------------------- |
| `build -n\|--agent <agent>`                           | You know an exact agent name or recorded agent family/workflow name.      |
| `build -a\|--artifact-dir <dir>`                      | You have one exact agent artifact directory.                              |
| `build -c\|--changespec <name>`                       | Work was organized around a ChangeSpec.                                   |
| `build -C\|--chat <chat>`                             | You have a chat path or chat basename.                                    |
| `build -s\|--since <date> -u\|--until <date> --split` | You are backfilling recent project work as separate connected components. |

The explicit selectors (`--agent`, `--artifact-dir`, `--changespec`, and `--chat`) keep rich transitive expansion.
`--split` still separates disconnected connected components; `--aggregate` keeps the temporary v1-compatible behavior
that collects one broad episode.

When no explicit selector is supplied, `build --split` uses a project scan where `--since` and `--until` select seed
records only. A seed inside the window may pull strong retry, fork, parent, chat, or workflow lineage outside the
window, but weak refs such as ChangeSpec, bead, family, touched path, or date proximity do not merge unrelated work.

For explicit selectors, `--since` and `--until` do not prune related records. Use the project-scan form when the date
window is the boundary you care about. `--limit` limits initial seed records for agent and project-scan builds; it is
not a hard cap on all transitive records.

`build` writes by default. Add `-D|--dry-run` to preview the deterministic episode without storing files, or
`-f|--force` to record force intent in the JSON build request. Current writes are content-idempotent: rerunning the same
episode leaves unchanged files untouched, and changed projections for the same episode id are updated. New v2 split
episodes write `episode.json` and `sources.jsonl`; legacy aggregate episodes also write `lesson.md`.

## Build Output

Human-mode builds print phase progress to stderr while keeping the final summary on stdout:

```bash
sase memory episodes build -n <agent-name>
```

Progress covers collection, episode construction, lesson rendering, and file writes. Use `-q|--quiet` when scripts or
logs should keep only errors plus the final human summary:

```bash
sase memory episodes build -n <agent-name> --quiet
```

JSON mode is silent on stderr and emits one deterministic stdout object:

```bash
sase memory episodes build -n <agent-name> --json
```

The build JSON includes:

- `episode`: the canonical `EpisodeWire` record.
- `build_request`: the `EpisodeBuildRequestWire` selector, bounds, write mode, force flag, and source refs used for the
  build.
- `build_report`: the `EpisodeBuildReportWire` project, source count, lesson count, episode id, write intent, change
  flag, and warnings.
- Compatibility summary fields such as `episode_id`, `episode_dir`, `source_count`, `lesson_count`, `dry_run`,
  `would_write`, `changed`, `wrote`, and `warnings`.

With `--split --json`, the top-level object contains `components` and `build_reports` lists, one entry per connected
component.

## Automatic Builder

`auto` runs one checkpointed build cycle over completed agent markers that have not yet been scanned by the automatic
builder. It is intended for scheduled maintenance and defaults to a bounded batch size; use `--limit` to override the
batch for one run. `--dry-run` reports the planned cycle and build reports without writing episodes, state, or metrics.
The automatic builder is deliberately single-shot; repeated execution comes from an external scheduler or an axe
lumberjack configured to run the `memory_episodes` chop script.

The builder records its checkpoint under the project episode state so repeated cycles only scan new done markers.
`status` reports the checkpoint, lock, index, and latest metrics. `doctor` inspects that state for recoverable problems;
with `--repair`, it can apply safe fixes such as restoring a previous `build_state.json` or removing abandoned temporary
builder directories.

## Inventory

`list` is the time-window inventory command. Date filters use episode event spans, not write time:

```bash
sase memory episodes list -s 2026-05-19 -u 2026-05-20 -g day
sase memory episodes list -b high -n <agent> -c <changespec> -B <bead> -q "retry"
sase memory episodes list -o importance -l 20 -j
```

Human output includes grouped headers when requested, event time span, importance band, status, title, agents, chat
count, source count, warning count, and alias/legacy markers. JSON output is deterministic and includes enriched episode
rows with `version`, `is_legacy`, `alias_episode_ids`, `warnings`, filter echo, and group membership.

`list`, `verify`, and `recall` also support `--json`. `show --json` is a shortcut for `show --format json`.

## Drill-Down Views

`show` reads the canonical `episode.json` and renders a specific view:

- `overview`: status, importance, summary, participants, warnings, weak metadata, and next commands.
- `timeline`: ordered events grouped by run or chat when possible, with evidence IDs.
- `graph`: deterministic component graph. Strong lineage edges are shown by default; use `--edge-mode all` to include
  weak metadata edges.
- `sources`: grouped source refs with stored existence, size, and SHA-256 details.
- `agent`: bounded evidence pack for agent consumption. The framing states that the episode is historical evidence, not
  instructions.
- `json`: canonical machine-readable episode record.
- `lesson`: legacy lesson rendering for v1 or aggregate compatibility episodes.

## Recall And Export

`recall` is v2-native. It searches title, summary, status, weak refs, source labels and paths, timeline text, importance
factors, safety flags, and legacy lessons. V2 matches return evidence cards with source links; legacy episodes still
return lesson cards when lesson records exist.

`export` is the event-readiness handoff command. It uses the same filters as `list`, defaults to importance order, and
is bounded by episode count plus per-episode source, factor, and safety limits:

```bash
sase memory episodes export -s 2026-05-01 -u 2026-05-26 -b high -j
```

The export JSON includes compact summaries, episode IDs, importance factors, source refs, safety flags, weak refs, and
`writes_events: false`. It does not write `sdd/events/`, event proposals, or memory files.

## Trust And Drift

Episodes are evidence, not instructions. Each lesson cites source IDs, and `verify` recomputes source existence, size,
and SHA-256 hashes without mutating the episode:

```bash
sase memory episodes verify <episode-id>
sase memory episodes verify --all
```

If a source is missing or changed, the episode remains stored and recallable, but the cited evidence should be reread
before relying on the lesson. Verification exits non-zero when any checked episode has drift, including JSON mode after
printing the report.

## Storage

Episode files live under the project state directory:

```text
~/.sase/projects/<project>/episodes/
  index.jsonl
  index.lock
  <episode_id>/
    episode.json
    sources.jsonl
    lesson.md   # legacy aggregate/v1 episodes only
```

`episode.json` is the canonical machine-readable record. `sources.jsonl`, legacy `lesson.md`, and `index.jsonl` are
deterministic projections that can be rebuilt from the canonical episode.
