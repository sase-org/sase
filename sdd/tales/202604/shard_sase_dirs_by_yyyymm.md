---
create_time: 2026-04-23 16:01:42
status: done
prompt: sdd/prompts/202604/shard_sase_dirs_by_yyyymm.md
---

# Shard high-volume `~/.sase/` directories into `YYYYMM/` subdirectories

## Problem

Several directories under `~/.sase/` have grown large enough to slow the TUI and other `sase` tooling. On the user's
machine today:

| Directory            | Top-level entries | Naming pattern                                  |
| -------------------- | ----------------- | ----------------------------------------------- |
| `chats/`             | **16,802** files  | `<slug>-<workflow>-YYmmdd_HHMMSS.md`            |
| `workflows/`         | **6,284** files   | `<safe_name>_ace-run-YYmmdd_HHMMSS.txt`         |
| `checks/`            | **4,278** files   | `<safe_name>-<check_type>-YYmmdd_HHMMSS.txt`    |
| `dismissed_bundles/` | **2,177** files   | `YYYYmmddHHMMSS[__cN].json`                     |
| `plans/`             | **818** files     | `<slug>.md` (no embedded timestamp)             |
| `plan_approval/`     | **648** subdirs   | `<uuid>/plan_{request,response}.json`           |
| `hooks/`             | **396** files     | `<safe_name>-YYmmdd_HHMMSS.txt`                 |
| `diffs/`             | **129** files     | `<name>-YYmmdd_HHMMSS.diff` (sometimes no name) |
| `mentors/`           | **111** files     | `<safe_name>-...-YYmmdd_HHMMSS.{txt,json}`      |

Callers routinely do `os.listdir(chats_dir)` / `scandir` / `dir.glob("*.json")` and then `stat` each entry (sort by
mtime, parse filename, match patterns). At 16k+ entries in `chats/` alone that's measurably slow — especially on TUI
refresh paths and `sase ace` startup, where collectors iterate the dir repeatedly.

## Goal

Introduce a transparent `YYYYMM/` sharding scheme for every `~/.sase/` directory that grows unboundedly over time, and
migrate the existing files on this machine into the new layout. Keep the change invisible to callers — they keep asking
for paths by filename/slug and the storage layer handles shard placement and cross-shard scans.

## Design

### 1. Central helpers (`src/sase/core/paths.py`)

Add a small API that every write/read site will use instead of hand-rolling `os.path.join(dir, filename)` or
`os.listdir(dir)`:

```python
def sharded_path(
    subdir: str,
    filename: str,
    *,
    ts: datetime | None = None,
    ensure: bool = True,
) -> str:
    """Return the sharded path for a file under ~/.sase/<subdir>/YYYYMM/<filename>.

    The shard is chosen from, in order:
      1. An explicit `ts` argument
      2. A `YYmmdd_HHMMSS` / `YYYYmmddHHMMSS` timestamp parsed from `filename`
      3. datetime.now()
    If `ensure=True`, the shard directory is created.
    """

def iter_sharded_files(
    subdir: str,
    *,
    pattern: str = "*",
    include_legacy: bool = True,
) -> Iterator[Path]:
    """Yield file paths across all YYYYMM/ shards under ~/.sase/<subdir>/.

    If `include_legacy=True`, also yields any files directly in <subdir>/
    (pre-migration stragglers and external tools that don't know about
    sharding).
    """

def find_sharded_file(
    subdir: str,
    filename: str,
    *,
    ts: datetime | None = None,
) -> str | None:
    """Look up a specific filename. Fast path: try the shard implied by `ts`
    or by a timestamp parsed from `filename`. Slow path: scan all YYYYMM/
    shards (+ legacy top-level) for an exact match. Returns None if missing.
    """
```

Filename-timestamp parsing covers the two formats used in the repo today:

- `-YYmmdd_HHMMSS.ext` suffix (chats, workflows, checks, hooks, diffs, mentors, comments)
- `YYYYmmddHHMMSS` at start (dismissed_bundles)

For `plans/` and `plan_approval/` (no timestamp in name/id), shard by "now()" at write time; reads do a cross-shard
lookup — acceptable since we only have ~12 shards per year and each has far fewer entries than today's flat dir.

### 2. Call-site updates

All write/read sites for the targeted directories are already centralized behind a handful of helpers, so the blast
radius is small:

| Directory            | Write sites                                                               | Read sites                                                                                                                |
| -------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `chats/`             | `history/chat.py::save_chat_history`                                      | `history/chat.py::{get_chat_file_path, list_chat_histories, find_chat_by_timestamp}`, `logs/collectors.py::collect_chats` |
| `workflows/`         | `agent/launcher.py`, `ace/scheduler/workflows_runner/starter.py`          | `axe/run_workflow_runner.py`, `logs/collectors.py::collect_workflows`                                                     |
| `checks/`            | `ace/scheduler/checks_runner.py::_get_check_output_path`                  | `ace/scheduler/checks_runner.py::_get_pending_checks`, `logs/collectors.py::collect_checks`                               |
| `dismissed_bundles/` | `ace/dismissed_agents.py::save_dismissed_bundle`                          | `ace/dismissed_agents.py::{load_dismissed_bundles, remove_bundle_by_identity}`                                            |
| `plans/`             | `llm_provider/_plan_utils.py::save_plan_to_sase`                          | `workflows/commit/precommit_hooks.py` (fallback lookup), `logs/collectors.py::collect_saved_plans`                        |
| `plan_approval/`     | `llm_provider/_plan_utils.py::handle_plan_approval`                       | `notifications/senders.py::notify_plan_approval` (receives path; no change), `logs/collectors.py::collect_plans`          |
| `hooks/`             | `ace/hooks/persistence.py::get_hook_output_path`                          | `logs/collectors.py::collect_hooks`                                                                                       |
| `diffs/`             | `workflows/commit_utils/workspace.py`, `workspace_provider/changespec.py` | `logs/collectors.py::collect_diffs`                                                                                       |
| `mentors/`           | `ace/scheduler/mentor_runner.py`                                          | `logs/collectors.py::collect_mentors`                                                                                     |

