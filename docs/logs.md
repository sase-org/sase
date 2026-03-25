# Logs

The `sase logs` command collects data from across sase's various subsystems into a self-contained **log pack** — a
timestamped directory containing everything relevant to a given date range.

## Usage

```bash
sase logs <daterange>
```

Date range formats:

| Format      | Example               | Description                  |
| ----------- | --------------------- | ---------------------------- |
| `today`     | `sase logs today`     | From midnight to now         |
| `yesterday` | `sase logs yesterday` | Full previous day            |
| `N{d,h,m}`  | `sase logs 3d`        | Last N days/hours/minutes    |
| `MMDD`      | `sase logs 0315`      | Specific date (current year) |
| `MMDD-MMDD` | `sase logs 0310-0315` | Date range                   |

## Pack Structure

Log packs are written to `~/.sase/logs/pack/<timestamp>/` and contain:

```
~/.sase/logs/pack/250325_143000/
├── manifest.json              # Pack metadata (range, file count, timestamps)
├── chats/                     # Agent chat transcripts (.md)
├── hooks/                     # Hook execution logs (.txt)
├── workflows/                 # Workflow execution logs (.txt)
├── diffs/                     # ChangeSpec diffs (.diff)
├── checks/                    # Check results
├── plans/                     # Plan approval files
├── questions/                 # User question files
├── comments/                  # Comment JSON files
├── mentors/                   # Mentor review JSON files
├── archived/                  # Archived diffs (.diff)
├── reverted/                  # Reverted diffs (.diff)
├── saved_plans/               # Saved plan files
├── artifacts/                 # Workflow artifacts (preserves project/workflow/timestamp hierarchy)
├── axe/                       # Axe lumberjack state (preserves per-lumberjack structure)
│   └── {lumberjack}/
│       ├── *.json             # State and metrics files
│       └── logs/output.log    # Lumberjack output log
├── notifications.jsonl        # Notification entries (ISO 8601 timestamps)
├── runs.jsonl                 # Agent run log entries
├── events.jsonl               # Event log entries
├── commit_stop_hook.jsonl     # Commit stop hook invocation log
└── git_commit.jsonl           # Git commit operation log
```

### Manifest

Each pack includes a `manifest.json` with:

```json
{
  "created": "2025-03-25T14:30:00-04:00",
  "range_start": "2025-03-25T00:00:00-04:00",
  "range_end": "2025-03-25T14:30:00-04:00",
  "range_spec": "today",
  "file_count": 42,
  "pack_dir": "/home/user/.sase/logs/pack/250325_143000"
}
```

## Collectors

Log packs are built from two types of collectors:

- **File-based collectors** — scan directories for files matching the date range (by filename timestamp suffix or file
  modification time) and copy them into the pack.
- **JSONL-based collectors** — filter lines from JSONL log files by their `timestamp` field and write matching entries
  to the pack.

### JSONL Log Files

| Log File                         | Contents                                          |
| -------------------------------- | ------------------------------------------------- |
| `~/.sase/logs/runs.jsonl`        | Agent run start/stop events                       |
| `~/.sase/logs/events.jsonl`      | General sase events                               |
| `~/.sase_commit_stop_hook.jsonl` | Commit stop hook invocations (decision, metadata) |
| `~/.sase_git_commit.jsonl`       | Git commit operations (commit hash, message)      |

All timestamps use the configured timezone (default: `America/New_York`). See
[`docs/configuration.md`](configuration.md) for timezone configuration.
