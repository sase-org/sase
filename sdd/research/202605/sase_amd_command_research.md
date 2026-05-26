---
create_time: 2026-05-26
updated_time: 2026-05-26
status: research
---

> Update 2026-05-26: extended with exit-code behavior, apply-mode console output, shared-renderer
> invariants, shim whitespace tolerance, and a test-surface map after a second pass through the
> implementation and the `tests/main/test_amd_*.py` suite.

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
sase init --check amd # equivalent; `--check` flows through to the alias
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
using the same `add_amd_init_arguments()` helper, and `src/sase/main/entry.py` dispatches it to
`handle_init_amd_command()`, which calls the same AMD initializer as `sase amd init`.

The `--check` flag on the `sase init amd` alias is registered with `default=argparse.SUPPRESS`, so when the user runs
`sase init --check amd`, the parent `init --check` flag is not silently overwritten by the alias's `False` default.
`tests/main/test_amd_parser_handler.py::test_parser_registers_amd_namespace` covers both `init amd --check` and
`init --check amd` forms.

`src/sase/amd/cli.py` is a thin lazy-import indirection. `amd_handler` imports `run_amd_init` / `run_amd_list` from
`sase.amd.cli`, and `cli.py` defers the heavyweight imports (`sase.amd.init`, `sase.amd.inventory`) until called. This
keeps `sase --help` and unrelated commands from paying the YAML/Rich import cost.

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

The `handle_amd_command` fallback (`Usage: sase amd {init,list}` → exit 1) is effectively dead code in
the CLI path because argparse rejects unknown subcommands before dispatch with its own exit code 2:

```text
$ sase amd foo
usage: sase amd [-h] {init,list} ...
sase amd: error: argument amd_subcommand: invalid choice: 'foo' (choose from init, list)
# exit code: 2
```

The fallback only matters for direct programmatic callers that build an `argparse.Namespace` with an
unsupported `amd_subcommand` value.

## Exit Codes and Console Output

`run_amd_init` and `run_amd_list` are pure `int`-returning callables; `amd_handler` wraps each in
`sys.exit(...)`, so the integer return is the process exit code.

| Invocation                                | Exit code | Output stream | Notable text |
|-------------------------------------------|-----------|---------------|--------------|
| `sase amd list` (always)                  | 0         | stdout        | Rich `AMD Inventory` + `Agent Markdown Documents` panels |
| `sase amd init` (clean, no writes needed) | 0         | stdout        | `init amd: agent markdown documents are current` |
| `sase amd init` (with writes)             | 0         | stdout        | `init amd: initialized agent markdown documents` followed by one `  <path>` line per write |
| `sase amd init` (blocker)                 | 1         | stderr        | one `init amd: <blocker>` line per blocker |
| `sase amd init --check` (clean)           | 0         | stdout        | onboarding-check renderer: `SASE is initialized. ... Checked: amd.` |
| `sase amd init --check` (drift or blocker)| 1         | stdout        | onboarding-check renderer: `SASE initialization check ... Needs attention:` lines |
| `sase init amd ...`                       | same as `sase amd init`; alias handler dispatches to the same `run_amd_init` |
| `sase amd foo` (unknown subcommand)       | 2         | stderr        | argparse error before dispatch (see CLI Wiring) |

`COMMAND_LABEL = "init amd"` (defined in `src/sase/amd/init.py`) is the prefix on every blocker and
applied-output line. Both `sase amd init` and `sase init amd` emit the same `init amd:` prefix
because they share `run_amd_init`. Test `test_amd_check_reports_drift_without_writing` pins both the
drift-exit-1 contract and the check-mode rendered text.

## Config Surface

`amd_h1_title` is wired in three places:

- `src/sase/default_config.yml` declares the default as `null`.
- `config/sase.schema.json` types it as `["string", "null"]` with the explanation that the generator ignores global
  values.
- This repo's own `sase.yml` sets it to `"Structured Agentic Software Engineering (SASE) - Agent Instructions"`.

Validation rules in `_load_project_amd_h1_title()` (`src/sase/amd/init.py`):

