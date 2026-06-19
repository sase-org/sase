# SASE License File Options and Best Practices

Date: 2026-06-19

This note reviews what it would mean for the SASE repository to have an "official" license file before public blog
promotion. It is research, not legal advice.

## Current repo state

- There is no tracked root `LICENSE`, `LICENSE.txt`, `COPYING`, or `NOTICE` file.
- `pyproject.toml` declares `license = "MIT"` and includes the legacy PyPI classifier
  `License :: OSI Approved :: MIT License`.
- `package.json` is marked `private: true` and does not publish a license signal.
- A quick tracked-file scan did not find vendored source directories, third-party license folders, existing SPDX headers,
  or copyright notices in `src`, `tests`, `docs`, `README.md`, or `pyproject.toml`.
- Git history shows the repository was initialized on 2026-02-14, with SASE project scaffolding and the `pyproject.toml`
  metadata appearing on 2026-02-15. The migration history mentions prior `gai` source, so the copyright year/holder line
  should account for the original ownership of that migrated code if it predates the SASE rename.

## What makes the repo license clear

GitHub's licensing docs are direct about the baseline: without an explicit license, default copyright rules apply and
others do not receive the normal open source rights to reproduce, distribute, or create derivative works. GitHub also
recommends putting the license text in a root file such as `LICENSE.txt`, `LICENSE.md`, or `LICENSE.rst`, and says a
license file should be included as a best practice. GitHub's license detection uses Licensee to compare repository
license files against known licenses; if the file has extra complexity, GitHub recommends simplifying the license file
and putting explanation elsewhere, such as the README.

For Python packages, current PyPA guidance follows PEP 639: use `license` as an SPDX license expression and
`license-files` as glob patterns for files containing the license text or other legal information. PyPA's licensing
examples say to paste the chosen license text into a root `LICENSE`/`COPYING` style file, set `license = "LICENSE-ID"`,
and list the license file under `license-files`. PEP 639 adds standardized `License-Expression` and `License-File`
metadata so sdists, wheels, and installed packages can carry both the machine-readable expression and the full text.

For SASE, that means `pyproject.toml` already has the likely SPDX expression, `MIT`, but the repository is missing the
root file that humans, GitHub, PyPI packaging metadata, downstream scanners, and source archives expect.

## Practical options

### 1. No license file

This is the worst option for a public launch. It leaves GitHub's repository view ambiguous, contradicts the package's
MIT metadata, and makes the repo look unfinished even if built artifacts claim MIT.

### 2. MIT

MIT matches the current `pyproject.toml` declaration. It is OSI-approved, has the SPDX short identifier `MIT`, and is a
short permissive license. ChooseALicense summarizes MIT as allowing commercial use, distribution, modification, and
private use, with the main condition that copyright and license notices be preserved.

This is the lowest-friction choice for a developer tool that wants adoption, package-manager comfort, and easy
commercial evaluation. The tradeoff is that MIT does not contain the explicit patent grant found in Apache-2.0, and it
does not require downstream forks to publish modifications.

### 3. Apache-2.0

Apache-2.0 is another permissive license. Its main advantage over MIT is an express patent license and patent
termination language. The Apache Software Foundation's own license page identifies `Apache-2.0` as the SPDX short
identifier and says to include a copy of the license, typically in a file called `LICENSE`, while optionally adding a
`NOTICE` file.

Apache-2.0 is a good option if patent posture matters or if SASE expects larger corporate contributions. The costs are
slightly more legal text, change-notice obligations, possible `NOTICE` handling, and a repo/package metadata change away
from today's MIT declaration.

### 4. Dual MIT OR Apache-2.0

Dual licensing as `MIT OR Apache-2.0` gives downstream users a choice. This is common in parts of the Rust ecosystem and
can be useful for projects with Rust crates or mixed-language components where consumers expect either license.

For SASE, this is viable but probably more complexity than needed right now. It would require two license files, updated
metadata, and a README sentence explaining the choice. If there are existing releases that already advertise MIT, this is
still permissive, but the project should intentionally document the change.

### 5. MPL-2.0

MPL-2.0 is a file-level weak copyleft license with an express patent grant. ChooseALicense summarizes it as requiring
source disclosure and same-license treatment for licensed files and modifications of those files, while allowing larger
works to use different terms.

This is useful if the goal is to keep modifications to SASE's own files open while allowing integration into larger
systems. It is not aligned with the current MIT metadata and will create more friction for some commercial users.

### 6. GPLv3 or AGPLv3

