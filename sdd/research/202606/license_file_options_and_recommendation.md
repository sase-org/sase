# Making the sase License "Official": Options, Best Practices, and Recommendation

**Date:** 2026-06-19
**Author:** Research conducted for Bryan Bugyi ahead of the sase launch blog post
**Scope:** The `sase-org/sase` repository's licensing — what file(s) should exist, which license to
pick, and how to make the declaration consistent and authoritative before a public launch.

---

## 1. Executive Summary

**You already chose a license — MIT — but you never shipped the file that makes it legally and
mechanically real.** `pyproject.toml` declares `license = "MIT"`, but there is **no `LICENSE` file in
the repo root**. That gap matters more than the license choice itself:

- GitHub will not display a license badge or "MIT License" in the repo sidebar without the file.
- Several tools (GitHub's `licensee`, FOSSA-style scanners, corporate OSS-review gates) treat a repo
  with *no* license file as **"all rights reserved"** regardless of what `pyproject.toml` says — the
  metadata is not the grant.
- Your `pyproject.toml` currently carries **both** a PEP 639 license expression (`license = "MIT"`)
  **and** the deprecated `License :: OSI Approved :: MIT License` classifier. Under PEP 639 these are
  not supposed to coexist, and modern build/upload tooling may warn or error on it.

**Recommendation (detail in §6):** Keep **MIT**, add a proper root `LICENSE` file with a correct
copyright line, wire it into `pyproject.toml` via `license-files`, drop the deprecated classifier, and
add a short License section to the README. This is ~15 minutes of work and makes the license fully
"official" across GitHub, PyPI, and license scanners.

---

## 2. Current State (Gap Analysis)

| Signal | Current state | Should be |
| --- | --- | --- |
| Root `LICENSE` file | **Missing** | Present (`LICENSE`, exact OSI text + copyright line) |
| `pyproject.toml` `license` | `license = "MIT"` (PEP 639 SPDX expression) ✅ | Keep |
| `pyproject.toml` `license-files` | **Missing** | `license-files = ["LICENSE"]` |
| `License ::` classifier | `"License :: OSI Approved :: MIT License"` present ⚠️ | **Remove** (deprecated alongside an expression) |
| README license section | **None** | Short "## License" section linking to `LICENSE` |
| Source-file SPDX headers | None | Optional for MIT (not required) |
| Sibling repos (`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`) | Out of scope here; **each needs its own `LICENSE`** | Verify separately |

Key facts about the project that shape the recommendation:

- Published to **PyPI** (`pypi.org/project/sase`), homepage `sase.sh`, repo `github.com/sase-org/sase`.
- Single author/maintainer in metadata: **Bryan Bugyi**. Org namespace: **sase-org**.
- Status `Development Status :: 3 - Alpha`; version `0.4.0`.
- Accepts contributions (`CONTRIBUTING.md`) but has **no CLA/DCO** mention.
- Runtime deps are all permissive (jinja2/BSD, rich/MIT, textual/MIT, pyyaml/MIT, jsonschema/MIT,
  pluggy/MIT, pillow/HPND, etc.) and the Rust core (`sase-core-rs`) is your own — so there is **no
  license-compatibility conflict** with shipping sase under MIT.

> **Why "metadata is not the grant" is the crux:** A license is a grant of rights from the copyright
> holder to everyone else. Courts and scanners look for that grant in a conventional, conspicuous place
> — a `LICENSE` file with the full license text. A one-word `license = "MIT"` in a build config is a
> *claim about* the license, not the license. GitHub's detector (`licensee`) even treats a file
> containing only a bare copyright line as "author intends to retain all rights." Ship the full text.

---

## 3. License Options (the menu)

Licenses fall into three families. For a developer tool whose explicit goal is adoption, the practical
choice is between the two permissive options.

### 3.1 Permissive — *let anyone use it, including in closed-source products*

| License | Patent grant | Notice burden | Notes |
| --- | --- | --- | --- |
| **MIT** | **None (implied only)** | Keep copyright + license text | Shortest, most recognized, lowest friction. What you already declared. |
| **Apache-2.0** | **Explicit** patent grant + patent-retaliation clause | Keep notices + state significant changes (`NOTICE` file) | Best when patents or corporate adoption matter; slightly more ceremony. |
| **BSD-2 / BSD-3-Clause** | None | Like MIT (+ no-endorsement clause in 3-Clause) | Functionally MIT-equivalent; less common for new projects. |

### 3.2 Weak copyleft — *modifications to these files stay open, but linking is fine*

- **MPL-2.0**: file-level copyleft. Reasonable if you want improvements to *sase's own files* returned
  but still allow embedding in proprietary tools. Heavier than most CLI tools need.

### 3.3 Strong / network copyleft — *derivatives must also be open source*

- **GPL-3.0 / AGPL-3.0**: anyone distributing (GPL) or running-as-a-service (AGPL) a derivative must
  release source. AGPL is the classic "stop a cloud provider from running a closed SaaS fork of my
  tool" choice. **Cost:** many companies ban (A)GPL dependencies outright, which suppresses adoption —
  usually the wrong trade for a tool you're trying to popularize via a launch post.

### 3.4 Source-available (NOT open source)

- **BSL-1.1 / SSPL / Elastic**: time-delayed or use-restricted. Used by commercial OSS companies to
  block hyperscaler competition. Not OSI-approved, not "open source," and the wrong fit for an
  alpha-stage tool seeking community trust. Mentioned only for completeness.

**Decision lens for sase:** The project's own README says the goal is to make agent-driven engineering
*dependable* and *widely usable*; it orchestrates other vendors' CLIs rather than competing as a hosted
service. That profile points squarely at **permissive**. There is no SaaS moat to defend (so AGPL's
upside doesn't apply) and copyleft friction would only deter the contributors and companies you want.

---

## 4. MIT vs. Apache-2.0 (the only choice worth deliberating)

These are the two realistic options. The deciding factor is the **patent grant**.

- **MIT** has *no express patent license.* In practice this is fine for the vast majority of small/solo
  projects, and MIT is the most instantly-recognized, lowest-friction license in existence.
- **Apache-2.0** adds an **explicit patent grant** from every contributor, plus **patent retaliation**
  (sue over the software's patents and your license terminates). This is why many companies *prefer*
  Apache-2.0 for tools they'll adopt: it reduces patent ambiguity. The cost is more ceremony (a `NOTICE`
  file, a "state your changes" requirement) and a slightly less famous name.

**When to switch sase to Apache-2.0:** if you expect meaningful corporate/enterprise contribution, want
defensive patent protection as the project grows, or anticipate vendors building on top of it. The
patent clause is genuinely valuable for an AI/agentic tool where patent activity is heavy.

**When to stay MIT:** if you value maximum simplicity, brand recognition, and the lowest possible
barrier to "yes" for casual users — and you're comfortable without an express patent grant.

**This research recommends staying with MIT** (see §6 rationale), but Apache-2.0 is the only defensible
alternative and is a one-file swap if you later decide patent protection matters. Note: **switching from
MIT to Apache-2.0 is easy early and gets harder later**, because once external contributors hold
copyright in the codebase you generally need their agreement to relicense. Decide before the launch
post drives contributions, not after.

---

## 5. Best Practices for an "Official" License

These are the conventions GitHub, PyPI, and license scanners actually key on:

1. **Ship the full text in a root `LICENSE` file.** Plain `LICENSE` (no extension) is the most
   universally detected; `LICENSE.txt` / `LICENSE.md` also work. One license = one file at repo root.
2. **Use the exact, unmodified OSI text.** Detectors compare against canonical text (Sørensen–Dice
   similarity). Don't reflow or edit the body — only fill the placeholders.
3. **Get the copyright line right.** `Copyright (c) <year> <holder>`. A `LICENSE` containing *only* a
   copyright line (no body) is read as "all rights reserved," so the body must be present.
   - *Year:* the year of first publication is fine; a single current year is the common modern practice
     (ranges like `2026` → `2026-2027` are optional and many projects skip them).
   - *Holder:* use a name that matches your metadata. `Bryan Bugyi` matches `pyproject.toml` authors.
     Alternatives: an org-style holder (`the sase authors`) if you want contributors implicitly
     included, or `Bryan Bugyi and the sase contributors`. Pick one and be consistent.
4. **Make the packaging metadata agree with the file (PEP 639).** Modern Python packaging uses an SPDX
   **license expression** plus a **`license-files`** glob, and **deprecates the `License ::`
   classifiers**:
   - Keep `license = "MIT"` (you already have the correct SPDX-expression form).
   - Add `license-files = ["LICENSE"]` so the license file is embedded in the sdist/wheel and surfaced
     on PyPI (Metadata-Version 2.4).
   - **Remove** `"License :: OSI Approved :: MIT License"` from `classifiers`. PEP 639 says tools MAY
     error when an expression *and* a license classifier are both present; don't carry both.
   - Ensure **hatchling ≥ 1.27** (your build backend), which is the version that added PEP 639 support.
5. **Surface it in the README.** A short `## License` section ("Licensed under the MIT License — see
   [`LICENSE`](LICENSE).") is what most readers and your blog audience will look for.
6. **Per-repo licensing.** Copyright/license is per repository. The sibling repos (`sase-core`,
   `sase-github`, `sase-telegram`, `sase-nvim`) each need their **own** `LICENSE` file; the main repo's
   file does not cover them.
7. **Source-file SPDX headers are optional for MIT.** A root `LICENSE` is sufficient. Add
   `# SPDX-License-Identifier: MIT` headers only if you later want per-file clarity for vendoring/reuse.
8. **Contributor licensing (optional, good hygiene before a launch).** With inbound contributions
   coming, decide how contributors grant rights. The lightweight, widely-accepted option is a **DCO**
   (a `Signed-off-by` line via `git commit -s`) noted in `CONTRIBUTING.md`. A full **CLA** is heavier
   and usually unnecessary for a permissive solo project. The common default ("inbound = outbound":
   contributions are licensed under the project's license) is implied by GitHub's Terms of Service but
   is worth stating explicitly in `CONTRIBUTING.md`.
9. **Trademark ≠ copyright.** A license grants copyright permissions, not naming rights. MIT is silent
   on trademarks (Apache-2.0 explicitly reserves them). If protecting the **"sase" / sase.sh** name
   matters, that's a separate trademark/branding decision, not something the code license handles.

---

## 6. Recommended Solution

**Keep MIT. Make it official with these concrete steps.** Rationale: MIT is already declared everywhere
(pyproject, README badges via PyPI, classifier), it maximizes adoption for a launch, imposes the least
friction on the users and contributors the blog post will attract, and has zero compatibility conflict
with your dependency tree. Apache-2.0 is the only sensible alternative — choose it instead *only if* you
specifically want the explicit patent grant for enterprise adoption; if so, do it **now**, before the
launch brings external copyright holders into the tree.

### Step 1 — Add a root `LICENSE` file

Create `LICENSE` (no extension) at the repo root with the canonical MIT text:

```
MIT License

Copyright (c) 2026 Bryan Bugyi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

(Tip: GitHub's "Add file → Create new file → name it `LICENSE`" offers a license picker that inserts
this exact text and fills the copyright line, which guarantees a clean `licensee` match. Either method
works.)

### Step 2 — Fix `pyproject.toml` (PEP 639 alignment)

- Keep: `license = "MIT"`
- Add: `license-files = ["LICENSE"]`
- Remove from `classifiers`: `"License :: OSI Approved :: MIT License"`
- Confirm the build uses **hatchling ≥ 1.27**.

### Step 3 — Add a README License section

```markdown
## License

sase is licensed under the [MIT License](LICENSE).
```

### Step 4 — (Optional, recommended before launch) Contributor terms

Add one line to `CONTRIBUTING.md` stating that contributions are accepted under the project's MIT
license (inbound = outbound), and optionally adopt the DCO (`git commit -s`) for a lightweight
provenance trail.

### Step 5 — Verify the sibling repos

Confirm `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim` each carry their own `LICENSE`
file (MIT, for consistency, unless a specific repo has a reason to differ). The main repo's license
does not extend to them.

### Verification checklist

- [ ] `LICENSE` exists at repo root with full MIT text + correct copyright line.
- [ ] GitHub repo page shows the "MIT License" label in the sidebar (confirms `licensee` detection).
- [ ] `pyproject.toml`: has `license`/`license-files`, no `License ::` classifier; builds clean.
- [ ] Next PyPI release shows the license on the project page (Metadata-Version 2.4).
- [ ] README has a License section.
- [ ] Sibling repos each have a `LICENSE`.

---

## 7. Sources

- [PEP 639 – Improving License Clarity with Better Package Metadata](https://peps.python.org/pep-0639/)
- [pyproject.toml specification — Python Packaging User Guide](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
- [Writing your pyproject.toml — Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Licensing examples and user scenarios — Python Packaging User Guide](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)
- [Hugo van Kemenade — Improving licence metadata (PEP 639 migration)](https://hugovk.dev/blog/2025/improving-licence-metadata/)
- [setuptools issue #4903 — migration guide for license expression / TOML-table deprecation](https://github.com/pypa/setuptools/issues/4903)
- [Licensing a repository — GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [licensee/licensee — GitHub's license detection gem](https://github.com/licensee/licensee)
- [github/choosealicense.com](https://github.com/github/choosealicense.com)
- [FOSSA — Open Source Licenses 101: Apache License 2.0](https://fossa.com/blog/open-source-licenses-101-apache-license-2-0/)
- [MIT vs Apache 2.0: Complete License Comparison Guide](https://licensecheck.io/blog/mit-apache-comparison)
- [Open Source Licenses: Which One Should You Pick? (MIT, GPL, Apache, AGPL)](https://dev.to/juanisidoro/open-source-licenses-which-one-should-you-pick-mit-gpl-apache-agpl-and-more-2026-guide-p90)
