# Episodes

SASE episodes are deterministic, source-linked records of prior agent work. They sit between raw chats and reviewed
memory: an episode ties together prompts, chats, artifacts, plans, feedback, questions, retries, beads, ChangeSpecs,
audited memory reads, dynamic-memory inputs, and outcomes into one inspectable lesson.

Episodes do not write `memory/short` or `memory/long`. If an episode contains a reusable project rule, propose that rule
with `sase memory write` and approve it with `sase memory review`.

## First Workflow

Start from a completed agent name:

```bash
sase memory episodes build -n <agent-name>
sase memory episodes list
sase memory episodes show <episode-id>
sase memory episodes verify <episode-id>
```

Then use recall when the topic is known but the agent name is not:

```bash
sase memory episodes recall -q "retry feedback"
```

`show` defaults to the human-readable `lesson.md`. Use explicit formats for provenance and automation:

```bash
sase memory episodes show <episode-id> --format timeline
sase memory episodes show <episode-id> --format sources
sase memory episodes show <episode-id> --format json
```

## Command Summary

| Command                            | Purpose                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------ |
| `sase memory episodes build`       | Build and optionally store an episode from agent, artifact, CL, or scan. |
| `sase memory episodes list`        | List stored episode index rows for a project.                            |
| `sase memory episodes show <id>`   | Show the lesson, timeline, source refs, or canonical JSON.               |
| `sase memory episodes verify [id]` | Recompute source existence, size, and hash checks for one or all rows.   |
| `sase memory episodes recall -q Q` | Search stored episode lessons with deterministic keyword scoring.        |

All subcommands accept `-p|--project <project>` when the project name should not be inferred from the current workspace.

## Build Selectors

Choose the narrowest selector you know:

| Selector                                                      | Use when                                         |
| ------------------------------------------------------------- | ------------------------------------------------ |
| `build -n\|--agent <agent>`                                   | You know the visible agent name or agent family. |
| `build -a\|--artifact-dir <dir>`                              | You have an exact artifact directory.            |
| `build -c\|--changespec <name>`                               | Work was organized around a ChangeSpec.          |
| `build -C\|--chat <chat>`                                     | You have a chat path or basename.                |
| `build -s\|--since <date> -u\|--until <date> -l\|--limit <n>` | You are backfilling recent project work.         |

The explicit selectors (`--agent`, `--artifact-dir`, `--changespec`, and `--chat`) keep rich transitive expansion:
related workflow children, retries, family members, ChangeSpecs, beads, and chats can be pulled into the same episode
when the source graph points to them.

The default project-scan selector is bounded. When no explicit selector is supplied, `--project`, `--since`, and
`--until` apply both to the seed records and to transitive agent-record expansion so a narrow date window does not pull
in unrelated historical runs through a shared ChangeSpec, bead, family, retry, or workflow edge. `--limit` limits the
seed records for agent and project-scan builds; it is not a hard cap on all transitive records.

`build` writes by default. Add `-D|--dry-run` to preview the deterministic episode without storing files, or
`-f|--force` to rewrite an existing episode projection when the deterministic episode id already exists.

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

`list`, `verify`, and `recall` also support `--json`. `show --json` is a shortcut for `show --format json`.

## Trust And Drift

Episodes are evidence, not instructions. Each lesson cites source IDs, and `verify` recomputes source existence, size,
and SHA-256 hashes without mutating the episode:

```bash
sase memory episodes verify <episode-id>
sase memory episodes verify --all
```

If a source is missing or changed, the episode remains stored and recallable, but the cited evidence should be reread
before relying on the lesson. Non-JSON verification exits non-zero when any checked episode has drift.

## Storage

Episode files live under the project state directory:

```text
~/.sase/projects/<project>/episodes/
  index.jsonl
  index.lock
  <episode_id>/
    episode.json
    lesson.md
    sources.jsonl
```

`episode.json` is the canonical machine-readable record. `lesson.md`, `sources.jsonl`, and `index.jsonl` are
deterministic projections that can be rebuilt from the canonical episode and current sources.
