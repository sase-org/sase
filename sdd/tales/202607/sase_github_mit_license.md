---
create_time: 2026-07-06 06:48:21
status: done
prompt: sdd/prompts/202607/sase_github_mit_license.md
---
# Plan: MIT License for the sase-github Repo

## Request

Add an appropriate MIT license to the `sase-github` linked repo (github.com/sase-org/sase-github).

## Key Finding: The Repo Is Already Fully MIT-Licensed

Investigation shows there is **no missing license**. The MIT license already exists and is correctly wired through every
layer where it matters:

| Layer                       | Current state                                                                                                                                                                                                         |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LICENSE` file at repo root | Standard MIT text, `Copyright (c) 2026 Bryan Bugyi` — byte-identical in substance to the primary sase repo's `LICENSE`. Present since the repo's initial commit (`5372725 feat: Initial sase-github plugin package`). |
| `pyproject.toml`            | `license = "MIT"` (PEP 639 SPDX license expression).                                                                                                                                                                  |
| GitHub license detection    | The GitHub API reports `spdx_id: MIT` / "MIT License" for `sase-org/sase-github`.                                                                                                                                     |
| PyPI metadata (v0.1.6)      | `license_expression: MIT` is published.                                                                                                                                                                               |
| Built wheel (v0.1.6)        | Bundles `sase_github-0.1.6.dist-info/licenses/LICENSE`.                                                                                                                                                               |
| `README.md`                 | Has a `## License` section stating "MIT".                                                                                                                                                                             |

So the literal request ("add a license") is already satisfied and no action is strictly required.

## Proposed Work (Optional Hardening)

Two small `pyproject.toml` deltas exist relative to the primary sase repo's packaging conventions. Aligning them is the
only meaningful work available here, and it is metadata-only (no runtime behavior change):

1. **Add `license-files = ["LICENSE"]` to `[project]`.** Today the LICENSE lands in the wheel only via hatchling's PEP
   639 _default_ license-file globs (`LICEN[CS]E*`, etc.). The primary sase repo declares `license-files = ["LICENSE"]`
   explicitly; matching that makes the intent explicit rather than default-dependent.

2. **Pin `requires = ["hatchling>=1.27"]` in `[build-system]`.** The bare SPDX string form `license = "MIT"` requires
   PEP 639 support, which hatchling added in 1.27. The build currently works only because the unpinned requirement
   resolves to a recent hatchling; the primary sase repo already pins `hatchling>=1.27`. Pinning makes the implicit
   constraint explicit and protects fresh builds in constrained environments.

**Recommendation:** apply both tweaks. They are a one-file, ~2-line change. Rejecting this plan and doing nothing is
also a perfectly sound outcome — the license itself is complete either way.

## Implementation Notes

- All changes are in the `sase-github` linked repo; nothing in the primary sase repo changes. Access the repo checkout
  with `sase workspace open -p sase-github -r "<reason>" <workspace_num>` (using the workspace number of your primary
  sase checkout).
  - Note: during planning, that command failed with
    `Project 'sase-github' has no WORKSPACE_DIR in ~/.sase/projects/sase-github/sase-github.sase` (the linked-repo name
    does not resolve to a registered project). If you hit the same error, the pre-allocated per-run checkout path in the
    `SASE_LINKED_REPO_SASE_GITHUB_DIR` environment variable is the same path `workspace open` would print — use that.
    (This resolution failure may itself be worth a bug bead in the primary repo.)
  - The linked-repo checkout may be behind `origin/master`; fast-forward it before editing.

### Steps

1. In the sase-github checkout, edit `pyproject.toml`:
   - `[build-system]`: `requires = ["hatchling"]` → `requires = ["hatchling>=1.27"]`
   - `[project]`: add `license-files = ["LICENSE"]` directly under `license = "MIT"`.
2. Verify with sase-github's own checks: `just check` (runs ruff, mypy, pytest via its Justfile).
3. Optionally confirm packaging is unchanged: `just build`, then `unzip -l dist/*.whl | grep -i license` should still
   show `dist-info/licenses/LICENSE`.
4. Commit in the sase-github repo via the standard sase commit flow (conventional-commit style, e.g.
   `chore: make license packaging metadata explicit`). Release-please will fold it into the next release PR; no version
   bump is needed for this.

## Out of Scope

- No changes to the `LICENSE` file itself (already correct, correct year and copyright holder).
- No README/docs changes (License section already present).
- No changes to other sase-org repos.

## Verification

- `just check` passes in sase-github.
- After the next release publishes, PyPI metadata still shows `license_expression: MIT` and the wheel still bundles the
  LICENSE (this is a regression check only; the tweaks cannot remove it).
