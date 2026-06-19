# SASE License File Options and Recommendation

Date: 2026-06-19

This note consolidates the two license-file research passes for the `sase-org/sase` repository. It is practical
engineering research, not legal advice.

## Current State

- The repo has no tracked root `LICENSE`, `LICENSE.txt`, `LICENSE.md`, `COPYING`, or `NOTICE` file.
- `pyproject.toml` already declares `license = "MIT"`, so the intended project license appears to be MIT.
- `pyproject.toml` also still includes the legacy classifier
  `"License :: OSI Approved :: MIT License"`.
- `pyproject.toml` does not declare `license-files`, so built distributions are not explicitly tied to a license text
  file.
- `package.json` is private and does not publish a license signal.
- README and CONTRIBUTING do not currently explain the license or contribution licensing terms.
- A tracked-file scan did not find vendored third-party source, third-party license directories, per-file SPDX headers,
  or existing root copyright notices that would complicate a simple MIT cleanup.
- Git history shows repo initialization on 2026-02-14 and SASE scaffolding plus `gai` to `sase` migration commits on
  2026-02-15. If migrated `gai` code was first published earlier or has a different holder, the copyright line should
  reflect that original ownership/publication history.

## What "Official" Means Here

For a public GitHub/PyPI launch, "official" mostly means three things agree:

1. The repo contains the full license grant in a conventional root file.
2. GitHub can detect the license from that file.
3. Python package metadata points to the same license and includes the license file in sdists/wheels.

GitHub's licensing docs say that without a license, default copyright rules apply and others do not receive normal open
source rights to reproduce, distribute, or create derivative works. GitHub recommends including a license file in the
repository root, and its license detection compares repository license files against known licenses. If the file has
extra complexity, GitHub recommends keeping the license file simple and putting explanation elsewhere, such as README.

For Python packaging, current PyPA guidance follows PEP 639: use `license` as an SPDX license expression and
`license-files` as glob patterns for files containing license text or legal notices. The resulting metadata should expose
`License-Expression: MIT` and `License-File: LICENSE`. PEP 639 also deprecates license classifiers in favor of SPDX
expressions, so SASE should not keep the old MIT classifier once the modern fields are in place.

## License Options

### No License File

This is the worst launch option. It conflicts with the existing MIT metadata, prevents GitHub from showing a detected
license, and makes the repo look unfinished to users and automated review tools.

### MIT

MIT matches the current `pyproject.toml` declaration. It is short, OSI-approved, widely recognized, and permissive:
commercial use, distribution, modification, and private use are allowed, with the main condition that copyright and
license notices are preserved.

This is the lowest-friction choice for a developer tool that wants adoption and easy commercial evaluation. The tradeoff
is that MIT does not include Apache-2.0's explicit patent grant or any requirement for downstream forks to publish their
changes.

### Apache-2.0

Apache-2.0 is also permissive, but adds an express patent license and patent termination language. The Apache Software
Foundation recommends including the license, typically in `LICENSE`, and optionally a `NOTICE` file.

This is the best alternative if patent posture or larger corporate contribution matters. The costs are more legal text,
more notice/change obligations, and a deliberate metadata change away from the repo's current MIT declaration.

### MIT OR Apache-2.0

Dual licensing as `MIT OR Apache-2.0` lets downstream users choose either license. This is common in parts of the Rust
ecosystem and could fit a mixed Python/Rust project, but it adds complexity: two license files, a more detailed SPDX
expression, and README explanation. It is viable, but probably unnecessary for SASE's immediate launch.

### MPL-2.0

MPL-2.0 is weak copyleft at the file level. It can keep modifications to SASE's own files open while allowing use in
larger proprietary works. It also includes patent language. The cost is more friction and a mismatch with the current MIT
metadata.

### GPLv3 or AGPLv3

GPLv3 and AGPLv3 are strong copyleft choices. They make sense when ensuring derivative software remains open is more
important than broad adoption. AGPLv3 also reaches modified network-service use. For SASE's launch goal, these would be a
strategic licensing pivot, not a license-file cleanup, and they would deter some companies from adopting or contributing.

### Custom or Source-Available Terms

