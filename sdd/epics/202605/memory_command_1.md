---
tier: epic
status: done
bead_id: sase-3z
prompt: sdd/prompts/202605/memory_command_1.md
---

# SASE Memory Command Plan

## Goal

Add a top-level `sase memory` command group with:

- `sase memory list`, also the default when `sase memory` is run with no subcommand.
- `sase memory init`, which becomes the primary implementation of the current `sase init memory` behavior.
- `sase init memory` retained as an alias, matching the existing `sase init sdd` pattern.

The high-risk part is `list`: it should show a polished Rich dashboard of the memory files that would be loaded into, or
referenced from, a SASE agent context launched from the current directory. It must distinguish `@path` references, whose
target contents are loaded into context, from plain `memory/...` references, whose target files are only mentioned
unless some loaded file also `@`-references them.

## Current Shape

- CLI wiring is centralized in `src/sase/main/parser.py` and `src/sase/main/entry.py`.
- `sase init memory` is registered in `src/sase/main/parser_init.py` and handled by
  `src/sase/main/init_memory_handler.py`.
- `sase init sdd` is already an alias for `sase sdd init`: entry code rewrites `args.sdd_subcommand = "init"` and calls
  the normal `sdd` handler.
- Memory initialization helpers already live under `src/sase/main/init_memory/`.
- Existing reachability validation is in `src/sase/main/init_memory/inventory.py`, but it currently treats `@`
  references and plain `memory/short|long/*.md` mentions as equivalent reachability edges.
- Dynamic memory is handled separately under `src/sase/memory/dynamic.py` and `src/sase/xprompt/loader_memory.py`.
  `sase memory list` should report the configured/discoverable long-term memory sources, but it should not generate
  `.sase/memory/long-*.md` files or require a prompt to match dynamic memory.
- Rich is already a dependency and is used by CLI surfaces such as telemetry, chats, agents, and search.

## Product Design

The dashboard should be useful without flags:

- Header panel: current directory, detected project name if available, instruction roots found, total loaded files,
  total referenced-only files, loaded line count, and approximate loaded token count.
- Main table: one row per memory file under `memory/short` and `memory/long` that is loaded, referenced, or present.
- Status column:
  - `loaded` for files reached by a transitive `@` edge from an instruction root or another loaded file.
  - `referenced` for files mentioned by plain `memory/...` text from loaded context, but not loaded via `@`.
  - `available` for memory files present on disk but not reached from the launch context.
  - `missing` for referenced memory paths that do not exist.
- Counts:
  - For `loaded`, show that file's full line and token estimates and include them in loaded totals.
  - For `referenced`, show the file's own lines/tokens for inspection, but do not include them in loaded totals.
  - For `available`, show file size stats but dim it because it would not affect a launch.
  - For `missing`, show the referring source and omit size counts.
- Reference detail column: show the first/root path by which the file is loaded or referenced, plus a compact count when
  multiple sources mention it.
- Footer notes: explain that `@` loads content, plain memory paths only create a visible reference, and dynamic memory
  is prompt-dependent.

Token count should be explicitly documented as approximate. Use a deterministic local estimator such as
`ceil(len(text) / 4)` or an existing repo helper if implementation finds one; do not add a heavyweight tokenizer
dependency just for this command.

## Technical Design

Create a reusable memory inventory module, separate from rendering:

- Suggested location: `src/sase/memory/inventory.py` for domain behavior used by CLI and future frontends.
- Keep initialization-only rendering and file creation in `src/sase/main/init_memory/`.
- Move or wrap the existing reference regex behavior so init validation and the list dashboard share parsing logic.
- Parse references into typed edges:
  - `loaded` edge for `@path`.
  - `plain` edge for bare `memory/short/*.md` and `memory/long/*.md` mentions.
- Resolve paths relative to the context root and the referring file, keeping the existing protections for URLs and paths
  escaping the root.
- Build the graph from instruction roots in this order:
  - Known provider shim files: `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`.
  - `AGENTS.md`.
  - If shims only contain `@AGENTS.md`, display them as roots but count the loaded content once.
- Traverse only `@` edges for loaded content. Record plain edges encountered inside already loaded files as
  referenced-only targets unless those targets are also loaded by another `@` edge.
- Include all on-disk `memory/short/**/*.md` and `memory/long/**/*.md` files in the report, even if available only.
- Model the report with dataclasses such as `MemoryInventory`, `MemoryFileEntry`, `MemoryReference`, and `MemoryStats`
  so tests can assert behavior without snapshotting Rich output.

For CLI wiring:

