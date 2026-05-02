---
create_time: 2026-05-01 23:45:33
status: done
prompt: sdd/prompts/202605/sdd_init_readme.md
---
# Plan: Add `sase sdd init`

## Goal

Add a new `sase sdd init` subcommand that creates or refreshes a high-quality `sdd/README.md` guide for an SDD tree,
then run the new command in this repository so `sdd/README.md` exists.

## Current Shape

- `sase sdd` is registered in `src/sase/main/parser_sdd.py` and dispatched from `src/sase/main/sdd_handler.py`.
- Existing SDD filesystem helpers live in `src/sase/sdd/files.py`; link validation/listing lives in
  `src/sase/sdd/links.py`.
- Tests for parser and handler behavior are concentrated in `tests/main/test_sdd_handler.py`; path helper tests live in
  `tests/test_sdd_paths.py`.
- This repo uses version-controlled SDD artifacts under `sdd/`, with canonical directories `prompts/`, `tales/`,
  `epics/`, `legends/`, and `beads/`.

## Design

1. Add `sase sdd init` to the argparse registration.
   - Keep the existing style and add a `-p`/`--path` option, because repo guidance requires short options on CLI
     arguments.
   - Interpret `--path` as either a project root or an SDD root, matching the existing SDD command behavior.

2. Add a deterministic README generator.
   - Place the implementation in the SDD Python layer, likely `src/sase/sdd/files.py`, because it is SDD file management
     rather than core Rust domain behavior.
   - Resolve the target as:
     - default: `./sdd/README.md`
     - project-root path: `<path>/sdd/README.md`
     - SDD-root path: `<path>/README.md`
   - Create the `sdd/` directory if needed.
   - Always write the canonical README content so the command is idempotent and can update stale generated docs.

3. README content should be useful in any project using SDD.
   - Explain the purpose of `sdd/`.
   - Document canonical subdirectories: `prompts`, `tales`, `epics`, `legends`, `beads`.
   - Explain `YYYYMM` organization and frontmatter links between prompts and plan-like artifacts.
   - Mention legacy compatibility for `plans`/`specs` only as a note, keeping `tales`/`prompts` canonical.
   - Include practical commands: `sase sdd list`, `sase sdd validate`, `sase sdd repair-links`, `sase bead`.

4. Wire handler behavior.
   - Add `_handle_init(args)` in `src/sase/main/sdd_handler.py`.
   - Print the created/updated README path on success and exit `0`.
   - Update the fallback usage string to include `init`.

5. Add focused tests.
   - Parser test confirms `sase sdd init -p <path>` registers correctly.
   - Handler test verifies the command creates `sdd/README.md` when pointed at a project root.
   - Handler test verifies repeated runs are idempotent and overwrite stale generated content with the canonical
     content.
   - If path resolution is factored into a helper, add helper-level coverage for project-root vs SDD-root targets.

6. Run and verify.
   - Run focused tests for SDD parser/handler/path helpers.
   - Run `just install` before final repo checks if needed for this workspace.
   - Run the implemented `sase sdd init` command in this repo to create `sdd/README.md`.
   - Run `just check` before finishing, per repo instructions.

## Non-Goals

- Do not migrate SDD artifacts or alter the existing SDD validation model.
- Do not initialize beads or create a standalone `.sase/sdd` git repo; `sase bead init` and existing SDD flows already
  own that behavior.
- Do not add interactive prompts. This should be deterministic and automation-friendly.
