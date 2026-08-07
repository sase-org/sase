# Agent Revival Audit Log

The TUI's revive flow (`R` on the Agents tab) writes a JSONL audit log to
`~/.sase/logs/events.jsonl` so post-mortem questions like "what was the last agent I
tried to revive?" can be answered without grepping through dismissed-bundle directories.
Paths shown here use the default SASE state root; when `SASE_HOME` is set, the log lives
under that root instead.

Three event kinds are emitted:

| event                  | meaning                                                                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `agent_revive_started` | User confirmed a revival in the modal. One record per invocation (single or batch); captured before any state mutation so a mid-flight crash still leaves a trace. |
| `agent_revived`        | A single agent was revived successfully. Batch revivals produce one record per agent.                                                                              |
| `agent_revive_failed`  | Either the "no dismissed agents" early-out fired, or an exception was raised mid-flow. Batch revivals produce one failure record per agent that failed.            |

## Record schema

Common fields on every record:

- `timestamp` — local time as `YYmmdd_HHMMSS`.
- `event` — one of the three names above.
- `batch_size` — `1` for a single revival; the count of selected agents for a batch.
- `agents` — only on `agent_revive_started`; a list of
  `[agent_type, cl_name, raw_suffix]` identities that were selected before mutation
  began.
- `outcome` — `"success"` or `"failure"` (omitted for `agent_revive_started`).
- `selection_scope` — `"all"`, `"home"`, `"project"`, or `"cl"`, plus
  `selection_project` / `selection_cl` when applicable. These fields are omitted when
  the revive was not launched from a scoped selection.
- `saved_group_id` / `saved_group_title` — present when the revival was launched from
  the saved-group modal rather than the custom scoped search.

Per-agent fields on `agent_revived` / `agent_revive_failed`:

- `agent_identity` — `[agent_type, cl_name, raw_suffix]`.
- `agent_type`, `cl_name`, `raw_suffix`, `project_file`.
- `bundle_path` — the path under `~/.sase/dismissed_bundles/YYYYMM/` that the revive
  flow loaded. Revive preserves the bundle as historical recovery data.
- `child_suffixes` — only on `agent_revived`; workflow steps / follow-up agents revived
  alongside the parent (sorted).

Failure-only fields:

- `stage` — one of `dismissed_set_update`, `artifact_restore`, `bundle_marking`,
  `reload`, `refresh_display`, `saved_group_load`, `saved_group_bundle_load`,
  `saved_group_mark_revived`, or `no_dismissed_agents`.
- `error_type` / `error_message` — exception class and `str(exc)` truncated to 500
  characters.
- `reason` — set for non-exceptional failures (currently only `no_dismissed_agents`).

## CLI

```
sase revive-log              # last 20 records, rich table
sase revive-log --all        # every record
sase revive-log --since -7d  # records on/after the daterange start
sase revive-log --outcome failure
sase revive-log --json       # one JSON object per line for agent consumption
```

`--since` accepts the same daterange grammar as `sase logs`.

## Backfill

There is no recoverable audit history before this feature shipped. Existing dismissed
bundles remain usable, but the first revival after the feature lands is the earliest
structured event.