Each write site becomes `sharded_path("chats", basename)` etc. Each scan site becomes
`iter_sharded_files("chats", pattern="*.md")`.

`logs/collectors.py` is a single helper (`_collect_by_filename_suffix` / `_collect_by_mtime`) — switch its internal
`d.glob(glob)` to recurse via `iter_sharded_files`, and every `collect_*` function picks up sharding for free.

### 3. One-shot migration

Ship an idempotent migration that runs on this machine and for any other user whose directories were populated before
sharding. Two options; plan recommends **(a)**:

**(a) Explicit CLI subcommand** — `sase migrate shard-dirs` (or reuse an existing admin entrypoint). Walks each
configured subdir, moves every top-level file into `YYYYMM/` based on its filename timestamp, falling back to mtime when
no timestamp is embedded (plans, plan_approval, reverted, etc.). Writes a sentinel `.sharded` in the subdir on success
to short-circuit future runs. User runs it once; then every fresh install starts sharded from day one and never needs to
migrate.

**(b) Auto-migrate on first use** — same logic, but triggered lazily the first time each dir is touched. Simpler UX but
risks surprising latency on a TUI startup. Reject.

Whichever path we take, readers must tolerate a mixed layout during the transition window
(`iter_sharded_files(include_legacy=True)` handles this).

### 4. Which directories are in scope

In scope (shard + migrate):

- `chats/`, `workflows/`, `checks/`, `dismissed_bundles/`, `plans/`, `plan_approval/`, `hooks/`, `diffs/`, `mentors/`

Not sharded:

- `projects/` — small, bounded by active project count.
- `comments/`, `reverted/`, `user_question/`, `notifications/`, `telegram/`, `axe/`, `commit_state/`, `logs/`, `home/`,
  `repos/`, `spec_writer/`, `images/`, `archived/`, `hooks-local state`, top-level JSON files — either already bounded,
  already structured, or current sizes don't justify the complexity. Revisit individually if any of these later crosses
  ~1000 entries.

A short rationale for each exclusion goes in a doc comment at the top of `paths.py` so future maintainers know the
criteria.

### 5. Tests

Add unit tests in `tests/core/test_sharded_paths.py`:

- `sharded_path` places files by explicit ts, name-derived ts, and now().
- `iter_sharded_files` surfaces files from multiple shards AND legacy top-level files.
- `find_sharded_file` fast-path hits the predicted shard and slow-path falls through.
- Round-trip: write via `sharded_path` → read via `iter_sharded_files`.

Extend the existing collector tests in `tests/logs/` to cover a multi-shard directory layout.

Smoke-test the migration: create a temp `~/.sase`-like tree with a handful of files per dir, run the migration, assert
layout, run it a second time and assert it's a no-op.

### 6. Rollout

1. Land helpers + tests (no behavior change; nothing calls them yet).
2. Land per-directory migration writes + reads one dir at a time, smallest first (`mentors`, `diffs`, `hooks`, …,
   `chats` last). Each PR is self-contained and `iter_sharded_files(include_legacy=True)` keeps legacy files readable.
3. Land the migration CLI.
4. Run the migration on this machine:
   ```
   sase migrate shard-dirs
   ```
   Verify: `chats/` now contains only `YYYYMM/` subdirs (plus `.sharded` sentinel), TUI startup / `sase ace` refresh
   feel snappy again.

## Non-goals

- Changing any filename format (suffix timestamp style stays `YYmmdd_HHMMSS`; dismissed_bundles names stay
  `YYYYmmddHHMMSS`). Sharding is purely a directory-layout change.
- Retention / cleanup of old shards. That's a separate policy question.
- Sharding in-project `.sase/` directories (memory, plans, etc.) — those live per-repo and aren't the source of the perf
  hit.

## Risks

- **Cross-shard scans become slow if we ever have >>12×N shards** — mitigated by scanning only when a caller truly needs
  "all" files (listing, collectors). Lookup-by-name first tries the shard predicted by the filename timestamp.
- **Legacy files created by other tooling** (e.g., user manually drops a file into `~/.sase/plans/`) won't be
  auto-sharded. `include_legacy=True` keeps them readable; we document that the migration CLI can be re-run to sweep
  them in.
- **Concurrent writes during migration** — the CLI should move files atomically (`os.rename` within the same filesystem)
  and skip files it can't move; worst case is a file remains top-level and is found via the legacy fallback.