Custom terms can be represented in Python metadata with `LicenseRef-*`, but they are harder for GitHub, PyPI users,
companies, distributions, and scanners to evaluate. Source-available licenses are not OSI open source. This would be the
wrong direction for an alpha developer tool seeking community trust unless there is a specific commercial strategy behind
it.

## Best Practices

- Use unmodified standard license text from a canonical source such as SPDX, OSI, the license steward, or GitHub's
  license picker. For MIT, the SPDX identifier is `MIT`.
- Put the text in a root `LICENSE` file. `LICENSE.txt` or `LICENSE.md` also work, but plain `LICENSE` is conventional.
- Keep project-specific explanation out of `LICENSE`; put it in README or CONTRIBUTING so GitHub's license detection has
  a clean file to match.
- Use an accurate copyright line. If Bryan owns the code and first publication was 2026, use
  `Copyright (c) 2026 Bryan Bugyi`. If the migrated `gai` source predates this repo, use the correct earlier year or
  holder notice.
- In `[project]`, keep `license = "MIT"` and add `license-files = ["LICENSE"]`.
- Remove the legacy `"License :: OSI Approved :: MIT License"` classifier once the SPDX expression is present.
- Pin the build backend conservatively as `hatchling >= 1.27`. Hatchling 1.26 added core metadata 2.4 and the current
  `license-files` shape; 1.27 made core metadata 2.4 the default.
- Build both sdist and wheel after the change. Confirm the artifacts include the license file and metadata contains
  `License-Expression: MIT` and `License-File: LICENSE`. This is especially worth checking because this repo has an
  explicit sdist `only-include = ["src/sase"]` rule.
- Add a short README section, for example: `sase is licensed under the MIT License. See LICENSE.`
- State contribution licensing in CONTRIBUTING before the launch if external contributions are expected. The lightweight
  default is "inbound = outbound": contributions are accepted under the project license. A DCO is optional; a CLA is
  heavier than this project likely needs right now.
- Verify sibling repos separately. `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim` each need their own root
  license file if they are public projects.
- Source-file SPDX headers are optional for this cleanup. A root `LICENSE` is enough; add
  `# SPDX-License-Identifier: MIT` later only if per-file reuse clarity becomes useful.
- Remember that copyright licenses do not solve trademark/brand questions. Protecting the `sase` name or `sase.sh` brand
  is a separate decision.

## Sources

- [GitHub Docs: Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [GitHub Docs: Adding a license to a repository](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-license-to-a-repository)
- [Python Packaging User Guide: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Python Packaging User Guide: Licensing examples and user scenarios](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)
- [Python Packaging User Guide: License expression specification](https://packaging.python.org/en/latest/specifications/license-expression/)
- [PEP 639: Improving License Clarity with Better Package Metadata](https://peps.python.org/pep-0639/)
- [Hatchling history](https://hatch.pypa.io/dev/history/hatchling/)
- [SPDX MIT License page](https://spdx.org/licenses/MIT.html)
- [Open Source Initiative: MIT License](https://opensource.org/license/mit)
- [ChooseALicense: MIT](https://choosealicense.com/licenses/mit/)
- [ChooseALicense: MPL-2.0](https://choosealicense.com/licenses/mpl-2.0/)
- [Apache Software Foundation: Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## Recommended Solution

Keep SASE on MIT for the blog launch. It is already the declared license, it is the lowest-friction choice for adoption,
and the current tree does not show vendored code or conflicting license signals that require a more complex answer.

Implement the cleanup as one small packaging/docs change:

1. Add a root `LICENSE` file with canonical MIT text and `Copyright (c) 2026 Bryan Bugyi`, unless the migrated `gai`
   source requires an earlier year or additional holder notice.
2. Update `pyproject.toml`: keep `license = "MIT"`, add `license-files = ["LICENSE"]`, change the build requirement to
   `hatchling >= 1.27`, and remove the legacy MIT license classifier.
3. Add a short README License section linking to `LICENSE`.
4. Optionally add one CONTRIBUTING sentence that contributions are accepted under the MIT license.
5. Build the sdist and wheel and inspect them for `LICENSE`, `License-Expression: MIT`, and `License-File: LICENSE`
   before publishing the launch post.

Only choose Apache-2.0 instead if you specifically want an explicit patent grant before external contributors arrive.
Otherwise, MIT plus the root license file and PEP 639 metadata is the recommended solution.