- Missing `sase.yml` or missing field → no blocker, no managed `AGENTS.md`.
- YAML parse error → blocker with the YAML exception message.
- Top-level value is not a mapping → blocker `expected a YAML mapping at the top level`.
- `amd_h1_title` set to a non-string non-null value → blocker `amd_h1_title must be a string or null`.
- `amd_h1_title` set to an empty/whitespace-only string → blocker `amd_h1_title must not be empty`.

Blockers surface through `InitPlan.blockers`, and propagate through `AmdMemorySyncPlan.blockers` into
`MemoryRootPlan.blockers`, so a malformed AMD title also blocks `sase memory init`.

## Managed Files And Markers

Shared AMD constants live in `src/sase/amd/constants.py`:

```python
AGENTS_FILENAME = "AGENTS.md"
PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
```

`PROVIDER_SHIM_FILES` is a tuple in iteration order, so init writes and inventory rendering both visit the providers in
the same Claude → Gemini → Qwen → OpenCode order.

Managed `AGENTS.md` memory sections are delimited by stable HTML comments:

```text
<!-- sase-amd:short-memory:start -->
<!-- sase-amd:short-memory:end -->
<!-- sase-amd:long-memory:start -->
<!-- sase-amd:long-memory:end -->
```

Those marker blocks are what let `sase memory init` update the short-memory bullet list and long-memory description list
without trying to rewrite arbitrary surrounding prose.

## Provider Shim State Machine

The init planner and inventory share a four-state classification for each root-level provider file:

| State        | Meaning                                                                 | Init behavior              |
|--------------|-------------------------------------------------------------------------|----------------------------|
| `missing`    | File does not exist                                                     | Created with `@AGENTS.md\n` |
| `exact_shim` | File contents exactly equal `PROVIDER_SHIM_CONTENT` (`@AGENTS.md\n`)    | Left alone                 |
| `shim`       | Stripped contents equal the shim, but trailing whitespace differs       | Silently rewritten to canonical |
| `custom`     | Anything else (including read errors)                                   | Treated as a migration source candidate; otherwise left alone if `AGENTS.md` already exists |

`_action_for_write()` only emits a no-op when current content matches byte-for-byte, so `shim` is reported as an
`overwrite` action by the planner even though the inventory's `_shim_summary` paints it as a yellow "noncanonical
whitespace" warning.

`InitAction.operation` is always `create` or `overwrite`. The planner never emits a delete, so a stale custom
provider file is *not* removed during init unless its content can be canonicalized.

The `shim` classification rule (`_is_shim_text`) compares `text.strip() == PROVIDER_SHIM_CONTENT.strip()`, so *any*
amount of leading or trailing whitespace — including extra blank lines, missing trailing newline, or BOM-less
whitespace — is treated as a recoverable shim and gets silently rewritten to the canonical `"@AGENTS.md\n"`. Content
with the shim text surrounded by *other* non-whitespace tokens (e.g. `# Notes\n@AGENTS.md\n`) is classified `custom`.

Init `detail` strings (the right column of the onboarding check renderer) are fixed:

- `"managed AGENTS.md"` — generated managed `AGENTS.md` write.
- `"provider instruction shim"` — any of the four provider shims.
- `"migrate <Provider>.md to AGENTS.md"` — single-file legacy migration write.

These strings are the only inputs to the single-action summary path of `_summarize_amd_actions`
(`"<operation> <detail>"`), so renaming any of them changes the user-facing onboarding-check output.

## `amd_h1_title`

`amd_h1_title` is the opt-in switch for generated project-managed `AGENTS.md`.

Example from this repo's `sase.yml`:

```yaml
amd_h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions"
```

The key point is scope: `_load_project_amd_h1_title()` in `src/sase/amd/init.py` reads only `./sase.yml` in the current
project root. It deliberately ignores merged/global config so a global `~/.config/sase/sase.yml` cannot accidentally opt
every repository into generated agent instructions. This is asserted by
`test_amd_init_ignores_global_amd_h1_title`.

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

The `explicit` flag is computed in `_plan_amd_init()` from `args.command == "init" and args.init_subcommand is None`,
so `sase amd init` and `sase init amd` are both treated as explicit even from the registry path.

Check mode uses the shared onboarding check renderer by wrapping AMD in a one-item `InitCommandSpec` and calling
`run_init_check()`. In this workspace, both `sase amd init --check` and `sase init amd --check` printed:

