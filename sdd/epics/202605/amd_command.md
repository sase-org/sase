---
create_time: 2026-05-24 17:51:26
status: done
prompt: sdd/prompts/202605/amd_command.md
bead_id: sase-44
tier: epic
---
# Plan: `sase amd` and Project-Managed AGENTS.md

## Goal

Add an `amd` command group for agent markdown documents and make project-local `amd_h1_title` opt a repo into a
generated, prescriptive `AGENTS.md`. The new command should keep provider-specific instruction files as simple
`@AGENTS.md` shims, migrate a single legacy provider file when possible, keep memory references synchronized, and expose
a polished inventory view of home and project `AGENTS.md` files.

`amd_h1_title` is a project-local `sase.yml` field. Add it to defaults/schema as `null`, but the AGENTS generator should
read the raw current-project `./sase.yml` value rather than inheriting a global value from merged config.

## Design Decisions

- Treat AMD as "agent markdown documents": `AGENTS.md` plus provider shims such as `CLAUDE.md`, `GEMINI.md`, `QWEN.md`,
  and `OPENCODE.md`.
- Keep `sase amd init` explicit and always active: it writes/repairs root-level provider shims regardless of
  `amd_h1_title`.
- Keep bare `sase init` conservative for repos that have not opted in. Register an AMD init planner, but in the bare
  coordinator it should plan AGENTS generation only when project-local `amd_h1_title` is set. Explicit `sase amd init` /
  `sase init amd` still performs the shim and migration behavior when the title is unset.
- Run AMD before memory in the init registry. Memory validation needs `AGENTS.md` reachability, and the AMD template is
  the new owner of that surface when `amd_h1_title` is set.
- Add stable HTML comment markers around generated memory blocks so `sase memory init` can update only the short-memory
  bullet list and long-memory description list without brittle string matching:
  - `<!-- sase-amd:short-memory:start -->`
  - `<!-- sase-amd:short-memory:end -->`
  - `<!-- sase-amd:long-memory:start -->`
  - `<!-- sase-amd:long-memory:end -->`
- When a repo is opted in, the generated `AGENTS.md` should intentionally look almost exactly like this repo's current
  file: same Tier 1/Tier 2/Tier 3 structure, same warning about memory files, same dynamic-memory explanation, and same
  long-memory description-list style with two trailing spaces after each `**path**` key line.
- For long-memory `description` frontmatter, use this priority:
  1. Existing `description` frontmatter.
  2. Existing matching Tier 3 description in `AGENTS.md`, so current curated descriptions survive the first migration.
  3. Deterministic fallback from the first body paragraph or H1 when no curated description exists.

## Phase 1: Config Contract and CLI Skeleton

Owner: one agent in the primary `sase` repo.

Add the public command/config surface without implementing heavy behavior yet.

- Add `amd_h1_title: null` to `src/sase/default_config.yml`.
- Add `amd_h1_title` to `config/sase.schema.json` as `string` or `null`.
- Document the field in `docs/configuration.md` as project-local and explain that global values are ignored by the
  generator.
- Add parser registration for top-level `sase amd` with default subcommand `list`, plus `sase amd init`.
- Add `sase init amd` as an alias in `parser_init.py` and dispatch it from `entry.py`.
- Add a thin `src/sase/main/amd_handler.py` and a package namespace such as `src/sase/amd/`.
- Add parser/dispatch smoke tests, including defaulting bare `sase amd` to `list`.

This phase should avoid changing memory generation behavior.

## Phase 2: AMD Init Engine

Owner: one agent in the primary `sase` repo.

Implement idempotent file planning and writing for root-level AMD files.

- Create reusable AMD constants for provider shim filenames and exact shim content; migrate current duplicates from
  `src/sase/main/init_memory/constants.py` to avoid drift.
- Implement a pure planner that reports `InitAction`s for:
  - Missing/stale provider shims.
  - Generated `AGENTS.md` when project-local `amd_h1_title` is set.
  - One-file legacy migration when `AGENTS.md` is missing, `amd_h1_title` is unset, and exactly one non-shim provider
    file exists.
  - A blocker when multiple non-shim provider files exist and no `AGENTS.md` exists.
- Implement `sase amd init` with `-c|--check`; explicit `init` should always create/repair shims.
- Implement `sase init amd` as a compatibility alias to the same handler.
- Migration behavior:
  - Copy the single legacy provider file content to `AGENTS.md`.
  - Replace that provider file with `@AGENTS.md`.
  - Create the remaining provider shims.
  - Do not migrate a provider file that is already only `@AGENTS.md` if the target `AGENTS.md` is missing; report a
    blocker instead.
- Generated-template behavior:
  - Use the configured `amd_h1_title` for the H1.
  - Always include `@memory/short/sase.md`.
  - Include all existing `memory/short/**/*.md` files as Tier 1 `@` references.
  - Include all existing `memory/long/**/*.md` files in the Tier 3 description list, using description metadata.
  - Overwrite the generated sections when opted in; setting `amd_h1_title` means the repo is choosing a managed
    `AGENTS.md`.

Add focused unit tests around shims, migration, blockers, generated template content, and check mode.

## Phase 3: Init Registry and Memory Synchronization

Owner: one agent in the primary `sase` repo.

Integrate AMD with bare `sase init` and `sase memory init`.

