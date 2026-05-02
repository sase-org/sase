---
create_time: 2026-04-23 18:34:03
status: done
prompt: sdd/prompts/202604/fix_pending_checks_poll_timeout.md
---
# Fix `sase axe` pending_checks_poll Timeout

## Problem

The user's `sase axe` is logging repeated errors:

```
Lumberjack: hooks
Job:        pending_checks_poll
Error:      timed out after 90s
```

(See `.sase/home/.sase/axe/error_digests/digest_20260423_182750.txt`.)

The `pending_checks_poll` chop runs every 5s inside the `hooks` lumberjack and is supposed to reap completed background
check output files from `~/.sase/checks/`. It is hitting the default `chop_timeout` of 90s
(`src/sase/default_config.yml:168`) on every tick, meaning the scheduler kills it mid-work and never actually reaps
anything.

## Root Cause

Investigation of the user's real `~/.sase/checks/` directory found **4,311 zero-byte orphan files** accumulated over 2+
months (oldest: 2026-02-18). Breakdown:

- **4,289 files** directly in `~/.sase/checks/` (legacy, pre-sharding layout).
- **107 files** in `~/.sase/checks/202604/` (current sharded layout).
- Virtually all are zero bytes with no completion marker, mostly named `my_feature-reviewer_comments-*.txt` (a test
  fixture name — likely leaked from an earlier non-isolated test run or a bug in a prior version of
  `_start_background_check`).

Three compounding bugs turn this pile of orphans into a 90s timeout:

### Bug 1 — No orphan cleanup

`_cleanup_check_file` (`src/sase/ace/scheduler/checks_runner.py:439`) is only called when `_parse_check_completion`
returns `is_complete=True`. A zero-byte file (background process died, was killed, or never wrote the marker) is
therefore skipped forever and stays on disk. There is no age-based cleanup anywhere.

### Bug 2 — O(N × M) scan pattern

`run_pending_checks_poll` (`src/sase/axe/hook_jobs.py:153`) iterates over every filtered ChangeSpec and calls
`check_pending_checks(changespec, ...)`, which calls `_get_pending_checks`, which calls
`iter_sharded_files("checks", pattern="*.txt")` — a full directory scan — once **per ChangeSpec**. With N ChangeSpecs
and M on-disk files the work is O(N × M) per tick.

### Bug 3 — Legacy files re-scanned every tick

`iter_sharded_files` (`src/sase/core/paths.py:174`) defaults to `include_legacy=True`, so the 4,289 top-level legacy
files get re-globbed and re-regex-matched in every per-ChangeSpec scan.

### Why this now exceeds 90s

At ~N=30 active ChangeSpecs and M≈4,300 files, each tick does ≈130,000 regex matches plus the subprocess startup cost of
the chop script (Python + full `sase` import). The 90s budget is blown before anything useful runs — which is why the
files never get cleaned up, which is why the pile keeps growing. It is a feedback loop.

## Fix Strategy

Three parts. (A) is the long-term root-cause fix. (B) is the structural efficiency fix. (C) is a one-time manual
remediation to unstick the user today.

### Part A — Age-based orphan cleanup (root-cause fix)

Add a cleanup pass inside the poll that deletes check output files which are (a) missing the completion marker **and**
(b) older than a threshold. Threshold is `2 × chop_timeout` (so 180s by default) — long enough to never race a
legitimately slow in-flight check, short enough to bound the orphan pile at a few minutes of production.

**Code sketch** in `src/sase/ace/scheduler/checks_runner.py`:

```python
_ORPHAN_AGE_SECONDS = 180  # 2× default chop_timeout

def _reap_orphan_check_files(log: LogCallback) -> int:
    """Delete check files with no completion marker older than _ORPHAN_AGE_SECONDS.

    Returns the count reaped. Called once per poll tick, not per ChangeSpec.
    """
    now = time.time()
    reaped = 0
    for path in iter_sharded_files("checks", pattern="*.txt"):
        try:
            st = path.stat()
        except OSError:
            continue
        if now - st.st_mtime < _ORPHAN_AGE_SECONDS:
            continue
        # Peek at contents; keep if a completion marker is there (poll will reap it).
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if CHECK_COMPLETE_MARKER in content:
            continue
        try:
            path.unlink()
            reaped += 1
        except OSError:
            pass
    if reaped:
        log(f"Reaped {reaped} orphaned check file(s)", "yellow")
    return reaped
```

Wire it into the existing single-scan poll (see Part B).

### Part B — Scan once per tick, dispatch by name

Invert the scan/loop order in `run_pending_checks_poll` so the directory is walked **once per tick** and the results are
grouped by ChangeSpec name. This alone takes the poll from O(N × M) to O(M) and makes it cheap even with thousands of
files.

**Code sketch** — new helper in `checks_runner.py`:

```python
def scan_all_pending_checks() -> dict[str, list[_PendingCheck]]:
    """Walk ~/.sase/checks/ once and group pending checks by ChangeSpec name."""
    pattern = re.compile(
        r"^(?P<name>.+)-(?P<type>cl_submitted|reviewer_comments)-(\d{6}_\d{6})\.txt$"
    )
    by_name: dict[str, list[_PendingCheck]] = {}
    for file_path in iter_sharded_files("checks", pattern="*.txt"):
        m = pattern.match(file_path.name)
        if not m:
            continue
        by_name.setdefault(m["name"], []).append(
            _PendingCheck(
                changespec_name=m["name"],
                check_type=m["type"],  # type: ignore[arg-type]
                timestamp=m[3],
                output_path=str(file_path),
            )
        )
    return by_name
```