```text
SASE is initialized. No init subcommands need to run.
Checked: amd.
```

The check-mode summary verbs come from `_summarize_amd_actions()`:

- `"agent markdown documents are current"` — no actions, no blockers.
- `"<operation> <detail>"` — exactly one action (e.g. `overwrite provider instruction shim`).
- `"create N agent markdown documents"` — multiple actions, all creates.
- `"overwrite N agent markdown documents"` — multiple actions, all overwrites.
- `"refresh N agent markdown documents"` — mixed operations.
- `"cannot initialize agent markdown documents until blockers are fixed"` — any blocker present.

Focused behavior tests are in `tests/main/test_amd_init.py`.

### Write Mechanics

`run_amd_init` walks `built.writes` in plan order and, for each write, calls
`write.path.parent.mkdir(parents=True, exist_ok=True)` before `write_text(..., encoding="utf-8")`. That
means project-managed `AGENTS.md` content can land into a path whose parents do not yet exist (relevant
for memory-init paths under `memory/long/...`) without failing.

Idempotency is guaranteed by `_action_for_write` returning `None` when current bytes already equal the
planned content; the planner skips that path entirely, so a clean `sase amd init` reports
`agent markdown documents are current` and writes nothing on a second back-to-back run.

`_render_managed_agents()` is the single source of truth for managed `AGENTS.md` content. It is invoked
by `_build_amd_init_plan` (during `sase amd init`) *and* by `plan_amd_memory_sync` (consumed by
`sase memory init`). Keep the two callers aligned by editing only the renderer — divergence would let
`memory init` overwrite `AGENTS.md` with content that AMD's planner immediately treats as drift.

## Long-Memory Description Generation

When generating Tier 3 entries, the planner runs each `memory/long/**/*.md` through `_long_memory_description()`
with a four-step fallback:

1. **Frontmatter `description` value** — non-empty string wins; whitespace is collapsed.
2. **Existing AGENTS.md Tier 3 description** — extracted by `_AGENTS_LONG_MEMORY_RE`, which matches
   `**`memory/long/...`**\n<body>` blocks terminated by a blank line or EOF. The trailing italic suffix
   `_Read when ..._` is stripped so legacy italicized triggers don't leak into the new generator's output.
3. **First body paragraph (or H1 fallback)** — `_first_body_paragraph_or_h1()` skips H1/H#/blank lines and joins the
   first non-heading paragraph's lines, collapsing whitespace.
4. **Filename fallback** — the file stem with `_`/`-` mapped to spaces and capitalized.

For long-memory files that lack frontmatter `description` at all, `_long_memory_description_updates()` plans an
in-place rewrite that inserts a `description:` line just before the closing `---` of the existing frontmatter using
`_with_description_frontmatter()`. If the file has no frontmatter, a fresh `---\ndescription: ...\n---` block is
prepended. PyYAML's `safe_dump` is used to encode the value so multi-line or quoted strings are properly escaped.

These description updates are produced by AMD but written by `sase memory init`, not by `sase amd init` (see the
memory-init section below).

## `sase amd list`

The inventory command is implemented in `src/sase/amd/inventory.py`. It is read-only and has no flags — the original
plan reserved `-j|--json` only if it would stay cheap, and the cheap path never materialized.

Project root detection (`_project_root()`):

- First walks up from CWD looking for `.git` or `.hg` via `_find_marker_root()`.
- Falls back to `git rev-parse --show-toplevel` or `hg --cwd <cwd> root` via `_run_vcs_root()` (subprocess).
- Falls back to the resolved CWD.

Project scanning prunes a fixed set of generated/cache/vendor directories. Full list from `_PRUNED_DIR_NAMES`:

```
.cache, .git, .hg, .hypothesis, .mypy_cache, .nox, .pytest_cache, .ruff_cache, .sase, .tox, .venv,
__pycache__, __pypackages__, artifacts, build, coverage, dist, generated, htmlcov, node_modules,
site, target, venv
```

Discovery rules:

