---
title: "Local state cutover"
description:
  "The temporary offline kit for moving legacy local state into canonical locations."
---

# Local state cutover

The temporary offline kit for moving legacy local state into canonical locations.

<a id="local-state-cutover-1"></a>

## Local State Cutover

`sase migrate` is a temporary, offline kit for the canonical-only local-state cutover.
It never runs automatically, no other SASE surface invokes it, and the whole command
group is deleted once the cutover completes. Reach for it only when you are deliberately
retiring legacy residue under `~/.sase` and `~/.macros`; nothing here is part of
day-to-day operation.

Every subcommand accepts `-j`/`--json` for a machine-readable object. Bare
`sase migrate` delegates to `sase migrate list`. Only `backup`, `restore`, `run`, and
`resume` accept `-a`/`--apply`. For those commands, `--apply` is the boundary for
changing the source or live root, not a promise that the default mode performs no
filesystem writes: `plan` persists control records, restore always creates a staging
copy, and path resolution may create the cutover control directories.

### Where The Kit Writes

Backups, staged restores, and run journals live under the cutover backup root:
`$SASE_CUTOVER_BACKUP_DIR` when set, otherwise `~/cutover-backups`. The root is created
with mode `0700` on first use. SASE rejects a root equal to or nested beneath `~/.sase`,
`~/.local/state/sase`, or `~/sase`. That check does not discover arbitrary custom
runtime roots, so if `SASE_HOME` or a checkout lives elsewhere, choose an unrelated
backup location yourself.

| Path                           | Contents                                                              |
| ------------------------------ | --------------------------------------------------------------------- |
| `backups/<backup-id>/payload/` | The copied source tree, mirroring the backed-up root.                 |
| `backups/<backup-id>/`         | `MANIFEST.json`, `SHA256SUMS`, and `provenance.json` for that backup. |
| `restores/`                    | Staged restores, before an apply swaps one into place.                |
| `runs/<run-id>/manifest.json`  | The planned operation, including any bound backup id.                 |
| `runs/<run-id>/journal.jsonl`  | The append-only, fsynced record a resume replays.                     |
| `runs/<run-id>/run.lock`       | The bounded lock `run` and `resume` take.                             |
| `runs/<run-id>/receipt.json`   | The final receipt written once an applied run finishes.               |

A backup id looks like `<host>-<YYYYMMDDTHHMMSS>-<random>`; a run is addressed by its
run id.

### The Operation Catalog

The catalog is fixed — `sase migrate list` reports it along with whether each declared
root is present on this machine.

| Operation       | What it does                                                                                                                              | Backup required | Apply supported | Declared roots                                                                                               |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------- | --------------- | ------------------------------------------------------------------------------------------------------------ |
| `import-purge`  | Wraps `sase agent names purge-local-state` behind a verified backup, then re-runs the import-state preview to verify.                     | yes             | yes             | `~/.sase/agents_sync`, `~/.sase/artifacts`, `~/.sase/chats`, `~/.sase/dismissed_bundles`, `~/.sase/projects` |
| `lock-residue`  | Classifies code-swap lock files and refuses to archive any lock the current code still writes.                                            | no              | no (read-only)  | `~/.sase/locks`                                                                                              |
| `procs-residue` | Parses residual `~/.sase/tasks` rows, reconciles them with canonical procs, and archives only a fully matched legacy tree.                | yes             | yes             | `~/.sase/tasks`, `~/.sase/procs`                                                                             |
| `state-residue` | Archives the legacy agent tribe file, `user_question`, `plan_approval`, and legacy `~/.macros` residue once canonical counterparts exist. | yes             | yes             | `~/.sase/agent_tags.json`, `~/.sase/plan_approval`, `~/.sase/user_question`, `~/.macros`                     |

Each operation declares its own preconditions and rollback unit; `list --json` prints
them verbatim. `lock-residue` reports a classification and never mutates anything, so it
has no apply mode.

### Backing Up And Restoring

Treat the kit's “offline” label as an operator requirement. Before capturing a backup,
stop sase's TUI, AXE, agents, procs, and any other process that can write the source
tree; the backup command does not stop writers or acquire a tree-wide lock. A safe
sequence is:

1. Stop writers, preview the backup, and then repeat it with `--apply` (preferably with
   `--secondary`).
2. Create the operation manifest with the verified backup id.
3. Run the manifest without `--apply` to preflight it.
4. Repeat `run` with `--apply`, then use `verify` and `status`.
5. Use `resume --apply` only for an interrupted applied run.

```bash
sase migrate backup ~/.sase                                  # report what would be captured
sase migrate backup ~/.sase --apply --secondary /mnt/backup  # capture, plus a second durable copy
sase migrate restore <backup-id>                             # verify, create a staging copy, and diff
sase migrate restore <backup-id> --apply                     # swap the staged copy into place
```

An applied capture checksums its file members and copies SQLite databases through the
database backup API rather than as raw bytes. Ordinary files are copied while the tree
is being walked, which is why stopping writers matters. The capture refuses to start
unless free space covers the measured size with 15 percent headroom. Without `--apply`,
it reports member counts, byte totals, and whether the destination passes the three
fixed root exclusions above; resolving that destination can still create the cutover
root and `backups/` directory.

A restore first hashes regular and SQLite payload files against the hashes stored in
`MANIFEST.json`. The backup also contains `SHA256SUMS`, but restore does not currently
read that file. After verification, restore always copies the payload to a new staging
path under `restores/` and reports the diff and ownership deltas against the live root,
even without `--apply`. With `--apply`, an existing live root is renamed to a sibling
`<name>.pre-restore-<YYYYMMDDTHHMMSS>` — never deleted — and the staged copy is moved
into its place. `-r`/`--root` targets a different live root than the one that was backed
up. The backup itself is never modified or deleted by a restore.

### Planning, Running, And Verifying

```bash
sase migrate plan state-residue --backup-id <backup-id>  # write runs/<run-id>/manifest.json
sase migrate run <manifest>                              # preflight only: digests, conflicts, backup record
sase migrate run <manifest> --apply                      # execute, journaling every step
sase migrate status                                      # every recorded run and its journal state
sase migrate verify <run-id>                             # re-check post-conditions and fingerprints
sase migrate resume <run-id> --apply                     # continue an interrupted run
```

`plan` mutates no source data: it writes a manifest plus an initial journal record and
prints the manifest path. `run` without `--apply` checks source digests, conflicts, and
the bound backup record; a refused preflight can append a refusal to the journal. With
`--apply`, `run` executes under a durable journal and writes a receipt. `resume` replays
the journal, re-checks source digests while the run has not started applying, and
continues from the next resumable step. `run` and `resume` accept
`-l`/`--lock-timeout-ms`; the bounded run lock is acquired only in apply mode.

`plan` and `list` accept `-r`/`--root` and `-d`/`--home` to resolve operation roots
against a SASE home other than the live one, which is how the kit is rehearsed against a
copy before it is pointed at real state.

## Related

- [Upgrading](index.md) — upgrade and history notes.
- [Content layout migration](content-layout.md) — related local-state paths.
