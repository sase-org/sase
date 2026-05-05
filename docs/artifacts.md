# Unified Artifacts

`sase artifact` is the CLI surface for the unified artifact graph. It reads and mutates a SQLite index of artifacts,
payloads, links, tombstones, and diagnostics. The default index is `~/.sase/artifacts.sqlite`; every subcommand accepts
`-i/--index` so tests, operators, and agents can work against a temporary or project-specific index.

Use JSON output for automation and agent workflows. Human output is intended for quick terminal inspection.

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

## Doctor Troubleshooting

Run doctor after suspected index corruption, stale data, or a rebuild:

```bash
sase artifact doctor -j
```

Doctor exits `0` when `ok` is true and there are no issues. It exits non-zero when issues are present. The JSON issue
rows include `issue_type`, `severity`, `artifact_id`, `link_id`, and `message`.

A typical stale-index refresh is:

```bash
sase artifact rebuild -j
sase artifact doctor -j
```

Keep troubleshooting commands pointed at a temporary index with `-i` when reproducing bugs. Do not let tests or examples
write to the default `~/.sase/artifacts.sqlite` unless they are intentionally exercising the user's live index.