- Project root file → scope `project`.
- Nested matches → scope `project-subdir`.
- Live `~/AGENTS.md` → scope `home`.
- Chezmoi-source `<chezmoi>/AGENTS.md` → scope `chezmoi`. Included when `config.use_chezmoi` is on *or* the source
  root exists (deduplicated against `home` via resolved path).

For each discovered `AGENTS.md`, the entry records:

- Scope (`project`, `project-subdir`, `home`, `chezmoi`).
- Display path: project-relative or `~`-relative depending on scope.
- First Markdown H1 title via `_H1_RE`, with whitespace collapsed.
- Management state:
  - `managed` — all four AMD marker comments are present.
  - `missing marker blocks` — some markers are present.
  - `custom` — no markers, or the file cannot be read.
- Unique short/long memory reference counts. The regex `_MEMORY_REF_RE` accepts both `@memory/...` and bare
  `memory/...` mentions and deduplicates per tier.
- Nearby provider shim status for `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md` in the same directory as the
  `AGENTS.md`.

Rendering uses two Rich panels:

- `_summary_panel` shows project root, home root, chezmoi-source path (when active), `Use chezmoi` (yes/no), and the
  total `AGENTS.md` count.
- `_documents_panel` is a six-column table: Scope / Path / H1 / State / Memory / Provider shims.

`_shim_summary` color-codes the provider column:

- All four exact shims → green `all shims`.
- Otherwise composite: `N shim(s)` (green), `noncanonical whitespace: <files>` (yellow), `custom: <files>` (yellow),
  `missing: <files>` (red).
- All four absent → red `missing all`.

Observed `sase amd list` in this workspace showed 5 documents: root project `AGENTS.md` as managed with short 5 / long 2
memory refs, two custom project-subdir `AGENTS.md` files, live home `~/AGENTS.md`, and one custom chezmoi-source
`AGENTS.md`. The two project subdir files had `CLAUDE.md` and `GEMINI.md` shims, and were missing `QWEN.md` and
`OPENCODE.md`.

Focused inventory/rendering tests are in `tests/main/test_amd_list.py`, including pruned-directory coverage and
partial-marker classification.

Important asymmetry between `list` and `init`: the inventory classifies a partially-markered
`AGENTS.md` as `missing marker blocks` (yellow), but the init planner does **not** treat partial
markers as drift. Init only touches `AGENTS.md` when `amd_h1_title` is set (always overwrites with
the rendered managed body) or when running the legacy single-file migration. A repository with
half-managed markers therefore stays half-managed across `sase amd init` runs unless the project
opts in via `amd_h1_title`.

Entry ordering in the table is `_SCOPE_ORDER` (project → project-subdir → home → chezmoi), with
ties broken by `display_path`. Home and chezmoi each contribute at most one entry; chezmoi is
deduplicated against home via resolved-path comparison so a chezmoi-managed symlink does not appear
twice.

## Integration With `sase init`

The init registry lives in `src/sase/main/init_registry.py` and runs in this order:

1. AMD
2. Memory
3. SDD
4. Skills

The order matters because memory validation needs to know what `AGENTS.md` will exist after AMD runs. `sase init -c`
uses read-only planning, but AMD still plans first so memory can reason about the same eventual agent-instruction
surface.

The "reason about" mechanism is the **validation overlay**. `_validation_overlay_for_expected_files()` in
`src/sase/main/init_memory/roots.py` maps each expected file's resolved path to its planned content. The overlay
includes:

- All planned `memory/short/**/*.md` and `memory/long/**/*.md` content (so reachability checks see freshly-described
  long files).
- The planned `AGENTS.md` content when AMD will overwrite it, or when AMD will create the minimal version.

Without that overlay, `sase init -c` would emit false "unreferenced memory" warnings whenever AMD has planned a new
short-memory reference that does not yet live in the on-disk `AGENTS.md`.

Docs in `docs/init.md` describe the same conservative policy: bare `sase init` only lets AMD generate managed
`AGENTS.md` when the project-local config opts in with `amd_h1_title`; explicit AMD commands still repair provider
shims and perform legacy single-file migrations when the title is unset.

## Integration With `sase memory init`

`sase memory init` still creates project/home memory roots, but it delegates AMD-managed AGENTS synchronization to
`plan_amd_memory_sync()` when AMD support is enabled.

