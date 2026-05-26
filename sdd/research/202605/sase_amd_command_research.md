---
create_time: 2026-05-26
updated_time: 2026-05-26
status: research
---

# `sase amd` Command Research

## Question

How does the new `sase amd` command work, what files does it manage, and how does it interact with `sase init` and
`sase memory init`?

## Short Answer

AMD means "agent markdown documents" in this codebase. The command group owns discovery and initialization of
`AGENTS.md` plus provider instruction shims such as `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`.

The public surface is small:

```bash
sase amd              # defaults to `sase amd list`
sase amd list         # read-only inventory
sase amd init         # create/repair AGENTS.md and provider shims
sase amd init --check # report AMD drift without writing
sase init amd         # compatibility alias for `sase amd init`
```

The command is intentionally split into two paths:

- `sase amd list` is read-only and renders a Rich dashboard of project, subdirectory, home, and chezmoi-source
  `AGENTS.md` files.
- `sase amd init` is the writer. It always repairs root provider shims, can migrate exactly one legacy provider file to
  `AGENTS.md`, and can generate a managed `AGENTS.md` when the current project's own `./sase.yml` sets
  `amd_h1_title`.

## CLI Wiring

Parser registration lives in `src/sase/main/parser_amd.py`. The top-level command uses an optional `amd_subcommand`; if
it is absent, `src/sase/main/amd_handler.py` treats it as `list`.

`sase init amd` is not a separate implementation. `src/sase/main/parser_init.py` registers it as a compatibility alias
using the same `-c|--check` argument helper, and `src/sase/main/entry.py` dispatches it to
`handle_init_amd_command()`, which calls the same AMD initializer as `sase amd init`.

Observed help output from this workspace:

```text
usage: sase amd [-h] {init,list} ...

Inspect agent markdown documents. With no subcommand, defaults to `sase amd
list`.
```

```text
usage: sase amd init [-h] [-c]

Create or refresh AGENTS.md and provider instruction shims. `sase init amd` is
a compatibility alias for this command.
```

Tests covering this wiring are in `tests/main/test_amd_parser_handler.py`.

## Managed Files And Markers

Shared AMD constants live in `src/sase/amd/constants.py`:

```python
AGENTS_FILENAME = "AGENTS.md"
PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
```

Managed `AGENTS.md` memory sections are delimited by stable HTML comments:

```text
<!-- sase-amd:short-memory:start -->
<!-- sase-amd:short-memory:end -->
<!-- sase-amd:long-memory:start -->
<!-- sase-amd:long-memory:end -->
```

Those marker blocks are what let `sase memory init` update the short-memory bullet list and long-memory description list
without trying to rewrite arbitrary surrounding prose.

## `amd_h1_title`

`amd_h1_title` is the opt-in switch for generated project-managed `AGENTS.md`.

Example from this repo's `sase.yml`:

```yaml
amd_h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions"
```

The key point is scope: `_load_project_amd_h1_title()` in `src/sase/amd/init.py` reads only `./sase.yml` in the current
project root. It deliberately ignores merged/global config so a global `~/.config/sase/sase.yml` cannot accidentally opt
every repository into generated agent instructions.

If the field is missing or null, AMD init still manages provider shims, but it does not generate a new managed
`AGENTS.md` unless it can perform the single-provider migration described below.

## `sase amd init`

The initializer is implemented in `src/sase/amd/init.py`. It builds a pure plan first, then either reports drift
(`--check`) or writes the planned files.

The core planner is `_build_amd_init_plan(root=None, explicit=True)`.

Behavior when `amd_h1_title` is set:

- Render a full managed `AGENTS.md` using the configured title.
- Include all `memory/short/**/*.md` files as Tier 1 `@memory/short/...` references.
- Always include `@memory/short/sase.md`, even if it has to be added to the reference set explicitly.
- Include all `memory/long/**/*.md` files in the Tier 3 description list.
- Preserve long-memory descriptions from frontmatter when available.
- If a long-memory file lacks description frontmatter, prefer a matching existing Tier 3 description from the current
  `AGENTS.md`, then fall back to the first body paragraph or H1.
- Create or overwrite all provider shims with exact `@AGENTS.md\n` content.

Behavior when `amd_h1_title` is not set and the command is explicit:

- If `AGENTS.md` exists, create or repair provider shims.
- If `AGENTS.md` is missing and exactly one provider file has custom content, copy that provider file into `AGENTS.md`
  and replace all provider files with shims.
- If `AGENTS.md` is missing and multiple provider files have custom content, block instead of guessing which file wins.
- If `AGENTS.md` is missing and only provider shims exist, block because the shims point at a nonexistent target.
- If no `AGENTS.md` and no provider files exist, create the provider shims only.

Behavior under bare `sase init`:

- The init registry calls the same AMD planner, but with `explicit=False` when the user invoked bare `sase init`.
- In that conservative mode, AMD does nothing unless project-local `amd_h1_title` is set.
- This avoids surprising existing repositories with new shims or migrations during a broad onboarding check.

Check mode uses the shared onboarding check renderer by wrapping AMD in a one-item `InitCommandSpec`. In this repo,
`./.venv/bin/sase amd init --check` printed:

```text
SASE is initialized. No init subcommands need to run.
Checked: amd.
```

Focused behavior tests are in `tests/main/test_amd_init.py`.

