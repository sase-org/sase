---
create_time: 2026-06-26
status: done
---

# Research: Should `sase amd init` Move Into `sase memory init`?

## Question

Should the functionality currently exposed by `sase amd init` be merged into `sase memory init`?

Short answer: no full merge. The commands overlap on `AGENTS.md` and provider shims, and `memory init` already reuses
AMD internals, but they still have different scopes, migration rules, and deployment semantics.

## Sources Reviewed

Prior agent work:

- `sdd/research/202606/amd_init_into_memory_init_research.md`
- `sdd/research/202606/merge_amd_init_into_memory_init.md`

Verified against current implementation, docs, help text, and tests:

- CLI: `src/sase/main/parser_amd.py`, `parser_memory.py`, `parser_init.py`, `init_registry.py`,
  `init_onboarding.py`
- AMD: `src/sase/amd/_planner.py`, `_config.py`, `_memory.py`, `_runner.py`, `_shared.py`, `constants.py`
- Memory init: `src/sase/main/init_memory_handler.py`, `src/sase/main/init_memory/roots.py`,
  `config.py`, `inventory.py`, `constants.py`
- Docs: `docs/init.md`, `docs/cli.md`, `docs/configuration.md`
- Tests: `tests/main/test_amd_init.py`, `test_amd_init_commit.py`, `test_init_memory_handler.py`,
  `test_init_memory_plan.py`, `test_init_memory_commit.py`, `test_init_memory_chezmoi.py`
- Help smoke checks: `./.venv/bin/sase amd init --help`, `sase memory init --help`,
  `sase init amd --help`, `sase init memory --help`

## User-Facing Contract

`sase amd init`:

- Primary command: `sase amd init`
- Alias: `sase init amd`
- Help: "Create or refresh AGENTS.md and provider instruction shims."
- `--check`: read-only AMD drift report
- `--no-commit`: skip the local AMD git commit

`sase memory init`:

- Primary command: `sase memory init`
- Alias: `sase init memory`
- Help: "Create or refresh SASE memory files and provider instruction shims."
- `--check`: read-only memory drift report
- `--no-commit`: skip the project git commit/pull/push path

The flag names look parallel, but `--no-commit` does not mean the same thing. AMD uses it to skip local commits for
AMD-managed files. Memory uses it to skip only the project deploy path; when `use_chezmoi` is enabled, standalone
memory init can still deploy home changes through the chezmoi path.

## What `sase amd init` Does

AMD means "Agent Markdown Documents." It is the narrower agent-instruction initializer:

- Manages `AGENTS.md`.
- Manages provider shims: `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`.
- Uses `*.md.tmpl` shim sources under the chezmoi home source root.
- Writes managed `AGENTS.md` when an AMD H1 title is available.
- Repairs provider shims even when no memory files are being generated.

Root selection is AMD-specific:

- Without `use_chezmoi`, it plans against the current directory.
- With `use_chezmoi` from the live home root, it redirects to the chezmoi home source root.
- With `use_chezmoi` from a project, it plans both the project root and the chezmoi home source root, deduplicated by
  resolved path.

Title resolution is also AMD-specific:

- Ordinary project roots use only project-local `./sase.yml`.
- Global/user `amd_h1_title` is ignored for ordinary project roots.
- Home-like roots can read user config from `~/.config/sase/` or the chezmoi source `dot_config/sase/`.
- Bare `sase init` can enable an onboarding fallback title for project memory that the minimal `AGENTS.md` template
  would leave unreferenced.

The important AMD-only safety behavior is legacy provider migration:

- If `AGENTS.md` is missing and exactly one custom provider file exists, AMD copies that content into `AGENTS.md` and
  replaces provider files with shims.
- If multiple custom provider files exist, AMD blocks rather than guessing.
- If only shims point at a missing `AGENTS.md`, AMD blocks rather than preserving a broken graph.

Deployment behavior:

- Writes planned AMD files.
- Runs precommit before staging when committing.
- Stages only AMD-changed paths.
- Commits locally per owning git repo with `chore: run sase init amd` and `TYPE=amd`.
- Does not pull, push, or apply chezmoi.
- Fails after writing if changed paths are not in a git repo, unless `--no-commit` is used.

## What `sase memory init` Does

Memory init owns generated memory setup and validation:

- Creates or refreshes project `memory/sase.md` and `memory/README.md`.
- Creates or refreshes home `memory/sase.md` and `memory/README.md`, using the chezmoi home source root when
  `use_chezmoi` is enabled.
- Creates a minimal `AGENTS.md` when absent and no managed AMD content is available.
- Repairs provider shims for both project and home roots.
- Validates that Markdown files under `memory/` are reachable from `AGENTS.md` through direct or transitive references.
- Requires every configured `linked_repos` or legacy `sibling_repos` entry to have a non-empty `description`.

Memory init already depends on AMD internals:

- `src/sase/main/init_memory/roots.py` imports `plan_amd_memory_sync()` and `AmdMemorySyncPlan` from `sase.amd.init`.
- It imports `provider_shim_plan()` from `sase.amd._shared`.
- It imports provider shim constants from `sase.amd.constants`.

