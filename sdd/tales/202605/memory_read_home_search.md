---
create_time: 2026-05-31 08:54:33
status: done
prompt: sdd/prompts/202605/memory_read_home_search.md
---
# Plan: Search Project and Home Memory for `sase memory read`

## Goal

Make `sase memory read <memory-relative-path>` resolve allowed long-term memory files from both the current
project-local `memory/` tree and the user's home `~/memory/` tree. The user-facing example
`sase memory read long/obsidian.md -r "foobar"` should work from a project workspace when `~/memory/long/obsidian.md`
exists and the project does not define that file.

## Current Behavior

The audited read path is implemented in `src/sase/memory/read_log.py`. `validate_memory_read_path()` validates that the
argument is relative, starts with an allowed tier (`long`), ends in `.md`, and has no traversal. It then resolves only
`<project_root>/memory/<path>`, where `project_root` defaults to `Path.cwd()`.

`sase memory list` already knows about both project and home memory roots, but `sase memory read` does not reuse that
multi-root model. The CLI handler in `src/sase/memory/cli_read.py` calls `validate_memory_read_path()` without a home
root, so missing project files fail before home memory is considered.

## Design

1. Keep the existing path validation rules unchanged:
   - absolute paths are rejected;
   - traversal is rejected;
   - `memory/short` remains blocked;
   - only configured allowed tiers, currently `long`, are readable;
   - only `.md` files are readable.

2. Resolve memory roots in deterministic precedence order:
   - project root: `(project_root or Path.cwd()) / "memory"`;
   - home root: `Path.home() / "memory"`, unless it resolves to the same root as the project root.

3. Treat "missing in this root" as a reason to continue to the next root. Treat an existing but invalid candidate
   (directory, symlink escaping its allowed tier, unreadable/unresolvable path) as an error rather than silently falling
   through to home memory. This preserves the security meaning of a project-local path when it exists.

4. Preserve audit compatibility:
   - `MemoryReadEvent.canonical_path` remains the user-supplied memory-relative path such as `long/obsidian.md`;
   - `MemoryReadEvent.resolved_path` records the actual project or home file path;
   - logs remain project-scoped via the existing `memory_read_log_path(cwd=...)` behavior.

5. Update the CLI call site to opt into home-memory resolution and update help/docs wording so the behavior is
   discoverable.

## Tests

Add focused unit coverage in `tests/test_memory_read_log.py`:

- a project memory file is preferred when both project and home define the same `long/<file>.md`;
- home memory is used when the project file is absent;
- duplicate project/home roots are deduped;
- an invalid existing project symlink does not fall through to a valid home file.

Add CLI-level coverage in `tests/main/test_memory_read_list.py`:

- `handle_memory_read_command()` prints the body from `~/memory/long/<file>.md` and records the resolved home path when
  the project file is absent.

Run the focused tests first:

```bash
.venv/bin/python -m pytest tests/test_memory_read_log.py tests/main/test_memory_read_list.py -q
```

Then run the required repository validation after file changes:

```bash
just install
just check
```
