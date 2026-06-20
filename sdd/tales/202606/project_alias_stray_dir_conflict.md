---
create_time: 2026-06-19 22:13:40
status: done
prompt: sdd/prompts/202606/project_alias_stray_dir_conflict.md
---
# Plan: Stop stray project directories from breaking project-alias launches

## Symptom (the recurring failure)

Launching an agent whose prompt contains a VCS tag fails with:

```
RuntimeError: project alias 'bob' for project 'bob-cli' conflicts with a real project name
  (raised at src/sase/project_aliases.py:133)
```

This is the error in the screenshot. Two prior efforts (epic `sase-4t`, the `,L` Log panel + durable launch-failure
logging; and today's prompt-preservation work, commit `1ffc49b0f`) made this failure **visible and survivable** but
never removed its cause — which is why "it happened again."

## Root cause (diagnosed and deterministically reproduced)

`bob` is a legitimate project alias for the real project `bob-cli` (`~/.sase/projects/bob-cli/bob-cli.sase` contains
`PROJECT_ALIASES: bob`). Every launch with a VCS tag runs `canonicalize_project_aliases_in_prompt()` →
`load_project_alias_map()` → `_project_alias_map_from_records()` (`src/sase/project_aliases.py`). That function builds
the set of "real project names" from **every** record returned by `list_project_records()` and raises if any alias
collides with one (line 130-134).

The Rust-backed `list_project_records()` (sase-core `crates/sase_core/src/project_spec.rs:353`) discovers a project for
**every sub-directory** of `~/.sase/projects/`, _even a bare directory that has no `.sase` ProjectSpec file_. Such a
directory yields a record with `launchable=False`, `aliases=[]`, and a warning `"active ProjectSpec file not found"`.

So when a stray `~/.sase/projects/bob/` directory exists (no spec file), it is treated as a **real project named
`bob`**, which collides with `bob-cli`'s `bob` alias and makes `load_project_alias_map()` raise — aborting _every_
VCS-tagged launch until the stray directory disappears. The directory is transient (it was present during one diagnostic
run and gone moments later), which is exactly why the failure is intermittent and hard to catch.

Deterministic reproduction (a spec-less `bob/` dir next to a real `bob-cli` with alias `bob`):

```
bob      launchable=False  project_file_exists=False  warnings=['active ProjectSpec file not found: .../bob/bob.sase']
bob-cli  launchable=True   project_file_exists=True   aliases=['bob']
load_project_alias_map(...) -> ValueError: project alias 'bob' for project 'bob-cli' conflicts with a real project name
```

There are **two** distinct defects:

1. **Fragility (primary):** alias-map construction treats a directory with no ProjectSpec as a "real project," so a
   stray directory hard-fails all launches.
2. **Hygiene (secondary):** something creates a stray `~/.sase/projects/<alias>/` directory keyed by the _alias_ (`bob`)
   instead of the canonical project name (`bob-cli`). The per-project data writers (`src/sase/skills/use_log.py:137`,
   `src/sase/memory/read_log.py:342`) each do `path.parent.mkdir(parents=True, exist_ok=True)` on
   `~/.sase/projects/<project>/...`, so any caller that hands them an un-canonicalized alias materializes the stray
   directory. (The currently-running `bob-cli` agents derive `bob-cli` correctly via `project_memory_name()`, so the
   exact leak site is not yet pinned with certainty — see Part 2.)

## Fix design

### Part 1 — Make alias resolution robust to stray directories (primary, must-fix)

A directory with no backing ProjectSpec is **not a real project** and must not be allowed to shadow a legitimate alias.

In `src/sase/project_aliases.py`, restrict the "real project names" used for conflict detection in
`_project_alias_map_from_records()` to **spec-backed** records only. A record is spec-backed when its ProjectSpec exists
on disk:

```python
Path(record.project_file).is_file() or record.archive_file is not None
```

(`archive_file is not None` keeps genuinely archived/inactive projects counted.) `launchable` is deliberately **not**
used as the signal — a real project whose workspace directory is missing is still `launchable=False` and must keep its
alias.

Apply the filter where the real-project-name set is computed (and, harmlessly, to the alias-source iteration, since
spec-less dirs have no aliases). This is a small, Python-only change in the launch-boundary adapter; it does not touch
Rust core discovery (other callers — agent scan, project-management UI — legitimately want to see spec-less directories,
e.g. to flag a broken project).

Validated behavior of the new rule (reproduced):

| Scenario                                              | Old        | New                                           |
| ----------------------------------------------------- | ---------- | --------------------------------------------- |
| stray `bob/` (no spec) + real `bob-cli` (alias `bob`) | **raises** | resolves `bob`→`bob-cli`, no error            |
| real spec-backed `bob` + `bob-cli` (alias `bob`)      | raises     | **still raises** (genuine conflict preserved) |

This single change permanently fixes the recurring symptom regardless of how the stray directory appears, and preserves
correct conflict detection for real same-named projects.

Scope note: `allocate_project_alias()` (occupancy/avoidance) is intentionally left as-is — being conservative about
stray names there is harmless.

### Part 2 — Stop creating stray alias-named directories (secondary, defense-in-depth)

So that stray directories stop appearing at all (they are benign after Part 1, but should not accumulate):

1. **Confirm the leak site.** Add temporary instrumentation that records a stacktrace whenever a project data directory
   is created under a name that is a known alias (i.e. `resolve_project_alias_ref(name) != name`), then exercise a
   VCS-tagged / `#<alias>` launch to capture the exact caller. Remove the instrumentation before commit.
2. **Canonicalize at the data-write boundary.** In the per-project path helpers (`skill_use_log_path`,
   `memory_read_log_path`, `memory_proposal_ledger_path`, and the artifacts path builder) resolve the project name
   through `resolve_project_alias_ref()` before building the directory path, so an alias can never materialize a
   `~/.sase/projects/<alias>/` directory. (Safe to do once Part 1 guarantees `resolve_project_alias_ref` never raises.)
   Prefer fixing the single upstream source of the project name if instrumentation pinpoints one, rather than patching
   every writer.
3. **One-time cleanup is not required** — the stray `bob/` directory is already gone and is harmless after Part 1.

## Tests

- **Regression (Part 1), in `tests/test_project_alias_services.py`** (uses the existing `projects_root` fixture +
  `_write_project` helper):
  - A real `bob-cli` with `PROJECT_ALIASES: bob` plus a **stray spec-less `bob/` directory** ⇒
    `load_project_alias_map(projects_root)` returns `{'bob': 'bob-cli'}` and does **not** raise;
    `canonicalize_project_aliases_in_prompt('#gh:bob …')` rewrites to `#gh:bob-cli`.
  - A real **spec-backed** `bob` project plus `bob-cli` (alias `bob`) ⇒ still raises the conflict (legitimate behavior
    preserved).
- **Part 2 tests:** each patched path helper canonicalizes an alias to the canonical project name (so the directory is
  created under `bob-cli`, never `bob`).
- `just check` (lint + mypy + fast tests) before finishing.

## Risk / boundary notes

- Rust core (`list_project_records`) is **not** changed; the policy "spec-less directories are not real projects for
  alias purposes" stays in the Python launch adapter, consistent with the core/back-end boundary.
- The new spec-existence check adds one `stat` per project record during alias-map construction — negligible, and these
  are already disk-backed operations.
- Conflict detection for genuinely same-named real projects is preserved.

## Outcome

After Part 1, VCS-tagged launches no longer fail when a stray alias-named directory exists; after Part 2, such
directories stop being created in the first place. The class of "launch dies because an alias collides with a phantom
project" is closed.
