---
create_time: 2026-06-26
status: done
---

# Research: Merge `sase amd init` Into `sase memory init`?

## Question

Should the functionality currently exposed by `sase amd init` be moved into `sase memory init`?

Short version: the commands overlap on `AGENTS.md` and provider shims, but they do not have the same product contract,
scope, or deployment semantics.

## Sources Reviewed

- CLI wiring:
  - `src/sase/main/parser_amd.py`
  - `src/sase/main/parser_memory.py`
  - `src/sase/main/parser_init.py`
  - `src/sase/main/amd_handler.py`
  - `src/sase/main/memory_handler.py`
  - `src/sase/main/init_registry.py`
  - `src/sase/main/init_onboarding.py`
- AMD implementation:
  - `src/sase/amd/_planner.py`
  - `src/sase/amd/_runner.py`
  - `src/sase/amd/_config.py`
  - `src/sase/amd/_memory.py`
  - `src/sase/amd/_shared.py`
  - `src/sase/amd/constants.py`
- Memory init implementation:
  - `src/sase/main/init_memory_handler.py`
  - `src/sase/main/init_memory/roots.py`
  - `src/sase/main/init_memory/config.py`
  - `src/sase/main/init_memory/inventory.py`
- Tests:
  - `tests/main/test_amd_init.py`
  - `tests/main/test_amd_init_commit.py`
  - `tests/main/test_init_memory_handler.py`
  - `tests/main/test_init_memory_plan.py`
  - `tests/main/test_init_memory_commit.py`
  - `tests/main/test_init_memory_chezmoi.py`
  - `tests/main/test_amd_parser_handler.py`
  - `tests/main/test_memory_parser_handler.py`
  - `tests/main/test_init_onboarding_flow.py`
- Docs and plans:
  - `docs/init.md`
  - `docs/memory.md`
  - `docs/cli.md`
  - `docs/configuration.md`
  - `sdd/epics/202605/amd_command.md`
  - `sdd/epics/202605/memory_command_1.md`
  - `sdd/epics/202605/init_memory.md`
  - `sdd/epics/202605/sase_init_onboarding.md`
- CLI help smoke checks:
  - `./.venv/bin/sase amd init --help`
  - `./.venv/bin/sase memory init --help`
  - `./.venv/bin/sase init amd --help`
  - `./.venv/bin/sase init memory --help`

## User-Facing Contract

`sase amd init`:

- Primary command: `sase amd init`.
- Compatibility alias: `sase init amd`.
- Help text: "Create or refresh AGENTS.md and provider instruction shims."
- Flags:
  - `-c, --check`: report AMD drift without writing.
  - `-C, --no-commit`: skip the local git commit of AMD-managed changes.

`sase memory init`:

- Primary command: `sase memory init`.
- Compatibility alias: `sase init memory`.
- Help text: "Create or refresh SASE memory files and provider instruction shims."
- Flags:
  - `-c, --check`: report memory drift without writing.
  - `-C, --no-commit`: skip the project git commit/push sequence.

The flag names overlap, but the deployment meaning differs. AMD's `--no-commit` controls local AMD commits. Memory's
`--no-commit` skips only the project commit/pull/push path; home/chezmoi deployment can still run.

## What `sase amd init` Does

AMD means "agent markdown documents." The command manages `AGENTS.md` plus provider instruction shims:

- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md`
- `OPENCODE.md`

The core planner is `build_amd_init_plan()` in `src/sase/amd/_planner.py`.

### Root Selection

Without chezmoi, AMD initializes only the current working directory.

With `use_chezmoi: true`:

- From the live home directory, AMD redirects to the chezmoi home source root.
- From another directory, AMD initializes both the current project root and the chezmoi home source root.
- Roots are deduplicated by resolved path.

This multi-root behavior is specific to AMD and is covered by tests such as
`test_amd_init_use_chezmoi_from_project_updates_project_and_source` and
`test_amd_init_multi_root_commits_each_repo`.

### Title Resolution and Managed `AGENTS.md`

AMD writes a managed `AGENTS.md` when it resolves an AMD H1 title.

For ordinary project roots, it reads only project-local `./sase.yml` and intentionally ignores user/global
`amd_h1_title`. For home-like roots, it can read user config from the live config directory or the chezmoi source
config directory.

There is also an onboarding fallback: when onboarding is enabled and a project has memory beyond the generated
`memory/sase.md` note, AMD can derive a title like `<project> - Agent Instructions`. Tests pin this behavior in
`test_bare_init_amd_plan_uses_fallback_title_when_memory_exists` and
`test_bare_init_amd_apply_writes_managed_agents_without_title`.

The managed `AGENTS.md` rendering:

- Includes a "do not modify memory files without approval" warning.
- Lists short-term memory as `@memory/...` references.
- Lists top-level long-term memory notes with descriptions.
- Preserves existing long-memory descriptions from frontmatter or from matching existing `AGENTS.md` text.
- Does not render the old dynamic-memory section.

Direct AMD init renders descriptions into `AGENTS.md`, but it does not update missing long-memory `description`
frontmatter. That frontmatter update is done by memory init's AMD sync path.

### Provider Shim Behavior

AMD uses shared provider shim constants and planning helpers from `src/sase/amd/_shared.py`.

Expected shim content depends on root type:

- Project root: `@AGENTS.md`
- Direct live home root: absolute `@/path/to/home/AGENTS.md`
- Chezmoi home source root: `*.md.tmpl` files with `@{{ .chezmoi.homeDir }}/AGENTS.md`

AMD also migrates legacy provider instruction files when `AGENTS.md` is missing:

- If exactly one custom provider file exists, copy its content to `AGENTS.md` and replace provider files with shims.
- If multiple custom provider files exist, block rather than guess which content wins.
- If provider shim files already point at missing `AGENTS.md`, block rather than silently preserve a broken graph.

This migration behavior is the biggest functional difference from memory init.

### Writes and Deployment

In apply mode, AMD:

- Writes planned `AGENTS.md` and shim files.
- Deletes safe legacy shim files when needed.
- Prints changed paths.
- By default, commits AMD-managed changes locally.
- Runs precommit before staging.
- Stages only AMD-changed paths.
- Groups changed paths by owning git repo.
- Commits once per owning git repo with `chore: run sase init amd` and `TYPE=amd`.
- Does not pull or push.
- Fails if changed paths are not inside a git repo, unless `--no-commit` is used.

The commit split is intentional. `test_bare_init_amd_commits_before_memory_runs` documents the regression this avoids:
bare `sase init` needs AMD to commit its own `AGENTS.md` changes before memory init starts, otherwise memory's
git pull/rebase path can inherit unstaged AMD dirt.

## What `sase memory init` Does

Memory init is implemented primarily in `src/sase/main/init_memory_handler.py` and
`src/sase/main/init_memory/roots.py`.

It initializes two memory roots:

- Project root: current working directory.
- Home root: `Path.home()`, or the chezmoi home source root when `use_chezmoi: true`.

For each root it creates or refreshes:

- `memory/sase.md`
- `memory/README.md`
- `AGENTS.md` when missing, or managed `AGENTS.md` when AMD sync is enabled and a title is resolved.
- Provider instruction shims.

### Config Inputs

Project memory uses project-local linked repo config from `./sase.yml`.

Home memory uses user/global config:

- `~/.config/sase/sase.yml` without chezmoi.
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml` with chezmoi.

The generated `memory/sase.md` includes:

- Project workspace naming guidance for project memory only.
- Linked repository descriptions.
- Static-path linked repo locations when `workspace.strategy: none`.
- `sase workspace open` guidance only when numbered-workspace linked repos are configured.

Config validation blocks generation if required linked repo descriptions are missing.

### AMD Integration Inside Memory Init

Memory init already integrates with AMD, but only in a memory-centered way.

For the project root, `_plan_memory_root(..., enable_amd=True)` calls `plan_amd_memory_sync(root, onboarding=True)`.
If that returns managed `AGENTS.md` content, memory init:

- Overwrites `AGENTS.md` with AMD-managed memory blocks.
- Inserts missing long-memory `description` frontmatter.
- Uses the would-be managed `AGENTS.md` as an overlay for reachability validation.

For the home root, `enable_amd` is false. Memory init can create a minimal home `AGENTS.md` and provider shims, but it
does not render home AMD-managed instructions from home/user `amd_h1_title`.

### Validation

Memory init validates reachability after planned/generated content is considered:

- Memory files under `memory/` must be reachable from `AGENTS.md`.
- Reachability follows direct and transitive references.
- Unreferenced memory files make the command fail.

Planning uses overlays so a stale or not-yet-written generated file does not create false unreferenced-memory blockers.

### Writes and Deployment

In apply mode, memory init:

- Writes project memory files.
- Writes home memory files.
- Writes or deletes provider shims.
- Checks for unreferenced memory files after writes.
- Prints project/home memory targets and the global config source.
- By default, commits project-side changes, pulls with rebase, and pushes.
- Uses commit message `chore: run sase init memory` with `TYPE=memory`.
- With `use_chezmoi: true`, deploys home changes through chezmoi and runs `chezmoi apply --force`.
- `--no-commit` skips the project deploy path only; it does not inherently skip home/chezmoi deployment.

## Overlap