- Register AMD before memory in `iter_init_command_specs()`.
- Make the AMD planner conservative for bare `sase init`: if `args.init_subcommand is None` and no project-local
  `amd_h1_title` is set, return no actions. Explicit `sase amd init` and `sase init amd` still do the full explicit
  behavior.
- Update onboarding rendering/tests for the new registry order and checked-command list.
- Teach memory planning to use the would-be generated AMD `AGENTS.md` as an overlay when `amd_h1_title` is set, so
  read-only `sase init -c` does not falsely report unreferenced memory before AMD has run.
- During `sase memory init`, when `amd_h1_title` is set:
  - Ensure every `memory/short/**/*.md` file has an `@` reference inside the AMD short-memory marker block.
  - Ensure every `memory/long/**/*.md` file has `description` frontmatter.
  - Update the AMD long-memory marker block from those descriptions.
  - Run reachability validation after these updates.
- Preserve the current backward-compatible minimal `AGENTS.md` behavior when `amd_h1_title` is unset.

Add tests covering memory init's AGENTS synchronization, long-memory description insertion, existing-description
preservation, first-migration extraction from current AGENTS descriptions, and overlay-based planning.

## Phase 4: `sase amd list`

Owner: one agent in the primary `sase` repo.

Implement a read-only inventory and a polished Rich rendering.

- Inventory project AGENTS files from the current VCS root, including subdirectories, while pruning `.git`, `.hg`,
  `.sase`, `.venv`, `node_modules`, `__pycache__`, and generated artifact/cache directories.
- Inventory home/global AGENTS files from the active home memory root and chezmoi source root when relevant. Include
  both live and chezmoi-source paths when they differ and exist.
- For each `AGENTS.md`, show:
  - Scope (`home`, `chezmoi`, `project`, or `project-subdir`).
  - Display path relative to home or repo.
  - H1 title.
  - Whether it appears AMD-managed, custom, or missing marker blocks.
  - Short/long memory reference counts.
  - Nearby provider shim status where useful.
- Render with a compact Rich table or grouped panels. The default output should be useful in a terminal without flags.
- Add `-j|--json` only if it stays cheap; otherwise keep the command flagless to avoid unnecessary surface area.

Add tests using temporary homes/repos and captured Rich console output. Include the current repo shape: root
`AGENTS.md`, root shims, `tools/AGENTS.md`, and `tools` shims.

## Phase 5: Repo Migration, Docs, and Examples

Owner: one agent in the primary `sase` repo.

Bring this repo onto the new managed model and update docs.

- Add to this repo's `sase.yml`: `amd_h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions"`.
- Add `description` frontmatter to current `memory/long/*.md` files. For this repo, preserve the existing AGENTS Tier 3
  descriptions:
  - `memory/long/generated_skills.md`: "Skill file generation pipeline, CLI/skill contract synchronization, commit
    skills per runtime."
  - `memory/long/tui_jk_baseline.md`: "Baseline j/k key-to-paint latency data and reproduction steps."
- Regenerate `AGENTS.md` through the new AMD/memory path so it matches the current content except for the marker
  comments and any ordering/formatting needed by the generator.
- Update `docs/init.md`, `docs/cli.md`, and relevant memory docs to describe `sase amd init`, `sase init amd`,
  `sase amd list`, and the `sase init` opt-in behavior.
- Update tests that asserted the old init registry order or old memory-owned shim constants.

This phase may touch canonical memory files because the user request explicitly asks for the new long-memory description
field.

## Phase 6: Verification and Acceptance

Owner: final integrating agent.

Run verification after all phases are integrated.

- Run `just install` first if the workspace has not been prepared recently.
- Run targeted tests:
  - AMD parser/handler/list tests.
  - `tests/main/test_init_memory_handler.py`.
  - `tests/main/test_init_memory_plan.py`.
  - `tests/main/test_init_onboarding.py`.
  - `tests/test_config_schema.py`.
- Run `sase amd init --check`, `sase init amd --check`, `sase amd list`, `sase memory init --no-commit`, and
  `sase init -c` from this repo.
- Run `just check` before finishing because this feature changes Python, YAML, docs, and repo memory files.
- Perform the requested TUI verification with tmux:
  1. Launch `sase ace --tmux --no-axe --tab agents`.
  2. Parse the printed `sase_tmux_session` and `sase_tmux_window`.
  3. Use `tmux send-keys` to emulate real user navigation/commands in the TUI.
  4. Use `tmux capture-pane -p` on that pane and include the important captured lines in the final verification notes.
  5. Close the tmux window cleanly.

## Risks

- Planning all init specs before running any of them can produce false memory blockers unless the memory planner uses an
  AMD overlay when the repo is opted in.
- Global config merging could accidentally apply `amd_h1_title` everywhere; use a helper that reads only project-local
  `./sase.yml`.
- Rewriting YAML frontmatter with PyYAML can cause noisy churn. Preserve existing frontmatter ordering/style as much as
  practical and keep description insertion narrowly scoped.
- Scanning all of `$HOME` for AGENTS files can be slow and noisy. Keep `amd list` focused on known home/chezmoi roots
  plus the current project repo.
- Generated marker comments are needed for robustness but make the file differ from this repo's current AGENTS.md; keep
  the visible Markdown content otherwise nearly identical.
