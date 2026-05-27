# Episodes

SASE episodes are deterministic, source-linked records of prior agent work. They sit between raw chats and reviewed
memory: an episode ties together prompts, chats, artifacts, plans, feedback, questions, retries, beads, ChangeSpecs,
audited memory reads, and outcomes into one inspectable lesson.

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

## Build Selectors

Choose the narrowest selector you know:

| Selector                                                      | Use when                                         |
| ------------------------------------------------------------- | ------------------------------------------------ |
| `build -n\|--agent <agent>`                                   | You know the visible agent name or agent family. |
| `build -a\|--artifact-dir <dir>`                              | You have an exact artifact directory.            |
| `build -c\|--changespec <name>`                               | Work was organized around a ChangeSpec.          |
| `build -C\|--chat <chat>`                                     | You have a chat path or basename.                |
| `build -s\|--since <date> -u\|--until <date> -l\|--limit <n>` | You are backfilling recent project work.         |

`build` writes by default. Add `-D|--dry-run` to preview the deterministic episode without storing files.

## Trust And Drift

Episodes are evidence, not instructions. Each lesson cites source IDs, and `verify` recomputes source existence, size,
and SHA-256 hashes without mutating the episode:

```bash
sase memory episodes verify <episode-id>
```

If a source is missing or changed, the episode remains stored and recallable, but the cited evidence should be reread
before relying on the lesson.

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
