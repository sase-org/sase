---
create_time: 2026-05-02 18:37:13
status: done
prompt: sdd/prompts/202605/sdd_init_tier_readmes.md
---
# Plan: Seed SDD Tier READMEs from `sase sdd init`

## Goal

Improve `sase sdd init` so it still refreshes the top-level generated `sdd/README.md` and diagram asset, and also
creates or refreshes brief `README.md` files in `sdd/tales/`, `sdd/epics/`, `sdd/legends/`, and `sdd/myths/`. After
implementation, run the command in this repository and commit the resulting code, tests, and generated SDD docs.

## Current Shape

- `sase sdd init` is registered in `src/sase/main/parser_sdd.py`, dispatched from `src/sase/main/sdd_handler.py`, and
  implemented in `src/sase/sdd/files.py` via `write_sdd_readme()`.
- `write_sdd_readme()` resolves a project root or SDD root, writes deterministic top-level README content, copies
  `assets/sdd-directory-map.png`, and returns the top-level README path.
- Existing focused tests live in `tests/main/test_sdd_handler.py` and `tests/test_sdd_paths.py`.
- Current SDD tooling treats `prompts`, `tales`, `epics`, `legends`, and `beads` as canonical operational directories.
  `myths` is not currently a plan kind, so this change should document and initialize the directory without broadening
  validation or plan-writing behavior unless directly necessary for init path resolution.

## Design

1. Add deterministic directory README content in `src/sase/sdd/files.py`.
   - Define concise, 1-3 sentence descriptions for `tales/`, `epics/`, `legends/`, and `myths/`.
   - Keep the text general enough for any SDD-using project.
   - Make each README clearly identify the directory with a Markdown heading.

2. Extend init writing without changing its public CLI shape.
   - Update `write_sdd_readme()` or a small helper it calls to create each tier directory and write `<tier>/README.md`.
   - Preserve idempotent behavior by overwriting stale generated tier README content with the canonical text on every
     run.
   - Keep returning the top-level README path so existing handler behavior and output remain stable.

3. Reconcile top-level docs with the new generated directory.
   - Update generated top-level README content to mention `myths/` as a broad, long-horizon narrative/strategy
     directory.
   - Avoid claiming that `myths` participates in existing prompt/plan frontmatter validation unless that behavior is
     actually implemented.
   - If `_looks_like_sdd_root()` needs to detect an existing SDD root that contains only `myths/`, include `myths` in
     the root-detection set. Do not add `myths` to `_SDD_PLAN_KINDS`, `sase sdd list --kind`, or link validation in this
     change.

4. Add focused tests.
   - Extend the init handler test to assert all four tier README files are created and contain brief expected
     descriptions.
   - Extend the idempotency test to cover stale tier README replacement.
   - Add or update path/root helper coverage only if `myths` is added to SDD root detection.

5. Run the command in this repo.
   - Use the locally installed command after implementation: `sase sdd init`.
   - Confirm `sdd/tales/README.md`, `sdd/epics/README.md`, `sdd/legends/README.md`, and `sdd/myths/README.md` exist.

6. Verify.
   - Run focused tests first: `pytest tests/main/test_sdd_handler.py tests/test_sdd_paths.py`.
   - Per repo instructions, run `just install` before final checks if the workspace environment may be stale.
   - Run `just check` before finishing.

7. Commit.
   - Use the `sase_git_commit` workflow only.
   - Inspect `git status` and `git diff`, include untracked generated README files, check for an in-progress bead, then
     commit with an appropriate conventional commit message.

## Non-Goals

- Do not change SDD approval flows, bead behavior, frontmatter link validation, or plan-kind writing semantics.
- Do not migrate existing artifacts into `myths/`.
- Do not remove existing `YYYYMM` organization or legacy compatibility notes.
