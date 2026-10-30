---
title: "Artifact configuration"
description: "Configuration behavior for agent artifacts and artifact references."
---

# Artifact configuration

Configuration behavior for agent artifacts and artifact references.

## artifacts

Bounds on automatic artifact capture at agent finalization, and the opt-in retention
policy that bounds the store afterwards. Capture keeps bytes only for files a run
authored that version control cannot reproduce; content already reachable from a durable
commit becomes a byte-free reference row. See
[VCS-Backed Artifact Files](../agent-attachments.md#vcs-backed-artifact-files) for the
decision matrix and the `vcs-cache` directory, and
[Store Lifecycle](../agent-attachments.md#store-lifecycle) for the report → dry run →
opt-in retention progression that `artifacts.retention` completes.

```yaml
artifacts:
  capture:
    max_stored_per_agent: 50
    max_history_scan: 20
    max_file_size_bytes: 104857600
    pool_max_bytes: 1073741824
```

[Generated reference for `artifacts`](runtime.md#artifacts)

These fields are read fail-open: a missing, non-integer, or out-of-range value falls
back to the built-in default rather than failing capture. Once `max_stored_per_agent` is
reached, the remaining byte-copy candidates are skipped and finalization reports
`cap_fired=true` on its `[artifacts] default capture:` summary line. Raising
`max_history_scan` widens the bounded search that recovers content whose recorded commit
was squash-rewritten, at the cost of a longer walk per file.

`max_file_size_bytes` and `pool_max_bytes` apply to launch-time prompt-artifact staging
under the workspace-local `.sase/artifacts/` tree. The local manifest still records
oversized files, but SASE does not copy their bytes into `.sase/artifacts/pool/`. See
[Prompt Artifact Staging and Archive](../agent-attachments.md#prompt-artifact-staging-and-archive)
for the layout and garbage-collection rules.

`artifacts.retention` is the opt-in policy the hourly `artifact_retention` housekeeping
job enforces against the indexed store. Agent finalization only runs a throttled
fallback when the last stamp is missing or older than 24 hours. It ships disabled with
generous values pre-filled, so enabling it later is a flag flip rather than a policy
design exercise.

```yaml
artifacts:
  retention:
    enabled: false
    empty_shard_removal_budget: 2000
    keep_per_label: 3
    keep_recent_run_months: 2
    max_age_days: 90
    trash_grace_days: 14
```

[Generated reference for `artifacts`](runtime.md#artifacts)

These fields are read fail-open the same way the capture fields are. The pass is bounded
and defensive: it never fails a run, and it removes nothing that retention's protection
contract keeps — explicit artifacts, artifacts referenced by a ProjectSpec, plan, bead,
or research document, artifacts recorded in the consumption ledger, and the newest
capture of every label. If any required protection source cannot be read, the whole pass
is skipped rather than under-protecting, and it prints
`[artifacts] retention skipped: protection sources unavailable: <sources>`. Otherwise it
prints one `[artifacts] retention:` line with rows trashed, bytes reclaimed, and trash
entries purged. A disabled or unavailable skip still stamps
`~/.sase/artifact_retention.json` so the runner fallback can stay quiet.

The same values drive the manual surfaces, so a dry run previews exactly what enabling
retention would do: `keep_per_label` is what `sase artifact prune` plans with when `-g`
is omitted, both predicates define the default-policy selection `sase artifact stats`
reports last, and `trash_grace_days` is the cutoff `sase artifact trash purge` honors
without `-a/--all` and the one `trash list` marks entries against. Setting both
predicates to `0` leaves a policy that selects nothing.

`keep_recent_run_months` drives `sase artifact prune-runs`, which previews old terminal
`artifacts/ace-run/` directories plus empty month/day/run shards outside sase's TUI
startup watch window. Deletion is currently preview-only: `--apply` fails closed before
removing run directories, empty shards, or artifact-index rows. The preview protects
recent months, incomplete runs, referenced agent names or paths, artifact-file
producers, and runs tied to non-closed beads. `empty_shard_removal_budget` bounds how
many empty shard directories one preview lists.

Source: `src/sase/config/core.py`, `src/sase/core/artifact_capture_policy.py`,
`src/sase/core/artifact_file_retention.py`,
`src/sase/core/agent_artifact_run_retention.py`,
`src/sase/axe/run_agent_exec_finalize.py`

<a id="artifactrefs"></a>

## artifact_refs

Allow-lists path-backed `@file:<path>` prompt references. Indexed
`@file:default:<digest>` and `@file:explicit:<digest>` references do not need these
roots; this section controls only references authored as absolute or `~/` paths.

```yaml
artifact_refs:
  file:
    roots:
      - name: notes
        path: ~/notes
        path_globs: ["**/*.md", "!private/**"]
      - name: reports
        path: /srv/reports
```

[Generated reference for `artifact_refs`](runtime.md#artifact_refs)

Root lists concatenate across ordinary config layers. A layer using the global
list-replacement merge strategy replaces the inherited list instead. When the same
`name` appears more than once, the later root overrides the earlier definition without
changing its position. Invalid entries are skipped with a warning rather than disabling
all usable roots.

Resolution accepts existing regular files only, requires the path to stay within an
effective root and its glob policy, and never interprets relative paths against the
current directory. At launch SASE snapshots accepted bytes into the workspace-local
artifact pool, so subsequent changes to the source file do not change the agent's
captured input. The normal `artifacts.capture.max_file_size_bytes` limit applies.

Run `sase doctor -C config.artifact_refs` to find malformed, missing, nested,
overlapping, or zero-usable-root configurations. See
[Artifact References](../artifact-references.md) for prompt syntax and context rules.

## Related

- [Runtime and stored data configuration](runtime.md) — generated artifact keys and
  defaults.