That reuse is project-root and memory-centered. For the project root, memory init calls `plan_amd_memory_sync()` with
AMD enabled. If that sync finds a title, memory init overwrites `AGENTS.md` with AMD-managed memory sections and inserts
missing long-memory `description` frontmatter before validation. For the home root, AMD sync is disabled; home gets
minimal memory wiring and shims, not a managed home `AGENTS.md` from user/global `amd_h1_title`.

Memory deployment behavior:

- Project side: runs precommit, stages generated project files, commits with `chore: run sase init memory` and
  `TYPE=memory`, then `git pull --rebase` and `git push`.
- Home/chezmoi side: standalone `sase memory init` can commit chezmoi source changes with
  `chore: initialize sase memory` and run `chezmoi apply --force`; this path is not skipped by memory's
  project-focused `--no-commit`.
- Bare `sase init` defers home/chezmoi paths across initializers and performs one consolidated deploy at the end.

## Overlap

Both commands can touch:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md`
- `OPENCODE.md`
- Chezmoi `*.md.tmpl` shim sources

This overlap is real, but not wholly duplicated. Memory already reuses AMD code for provider shim planning and
project-root managed memory block synchronization. Bare `sase init` is already the combined workflow: it plans and runs
AMD, memory, SDD, then skills in registry order.

## Differences That Matter

| Area | `sase amd init` | `sase memory init` |
| --- | --- | --- |
| Product scope | Agent instruction files | Generated memory roots and memory reachability |
| Primary artifacts | `AGENTS.md` and provider shims | `memory/sase.md`, `memory/README.md`, `AGENTS.md`, shims |
| Root scope | Current root plus chezmoi home source when configured | Project root plus home memory root |
| Managed home `AGENTS.md` | Yes, from user/source config | No, home AMD sync is disabled |
| Legacy provider migration | Yes | No |
| Shims without memory generation | Yes | No; memory init always generates/validates memory |
| Long-memory description frontmatter | Reads/preserves for rendering | Inserts missing descriptions during AMD sync |
| Memory reachability validation | No | Yes |
| Linked repo description validation | No | Yes |
| Project git behavior | Local commit only, no pull/push | Commit, pull --rebase, push |
| Chezmoi behavior | Writes source files only; no apply | Can commit/apply home memory changes |

## Safety Findings

The highest-risk mismatch is legacy provider content. AMD has explicit one-file migration and multi-file blocker logic.
Memory init does not call that migration path. It calls `provider_shim_plan()` directly, so a custom provider file can be
planned as an overwrite while memory init creates or preserves `AGENTS.md`. Existing tests intentionally cover stale
provider shim overwrites; AMD tests separately cover custom legacy migration and blockers.

The second mismatch is git cleanliness. A regression test documents that bare `sase init` must let AMD commit its
`AGENTS.md` changes before memory starts. Otherwise memory's later `git pull --rebase` path can inherit unstaged AMD
edits. Any consolidation must preserve this boundary or redesign memory deployment around it.

The third mismatch is home behavior. AMD is the command that can generate a managed home/chezmoi `AGENTS.md` from
home-level config. Memory init writes home memory files and shims, but intentionally does not enable AMD-managed home
instructions.

## Merge Options

Option A: fully merge AMD into memory and remove `sase amd init`.

- Benefit: one fewer visible command that writes `AGENTS.md`.
- Cost: memory init must absorb home/chezmoi managed `AGENTS.md`, legacy provider migration, shim-only repair, and AMD's
  local-commit-only behavior.
- Assessment: not worth it. The command would become a broad agent-doc/memory/deploy catch-all, and compatibility would
  still require `sase init amd` behavior for existing users and docs.

Option B: keep the command split.

- Benefit: preserves the current layering and narrow operational contracts.
- Cost: users can still be confused because both commands mention `AGENTS.md` and provider shims.
- Assessment: acceptable baseline. Bare `sase init` already provides the combined entry point.

Option C: keep commands separate, but share more AMD safety in memory init.

- Benefit: addresses the real risk without broadening the public memory command.
- Implementation direction: factor AMD's project-root migration/blocker logic into a reusable planning helper that
  memory init can apply before overwriting custom provider files, while leaving AMD root expansion and AMD commits in
  the AMD command.
- Assessment: best follow-up if reducing overlap or footguns is the goal.

## Recommendation

Do not move forward with a full merge of `sase amd init` into `sase memory init`.

Keep `sase amd init` as the explicit agent-markdown initializer, keep `sase memory init` as the memory initializer, and
point users who want one command at bare `sase init`. If you want to improve the design, do a narrower engine-level
cleanup: make memory init reuse AMD's legacy provider migration/blocker safety before it overwrites provider files, and
clarify docs/help so the command split is easier to understand. This preserves AMD-only capabilities, avoids merging
conflicting commit/deploy semantics, and reduces the most meaningful duplication without turning memory init into a
misnamed catch-all.