Both commands can create or update:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md`
- `OPENCODE.md`
- Chezmoi `*.md.tmpl` shim sources

Both commands share provider shim constants and planner helpers from `src/sase/amd/_shared.py`. Both have `--check` and
`--no-commit`. Both are part of bare `sase init`, where the registry order is AMD, memory, SDD, skills.

Memory init already has a project-root AMD sync path, so part of the desired consolidation already exists.

## Differences That Matter

| Area | `sase amd init` | `sase memory init` |
| --- | --- | --- |
| Product owner | Agent markdown documents | Generated SASE memory roots |
| Primary files | `AGENTS.md`, provider shims | `memory/sase.md`, `memory/README.md`, `AGENTS.md`, provider shims |
| Root scope | Current root plus chezmoi home source when configured | Project root plus home memory root |
| Home AMD title support | Yes, from user/source config | No, home root uses minimal memory wiring |
| Legacy provider migration | Yes, preserves one custom provider file by moving it to `AGENTS.md` | No, shim planning can overwrite provider files as shims |
| Long memory description frontmatter | Reads/preserves descriptions for rendering | Inserts missing descriptions before rendering/validation |
| Commit behavior | Local commit per owning git repo, no pull/push | Project commit, pull --rebase, push; separate chezmoi deployment |
| `--no-commit` meaning | Skip AMD local commits | Skip project commit/pull/push only |
| Standalone usefulness | Repair/migrate agent docs without memory | Initialize memory and validate memory reachability |

## Safety Findings

The most important safety asymmetry is legacy provider content.

If a repo has custom `CLAUDE.md` and no `AGENTS.md`, explicit AMD init is careful: it can migrate that custom content
to `AGENTS.md` when there is exactly one custom provider source, and it blocks when there are multiple candidates.

Memory init does not run that migration logic. Its shim planner can overwrite provider instruction files as shims while
creating a minimal or managed `AGENTS.md`. Existing tests intentionally cover overwriting stale provider shims, but they
do not cover the "single custom provider file and no `AGENTS.md`" preservation path from AMD.

If the goal is to reduce user footguns, this argues for importing AMD's legacy migration safety into memory init. It
does not argue for deleting the AMD command.

The second important safety issue is git cleanliness. AMD currently commits before memory runs in bare `sase init`.
Merging the apply paths would need to preserve that boundary or redesign memory's deploy path so it cannot inherit
uncommitted AMD changes.

## Possible Merge Shapes

### Option 1: Full Merge and Remove `sase amd init`

This would make `sase memory init` responsible for all AMD initialization.

Pros:

- One fewer explicit init command.
- Less visible overlap around shims and `AGENTS.md`.

Cons:

- `sase memory init` would become responsible for non-memory agent document migration.
- The command name would be misleading for home/project provider shim repair that has nothing to do with memory files.
- The existing AMD git commit contract would either disappear or make memory init's deploy behavior more complicated.
- Home AMD-managed `AGENTS.md` generation would need to be added to memory init, changing the scope of a memory command.
- `sase amd list` would remain, but its paired `init` action would disappear or be hidden elsewhere.
- Compatibility with `sase init amd` would still be needed for existing users and docs.

I would not choose this.

### Option 2: Make `sase memory init` Call the Full AMD Initializer First

This keeps `sase amd init`, but memory init would effectively run AMD init internally.

Pros:

- Preserves AMD migration logic.
- Keeps a single user action for memory setup.

Cons:

- It risks nested or surprising commits. Running AMD's default commit path from memory init would mean one command can
  create an AMD commit and then a memory commit/pull/push.
- Passing memory's `--no-commit` through to AMD is semantically ambiguous.
- Multi-root AMD behavior from a project would also initialize the chezmoi home source before memory's home root logic,
  producing two different deployment systems in one command.
- It could make `sase memory init --check` report AMD drift beyond memory's concern.

I would not choose this as a blanket behavior.

### Option 3: Keep Commands Separate, Share/Reuse More AMD Safety Inside Memory Init

This keeps the public command split:

- `sase amd init`: explicit agent markdown document repair, migration, and AMD commits.
- `sase memory init`: generated memory setup, reachability validation, and memory deployment.
- `sase init`: one-stop orchestrator that runs AMD before memory.

But memory init can reuse targeted AMD logic where memory correctness requires it:

- Use AMD migration/blocker logic before overwriting custom provider instruction files when `AGENTS.md` is missing.
- Keep using `plan_amd_memory_sync()` for project managed-memory blocks and long-memory descriptions.
- Possibly make docs clearer that `sase init --yes` is the full initialization command, while `memory init` is not the
  complete AMD migration surface.

This is the best fit for the existing architecture.

## Recommendation

Do not move forward with a full merge of `sase amd init` into `sase memory init`.

The commands overlap, but the overlap is not accidental duplication. AMD owns agent markdown documents, legacy provider
document migration, home/chezmoi AMD roots, and local AMD commits. Memory init owns generated memory files, reachability
validation, linked-repo memory rendering, project commit/pull/push, and home memory deployment. Combining those into one
command would blur two different deployment contracts and would make `--no-commit` and bare `sase init` behavior harder
to reason about.

Move forward with a narrower cleanup instead: keep `sase amd init` as an explicit command and compatibility target, keep
`sase memory init` as the memory initializer, and improve memory init by reusing AMD's legacy provider migration/blocker
logic where it currently risks overwriting custom provider instruction content. Treat bare `sase init` as the single
high-level onboarding path that intentionally runs AMD before memory.
