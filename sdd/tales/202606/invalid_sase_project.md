---
create_time: 2026-06-02 07:23:12
status: done
prompt: sdd/prompts/202606/invalid_sase_project.md
---
# Stop Hidden `.sase` Project Records

## Context

`sase project` is showing an invalid `.sase` project:

```text
PROJECT                  STATE      CLAIMS LAUNCH  WORKSPACE
.sase                    active          0 no      -
```

The live state confirms this is a real but invalid state directory:

- Project dir: `/home/bryan/.sase/projects/.sase`
- Project file: `/home/bryan/.sase/projects/.sase/.sase.sase`
- File content: zero bytes
- Created: `2026-06-02 07:12:48 -0400`
- Lifecycle state: defaulted to `active` because missing `PROJECT_STATE` means active
- Launchable: false because `WORKSPACE_DIR` is not set

This explains why it appears in `sase project list`: `src/sase/main/project_handler.py` delegates listing to
`list_project_records(...)` and then prints every active record, even non-launchable ones.

## Likely Root Cause

The zero-byte shape matches `create_project_file(".sase")`:

```text
~/.sase/projects/<project>/<project>.sase
=> ~/.sase/projects/.sase/.sase.sase
```

The probable creation chain is:

1. `/home/bryan/.sase` itself is a Git repo.
2. `BareGitWorkspacePlugin.ws_get_workspace_name()` falls back to `git rev-parse --show-toplevel` and returns the
   basename of the repo root. For `/home/bryan/.sase`, the direct plugin result is `.sase`.
3. `launch_agents_from_cwd()` calls `ensure_project_file_and_get_workspace_num()` before explicit VCS refs such as
   `#gh:sase` are fully resolved.
4. If a launch or workflow starts with CWD under `/home/bryan/.sase`, that eager project preflight can infer `.sase`.
5. `create_project_file()` accepts the inferred name without validation and writes an empty `.sase.sase` ProjectSpec.
6. The lifecycle scanner treats that empty ProjectSpec as an active project, because default-active is intentional for
   legacy valid projects.

The timestamp aligns with automated axe launches around `07:12:47`, so this may be a background launch/preflight from
SASE state rather than an explicit user request for a `.sase` project.

## Plan

1. Add a single project-name validation helper.

   Define a shared Python helper for SASE project directory names, for example in a core/path-adjacent module. It should
   reject:
   - empty names
   - `.` and `..`
   - names with path separators
   - hidden names starting with `.`
   - names that cannot round-trip as one direct child under `~/.sase/projects`

   It should continue to allow existing valid names such as `sase`, `beads`, `bob-cli`, `CV`, `zorg`, `home`, and
   underscore/dot-internal names if needed.

2. Prevent invalid project creation.

   Use the helper before every path that creates or auto-initializes a project:
   - `create_project_file(project)`
   - `ensure_project_file_and_get_workspace_num()`
   - bare-git auto-init paths in `resolve_git_ref()` / `init_bare_git_project()`
   - lifecycle mutation/deletion resolution in `project_handler.py`

   For inferred CWD project names, invalid should behave like “no recognized project” rather than creating state. This
   preserves explicit prompt refs: a launch from `~/.sase` with `#gh:sase` should still resolve to the real `sase`
   project later.

3. Prevent bad CWD inference at the provider boundary.

   Update `BareGitWorkspacePlugin.ws_get_workspace_name()` so names derived from remote URLs or Git root basenames are
   validated before returning. If the Git root is `/home/bryan/.sase`, return `None` rather than `.sase`.

   This avoids bad project names leaking into prompt history, artifact paths, launch preflight, or other CWD-based
   helpers.

4. Stop invalid records from appearing in project discovery.

   `sase project list`, ACE project management, launch pickers, xprompt project discovery, and mobile helper catalogs
   all consume `list_project_records(...)`. Add a guard at this shared boundary so direct child directories with invalid
   project names do not become normal project records.

   The durable backend-owned version belongs in `sase-core` because `list_project_records` is Rust-backed. Opening the
   matching `sase-core` workspace is currently blocked because `sase workspace open -p sase-core 10` reports no
   `WORKSPACE_DIR`. If that cannot be repaired immediately, add a Python facade filter as a tactical guard, then mirror
   the rule in Rust when backend workspace access is available.

5. Add focused regression tests.

   Cover the full failure chain:
   - `BareGitWorkspacePlugin.ws_get_workspace_name()` returns `None` for a Git top-level basename `.sase`.
   - `create_project_file(".sase")` refuses and does not create `projects/.sase/.sase.sase`.
   - `ensure_project_file_and_get_workspace_num()` ignores invalid inferred names and does not create a ProjectSpec.
   - A launch path with explicit `#gh:sase` and an invalid inferred CWD project still launches against `sase`, not
     `.sase`.
   - `list_project_records` / `sase project list` excludes a hidden `.sase` child directory.

   If Rust backend changes are made, add the corresponding `sase-core` scanner test for hidden project directories.

6. Handle the existing bad state after code changes.

   Once the guardrails are in place, the already-created `/home/bryan/.sase/projects/.sase` directory can be removed or
   left hidden by discovery. Because deletion touches user state, do it deliberately after confirming it contains only
   the zero-byte `.sase.sase` file and no artifacts, episodes, memory proposals, or running claims.

7. Verify.
   - Run `just install` before tests if the workspace environment is not already current.
   - Run targeted Python tests for the changed modules.
   - Run Rust tests if `sase-core` is changed.
   - Run `just check` after source changes.
   - Confirm `sase project list --state all --json` no longer includes `.sase`.

## Expected Outcome

The invalid `.sase` project stops being created from SASE state CWDs, existing hidden state directories no longer
pollute project discovery, and explicit launches such as `#gh:sase` continue to target the real `sase` project even when
initiated by background automation.
