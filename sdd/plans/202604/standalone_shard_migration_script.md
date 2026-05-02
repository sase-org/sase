---
create_time: 2026-04-23 16:46:02
status: done
prompt: sdd/prompts/202604/standalone_shard_migration_script.md
---

# Standalone migration script for sharding `~/.sase/` dirs on another machine

## Context

Commit `852f8fd0` introduced `YYYYMM/` sharding for 9 high-volume `~/.sase/` subdirs and shipped
`sase migrate shard-dirs` as the migration entrypoint. That CLI works well on machines that are running a current `sase`
install. The user now wants to migrate a **different** machine (another of their personal machines, or any environment
where the installed `sase` may not yet include the new migrate subcommand).

## Problem

Requiring the target machine to first upgrade `sase`, resolve deps, and then run the CLI is fragile:

- The target may be running an older `sase` checkout, a stale venv, or a tagged release that predates the migrate
  command.
- Upgrading `sase` on the target machine may itself drag in unrelated changes the user isn't ready to deploy there.
- The migration is a one-shot, idempotent data move — it shouldn't be coupled to an application upgrade.

## Goal

Ship a **single-file, stdlib-only Python script** that re-implements the shard migration end-to-end and can be copied to
any machine (`scp`, `rsync`, pasted over SSH, etc.) and executed as:

```bash
python3 migrate_sase_shard_dirs.py [--dry-run] [--force] [--only chats,plans] [--sase-home PATH]
```

The output and semantics must match `sase migrate shard-dirs` exactly, so:

- Running the standalone script on machine B produces a layout identical to what the in-process CLI would produce.
- Running it twice is a no-op (`.sharded` sentinel).
- After the user later upgrades `sase` on machine B, `sase migrate shard-dirs` sees the sentinel and skips cleanly.

## Design

### 1. Location and shape

- Add `tools/migrate_sase_shard_dirs.py` — a standalone, executable, stdlib-only script.
  - `tools/` is the natural home (parallels `tools/run_silent`, `tools/sase_bead`, etc.) and keeps the script outside
    the installed `sase` package so it's copy-paste portable.
  - Single file, `#!/usr/bin/env python3` shebang, `chmod +x`.
  - No third-party imports; only `argparse`, `datetime`, `pathlib`, `re`, `shutil`, `sys`.
  - Python ≥ 3.9 (broader than `sase`'s `>=3.12` pin, since the target machine may be older — the logic is simple enough
    that there's no reason to require 3.12).

### 2. Logic (mirrored from `src/sase/main/migrate_handler.py` + `src/sase/core/paths.py`)

Inline copies of exactly these primitives:

- `_SHARD_DIR_RE = re.compile(r"^\d{6}$")`
- `_TS_SUFFIX_RE` / `_TS_PREFIX_RE` and `parse_filename_timestamp()`
- `_shard_name(ts)` → `"YYYYMM"`
- `_shard_for_path(path)` — filename-timestamp first, then mtime, then now
- `_SHARDED_LAYOUT` map (same 9 entries, same `file` vs `dir` kinds)
- `_migrate_one(base, kind, dry_run)` with the same atomic-rename + copy-then-unlink fallback for cross-device moves
- `.sharded` sentinel check/write (`shard_is_migrated` / `mark_shard_migrated`)

The only deliberate divergence from the in-process version:

- Accept `--sase-home PATH` to override `~/.sase` (useful for testing, for users with a relocated SASE home, and to make
  it trivial to dry-run against a snapshot/copy of the data before committing to the move).

### 3. CLI surface

```
usage: migrate_sase_shard_dirs.py [-h] [-n] [-f] [-o DIRS] [-s PATH]

Migrate top-level files under ~/.sase/<subdir>/ into YYYYMM/ shards.

  -n, --dry-run          Report what would move, change nothing.
  -f, --force            Re-run even if .sharded sentinel is present.
  -o, --only DIRS        Comma-separated subdir names to migrate (default: all 9).
  -s, --sase-home PATH   Override ~/.sase (default: $HOME/.sase).
```

Output format matches the in-process handler line-for-line so users comparing logs across machines see the same text:

```
chats: moved 16802, skipped 0
workflows: moved 6284, skipped 0
...
Moved 31743 entries (0 skipped) across 9 directories.
```

Exit codes: `0` on success, `2` on unknown `--only` names, `1` on unrecoverable errors.

### 4. Drift prevention

The script is a small duplicate of logic in `paths.py` + `migrate_handler.py`. Two lightweight guards:

1. **Docstring cross-reference**: top-of-file docstring names the two source files and commit `852f8fd0`, and a comment
   at the top of `_SHARDED_LAYOUT` says "keep in sync with `src/sase/main/migrate_handler.py`".
2. **Parity test** (`tests/tools/test_migrate_sase_shard_dirs_script.py`): build a synthetic `~/.sase`-like tree with a
   handful of files per sharded dir, run the in-process `_handle_shard_dirs` on one copy and the standalone script (via
   `subprocess`) on a second copy, and `assert` the resulting trees are byte-identical. This catches future edits to
   either side that forget to propagate.

### 5. Smoke tests for the script itself

In the same test file:

- Fresh migrate: seeded layout → correct shard placement → `.sharded` sentinel present → second run is a no-op.
- `--dry-run`: reports counts but changes nothing on disk.
- `--force`: re-runs past the sentinel and handles any newly-dropped legacy files.
- `--only plans,hooks`: touches only the listed subdirs.
- `--sase-home <tmp>`: honors the override and does not touch `~/.sase`.

### 6. Distribution / usage doc

Add a short "Migrating another machine" section to the top of the script's docstring (which is what users see if they
`head` the file after copying it over). It should include the three one-liners they actually need:

```bash
scp tools/migrate_sase_shard_dirs.py <host>:/tmp/
ssh <host> 'python3 /tmp/migrate_sase_shard_dirs.py --dry-run'
ssh <host> 'python3 /tmp/migrate_sase_shard_dirs.py'
```

No README/docs churn beyond that — the single script is the documentation.

## Non-goals

- Replacing or deprecating `sase migrate shard-dirs`. The in-process CLI stays the primary entrypoint on up-to-date
  machines; the standalone script is for machines where upgrading first is inconvenient.
- Changing any shard-layout rules, filename formats, or the set of sharded subdirs.
- Automating the copy step (scp/rsync). The user runs the script however they prefer.
- Any remote-execution tooling (Ansible, Fabric, etc.) — out of scope for a one-shot migration.

## Risks

- **Silent drift from the in-process implementation.** Mitigated by the parity test (§4) that cross-checks outputs.
- **Older Python on the target.** Mitigated by sticking to Python 3.9 syntax and stdlib only; verified by running the
  script under `python3.9` in CI if we have it, or by
  `python -c "import ast; ast.parse(open('...').read(), feature_version=(3,9))"` in the parity test.
- **Cross-filesystem `~/.sase`.** The in-process version already handles `OSError` from `Path.rename` with a
  `copy2 + unlink` fallback; the standalone script mirrors that exactly.
- **Concurrent writes during migration.** Same as the in-process version — atomic rename within a filesystem, and any
  file the script can't move is simply skipped and remains reachable through the legacy-top-level fallback in readers
  (once the target upgrades `sase`). Document in the script's docstring: "stop long-running `sase` processes on the
  target before running".