GPLv3 is strong copyleft: distributed modified versions and larger works using the licensed work must provide complete
source code under the same license. AGPLv3 extends this posture to modified network services. These licenses make sense
when preserving software freedom is more important than frictionless embedding into proprietary tools.

For SASE's current blog-launch goal, they are probably not the right fit. They would be a strategic licensing pivot, not
a cleanup of the existing license file.

### 7. Custom or proprietary license

Custom terms can be represented in Python metadata with `LicenseRef-*` identifiers, but they are harder for users,
companies, GitHub, package scanners, and distributions to evaluate. A custom license would also be inconsistent with the
current "open source developer tool on PyPI" posture.

## Best practices for the file and metadata

- Use the unmodified standard license text from SPDX, OSI, or the license steward. For MIT, the SPDX page identifies the
  full name as "MIT License" and short identifier as `MIT`; the OSI page identifies MIT as OSI approved.
- Put the license text in a root `LICENSE` file. `LICENSE.txt` is also fine, but `LICENSE` is the most common and clean.
- Do not add project-specific explanation inside `LICENSE`; keep that file simple for GitHub Licensee and compliance
  tooling. Put explanatory text in `README.md` if needed.
- Use one copyright line that reflects ownership accurately. If Bryan owns all code and it was first published in 2026,
  `Copyright (c) 2026 Bryan Bugyi` is the clean MIT line. If the migrated `gai` code was first published earlier, use the
  earlier first-publication year or a year range. If there are material outside contributors, do not imply an assignment
  that did not happen; use a contributors notice or separate contributor process deliberately.
- Add `[project] license-files = ["LICENSE"]` to `pyproject.toml`.
- Consider updating `[build-system] requires` to `["hatchling >= 1.27.0"]`, because current PyPA guidance lists
  Hatchling 1.27.0 as the version that introduced support for the current PEP 639 `license` and `license-files` format.
- Consider removing `License :: ...` classifiers once `license` and `license-files` are in place, because PyPA's current
  licensing examples recommend removing legacy `License ::` classifiers in favor of SPDX license expressions.
- After editing, build both sdist and wheel and inspect them. Confirm the root license file is included and the wheel
  metadata contains `License-Expression: MIT` and `License-File: LICENSE`. This matters because SASE's sdist config
  currently uses `only-include = ["src/sase"]`, so the release artifact should be verified rather than assumed.
- SPDX source headers are optional for this immediate cleanup. If adopted later, use a single comment line such as
  `# SPDX-License-Identifier: MIT` in new files and migrate existing files gradually. SPDX notes that per-file identifiers
  are machine-readable and help files carry license information when reused outside the repo.

## Sources

- [GitHub Docs: Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [Python Packaging User Guide: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Python Packaging User Guide: Licensing examples and user scenarios](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)
- [Python Packaging User Guide: License Expression specification](https://packaging.python.org/en/latest/specifications/license-expression/)
- [PEP 639: Improving License Clarity with Better Package Metadata](https://peps.python.org/pep-0639/)
- [SPDX License List](https://spdx.org/licenses/)
- [SPDX MIT License page](https://spdx.org/licenses/MIT.html)
- [SPDX: Handling License Info](https://spdx.dev/learn/handling-license-info/)
- [Open Source Initiative: Approved Licenses](https://opensource.org/licenses)
- [Open Source Initiative: MIT License](https://opensource.org/license/mit)
- [ChooseALicense: MIT](https://choosealicense.com/licenses/mit/)
- [ChooseALicense: Apache-2.0](https://choosealicense.com/licenses/apache-2.0/)
- [ChooseALicense: GPL-3.0](https://choosealicense.com/licenses/gpl-3.0/)
- [ChooseALicense: AGPL-3.0](https://choosealicense.com/licenses/agpl-3.0/)
- [ChooseALicense: MPL-2.0](https://choosealicense.com/licenses/mpl-2.0/)
- [Apache Software Foundation: Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.en.html)
- [Mozilla Public License 2.0](https://www.mozilla.org/en-US/MPL/2.0/)

## Recommended solution

Keep SASE on MIT for the blog launch. Add a root `LICENSE` file containing the standard MIT text, with the copyright line
`Copyright (c) 2026 Bryan Bugyi` unless the migrated `gai` source requires an earlier year or additional holder notice.
Then update `pyproject.toml` to keep `license = "MIT"`, add `license-files = ["LICENSE"]`, pin the build backend as
`hatchling >= 1.27.0`, and remove the legacy MIT license classifier in the same packaging cleanup. Before announcing the
repo publicly, build the sdist and wheel and confirm the `LICENSE`, `License-Expression: MIT`, and
`License-File: LICENSE` signals are present.
