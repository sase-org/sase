---
create_time: 2026-07-06 07:04:25
status: done
prompt: sdd/prompts/202607/sase_telegram_mit_license.md
---
# Plan: MIT License for the sase-telegram Repo

## Request

Add an appropriate MIT license to the `sase-telegram` linked repo (github.com/sase-org/sase-telegram), mirroring the
recently-completed `sase_github_mit_license` work.

## Key Finding: Unlike sase-github, the LICENSE File Is Actually Missing

The sase-github investigation found the license already fully wired; sase-telegram is the opposite case. The repo
_declares_ MIT everywhere but ships **no license text at all**:

| Layer                       | Current state                                                                                                    |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `LICENSE` file at repo root | **Missing.** No `LICENSE`/`COPYING`/etc. anywhere in the repo, at current `origin/master` (v0.2.2).              |
| `pyproject.toml`            | `license = "MIT"` (PEP 639 SPDX expression) — but no `license-files`, and nothing for the default globs to find. |
| GitHub license detection    | The GitHub API reports `license: null` for the public `sase-org/sase-telegram` repo.                             |
| PyPI metadata (v0.2.2)      | `license_expression: MIT` is published.                                                                          |
| Published wheel (v0.2.2)    | **No license file bundled** — dist-info contains only METADATA/WHEEL/entry_points.txt/RECORD.                    |
| `README.md`                 | Has a `## License` section stating "MIT".                                                                        |

This is a real compliance gap, not just cosmetics: the MIT license requires the copyright/permission notice to be
included with copies of the software, but the wheels published to PyPI carry only the bare `MIT` SPDX string with no
license text. GitHub also cannot detect a license, so the repo page shows none.

## Proposed Work

One new file plus the same two `pyproject.toml` tweaks already applied to sase-github:

1. **Add a `LICENSE` file at the repo root.** Standard MIT text with `Copyright (c) 2026 Bryan Bugyi` — byte-identical
   to the primary sase repo's `LICENSE` (the repo's first commit is 2026-02-28, so the 2026 year is correct). Standard
   verbatim MIT text at the root is also what GitHub's licensee needs to start reporting `spdx_id: MIT`.

2. **Add `license-files = ["LICENSE"]` to `[project]`** in `pyproject.toml`, directly under `license = "MIT"`. This
   makes the wheel bundle the license explicitly rather than relying on hatchling's default PEP 639 globs, matching the
   primary sase repo and sase-github.

3. **Pin `requires = ["hatchling>=1.27"]` in `[build-system]`.** The bare SPDX string form `license = "MIT"` (and
   `license-files`) requires PEP 639 support, added in hatchling 1.27. Currently unpinned; sase and sase-github both pin
   `>=1.27`.

## Implementation Notes

- All changes are in the `sase-telegram` linked repo; nothing in the primary sase repo changes. Access the checkout with
  `sase workspace open -p sase-telegram -r "<reason>" <workspace_num>` (using the workspace number of your primary sase
  checkout).
  - Note: during planning, that command failed with
    `Project 'sase-telegram' has no WORKSPACE_DIR in ~/.sase/projects/sase-telegram/sase-telegram.sase` — the same
    registration gap already seen with sase-github. If you hit it, use the pre-allocated per-run checkout path in the
    `SASE_LINKED_REPO_SASE_TELEGRAM_DIR` environment variable; it is the same path `workspace open` would print.
  - The linked checkout may be behind `origin/master`; fast-forward it before editing (during planning it was 8 commits
    behind).

### Steps

1. In the sase-telegram checkout, create `LICENSE` at the repo root by copying the primary sase repo's `LICENSE`
   verbatim (MIT text, `Copyright (c) 2026 Bryan Bugyi`).
2. Edit `pyproject.toml`:
   - `[build-system]`: `requires = ["hatchling"]` → `requires = ["hatchling>=1.27"]`
   - `[project]`: add `license-files = ["LICENSE"]` directly under `license = "MIT"`.
3. Verify with the repo's own checks: `just check` (ruff, mypy, pytest via its Justfile).
4. Confirm packaging now includes the license: `just build`, then `unzip -l dist/*.whl | grep -i license` should show
   `sase_telegram-<ver>.dist-info/licenses/LICENSE`.
   - Caveat from the sase-github run: the `build` module is not part of this repo's dev deps, so `just build` will fail
     out of the box. Either `uv pip install build` into the repo's local `.venv` first (tool-only, no repo file
     changes), or verify with `uv build` instead, which is what the publish workflow itself uses.
5. Commit in the sase-telegram repo via the standard sase commit flow. **Use a `fix:` type** (e.g.
   `fix: add MIT LICENSE file and bundle it in wheels`): the published wheels currently omit legally required license
   text, so this should trigger release-please to cut a patch release (0.2.2 → 0.2.3) whose artifacts actually ship the
   LICENSE, rather than waiting for an unrelated release-triggering commit. (If a release is deemed unnecessary, a
   `build:`/`chore:` type folds the change into whatever release comes next — but `fix:` is the recommendation.)

## Out of Scope

- No README/docs changes (the `## License` section already exists and is accurate once the file lands).
- No changes to the publish workflow (`uv build` picks up the new metadata automatically).
- No changes to other sase-org repos.

## Verification

- `just check` passes in sase-telegram.
- A locally built wheel bundles `sase_telegram-<ver>.dist-info/licenses/LICENSE`.
- After the release-please PR for the next release merges and publishes: the GitHub API reports `spdx_id: MIT` for the
  repo (detection may lag a few minutes after push), and the new PyPI wheel bundles the LICENSE alongside
  `license_expression: MIT`.