The integration point is `src/sase/main/init_memory/roots.py`:

- `_amd_sync_plan(root, enable_amd=True)` calls `plan_amd_memory_sync(root)`.
- `_render_expected_memory_files()` appends planned long-memory description frontmatter updates as
  `MemoryExpectedFile` entries with `stale_operation="update"` (so the memory-init UI reports them as `update` rather
  than `overwrite`).
- It also appends an overwrite for root `AGENTS.md` with the AMD-rendered managed content.
- If AMD is not active (no project-local `amd_h1_title`), memory init falls back to creating a minimal `AGENTS.md`
  via `MINIMAL_AGENTS_CONTENT` (`# Agent Instructions\n\n@memory/short/sase.md\n`) with
  `write_policy="create_if_missing"` so it never overwrites a hand-curated file.
- Provider shim constants now come from `sase.amd.constants` re-exports in `init_memory/constants.py`, avoiding
  drift between memory and AMD code paths.

This means the practical split is:

- `sase amd init` owns agent markdown document setup and shim repair.
- `sase memory init` owns generated memory files and, when the project opted into AMD, keeps the AMD memory blocks and
  long-memory `description` frontmatter synchronized.

`AmdMemorySyncPlan` also carries a `blockers` tuple. If `amd_h1_title` is malformed, the blocker reaches
`MemoryRootPlan.blockers` and `sase memory init --check` will surface it without trying to write.

## Design Intent From The Original Plan

The originating plan is `sdd/epics/202605/amd_command.md`. It frames AMD as a migration from scattered provider-specific
instruction files toward a shared `AGENTS.md` model with provider shims.

Important design decisions from that plan that are reflected in the implementation:

- Treat `AGENTS.md` as the canonical instruction file and provider files as `@AGENTS.md` shims.
- Keep explicit AMD init active even for repos without `amd_h1_title`.
- Keep bare `sase init` conservative for repos that have not opted in.
- Register AMD before memory.
- Use marker comments so memory init can update generated memory blocks robustly.
- Preserve curated long-memory descriptions during first migration (via `_AGENTS_LONG_MEMORY_RE`).
- Keep `sase amd list` focused on known roots rather than scanning all of `$HOME`.
- Read `amd_h1_title` directly from `./sase.yml` instead of merged config to prevent global opt-in.

## Source Map

- CLI parser: `src/sase/main/parser_amd.py`
- Init alias parser: `src/sase/main/parser_init.py` (`add_amd_init_arguments(..., suppress_check_default=True)`)
- Top-level dispatch: `src/sase/main/amd_handler.py`
- Compatibility alias dispatch: `src/sase/main/entry.py`
- Lazy import shim: `src/sase/amd/cli.py`
- AMD init planner/writer: `src/sase/amd/init.py`
- AMD inventory renderer: `src/sase/amd/inventory.py`
- Shared constants: `src/sase/amd/constants.py`
- Init registry order: `src/sase/main/init_registry.py`
- Memory init integration: `src/sase/main/init_memory/roots.py`
- Memory minimal fallback: `src/sase/main/init_memory/constants.py`
- Config default: `src/sase/default_config.yml` (`amd_h1_title: null`)
- Config schema: `config/sase.schema.json` (`amd_h1_title: string|null`)
- This repo's opt-in: `sase.yml` (`amd_h1_title: "Structured Agentic Software Engineering ..."`)
- Config docs: `docs/configuration.md`
- Init docs: `docs/init.md`
- Memory docs: `docs/memory.md`
- CLI command index: `docs/cli.md`
- Parser tests: `tests/main/test_amd_parser_handler.py`
- Init tests: `tests/main/test_amd_init.py`
- Inventory tests: `tests/main/test_amd_list.py`

## Test Surface

The three AMD-specific test files pin the observable contract at a granular level. For onboarding
new contributors, the mapping below shows which test guards which behavior so changes can be
intentional rather than accidental.

`tests/main/test_amd_parser_handler.py`:

- `test_parser_registers_amd_namespace` — locks the four parse paths (`amd`, `amd list`,
  `amd init -c`, `init amd --check`, `init --check amd`) including the `--check` SUPPRESS default
  that makes `init --check amd` work.
