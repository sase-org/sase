---
create_time: 2026-06-19 13:34:19
status: done
prompt: sdd/prompts/202606/license_file_cleanup.md
---
# Plan: Add Official MIT License File and Packaging Metadata

## Goal

Implement the non-optional file changes recommended by `sdd/research/202606/sase_license_file_consolidated.md` so the
public repository, GitHub license detection, and Python package metadata all agree that SASE is MIT licensed.

This plan intentionally excludes the research note's optional CONTRIBUTING sentence, sibling-repository audits, and
per-file SPDX headers. The requested implementation is a focused cleanup for this repository's root license file,
packaging metadata, and README.

## Current State Verified

- The repository has no root `LICENSE`, `LICENSE.txt`, `LICENSE.md`, `COPYING`, or `NOTICE` file.
- `pyproject.toml` declares `license = "MIT"` and still carries the legacy `"License :: OSI Approved :: MIT License"`
  classifier.
- `pyproject.toml` does not declare `license-files`.
- `[build-system]` currently requires unpinned `"hatchling"`.
- `[tool.hatch.build.targets.sdist]` uses `only-include = ["src/sase"]`, so the implementation must verify that a root
  `LICENSE` actually lands in the sdist and adjust the sdist include list if Hatchling does not include it
  automatically.
- README has no License section; CONTRIBUTING has no contribution-license note, but the consolidated recommendation
  marks that note as optional.
- The only non-SDD copyright-like project signal found is `mkdocs.yml` using `Copyright &copy; 2026 SASE contributors`;
  `pyproject.toml` names Bryan Bugyi as author and maintainer, and the root git history starts on 2026-02-14 under
  Bryan's authorship. No tracked source-file SPDX or conflicting copyright header was found outside
  generated/site/research material.

## Implementation Plan

1. **Add the canonical MIT license text at the repository root.**
   - Create `LICENSE` with standard MIT License text.
   - Use `Copyright (c) 2026 Bryan Bugyi`, matching the research recommendation and package author metadata.
   - If a final narrow check uncovers older migrated `gai` ownership or a different explicit holder before editing, stop
     and ask for the correct copyright line rather than guessing.

2. **Update Python package metadata for PEP 639 clarity.**
   - In `[build-system]`, change the backend requirement to a conservative Hatchling pin such as `hatchling>=1.27`.
   - In `[project]`, keep `license = "MIT"` and add `license-files = ["LICENSE"]` near it.
   - Remove the legacy MIT license classifier from `classifiers`.
   - Do not update `uv.lock` unless `uv lock` or build tooling shows the project metadata change requires it; the
     current lock file does not appear to lock Hatchling because Hatchling is only a build backend dependency.

3. **Make sure source distributions include the root license file.**
   - First rely on `license-files = ["LICENSE"]` and build to inspect the produced artifacts.
   - If the sdist omits `LICENSE` because of the existing `only-include = ["src/sase"]`, add `LICENSE` to the sdist
     target include configuration in the narrowest Hatchling-compatible way, likely
     `only-include = ["src/sase", "LICENSE"]`.
   - Rebuild after any sdist include adjustment and keep the config comment accurate.

4. **Add a concise README license section.**
   - Add a short `## License` section near the end of README:
     `sase is licensed under the MIT License. See [LICENSE](LICENSE).`
   - Keep the wording minimal so the root `LICENSE` remains the authoritative legal text.

## Verification Plan

1. Run the package build path, preferably `just clean` followed by `just build` or the equivalent project build command.
2. Inspect the wheel and sdist contents to confirm `LICENSE` is present.
3. Inspect generated package metadata to confirm it includes `License-Expression: MIT` and `License-File: LICENSE`, and
   no longer depends on the deprecated license classifier for the license signal.
4. Run `git diff --check`.
5. Run the smallest relevant docs/package validation available after the build, likely `just build-check` if the build
   already succeeded and `twine` is installed through the repo dev environment. Full test suite execution is not needed
   because this is a packaging/docs-only change.

## Expected Changed Files

- `LICENSE`
- `pyproject.toml`
- `README.md`
- Potentially no other files. `uv.lock` should remain unchanged unless tooling requires regeneration.

## Risks and Mitigations

- **Wrong copyright holder/year:** mitigated by using the research recommendation and current repo metadata, with a
  stop-and-ask fallback if contradictory source evidence appears before editing.
- **License file missing from sdist:** mitigated by artifact inspection and a targeted sdist include adjustment.
- **Hatchling metadata behavior differs from expectation:** mitigated by pinning `hatchling>=1.27`, rebuilding in
  isolation, and inspecting final metadata rather than trusting configuration alone.
- **Scope creep into optional policy work:** avoid changing CONTRIBUTING, sibling repos, trademark language, or per-file
  SPDX headers in this pass.
