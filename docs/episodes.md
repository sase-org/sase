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
```

`show` defaults to the human-readable view. Use explicit formats for provenance and automation:

```bash
sase memory episodes show <episode-id> --format timeline
sase memory episodes show <episode-id> --format sources
sase memory episodes show <episode-id> --format json
```

For a day or week of project work, prefer split builds and inventory filters:

```bash
sase memory episodes build -p <project> -s 2026-05-19 -u 2026-05-20 --split
sase memory episodes list -p <project> -s 2026-05-19 -u 2026-05-20 -g day
sase memory episodes list -p <project> -s 2026-05-19 -u 2026-05-20 -b high -j
```

## Command Summary

| Command                            | Purpose                                                                                 |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| `sase memory episodes build`       | Build aggregate compatibility output or split v2 component episodes.                    |
| `sase memory episodes list`        | Inventory stored episodes by event time, status, metadata, and importance.              |
| `sase memory episodes show <id>`   | Show the lesson, timeline, source refs, or canonical JSON.                              |
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