- Add `src/sase/main/parser_memory.py` with a `register_memory_parser()` function.
- Register it alphabetically from `parser.py`.
- Add `src/sase/main/memory_handler.py` with `handle_memory_command(args)`.
- `memory_subcommand` should not be required; a missing value should dispatch to `list`.
- Move the current init command body into a primary memory init handler, for example `handle_memory_init_command(args)`.
- Keep `handle_init_memory_command(args)` as a thin compatibility wrapper that calls the new handler.
- In `entry.py`, add a `memory` command branch and change the existing `init memory` branch to call the alias wrapper or
  set `args.memory_subcommand = "init"` and dispatch through `handle_memory_command(args)`.

For rendering:

- Add `src/sase/memory/cli_list.py` or keep rendering in `memory_handler.py` if small.
- Use Rich `Panel`, `Table`, `Text`, and possibly `Group`; avoid a large live dashboard since this is static output.
- Use non-color semantics in tests by rendering with
  `Console(file=StringIO(), force_terminal=False, color_system=None, width=...)`.
- Keep output resilient at narrow widths by using compact columns and letting Rich wrap paths.

## Phases

### Phase 1: CLI Group and Init Alias

Owner: one agent instance.

Scope:

- Add `sase memory` parser and handler.
- Implement `memory init` by moving/renaming the existing `sase init memory` handler entry point without changing its
  behavior.
- Make `sase init memory` an alias to the new handler, using the same design as `sase init sdd`.
- Add parser/handler tests proving:
  - `sase memory init -C` reaches the init implementation.
  - `sase init memory -C` still works.
  - `sase memory` with no subcommand parses and dispatches to list.

Validation:

- Focused tests for parser and init memory handler.
- `just install`, then `just check` after source edits.

### Phase 2: Inventory Engine

Owner: separate agent instance.

Scope:

- Add the reusable inventory dataclasses and graph builder.
- Preserve or improve existing unreferenced-memory validation by reusing the new graph while keeping the current init
  behavior unless a test intentionally changes it.
- Encode the distinction between loaded `@` references and plain memory references.
- Include missing referenced targets and all available on-disk memory files.
- Add focused unit tests for:
  - Transitive `@` loading.
  - Plain memory references remaining referenced-only.
  - Duplicate/root shim references counted once for loaded totals.
  - Missing referenced files.
  - Available but unreachable memory files.
  - Paths outside the root are ignored or flagged consistently with existing inventory behavior.

Validation:

- Focused inventory tests and existing `tests/main/test_init_memory_handler.py`.
- `just install`, then `just check`.

### Phase 3: Rich `sase memory list` Dashboard

Owner: separate agent instance.

Scope:

- Implement the default `list` subcommand using the Phase 2 inventory engine.
- Lead with a polished summary panel and table.
- Display loaded line/token totals and per-file line/token stats.
- Make status semantics visually distinct while keeping plain text readable in non-color terminals.
- Add `--json` only if implementation finds an established pattern worth matching; otherwise keep the first version
  focused on the Rich dashboard the user asked for.
- Add tests rendering the dashboard to a string and asserting durable text rather than brittle box drawing.

Validation:

- Focused `sase memory list` tests.
- Manual smoke from this repo root to inspect the real dashboard.
- `just install`, then `just check`.

### Phase 4: Integration Polish and Documentation

Owner: separate agent instance.

Scope:

- Update help text and any README/docs references that mention `sase init memory` as the primary command.
- Ensure `memory/README.md` wording matches the new loaded vs referenced distinction if init renders it.
- Check that dynamic memory wording is clear: long-term sources are discoverable, but `.sase/memory/` prompt matches are
  only generated when a prompt triggers them.
- Do final compatibility checks for `sase init memory`, `sase memory init`, `sase memory`, and `sase memory list`.

Validation:

- Focused command smoke tests through the installed CLI if feasible.
- `just install`, then `just check`.

## Open Decisions

- Whether to add `sase memory list --json` in the first pass. I would defer unless another consumer already needs it.
- Whether `sase memory list` should consider every provider shim as a root or only the effective default provider. I
  recommend considering all known instruction roots and de-duplicating loaded files, because SASE initializes shims for
  all supported runtimes and the command is meant to describe SASE agent launch context generically.
- Whether init validation should continue treating plain references as sufficient reachability. I recommend preserving
  current acceptance initially and using the dashboard to make the weaker semantics visible. Tightening validation can
  be a later behavior change.

## Risks

- The exact agent-runtime behavior for instruction files differs across Claude, Gemini, Codex, Qwen, and OpenCode. The
  SASE convention already normalizes this with provider shims, so the implementation should model SASE's shim graph
  rather than hard-code runtime-specific assumptions.
- Token estimates can create false precision. Label them as approximate and keep the estimator deterministic.
- Rich snapshot tests can be brittle. Test the data model thoroughly, then assert key substrings for rendering.
- The old init validation has tests around transitive memory references; reuse should avoid silently changing that
  behavior in the CLI alias phase.
