---
create_time: 2026-06-20 15:31:06
status: done
prompt: sdd/prompts/202606/workspace_open_reason.md
---
# Require a Reason for `sase workspace open`

## Goal

Require callers to provide `-r|--reason` when using `sase workspace open`, update the generated SASE memory guidance so
agents learn the new form, and keep existing workspace-open behavior unchanged once a valid reason is supplied.

## Current Shape

- `sase workspace open` is registered in `src/sase/main/parser_workspace.py` and currently accepts `workspace_num`,
  `-p|--project`, `-P|--print`, and `-c|--clean`.
- The open implementation flows through `src/sase/main/workspace_handler.py` into
  `src/sase/main/workspace_handler_list.py::handle_open_clean`.
- `handle_open_clean` has side effects: it can initialize SDD guide files, materialize a checkout, prepare/clean/sync
  the workspace, record opened linked/sibling repos in the current run artifacts, and print the resulting path.
- Generated `memory/sase.md` content comes from `src/sase/main/init_memory/roots.py`; the checked-in `memory/sase.md`
  should be refreshed to match that renderer.
- Existing tests cover parser behavior, open handler behavior, and generated memory rendering, but they currently
  construct open commands without any reason.

## Design

1. Add a required `-r|--reason` option to only the `open` subcommand.
   - The help text should make it clear this is a non-empty reason for opening/preparing the workspace.
   - Keep the touched option listing clean and consistent with CLI rules.

2. Validate the reason before any open-side effects.
   - Add a small workspace-open reason normalizer, mirroring the `sase memory read` pattern: trim whitespace and reject
     empty values.
   - Parser-level `required=True` catches omitted CLI flags.
   - Handler-level validation catches blank strings and direct handler test/integration calls.
   - Return command-line usage-style failure (`2`) for missing/empty reason before resolving context, initializing SDD
     files, materializing, preparing, recording, or printing.

3. Keep the reason as an explicit intent gate for this change.
   - Do not expand the opened-linked/sibling marker schema in this pass; current consumers only need repo name and
     workspace path.
   - This avoids turning a narrow CLI safety contract into a broader audit-schema migration.

4. Update generated memory rendering.
   - Change the numbered-workspace sibling command snippet in `src/sase/main/init_memory/roots.py` to include
     `-r "<reason>"`.
   - Refresh the checked-in `memory/sase.md` so it matches what `sase memory init` generates.
   - Update generated-memory tests to assert the new command form and to continue asserting static-path siblings do not
     get workspace-open guidance.

5. Update active documentation and examples that show literal `sase workspace open` invocations.
   - Update README and active docs such as workspace, configuration, init, commit workflow, CLI/project spec references
     where examples would otherwise become invalid.
   - Leave purely descriptive mentions alone when they are not command examples, unless a small wording change improves
     clarity.
   - Re-run `rg` for `sase workspace open` afterward to verify remaining references are either updated examples or
     intentional generic mentions.

6. Update tests.
   - Parser tests: `-r` and `--reason` parse correctly; omitting the option exits; existing compatibility flags still
     parse when a reason is supplied.
   - Handler tests: all successful opens pass a reason; blank reason returns `2` and performs no side effects.
   - Generated memory tests: expected snippets include the required reason flag.
   - Help tests if needed: workspace-open help exposes `--reason REASON`.

## Validation

Run targeted tests first:

```bash
uv run pytest tests/main/test_workspace_handler_parser.py tests/main/test_workspace_handler_list_path.py tests/main/test_init_memory_handler.py tests/main/test_parser_command_help.py
```

Then run drift checks for generated memory and the repo-required full check after file changes:

```bash
sase memory init --check
just check
```

If `sase memory init --check` reports unrelated existing drift, inspect the diff and keep the implementation scoped to
the workspace-open reason change.
