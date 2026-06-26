---
create_time: 2026-06-26 12:38:21
status: done
prompt: sdd/prompts/202606/migrate_amd_into_memory.md
---
# Plan: Migrate `sase amd` Into `sase memory`

## Goal

Remove the public `sase amd` command group and move its useful `list` and `init` behavior under `sase memory`, without
carrying forward the legacy provider-file migration path or compatibility aliases.

The end state should make `sase memory` the single public surface for memory context and agent instruction documents:

- `sase memory list` remains the default memory-context dashboard.
- `sase memory agent-docs list` replaces `sase amd list`.
- `sase memory init` becomes the canonical initializer for generated memory files, `AGENTS.md`, provider shims, and
  home/chezmoi memory surfaces.
- The top-level `sase amd` command and `sase init amd` alias are removed.

## Existing Behavior To Preserve

Preserve the non-legacy AMD behavior that still matters:

- Agent-document inventory:
  - discover project, subdirectory, home, and chezmoi-source `AGENTS.md` files;
  - show H1 title, managed/custom state, memory reference counts, and provider shim status;
  - keep provider shim handling for `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`, including chezmoi
    `*.md.tmpl` shims.
- Managed `AGENTS.md` generation:
  - project-local `amd_h1_title` still opts a project into managed `AGENTS.md`;
  - home/chezmoi roots can still derive the title from user/source config;
  - bare onboarding can still derive a fallback project title when memory files would otherwise be unreachable from a
    minimal `AGENTS.md`;
  - long-memory descriptions are preserved or derived and missing description frontmatter is inserted when needed.
- Provider shim repair:
  - use the existing shim planner for project, home, and chezmoi roots;
  - preserve chezmoi plain-file-to-template shim cleanup.
- Init planning:
  - `--check` stays read-only and reports drift through the shared init summary;
  - bare `sase init --check` still reports all SASE initialization drift.
- Deployment safety:
  - precommit runs before staging generated project files;
  - only generated/managed paths from the memory+agent-doc plan are staged;
  - unrelated dirty user edits are not swept into an auto-commit;
  - home/chezmoi paths are still deferred during bare `sase init` and deployed once at the end.

## Behavior To Drop

Do not reimplement these old AMD-specific paths:

- `sase amd`, `sase amd list`, `sase amd init`.
- `sase init amd`.
- The single-custom-provider-file migration that copies legacy provider content into `AGENTS.md`.
- Compatibility wrappers whose only purpose is preserving the old command names.

If the old migration tests cover only the dropped behavior, delete or rewrite them around the new memory-owned contract.

## Proposed Command Surface

Update the parser and help text to expose:

- `sase memory` / `sase memory list`: unchanged default memory-context dashboard.
- `sase memory agent-docs` / `sase memory agent-docs list`: migrated AMD inventory. The nested group has an exact `list`
  child so the central default-list delegation can handle bare `sase memory agent-docs`.
- `sase memory init`: combined initializer. Its help should say it creates or refreshes memory files, `AGENTS.md`, and
  provider instruction shims.
- `sase init`: still the onboarding coordinator, but its registry should be `memory`, `sdd`, `skills` because AMD is no
  longer a separate initializer.
- `sase init memory`: remains the existing alias for `sase memory init`.

Avoid adding a new `sase memory agent-docs init` unless implementation exposes a real need for an agent-doc-only
maintenance workflow. The primary goal is that old `sase amd init` effects are available through `sase memory init`.

## Implementation Steps

1. Refactor the agent-document implementation behind memory-owned entry points.
   - Keep the internal modules initially if that avoids unnecessary churn, but stop exposing public command/help text
     that uses the AMD command name.
   - Rename user-facing labels from `AMD Inventory` / `init amd` to memory/agent-document wording.
   - Extract the useful non-legacy init planner/apply pieces so `memory init` can compose them directly.

2. Remove the old public parser and dispatch paths.
   - Stop importing/registering `register_amd_parser()` in `src/sase/main/parser.py`.
   - Remove the `args.command == "amd"` branch from `src/sase/main/entry.py`.
   - Remove the `init amd` parser entry and dispatch branch.
   - Delete or retire `src/sase/main/parser_amd.py` and `src/sase/main/amd_handler.py` once no tests import them.