## `sase amd list`

The inventory command is implemented in `src/sase/amd/inventory.py`. It is read-only.

Project root detection:

- First walks up from CWD looking for `.git` or `.hg`.
- Falls back to `git rev-parse --show-toplevel` or `hg root`.
- Falls back to the resolved CWD.

Project scanning:

- Walks the project root looking for `AGENTS.md`.
- Includes the root file as `project`.
- Includes nested files as `project-subdir`.
- Prunes generated/cache/vendor directories including `.git`, `.hg`, `.sase`, `.venv`, `node_modules`, `__pycache__`,
  `target`, `build`, `dist`, `site`, and similar cache directories.

Home and chezmoi scanning:

- Includes live `~/AGENTS.md` when it exists.
- Includes chezmoi-source `AGENTS.md` when `use_chezmoi` is enabled or the source root exists.
- Deduplicates resolved paths so the same file is not shown twice.

For each discovered `AGENTS.md`, the entry records:

- Scope: `project`, `project-subdir`, `home`, or `chezmoi`.
- Display path relative to the project root or home root.
- First Markdown H1 title, if present.
- Management state:
  - `managed` when all four AMD marker comments are present.
  - `missing marker blocks` when only some markers are present.
  - `custom` when no markers are present or the file cannot be read.
- Unique short/long `memory/.../*.md` reference counts.
- Nearby provider shim status for `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`.

Observed `sase amd list` in this workspace showed 4 documents: root project `AGENTS.md` as managed with short 5 / long 2
memory refs, two custom project-subdir `AGENTS.md` files, and one custom chezmoi-source `AGENTS.md`.

Focused inventory/rendering tests are in `tests/main/test_amd_list.py`.

## Integration With `sase init`

The init registry lives in `src/sase/main/init_registry.py` and runs in this order:

1. AMD
2. Memory
3. SDD
4. Skills

The order matters because memory validation needs to know what `AGENTS.md` will exist after AMD runs. `sase init -c`
uses read-only planning, but AMD still plans first so memory can reason about the same eventual agent-instruction
surface.

Docs in `docs/init.md` describe the same conservative policy: bare `sase init` only lets AMD generate managed
`AGENTS.md` when the project-local config opts in with `amd_h1_title`; explicit AMD commands still repair provider
shims and perform legacy single-file migrations when the title is unset.

## Integration With `sase memory init`

`sase memory init` still creates project/home memory roots, but it delegates AMD-managed AGENTS synchronization to
`plan_amd_memory_sync()` when AMD support is enabled.

The integration point is `src/sase/main/init_memory/roots.py`:

- `_amd_sync_plan(root, enable_amd=True)` calls `plan_amd_memory_sync(root)`.
- `_render_expected_memory_files()` appends planned long-memory description frontmatter updates.
- It also appends an overwrite for root `AGENTS.md` with the AMD-rendered managed content.
- If AMD is not active, memory init falls back to creating a minimal `AGENTS.md` only when missing.
- Provider shim constants now come from `sase.amd.constants`, avoiding drift between memory and AMD code paths.

This means the practical split is:

- `sase amd init` owns agent markdown document setup and shim repair.
- `sase memory init` owns generated memory files and, when the project opted into AMD, keeps the AMD memory blocks and
  long-memory `description` frontmatter synchronized.

## Design Intent From The Original Plan

The originating plan is `sdd/epics/202605/amd_command.md`. It frames AMD as a migration from scattered provider-specific
instruction files toward a shared `AGENTS.md` model with provider shims.

Important design decisions from that plan that are reflected in the implementation:

- Treat `AGENTS.md` as the canonical instruction file and provider files as `@AGENTS.md` shims.
- Keep explicit AMD init active even for repos without `amd_h1_title`.
- Keep bare `sase init` conservative for repos that have not opted in.
- Register AMD before memory.
- Use marker comments so memory init can update generated memory blocks robustly.
- Preserve curated long-memory descriptions during first migration.
- Keep `sase amd list` focused on known roots rather than scanning all of `$HOME`.

## Source Map

- CLI parser: `src/sase/main/parser_amd.py`
- Top-level dispatch: `src/sase/main/amd_handler.py`
- Compatibility alias dispatch: `src/sase/main/entry.py`
- AMD init planner/writer: `src/sase/amd/init.py`
- AMD inventory renderer: `src/sase/amd/inventory.py`
- Shared constants: `src/sase/amd/constants.py`
- Init registry order: `src/sase/main/init_registry.py`
- Memory init integration: `src/sase/main/init_memory/roots.py`
- Config docs: `docs/configuration.md`
- Init docs: `docs/init.md`
- CLI command index: `docs/cli.md`
- Parser tests: `tests/main/test_amd_parser_handler.py`
- Init tests: `tests/main/test_amd_init.py`
- Inventory tests: `tests/main/test_amd_list.py`

## Open Questions

- `sase amd list` is currently human-rendered only. The original plan allowed `--json` if cheap, but the implemented
  parser is flagless.
- Subdirectory provider shims are only inventoried next to each discovered `AGENTS.md`; `sase amd init` repairs root
  provider shims only.
- `sase amd init` and `sase memory init` both know how to produce AMD-managed `AGENTS.md`; the current division is
  intentional, but future edits should preserve the shared renderer path to avoid drift.
