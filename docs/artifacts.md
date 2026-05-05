# Unified Artifacts

`sase artifact` is the CLI surface for the unified artifact graph. It reads and mutates a SQLite index of artifacts,
payloads, links, tombstones, and diagnostics. The default index is `~/.sase/artifacts.sqlite`; every subcommand accepts
`-i/--index` so tests, operators, and agents can work against a temporary or project-specific index.

Use JSON output for automation and agent workflows. Human output is intended for quick terminal inspection.

## Product Model

The graph is an index over existing SASE state. It does not own project files, beads, agent marker files, chat logs,
diffs, plans, questions, images, or generated PDFs, and rebuilds must not delete those source files.

Artifact IDs are stable identifiers for graph nodes:

- `/` is the root artifact.
- File and directory artifacts use absolute normalized paths.
- Project artifacts use absolute `~/.sase/projects/*/*.gp` paths, including archive project files.
- ChangeSpec artifacts use the ChangeSpec `NAME`.
- Commit artifacts use `<changespec_name>:<commit_number>`.
- Bead artifacts use bead IDs such as `sase-23.5.6`.
- Agent artifacts use the stable agent name when present.
- Legacy unnamed agents use `agent:<project>:<workflow>:<timestamp>`. This fallback is a graph ID, not a renamed display
  name, and the node metadata includes the source artifact directory for later repair.
- Thought artifacts use content-addressed `thought:<sha256-prefix>` IDs.

Link direction is part of the contract:

- `parent` points from child to parent. Walking reverse `parent` links finds children; walking forward reaches `/`.
- `created` points from the creator agent to files, thoughts, plans, questions, diffs, transcripts, and other created
  artifacts.
- `worker` points from a bead to the agent responsible for the work.
- `related` points between associated artifacts such as ChangeSpecs, agents, retries, follow-up agents, commits, and
  beads when the relationship is not ownership.

Rows are either `manual` or `derived`. Manual rows are created with `sase artifact add`. Derived rows come from rebuilds
over project files, bead stores, workspace paths, and agent artifact directories.

## Read-Only Discovery

Start with a bounded list:

```bash
sase artifact list -j -l 50
```

Useful filters include:

```bash
sase artifact list -j -k file -l 50
sase artifact list -j -q "needle" -l 50
sase artifact list -j -L parent -r <root_id> -l 50
sase artifact list -j -P manual -l 50
```

Inspect one artifact exactly before summarizing its relationships or payloads:

```bash
sase artifact show -j -a <artifact_id>
```

`show` returns the node, payloads, inbound and outbound links, direct children, path to root, and diagnostics. A missing
artifact returns a detail object with `node: null`.

## Graph Output

Use graph output when relationships matter:

```bash
sase artifact graph -j -a <artifact_id> -d 2
sase artifact graph -f text -a <artifact_id> -d 2
sase artifact graph -f dot -a <artifact_id> -d 2
sase artifact graph -f mermaid -a <artifact_id> -d 2
```

`json` is the stable machine format. `text` is a compact edge list for terminal debugging. `dot` and `mermaid` are raw
Rust exports suitable for graph renderers. Use `-F/--full` only when a bounded full-graph view is appropriate, and keep
`-l/--limit` set unless the graph is known to be small. If JSON reports `truncated: true`, treat the graph as partial.

## Mutations And Tombstones

Manual artifact changes require explicit intent:

```bash
sase artifact add -j -a <id> -k <kind> -t "Title"
sase artifact add -j -a <id> -P summary -p '{"body": "text"}'
sase artifact add -j -l 'parent|<child_id>|<parent_id>'
sase artifact remove -j -a <artifact_id> -p manual -r "reason"
sase artifact remove -j -T <type> -S <source_id> -D <target_id> -p manual -r "reason"
```

Manual rows are removed directly when Rust can safely remove them. Derived rows are tombstoned when the removal request
selects derived provenance, so future rebuilds can respect the operator's override. Mutation JSON reports affected node
IDs, affected link IDs, tombstone IDs, counts, and errors; stop and report errors if the `errors` array is non-empty.

Tombstones only suppress graph rows or links. They do not delete the project file, bead record, agent directory,
response file, or any other source artifact. To inspect suppressed rows while debugging, use
`list -u/--include-tombstoned` and a temporary index when possible.

## Rebuild Behavior

`sase artifact rebuild` mutates the index by refreshing derived graph rows from configured sources. It can rebuild from
project files, workspaces, bead stores, and agent artifact directories depending on the request options:

