# SASE Beads

This public sidecar repository stores durable bead state for its SASE-managed source repository. SASE automatically
clones it into each workspace at `sase/repos/beads`, keeping work tracking available to humans and agents without
sharing the plans repository's history or write lock.

![Beads directory map](assets/beads-directory-map.png)

## Directory Layout

| Path | Purpose |
| --- | --- |
| `README.md` | This generated guide. |
| `assets/beads-directory-map.png` | The generated directory-map infographic used by this README. |
| `.gitignore` | Excludes the local `beads.db`, `beads.db-shm`, and `beads.db-wal` SQLite cache files. |
| `config.json` | Bead store configuration. |
| `metadata.json` | Bead store metadata. |
| `issues.jsonl` | Generated compatibility projection of current bead state. |
| `events/manifest.json` | Manifest for the canonical event store. |
| `events/streams/*.jsonl` | Canonical append-only bead event streams. |

`events/**` is the append-only source of truth. `issues.jsonl` is generated only as a compatibility projection, while
`beads.db*` is a gitignored local SQLite cache and never durable shared state.

## Commands

- `sase bead list` lists current work.
- `sase bead ready` shows open work with no active blockers.
- `sase bead show <id>` displays one bead and its relationships.
- `sase bead history <id>` replays the bead's canonical event history.
- `sase bead work <epic-id|plan.md>` launches an epic's phase and landing agents.
- `sase repo path beads` prints this clone's root.
