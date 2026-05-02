---
create_time: 2026-05-02 18:49:44
status: done
prompt: sdd/prompts/202605/sdd_research_readme.md
---
# Initialize SDD Research README

## Context

`sase sdd init` currently refreshes `sdd/README.md`, copies the directory-map asset, and creates README files for
`tales/`, `epics/`, `legends/`, and `myths/` through `src/sase/sdd/files.py`. The top-level generated README lists the
canonical SDD directories, but it does not mention `research/`, even though the repository already stores substantial
research artifacts under `sdd/research/YYYYMM/`.

The built-in default xprompts in `src/sase/default_config.yml` include:

- `research`, which tells agents to store research in `sdd/research/`.
- `research/prompt`, which composes through `#research`.
- `research/more`, which improves an existing research markdown file.

Those xprompts are loaded from default config and covered lightly by `tests/test_xprompt_loader_config.py`, but the test
only checks that `#research` composition remains present.

## Goals

- Make `sase sdd init` create or refresh `sdd/research/README.md`.
- Treat `research/` as a first-class generated SDD directory in docs and SDD-root detection.
- Update the built-in `#research` xprompt language in `src/sase/default_config.yml` so research agents follow the
  generated directory contract.
- Add focused regression coverage for the generated README and default xprompt text.
- Run the generated init command in this repo so the checked-in `sdd/research/README.md` exists.

## Non-Goals

- Do not add `research` to plan kinds, list kinds, bidirectional prompt/plan validation, or bead tiers.
- Do not rewrite old research files or add frontmatter requirements for research artifacts.
- Do not change how `research/prompt` composes through `#research`; that composition is intentional.

## Implementation Plan

1. Update generated SDD README content in `src/sase/sdd/files.py`.
   - Add `research/` to `_SDD_CANONICAL_DIRS` so a custom path containing only `research/` is recognized as an SDD root.
   - Add a top-level `research/` bullet to `SDD_README_CONTENT`.
   - Add `research/` to the canonical directory list in the compatibility section.
   - Add generated content for `research/README.md` alongside the existing generated per-directory README content.
   - Keep the copy concise: research stores exploratory findings, prior art, options, critiques, and recommendations
     that inform later tales, epics, legends, or implementation work.

2. Update `src/sase/default_config.yml` research xprompts.
   - Change the `research` xprompt from a one-line storage instruction into a slightly stronger contract: store new
     research under `sdd/research/`, organize month-based files consistently with existing SDD docs, and consult
     `sdd/research/README.md` when present.
   - Keep `research/prompt` ending its setup with `#research` so it still composes through the built-in research prompt.
   - Consider whether `research/more` should explicitly preserve the existing file path and follow the same README
     conventions. If updated, keep it short and avoid making "more research" create a new file unless the user asked for
     one.

3. Extend focused tests.
   - Update `tests/main/test_sdd_handler.py` so `_tier_readmes()` or its equivalent includes `research`.
   - Assert `sase sdd init` creates `sdd/research/README.md`, overwrites stale content idempotently, and the generated
     top-level README mentions `research/`.
   - Add a `tests/test_sdd_paths.py` case showing a path with only a `research/` child resolves as an SDD root.
   - Strengthen `tests/test_xprompt_loader_config.py::test_research_xprompts_load_from_default_config` to assert the
     default `research` xprompt mentions `sdd/research/README.md` and the `sdd/research/` directory while
     `research/prompt` still contains `#research`.

4. Refresh checked-in generated files.
   - Run `sase sdd init` in this repository after code changes.
   - Confirm it writes `sdd/research/README.md` and refreshes `sdd/README.md` without unexpected churn.

5. Verify.
   - Per workspace memory, run `just install` before test gates if the editable environment is stale or before the final
     full check.
   - Run focused tests first:
     - `.venv/bin/pytest tests/main/test_sdd_handler.py tests/test_sdd_paths.py tests/test_xprompt_loader_config.py`
   - Run formatting as needed with `just fmt`.
   - Run the required full gate with `just check` before reporting completion.

## Risks and Mitigations

- `research/` is not a plan tier, so adding it to the existing tier README map could make naming a little misleading.
  Keep the behavioral change small; rename the helper only if the edit stays mechanical and improves clarity without
  broad churn.
- Built-in xprompt text is user-facing. Keep the new guidance compact and avoid over-constraining research output beyond
  directory placement and README conventions.
- `sase sdd init` overwrites generated README files. Tests should assert stale replacement and idempotence for
  `research/README.md` just like the existing tier README coverage.