3. Add `sase memory agent-docs list`.
   - Extend `src/sase/main/parser_memory.py` with a nested `agent-docs` group and `list` child.
   - Dispatch it from `src/sase/main/memory_handler.py` to the migrated inventory renderer.
   - Keep `sase memory list` unchanged so bare `sase memory` is not made noisy.

4. Merge agent-document init into `sase memory init`.
   - In memory planning, build a combined per-root plan that includes: generated memory files, managed/minimal
     `AGENTS.md`, long-memory description updates, provider shim writes/deletes, and managed home/chezmoi `AGENTS.md`
     when configured.
   - Enable managed `AGENTS.md` sync for the home/chezmoi root instead of limiting it to the project root.
   - Remove the separate AMD init registry spec. The memory planner must report both memory-file and agent-document
     drift.
   - Preserve validation overlay behavior so newly planned `AGENTS.md` and generated memory files are considered before
     unreferenced-memory blockers are emitted.

5. Rework deployment around the single memory initializer.
   - Project deployment stages all combined project-root generated paths, including `AGENTS.md` and provider shims.
   - The project auto-commit uses the existing memory commit path unless a product decision is made to introduce a
     broader commit message such as `chore: initialize sase memory`.
   - Chezmoi/home generated paths flow through the existing memory chezmoi deploy/defer mechanism.
   - Remove the AMD-only local commit runner after its useful staging/precommit safeguards are covered by memory deploy
     tests.

6. Simplify legacy migration handling.
   - Delete the custom-provider migration planner.
   - Keep ordinary provider shim writes/deletes and custom-delete safeguards.
   - Add explicit tests for the new intended behavior when custom provider files exist so the implementation does not
     silently preserve old migration semantics by accident.

7. Update docs and help expectations.
   - Update `docs/init.md`, `docs/memory.md`, `docs/cli.md`, and `docs/configuration.md`.
   - Remove command tables and examples for `sase amd` / `sase init amd`.
   - Document `sase memory agent-docs list` as the way to inspect `AGENTS.md` and provider shims.
   - Document `sase memory init` as the combined initializer.
   - Keep `amd_h1_title` documented unless a separate config-rename task is explicitly added; changing that config key
     would expand this migration.

8. Update tests.
   - Replace parser/handler tests for `sase amd` with tests asserting the command is absent and
     `sase memory agent-docs list` parses/dispatches.
   - Move AMD inventory tests to the memory command surface.
   - Convert AMD init planning/apply tests into memory-init tests for preserved behavior: project title, home/source
     title, chezmoi templates, check mode, fallback title, provider shim repair, and no unrelated staging.
   - Delete tests whose only purpose is old command compatibility or legacy provider migration.
   - Update onboarding tests for registry order and prompt text: `memory`, `sdd`, `skills`.

## Verification

Run focused checks first:

```bash
pytest tests/main/test_memory_parser_handler.py \
  tests/main/test_parser_command_help.py \
  tests/main/test_parser_command_defaults.py
pytest tests/main/test_memory_read_list.py \
  tests/main/test_init_memory_plan.py \
  tests/main/test_init_memory_handler.py \
  tests/main/test_init_memory_commit.py \
  tests/main/test_init_memory_chezmoi.py \
  tests/main/test_init_onboarding_parser.py \
  tests/main/test_init_onboarding_flow.py
```

Then run broader quality gates:

```bash
ruff check src tests
mypy src
pytest
```

Also smoke-check help output manually:

```bash
sase --full-help
sase memory --help
sase memory agent-docs --help
sase memory agent-docs list --help
sase memory init --help
sase init --help
```

## Risks

- Combining AMD and memory initialization changes auto-commit boundaries. The memory commit path must stage all combined
  generated paths and leave unrelated dirty files untouched.
- Dropping the legacy provider migration may expose repositories with custom provider files that previously migrated
  automatically. This should be treated as an intentional breaking change with clear check-mode output.
- The `amd_h1_title` config name remains awkward after the command removal, but renaming it in the same change would
  create a broader config migration.
- Nested default-list behavior needs tests so bare `sase memory agent-docs` delegates correctly without changing bare
  `sase memory`.