```bash
sase artifact rebuild -j
sase artifact rebuild -j -w <workspace_root> -b <beads_dir>
sase artifact rebuild -j -S directory -t <target_path>
sase artifact rebuild -j -c mark
```

Use rebuild for stale or missing derived data, not for routine read-only discovery. The default stale cleanup mode is
`none`; `-c mark` lets Rust mark stale derived rows when that behavior is needed.

Default rebuilds are the migration path for existing user state. With no source filters, rebuild discovers the standard
projects root, current workspace context, the current workspace bead store when supplied by the caller, and agent
artifact directories under supported layouts. It backfills graph rows for current and archived ChangeSpecs, commits,
beads, dismissed agents whose marker files remain on disk, named agents, legacy unnamed agents, created files, and
thoughts.

Use targeted rebuilds when a specific source changed:

```bash
# One project file or ordinary file path.
sase artifact rebuild -j -S project_file -S changespec -S commit -t <project.gp>
sase artifact rebuild -j -S directory -t <path>

# One bead store.
sase artifact rebuild -j -S bead_store -b <workspace>/sdd/beads

# One agent artifact directory.
sase artifact rebuild -j -S agent_artifact -S agent_created_file -a <artifact_dir>
```

Targeted rebuilds are the preferred operational repair for a missing current ChangeSpec, selected agent, updated
`issues.jsonl`, or fresh marker file write. Full rebuilds are appropriate for first migration, suspected broad drift, or
explicit operator refreshes.

## Doctor Troubleshooting

Run doctor after suspected index corruption, stale data, or a rebuild:

```bash
sase artifact doctor -j
```

Doctor exits `0` when `ok` is true and there are no issues. It exits non-zero when issues are present. The JSON issue
rows include `issue_type`, `severity`, `artifact_id`, `link_id`, and `message`.

Migration-specific issue types include:

- `fallback_agent_id`: a legacy unnamed agent was indexed with a deterministic fallback ID. This is expected during
  migration unless the operator chooses to repair marker metadata.
- `unresolved_timestamp_link`: retry, question, or follow-up metadata names a timestamp that did not resolve to an
  indexed agent.
- `unresolved_changespec_reference`: a marker or bead references a ChangeSpec that is not in the rebuilt project set.
- `unresolved_bead_reference`: metadata references a bead missing from the rebuilt bead store.
- `stale_derived`: `rebuild -c mark` found previously-derived rows whose source is no longer present.

A typical stale-index refresh is:

```bash
sase artifact rebuild -j
sase artifact doctor -j
```

For unresolved references, rerun rebuild with the missing source root or a targeted source. For fallback agent IDs,
repair only when a stable real agent name is known; marker repair should be explicit and additive so older marker fields
remain compatible.

## Migration Runbook

1. Back up or copy the current index if the user wants a rollback point:

   ```bash
   cp ~/.sase/artifacts.sqlite ~/.sase/artifacts.sqlite.bak
   ```

2. Rebuild into the default graph index:

   ```bash
   sase artifact rebuild -j
   ```

3. Validate the graph:

   ```bash
   sase artifact doctor -j
   ```

4. Spot-check a few expected entry points:

   ```bash
   sase artifact show -j -a <changespec_name>
   sase artifact show -j -a <agent_name_or_fallback_id>
   sase artifact graph -j -a <changespec_name> -d 1 -I -l 100
   ```

5. If doctor reports stale derived rows after a source was intentionally removed, mark stale rows:

   ```bash
   sase artifact rebuild -j -c mark
   sase artifact doctor -j
   ```

6. If a current TUI selection opens as missing, run a targeted rebuild for that context and retry:

   ```bash
   sase artifact rebuild -j -t <project_or_file_path>
   sase artifact rebuild -j -a <agent_artifact_dir>
   ```

## Compatibility Notes

The unified graph is the default artifact discovery surface in the TUI. The old `~/.sase/agent_artifact_index.sqlite`
can remain as a compatibility index for fast agent startup and legacy agent-list loading paths; do not delete it as part
of artifact graph migration. Live agent detail, file, and thinking surfaces may still exist where they serve active
monitoring. Historical discovery should use the artifact panel and `sase artifact`.

Keep troubleshooting commands pointed at a temporary index with `-i` when reproducing bugs. Do not let tests or examples
write to the default `~/.sase/artifacts.sqlite` unless they are intentionally exercising the user's live index.
