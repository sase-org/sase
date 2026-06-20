---
create_time: 2026-06-19 23:47:44
status: done
prompt: sdd/prompts/202606/pyscripts_skip_nested_repos.md
---
# Plan: Stop `pyscripts` linter from descending into nested sibling-repo checkouts

## Problem / CI symptom

The sase repo's GitHub Actions `lint` job fails with:

```
---------- Validating scripts/tools directory structure... ----------
.venv/bin/python tools/pyscripts-260314
[Rule 1] Unused: sase-core/.github/scripts/check_cargo_version_edits.py is not referenced in sase-core/.github/
error: Recipe `_lint-pyscripts` failed on line 138 with exit code 1
error: Recipe `lint` failed on line 122 with exit code 1
```

## Root cause (diagnosed)

- The CI `lint` job (`.github/workflows/ci.yml`) checks out the sibling `sase-org/sase-core` repo into a **nested
  subdirectory** `./sase-core/` (`path: sase-core`). This is required so `just install` can build the `sase_core_rs`
  binding that `mypy`/`pyvision` later import.
- `just lint` → `_lint-pyscripts` (Justfile line 137-138) runs `tools/pyscripts-260314` with the default directory `.`
  (the repo root, which in CI now contains the nested `sase-core/` checkout).
- `pyscripts` recursively walks the **entire** working tree (`_find_target_dirs`) and discovers
  `sase-core/.github/scripts/`, treating its files as scripts that belong to the sase repo.
- For **Rule 1** ("every script must be referenced within its parent dir"), it runs `git grep` against the **sase
  repo's** git index for `check_cargo_version_edits.py` under `sase-core/.github`. But `sase-core/` is a separate,
  untracked nested checkout — the sase repo's index has zero entries there — so `git grep` returns nothing → a
  false-positive "Unused" violation.
- This is **brand new** because `check_cargo_version_edits.py` (added in sase-core commit
  `081c6da "ci: guard cargo release versions"`) is the **first** file ever placed under `sase-core/.github/scripts/`.
  Within sase-core's own repo it is correctly referenced by `.github/workflows/pr-title.yml`, so sase-core's own CI is
  unaffected. Only the sase repo's linter — which cannot see sase-core's git refs — trips.
- It is **CI-only**: locally `sase-core` is a _sibling_ directory, never nested inside the sase workspace, so the walk
  never reaches it. Confirmed: `tools/pyscripts-260314 .` exits 0 locally.

**Underlying defect:** `pyscripts` is a per-repository linter, but it descends into nested _foreign_ git repositories
(sibling checkouts / submodules) and validates their scripts against the host repo's git index. Any sibling repo that
ever gains a `scripts/`, `tools/`, or `.github/scripts/` directory and is checked out nested in CI will break the host
repo's lint the same way.

## Fix strategy (recommended)

Teach `pyscripts` to **skip nested git repositories** during its walk — it should only validate the repository it was
invoked on, not foreign checkouts that happen to live inside the tree.

`tools/pyscripts-260314` is **vendored** from the chezmoi dotfiles repo
(`~/.local/share/chezmoi/home/bin/executable_pyscripts`). Per `tools/AGENTS.md`, vendored `-YYmmdd` files must **not**
be edited in place; the change is made at the source and re-vendored. The vendored copy is byte-identical to the chezmoi
source apart from the 2-line provenance header.

### Step 1 — Edit the chezmoi source

File: `~/.local/share/chezmoi/home/bin/executable_pyscripts`

In `_find_target_dirs(root)`, after the existing `_EXCLUDE_DIRS` prune of `dirnames`, additionally prune any child
directory that is itself a git repo root — i.e. where `(<dirpath>/<child>/.git)` exists (covers both a `.git` directory
and a `.git` file used by worktrees/submodules). This stops the walk from descending into nested checkouts like
`sase-core/`.

Notes on correctness:

- The walk starts at `root` (the repo being linted); `root` is only ever a `dirpath`, never inspected as a prunable
  child, so the host repo is never pruned by its own `.git`.
- Pruning at discovery is sufficient: target dirs under a nested repo are never added to `target_dirs`, so no later rule
  (1/2/3) processes them.
- Add a one-line note to the module docstring documenting that nested git repositories are skipped.

### Step 2 — Apply and commit the dotfiles change

- `chezmoi apply` to materialize the change into `~/bin/pyscripts`.
- Commit in the chezmoi/dotfiles repo using the **commit skill** (`sase_git_commit`), **not** `git commit`.

### Step 3 — Re-vendor into the sase repo

- Run `pyvendor` to re-vendor the updated script into this repo's `tools/` directory. `pyvendor` will:
  - write a fresh date-stamped copy (`tools/pyscripts-260619`),
  - remove the stale `tools/pyscripts-260314`,
  - rewrite references to the old name (e.g. the `Justfile` `_lint-pyscripts` recipe) to the new name,
  - refresh the provenance header date.
- Sanity-check that the only diff vs. the old vendored file is the new traversal logic + header date, and that the
  `Justfile` reference was updated.

### Step 4 — Verify

- **Targeted reproduction** of the bug pre/post fix: build a temporary tree that mirrors the CI layout — an outer git
  repo whose tree contains a nested git repo with a `.github/scripts/<file>.py` that is referenced only inside the
  nested repo. Confirm the old logic reports a Rule 1 violation and the patched logic reports none (the nested repo is
  skipped).
- **No regression on the real tree**: run `just install` then `just check` in the sase repo; pyscripts must still
  validate the sase repo's own `tools/` and any `scripts/` dirs and pass.
- Optionally, simulate CI by cloning sase-core into `./sase-core` within a throwaway copy of the workspace and
  confirming the patched linter no longer flags `sase-core/.github/scripts/check_cargo_version_edits.py`.

## Scope / files touched

- `~/.local/share/chezmoi/home/bin/executable_pyscripts` (source of fix) — committed in the dotfiles repo via the commit
  skill.
- `tools/pyscripts-260314` → `tools/pyscripts-260619` (re-vendored) and the `Justfile` reference update — in the sase
  repo.

## Out of scope / considered-and-rejected alternatives

- **Editing `tools/pyscripts-260314` directly** — prohibited by `tools/AGENTS.md`; would be overwritten on the next
  vendor.
- **Removing the `sase-core` checkout from the lint job** — rejected: `just lint` runs `mypy`/`pyvision`, which import
  the compiled `sase_core_rs` binding built from the nested sase-core during `just install`.
- **Splitting `_lint-pyscripts` into a CI step that runs before the sase-core checkout** — rejected: a CI-config-only
  band-aid that leaves the underlying tool bug in place and doesn't help any other repo.
- **Hardcoding `sase-core` into `_EXCLUDE_DIRS`** — rejected: brittle and name-specific; the nested-git-repo skip is the
  general, correct fix.
- **Adding a unit test in the dotfiles repo** — the dotfiles `tests/` directory currently only covers `bash`/`nvim`;
  there is no Python test harness for `bin/` scripts and `pyscripts` has no existing coverage. Adding one is out of
  scope; verification is done via the targeted reproduction in Step 4.

## Risk

Low. The change is additive pruning during directory discovery. Nested foreign repos are exactly what should not be
linted as part of the host repo, and the host repo root is never pruned. Local `just check` and the targeted
reproduction gate the change before it lands.
