---
create_time: 2026-06-13 08:18:47
status: wip
---
# Plan: PyPI Version Badges

## Goal

Add a PyPI version badge to the top-level README in each of these repositories:

- `sase`
- `sase-core`
- `sase-github`
- `sase-telegram`

Each badge should display the latest version currently published to PyPI for that repo's corresponding Python
distribution and should update automatically when future releases are published.

## Current Findings

- `sase` is a Python package named `sase`, released with release-please via `.github/workflows/publish.yml`.
- `sase-github` is a Python package named `sase-github`, released with release-please via
  `.github/workflows/publish.yml`.
- `sase-telegram` is a Python package named `sase-telegram`, released with release-please via
  `.github/workflows/publish.yml`.
- `sase-core` is a Rust workspace released with release-plz, but its PyPI distribution is `sase-core-rs`, built from
  `crates/sase_core_py/` and published by `.github/workflows/release-plz.yml`.
- Current PyPI versions verified from PyPI are:
  - `sase`: `0.1.7`
  - `sase-core-rs`: `0.1.2`
  - `sase-github`: `0.1.1`
  - `sase-telegram`: `0.1.0`

## Technical Approach

Use Shields.io dynamic PyPI version badges instead of checking version numbers into README text:

```markdown
[![PyPI](https://img.shields.io/pypi/v/<distribution>?logo=pypi&logoColor=white)](https://pypi.org/project/<distribution>/)
```

This is the right automation boundary because the badge is rendered from PyPI metadata at request time. Once
release-please or release-plz publishes a new version to PyPI, Shields.io will show the new published version without a
separate README update PR.

Distribution mapping:

| Repository      | PyPI distribution |
| --------------- | ----------------- |
| `sase`          | `sase`            |
| `sase-core`     | `sase-core-rs`    |
| `sase-github`   | `sase-github`     |
| `sase-telegram` | `sase-telegram`   |

## Implementation Steps

1. Add one PyPI badge to each root `README.md` badge block.
   - For `sase`, place it after the Docs badge and before tool/test badges.
   - For `sase-github` and `sase-telegram`, place it before the Ruff badge.
   - For `sase-core`, add a new badge block immediately under the `# sase-core` heading.

2. Do not add release-please, release-plz, or custom workflow changes.
   - The existing workflows already publish the packages to PyPI.
   - The badge URL itself is the automatic update mechanism.
   - Static version replacement by release tooling would be worse here because it could show a version before PyPI
     publication succeeds; the dynamic badge reflects the artifact that actually reached PyPI.

3. Validate the badge image and target URLs.
   - Check all four PyPI project URLs exist.
   - Check the Shields badge URLs return valid SVG responses.
   - Re-read README tops to confirm placement and formatting.

4. Run repo-appropriate verification.
   - In `sase`, follow the repo instruction to run `just install` before `just check` because `README.md` changes are
     not covered by the documented exceptions.
   - For the sibling repos, run lightweight README/link validation where available; if no markdown-specific check
     exists, record that the change is documentation-only and that the dynamic badge URLs were validated directly.

## Expected Files Changed

- `README.md` in the `sase` workspace.
- `README.md` in the `sase-core` workspace.
- `README.md` in the `sase-github` workspace.
- `README.md` in the `sase-telegram` workspace.

## Risks and Mitigations

- **Wrong package name for `sase-core`:** Use `sase-core-rs`, confirmed by `crates/sase_core_py/pyproject.toml` and the
  release workflow's PyPI guard.
- **Badge shows repository version instead of published PyPI version:** Use Shields' `/pypi/v/` endpoint, not static
  text or GitHub release metadata.
- **Badge cache delay after release:** Shields.io may cache briefly, but it will converge automatically from PyPI
  without a repo commit.
- **Release succeeds in GitHub but PyPI publish fails:** The badge continues to show the last successfully published
  PyPI version, matching the user-visible installable package state.