Refactor `run_pending_checks_poll` (`hook_jobs.py:153`) to:

```python
def run_pending_checks_poll(self, filtered_changespecs):
    _reap_orphan_check_files(self._log)          # Part A
    by_name = scan_all_pending_checks()          # Part B
    # Build a lookup by the safe_name used in filenames.
    safe_to_cs = {_safe_name(cs.name): cs for cs in filtered_changespecs}
    for safe, checks in by_name.items():
        cs = safe_to_cs.get(safe)
        if cs is None:
            continue  # file belongs to a deleted/unknown ChangeSpec
        updates = process_pending_checks_for(cs, checks, self._log)
        ...
```

Where `_safe_name` is the same `re.sub(r"[^a-zA-Z0-9_]", "_", name)` used in `_get_check_output_path`.
`process_pending_checks_for` is a thin refactor of today's `check_pending_checks` that takes pre-scanned
`_PendingCheck`s instead of rescanning. The existing `check_pending_checks(changespec, log)` stays for other callers
(e.g. `has_pending_check`, tests).

Also consider setting `include_legacy=False` in the new scan path: legacy files belong to pre- sharding state and don't
appear in the current write path, so scanning them only costs time. Part A will reap them across a handful of ticks,
after which they're gone.

### Part C — One-time manual cleanup

The plan itself doesn't delete files behind the user's back, but once the code changes are in place we'll instruct the
user to run:

```bash
find ~/.sase/checks -type f -mmin +5 -size 0 -delete
```

to clear the 4,000+ existing zero-byte orphans immediately instead of waiting for the new reaper to chew through them
over several ticks. (Kept outside the code so the user explicitly authorizes touching their home directory.)

## Files Touched

| File                                      | Change                                                                                                                                                             |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/sase/ace/scheduler/checks_runner.py` | Add `_reap_orphan_check_files`, `scan_all_pending_checks`, `_safe_name`; refactor `check_pending_checks` into `process_pending_checks_for(cs, checks, log)` + shim |
| `src/sase/axe/hook_jobs.py`               | Refactor `run_pending_checks_poll` to call the reaper once, scan once, dispatch by name                                                                            |
| `tests/test_checks_runner.py`             | New tests (below)                                                                                                                                                  |

No schema changes, no config changes, no default-config changes. `chop_timeout` stays at 90s — the refactor brings the
actual runtime well under it so the timeout no longer fires.

## Testing

New tests in `tests/test_checks_runner.py`, all using `redirect_sase_home(monkeypatch, tmp_path)`:

1. **`test_reap_orphan_check_files_deletes_old_marker_less`** — write a zero-byte file with `mtime = now - 300s`, run
   reaper, assert deleted and count == 1.
2. **`test_reap_orphan_check_files_preserves_recent`** — write a zero-byte file with `mtime = now`, run reaper, assert
   still present.
3. **`test_reap_orphan_check_files_preserves_completed`** — write a file with `CHECK_COMPLETE_MARKER` but old mtime, run
   reaper, assert still present (the poll will reap it through the normal path).
4. **`test_scan_all_pending_checks_groups_by_name`** — write files for two ChangeSpec names in two different shard dirs,
   assert the returned dict keys and lengths.
5. **`test_scan_all_pending_checks_ignores_malformed_filenames`** — write `nonsense.txt` and
   `foo-badtype-123456_123456.txt`, assert neither appears in the result.
6. **`test_run_pending_checks_poll_scans_once`** — mock `iter_sharded_files` and call `run_pending_checks_poll` with 5
   mock ChangeSpecs; assert mock called exactly once (proving the O(N) scan is gone).

Existing tests keep the `check_pending_checks(changespec, log)` shim honest.

## Risk & Rollback

- **Data loss risk**: the reaper deletes files. Mitigation: only files older than 3 minutes **and** missing the
  completion marker are deleted. A real in-flight check that takes >3 minutes is already unusable (the chop_timeout is
  90s; anything that slow has been killed by the parent). If we want to be extra-cautious, gate the reaper on
  `mtime > 600s` and document it — trivial follow-up.
- **Behavioral risk**: the `by_name` dispatch uses `safe_name` as the key. If two different ChangeSpec names collapse to
  the same safe_name (e.g. `foo-bar` and `foo_bar`), they'd share pending checks. This is a pre-existing ambiguity — the
  filename encoding is already lossy. Call it out in a comment; don't try to fix it in this plan.
- **Rollback**: straight revert; no persistent state is touched apart from deleting orphan files, and those are by
  definition already unreachable.

## Out of Scope

- Changing the default `chop_timeout` (no longer needed once the poll is fast).
- Making `include_legacy=False` the global default (narrow concern of this codepath; other callers may legitimately want
  legacy files).
- Adding a dedicated housekeeping chop for orphan cleanup — folding it into the poll keeps the feedback tight (the work
  happens on the same cadence as the thing that creates the orphans) and avoids a new config surface.