- `test_bare_amd_defaults_to_list` — guarantees the no-subcommand default routes to `list`.
- `test_amd_init_dispatches_to_initializer` — locks `amd init` dispatch path.
- `test_init_amd_alias_dispatches_to_amd_init` — locks the cross-handler alias path through
  `sase.main.entry.main` (proves the alias goes through the same code).

`tests/main/test_amd_init.py`:

- `test_amd_init_creates_and_repairs_provider_shims` — bare project with non-shim `CLAUDE.md` gets
  repaired and idempotency (`plan_amd() == set()` after first run).
- `test_amd_check_reports_drift_without_writing` — check returns exit 1 on drift, writes nothing,
  and emits the onboarding check renderer output.
- `test_bare_init_amd_plan_is_conservative_without_project_title` — bare `sase init` skips AMD if
  no project-local `amd_h1_title`, but explicit `sase amd init` still repairs shims.
- `test_bare_init_amd_plan_generates_when_project_title_is_set` — bare `sase init` *does* generate
  AMD when project opts in.
- `test_amd_init_migrates_single_legacy_provider_file` — exact byte-preservation contract on the
  legacy migration path.
- `test_amd_init_blocks_multiple_legacy_provider_files` — multi-custom-file blocker exits 1,
  stderr contains the explanation, files are untouched.
- `test_amd_init_blocks_shim_only_without_agents_target` — orphan-shim blocker.
- `test_amd_init_generates_managed_agents_from_project_local_title` — full managed render path,
  proves `@memory/short/sase.md` is forced into the list, `@memory/short/extra.md` is picked up,
  long-memory descriptions come from frontmatter when present and from the existing AGENTS body
  when not.
- `test_amd_init_ignores_global_amd_h1_title` — `~/.config/sase/sase.yml` does *not* count.

`tests/main/test_amd_list.py`:

- `test_build_inventory_scans_project_agents_from_vcs_root_and_prunes` — VCS-marker walk from a
  nested CWD, `_PRUNED_DIR_NAMES` enforcement (.sase, node_modules, __pycache__), per-entry
  classification, partial-shim missing-list ordering matches `PROVIDER_SHIM_FILES`.
- `test_build_inventory_includes_live_home_and_chezmoi_source` — home and chezmoi entries appear
  with the right scopes and display paths (`~/AGENTS.md`, `~/.local/share/chezmoi/home/AGENTS.md`).
- `test_build_inventory_reports_partial_marker_blocks` — partial markers map to
  `missing marker blocks` and memory-ref count still works.
- `test_render_amd_inventory_outputs_compact_rich_table` — Rich panel titles, scope rows, the
  `short N / long M` formatting, and the `missing: QWEN.md, OPENCODE.md` summary line.

## Open Questions

- `sase amd list` is currently human-rendered only. The original plan allowed `--json` if cheap, but the implemented
  parser is flagless.
- Subdirectory provider shims are only inventoried next to each discovered `AGENTS.md`; `sase amd init` repairs root
  provider shims only.
- `sase amd init` and `sase memory init` both know how to produce AMD-managed `AGENTS.md`; the current division is
  intentional, but future edits should preserve the shared renderer path (`_render_managed_agents` /
  `plan_amd_memory_sync`) to avoid drift.
- The planner never emits a `delete` action, so a stale provider file with custom content next to a working
  `AGENTS.md` is left in place. Cleaning it up requires manual intervention or future tooling.
- `sase amd list` and `sase amd init` apply different definitions of "drift": `list` flags
  partial-marker `AGENTS.md` files as `missing marker blocks`, but `init` does nothing about them
  unless `amd_h1_title` is set. A future "repair partially-managed AGENTS.md" mode would close that
  gap.
- `_render_managed_agents` is currently the only consumer of `_short_memory_references` and
  `_iter_memory_markdown(root, "long")`. There is no JSON/structured surface for downstream tools
  (e.g. an editor extension) to ask "what would AMD generate?" without re-parsing the rendered
  Markdown.
- The `handle_amd_command` fallback branch (`Usage: sase amd {init,list}` → exit 1) is unreachable
  via the CLI because argparse rejects unknown subcommands first; it could be deleted or repurposed
  to surface a programmatic-misuse error.
