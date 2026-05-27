---
create_time: 2026-05-27 12:40:01
status: done
prompt: sdd/prompts/202605/auto_sdd_init_for_bare_git.md
---
# Plan: Auto-Run SDD Init For Bare-Git Repositories

## Goal

Bare-git projects now use version-controlled SDD under `sdd/` automatically. Extend that behavior so SASE also creates
or refreshes the generated SDD guide files when needed, without requiring the user to run `sase sdd init` manually.

The target generated files are the same files managed by `sase sdd init`: `sdd/README.md`, the tier README files under
`sdd/tales/`, `sdd/epics/`, `sdd/legends/`, `sdd/myths/`, `sdd/research/`, and `sdd/assets/sdd-directory-map.png`.

## Current Behavior

`sase sdd init` is explicit and idempotent, but automatic bare-git project setup does not run it. A new `sase git init`
project gets an initial empty commit and no generated SDD files. Existing bare-git projects resolved through `#git` or
`sase workspace open` can now be treated as version-controlled SDD projects, but their `sdd/` tree may still be missing
the generated docs until a user runs `sase sdd init`.

Plan approval and bead initialization create task data under `sdd/prompts/`, `sdd/tales/`, `sdd/epics/`, `sdd/legends/`,
or `sdd/beads/`, but they do not ensure the generated SDD root documentation exists first.

## Design

Add one shared SDD bootstrap helper and call it only from flows that already perform setup or SDD writes.

1. Add a public, idempotent helper near the SDD file-generation code, for example
   `ensure_sdd_initialized(path: str | Path | None = None, *, cwd: Path | None = None) -> tuple[Path, ...]`.
   - It should compare the expected generated SDD files before writing, using the same canonical content already used by
     `sase sdd init`.
   - If every generated file is current, it returns an empty tuple and performs no writes.
   - If any generated file is missing or stale, it calls the existing writer equivalent to `sase sdd init -p <path>` and
     returns the generated file paths it refreshed.
   - `sase sdd init` and `plan_sdd_init` should keep their current CLI behavior, but they should share this comparison
     logic so the automatic path and command path cannot drift.

2. Add a bare-git wrapper that can optionally commit generated SDD init files.
   - Scope it to bare-git workspaces, using the effective SDD mode/provider identity from the previous change.
   - For clean/no-op cases it should do nothing.
   - When committing, stage and commit only the generated SDD init paths, so unrelated user changes are not swept into
     the auto-init commit.
   - Use an auto-init commit message tagged through the existing runtime tag helper, e.g. `Initialize SDD` with
     `TYPE=init`.
   - Push only in flows that already own bare-git repository setup/materialization. If push or commit fails in an
     existing dirty/conflicted repo, surface a warning or setup error rather than silently claiming success.

3. Run the helper during bare-git project creation.
   - For a newly created bare repo, run SDD init in the clone before the initial commit, add the generated SDD files,
     and let the existing initial commit/push publish them.
   - For `sase git init --existing`, run SDD init after cloning the existing bare repo. If files changed, commit and
     push just those generated files so the registered repo is ready immediately.
   - Keep project-spec creation unchanged except for any paths/messages needed to report SDD init failures clearly.

4. Run the helper when an already registered bare-git project is materialized or opened.
   - In the bare-git workspace provider, ensure the primary workspace has generated SDD files before returning a primary
     or numbered workspace directory.
   - For numbered workspaces, initialize the primary first so fresh clones inherit the files. Existing numbered clones
     can rely on the normal checkout/fetch/clean path to catch up after the auto-init commit is pushed.
   - `sase workspace path/list` should remain read-only; `sase workspace open` may run the helper because it already
     materializes and cleans a checkout.

5. Run the helper immediately before SASE writes version-controlled SDD content.
   - In plan approval archiving, call the helper after resolving `sdd_dir` and before writing prompt/plan files when
     effective SDD mode is version-controlled for a bare-git workspace.
   - In mobile/TUI approval archiving, do the same before copying the approved plan into `sdd/<kind>/<YYYYMM>/`.
   - In version-controlled bead initialization, run it before `BeadProject.init(...)` so `sase bead init` and
     epic/legend approval both leave a complete SDD tree.

6. Avoid read-only side effects.
   - Do not run automatic SDD init from bead list/read fast paths, workspace list/path, SDD validation/listing, or
     provider detection.
   - Do not broaden this to GitHub or other providers as part of this change. The request is tied to built-in bare-git
     repositories, and other providers may have different expectations around automatic commits.

## Tests

Add focused tests for the helper and each integration point:

- SDD helper reports no changes and performs no writes when generated files are current.
- SDD helper writes the same files as `sase sdd init` when files are missing or stale.
- New `init_bare_git_project(...)` includes generated SDD files in the initial commit path.
- `init_bare_git_project(..., existing_bare=...)` runs SDD init and commits/pushes only generated SDD paths when needed.
- Existing bare-git workspace materialization invokes the helper, while workspace path/list stays read-only.
- Plan approval and mobile/TUI approval archiving initialize generated SDD files before writing version-controlled SDD
  plans.
- Version-controlled bead initialization calls SDD init before creating `sdd/beads/`.

Run focused pytest for SDD init, bare-git workspace, plan approval archiving, and bead initialization first. Then run
`just install` if needed and `just check` after implementation, following the repo instructions.

## Documentation

Update the SDD, configuration, workspace, and git-init docs to state that built-in bare-git repositories use
version-controlled SDD and SASE automatically creates or refreshes generated SDD guide files during repository setup or
the first SDD write. Keep the explicit `sase sdd init` docs for manual refresh/check workflows.
