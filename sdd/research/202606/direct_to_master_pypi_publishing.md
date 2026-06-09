# Publishing Direct-to-`master` Changes to PyPI Timely and Correctly

Status: Research / options memo (no implementation)
Date: 2026-06-09

## Request

We want to stabilize `sase` so users can always `pip`/`uv` install the latest **stable** version from PyPI. Releases are
already automated with [Release Please](https://github.com/googleapis/release-please) release PRs. The open concern is
changes that are **merged or pushed directly to `master`** (bypassing the normal PR flow), which we may never fully
disallow. What are our options for ensuring direct-to-`master` changes reach PyPI in a **timely** and **correct** way?

This memo answers that specific question. It builds on, and does not repeat, the broader tooling decision already made in:

- `sdd/research/202606/automated_semver_releases_consolidated.md` — chose the release-PR model + Release Please for
  `sase`/`sase-github`/`sase-telegram`, release-plz for `sase-core`, and the zero-ver bump policy.
- `sdd/research/202605/public_release_process_and_install_research.md` — the coordinated package family
  (`sase-core-rs` → `sase` → plugins), abi3 wheels, Trusted Publishing.

And it is grounded in three in-flight SDD items that are live examples of the failure modes discussed here:

- `sdd/tales/202606/fix_manual_pypi_publish_from_tag.md` — provenance/guard bug publishing `sase-core-rs` from a tag.
- `sdd/tales/202606/github_ci_sase_version_skew.md` — `sase-github` source needs `sase>=0.1.3` but PyPI only has `0.1.0`.
- `sdd/tales/202606/sase_telegram_pypi_release.md` — a release PR merged but `release_created` was never emitted, so
  nothing published.

## Executive Summary

**Direct-to-`master` changes already flow to PyPI today — conditionally.** `release.yml` runs Release Please on *every*
push to `master`, so a direct push is parsed the same way a squash-merge is: Release Please reads the **commit messages**
(not PR titles) from git history, keeps the release PR up to date, and the build→smoke→publish chain fires when that
release PR is merged. So a direct push is published **if and only if** three things hold:

1. its commit message is a parseable **Conventional Commit**, and
2. its type is **releasable** (`feat`, `fix`, `deps`, `docs`, or a `!`/`BREAKING CHANGE`; for the `python` release type
   `docs` counts — but `chore`/`ci`/`test`/`refactor`/`style`/`build` do **not**), and
3. someone eventually **merges the release PR**.

Each condition is a distinct failure mode for *direct* pushes specifically, because the one guard we have today
(`pr-title.yml`) validates **PR titles only** and is completely bypassed by `git push`:

- **Correctness gap** — a direct push with a non-conventional message, or a user-facing change mislabeled `chore:`/`refactor:`,
  is **silently dropped** by Release Please: no bump, no changelog line, never published.
- **Timeliness gap** — nothing auto-merges the release PR, so direct changes can sit on `master`, unreleased,
  indefinitely. This is exactly the `sase-github` skew: `master` is at the `0.1.3` API while PyPI is still `0.1.0`.
- **Cross-repo gap** — a direct push that advances an API plugins depend on (or the `sase-core` wire/ABI) without a
  coordinated publish breaks downstream installs/CI.

The recommendation, tuned to "we won't fully ban direct pushes," is a small layered change set:

1. **Make direct pushes correct at push time** with a GitHub **repository ruleset "Restrict commit metadata"** regex on
   `master` that requires a Conventional Commit message. This is the cloud-native equivalent of a server-side commit hook
   and *rejects* a bad direct push without banning direct pushes (use a bypass list for the release bot). Back it with a
   client-side `commit-msg` hook for fast local feedback.
2. **Make releases timely** by choosing a point on the auto-merge spectrum: start with a **staleness alert** on the open
   release PR, and graduate to **scheduled auto-merge** (e.g. daily) or **full auto-merge** of the release PR for true
   continuous-delivery-to-PyPI. (Auto-merge needs `SASE_RELEASE_TOKEN`, which we already have, so required CI runs on the
   release PR.)
3. Optionally, run a **dev/pre-release stream to TestPyPI** on every `master` push (dynamic `.devN` versioning) so
   `master` is always installable by early adopters, while real PyPI stays stable-only.
4. Keep a **tag-driven, build-from-tag publish** as an out-of-band escape hatch (reuse the hardened pattern from
   `fix_manual_pypi_publish_from_tag`), and enforce **release ordering** (`sase-core-rs` → `sase` → plugins).

---

## Current State (verified from this repo)

`.github/workflows/release.yml`:

- Trigger: `on: push: branches: [master]` **and** `workflow_dispatch`. So Release Please re-runs on every commit that
  lands on `master`, however it lands.
- `release` job: `googleapis/release-please-action@v5`, `token: ${{ secrets.SASE_RELEASE_TOKEN || secrets.GITHUB_TOKEN }}`,
  output `release_created`.
- `build` / `install-smoke` / `publish` jobs all gated on `needs.release.outputs.release_created == 'true'`. `publish`
  uses the `pypi` GitHub environment + `id-token: write` and `pypa/gh-action-pypi-publish@release/v1` (OIDC Trusted
  Publishing, no stored token).

`release-please-config.json`: `release-type: python`, `include-v-in-tag: true`, `include-component-in-tag: false`,
`bump-minor-pre-major: true`, `bump-patch-for-minor-pre-major: true`, `extra-files: src/sase/__init__.py`, single root
package `"."`. Manifest currently `0.1.3`.

`.github/workflows/ci.yml`: runs `on: push: branches:[master]` **and** `on: pull_request`. Note the push variant runs
*after* the commit is already on `master` — detective, not preventive, for direct pushes.

`.github/workflows/pr-title.yml`: enforces the Conventional Commits regex against the **PR title** only. A direct `git
push` never triggers it.

**Key consequence:** because `build`/`publish` are later jobs *in the same workflow run* as the `release` job, we do **not**
hit the well-known "`GITHUB_TOKEN`-created events don't trigger workflows" problem for publishing — when a release PR
merge lands on `master`, that push runs `release.yml`, Release Please emits `release_created=true` in that same run, and
publish proceeds. The `SASE_RELEASE_TOKEN` PAT matters for a *different* reason: so that the **release PR itself** gets
CI runs (a PR opened with the default `GITHUB_TOKEN` won't trigger `ci.yml`). That same caveat will matter again if we
ever move publishing to a *separate* tag/release-triggered workflow (see Option C2).

---

## How Release Please actually treats direct pushes (verified mechanics)

| Question | Answer | Source |
| --- | --- | --- |
| Does it parse raw **commit messages** on direct push, or only merged PR titles? | **Commit messages.** It "parses your git history, looking for Conventional Commit messages." Squash-merge is recommended for clean history but not required; direct pushes are parsed identically. `pull-request-title-pattern` controls the title of *its own* release PR, not commit-vs-PR parsing. | release-please README; `docs/customizing.md` |
| Which types trigger a release? | `feat`, `fix`, `deps`, and `!`/`BREAKING CHANGE`. For the **`python`** (and Java) release type, `docs` is *also* releasable. `chore`/`build`/`ci`/`test`/`refactor`/`style` are **not**. | release-please README ("a releasable unit is a commit with prefix feat, fix, deps … docs is a releasable prefix in Java and Python") |
| A commit with **no** recognizable type? | Not a releasable unit; contributes no bump and no changelog entry. On its own it never produces a release. | release-please README / source |
| Can I make **every** type always bump? | No single official switch. You can surface a type via `changelog-sections` and/or force increments with `versioning: always-bump-patch`, but there's no guaranteed "every commit type is releasable" flag. Enforcing correct classification is the better lever than making `chore` publish. | `docs/customizing.md`, `docs/manifest-releaser.md` |
| Force a specific version from a direct commit? | `Release-As: x.y.z` footer in the commit body (works even on a `chore:` and on direct pushes), or the `release-as` config key. | release-please README; `docs/manifest-releaser.md` |
| Does a `GITHUB_TOKEN`-created tag/release trigger other workflows? | **No** — events from the default `GITHUB_TOKEN` don't start new workflow runs. Need a PAT/App token (our `SASE_RELEASE_TOKEN`) for CI on the release PR, and *would* need it if publishing moved to a separate `release:`/tag-triggered workflow. | release-please-action README; GitHub Actions docs |

---

## Failure modes specific to direct-to-`master`

- **FM1 — Unparseable message → silent drop.** `git push` with `fixed the thing` (no `fix:`). `pr-title.yml` never ran.
  Release Please ignores it: no bump, no changelog, never published. *Correctness.*
- **FM2 — Under-classified change → silent drop / ride-along.** A user-facing fix committed as `chore:`/`refactor:`.
  Ignored for versioning and changelog; it either never ships, or rides silently into the next release triggered by some
  *other* commit, with no changelog credit. *Correctness.*
- **FM3 — Multi-commit push pollutes the changelog.** A single direct `git push` of several commits has every message
  parsed (no squash-title collapse), so WIP/junk intermediate messages leak into the release notes. *Correctness/quality.*
- **FM4 — Release PR never merged → unbounded lag.** Direct changes accumulate in the release PR; with no merge there is
  no tag, no publish. PyPI drifts arbitrarily far behind `master`. This is the live `github_ci_sase_version_skew` case.
  *Timeliness.*
- **FM5 — Cross-repo skew.** A direct push advancing a `sase` API (or `sase-core` wire/ABI) without a coordinated publish
  breaks plugin installs/CI (`github_ci_sase_version_skew`) or ships mislabeled artifacts (`fix_manual_pypi_publish_from_tag`).
  *Correctness across the package family.*
- **FM6 — Broken commit packaged into a release.** Direct push bypasses the `pull_request` CI gate; `ci.yml`'s push run
  is after the fact. `install-smoke` in `release.yml` is the backstop, but only at publish time. *Correctness.*

---

## Options

### Goal A — Make direct pushes *correct* (parseable + classified)

**A1. Ruleset "Restrict commit metadata" regex on `master` (recommended primary).**
GitHub.com has **no** server-side pre-receive hook (Enterprise-Server only), but **repository rulesets** include a
"Restrict commit metadata" restriction that can require the commit **message** to match a regex — and it is enforced on
ref update, so it **rejects a non-conforming direct push** at push time. This is the cloud-native equivalent of a
server-side commit-message gate, and it does *not* require banning direct pushes.

- Pattern: a Conventional Commits regex, e.g. `^(feat|fix|perf|deps|docs|ci|test|chore|refactor|build|revert)(\(.+\))?!?: .+`.
- Caveats: regexes don't span lines by default (prefix `(?m)`); negative lookahead `(?!...)` is unsupported (use "Must
  not match"); squash merges validate the resulting single commit and committer-email rules often must allow
  `noreply@github.com`. Adding **bypass actors** (for the release bot/admin) requires an **org-owned** repo — `sase-org`
  qualifies.
- Note this regex should *accept* all conventional types (so commits aren't blocked), while a separate concern (Goal B)
  decides what publishes. The win is FM1/FM3 become impossible via direct push.

**A2. Client-side `commit-msg` hook shipped with the repo (defense in depth).**
`pre-commit` + `conventional-pre-commit` (runs at the `commit-msg` stage), or husky+commitlint, or a tracked hooks dir
via `core.hooksPath`. Best-effort and bypassable (`--no-verify`), but gives fast local feedback before a push ever
reaches the ruleset. Complements A1; does not replace it.

**A3. Detective commitlint in CI `on: push` (alternative/supplement).**
`wagoid/commitlint-github-action` supports `on: [push]` and lints the just-landed commits, failing the run (and thus
alerting) on a bad message. With `actions/checkout` `fetch-depth: 0`. This is **detective only** for direct pushes — the
commit is already on `master` — so prefer A1 for prevention and use A3 only if the ruleset regex proves too blunt.

**A4. Don't try to "make everything publish."** Tempting fix for FM2 is to make `chore`/etc. releasable, but there is no
clean switch and it makes the public changelog noisy and burns immutable PyPI versions for non-user-facing churn (the
`automated_semver_releases_consolidated` memo recommends against it). Enforcing correct *classification* (A1/A2) is the
right lever.

### Goal B — Make releases *timely* (the release PR actually publishes)

A spectrum from "human gate, just don't let it rot" to "true continuous delivery." Pick one; they're easy to escalate.

**B1. Auto-merge the release PR → continuous delivery to PyPI (strongest "timely").**
Release Please labels its release PR `autorelease: pending`. Enable GitHub native **auto-merge** on it
(`gh pr merge --auto --squash`, or `peter-evans/enable-pull-request-automerge`, keyed off that label), so every releasable
change auto-publishes once required checks pass. This most directly satisfies "users always get the latest stable."
Requires: repo "Allow auto-merge" on; required status checks configured; `SASE_RELEASE_TOKEN` so CI runs on the release
PR; and "Allow GitHub Actions to create and approve pull requests" if auto-approving. Trade-off: removes the human
release gate — couple it with the existing `install-smoke` gate.

**B2. Scheduled merge cadence (batched auto).**
A `schedule:` cron workflow that finds the open `autorelease: pending` PR and merges it (e.g. daily or weekly). "Timely"
without per-commit churn; bounds lag to the cadence. Good middle ground while building confidence toward B1.

**B3. Staleness alert (keep the human gate, kill silent rot — minimal first step).**
A workflow that flags when the release PR has been open > N days with unreleased user-facing changes (could route through
`sase notify`). Cheapest change; directly addresses FM4 without changing who decides to release.

**B4. Manual dispatch (already available).** `workflow_dispatch` on `release.yml` stays as the on-demand path.

### Goal C — Complementary publish models for `master`

**C1. Continuous dev stream to TestPyPI on every push (`master` always installable).**
Add a `master`-push job that builds a **PEP 440 dev version** (`0.1.4.dev12`) via dynamic versioning (`hatch-vcs` with
`local_scheme = "no-local-version"`, since PyPI/TestPyPI **reject** the `+gHASH` local segment) and publishes to
**TestPyPI** (separate index, Trusted Publishing works there too). Early adopters get every `master` commit via
`pip install --pre -i https://test.pypi.org/simple/ sase`; normal users on real PyPI are unaffected (pip won't surface
dev versions without `--pre`). Keep this on **TestPyPI**, not real PyPI: PyPI files are immutable and have **no retention
policy**, so an every-commit `.devN` stream there accumulates forever (the scikit-learn/scipy ecosystem abandoned
TestPyPI nightlies for exactly this and pip-friendly alternatives; Streamlit ships a *separate* `streamlit-nightly`
package instead). This is the most direct literal answer to "direct-to-`master` changes available immediately," at the
cost of an extra index and never confusing dev with stable.

**C2. Tag-driven build-from-tag publish (out-of-band escape hatch).**
Allow `git tag vX.Y.Z && git push --tags` to publish, **building artifacts from the tag** (not the dispatched HEAD) with
a provenance guard that asserts every `dist/*` reports the expected name+version. This is precisely the hardened pattern
worked out in `fix_manual_pypi_publish_from_tag.md` (the bug there was building from `master` HEAD while labeling it with
the tag's version). Reuse it. If implemented as a *separate* workflow triggered by the tag/`release: published`, remember
the `GITHUB_TOKEN` downstream-trigger caveat — the tag must be pushed by a PAT/App token or the publish workflow won't
fire. Useful for emergency releases when the release-PR flow is blocked.

### Goal D — Cross-repo coordination (the family must move together)

**D1. Enforce release order:** `sase-core-rs` → `sase` → plugins (`sase-github`/`sase-telegram`). A `sase` publish that
relies on a new `sase-core-rs` must wait for that wheel; plugins must wait for the `sase` version they require. Encode in
docs and, where possible, in the publish workflow's guards.

**D2. Pin plugins to *published* versions:** plugins should require the `sase`/`sase-core-rs` version that exists on PyPI,
not whatever source `master` has reached. The `github_ci_sase_version_skew` plan is already moving `sase-github` to
`sase>=0.1.3` and pinning CI to a source checkout until that publishes — generalize that discipline.

**D3. Keep the `install-smoke` gate (and extend it).** `release.yml` already installs the built wheel from a clean venv
and runs `sase core health` (resolving `sase-core-rs` from PyPI), which catches ABI/version skew before publish. Mirror
it in the plugin release pipelines.

---

## Comparison

| Option | Goal | Prevents/Fixes | Effort | Keeps direct push? | Keeps human gate? |
| --- | --- | --- | --- | --- | --- |
| A1 Ruleset commit-metadata regex | Correct | FM1, FM3 (preventive, cloud) | Low (settings) | Yes (bypass list) | n/a |
| A2 Client commit-msg hook | Correct | FM1 (early, bypassable) | Low | Yes | n/a |
| A3 CI commitlint on push | Correct | FM1 (detective) | Low | Yes | n/a |
| B1 Auto-merge release PR | Timely | FM4 (eliminates lag) | Medium | Yes | No (CD) |
| B2 Scheduled merge | Timely | FM4 (bounded lag) | Low–Med | Yes | Partial |
| B3 Staleness alert | Timely | FM4 (visibility) | Low | Yes | Yes |
| C1 Dev stream → TestPyPI | Timely (preview) | FM4 for early adopters | Medium | Yes | Yes (stable) |
| C2 Tag build-from-tag publish | Timely (manual) | FM4 escape hatch; FM5 provenance | Medium | Yes | Yes |
| D1–D3 Family coordination | Correct (family) | FM5 | Low–Med | Yes | n/a |

## Recommended minimal change set

Given "we won't fully ban direct-to-`master`," layered and incremental:

1. **A1 + A2** — ruleset commit-metadata regex on `master` (release bot on the bypass list) plus a shipped `commit-msg`
   hook. This single step closes the *correctness* gap that makes direct pushes risky: a direct push must now be a
   parseable Conventional Commit, so Release Please can never silently drop it.
2. **B3 → B2 → B1** — start with a staleness alert on the release PR; move to scheduled (e.g. daily) auto-merge; graduate
   to full auto-merge of the release PR once confidence in `install-smoke` + required CI is high. B1 is what "users
   always get the latest stable" really implies.
3. **D1–D3** — codify `sase-core-rs` → `sase` → plugins ordering, pin plugins to published versions, keep/extend the
   install-smoke gate. Needed regardless, and already half-done in the in-flight skew/telegram plans.
4. **Optional C1** — a TestPyPI `.devN` stream for early adopters if we want `master` continuously installable without
   touching real-PyPI stability; **C2** as an emergency tag publish using the hardened build-from-tag guard.

What we explicitly should *not* do: make non-releasable commit types (`chore`/`ci`/…) publish (A4), or publish an
every-commit `.devN` stream to **real** PyPI (immutable + no retention).

---

## Sources

Release Please / Actions:
- release-please README — https://github.com/googleapis/release-please/blob/main/README.md
- customizing — https://github.com/googleapis/release-please/blob/main/docs/customizing.md
- manifest-releaser — https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md
- release-please-action — https://github.com/googleapis/release-please-action/blob/main/README.md
- GITHUB_TOKEN won't trigger workflows — https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow

GitHub commit governance:
- Pre-receive hooks (Enterprise Server only) — https://docs.github.com/en/enterprise-server@3.16/admin/enforcing-policies/enforcing-policy-with-pre-receive-hooks/about-pre-receive-hooks
- Rulesets available rules (incl. Restrict commit metadata) — https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- Creating rulesets — https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- Allow bypassing required PRs — https://github.blog/changelog/2021-11-19-allow-bypassing-required-pull-requests/
- Native auto-merge — https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request ; `gh pr merge --auto` — https://cli.github.com/manual/gh_pr_merge ; action — https://github.com/peter-evans/enable-pull-request-automerge
- commitlint action (push) — https://github.com/wagoid/commitlint-github-action ; conventional-pre-commit — https://github.com/compilerla/conventional-pre-commit

PyPI / packaging:
- PEP 440 (dev/pre/local) — https://peps.python.org/pep-0440/ ; PyPI rejects local versions — https://github.com/pypi/warehouse/issues/18348
- pip `--pre` behavior — https://pip.pypa.io/en/stable/cli/pip_install/
- hatch-vcs / setuptools-scm `no-local-version` — https://setuptools-scm.readthedocs.io/ , https://pypi.org/project/hatch-vcs/
- TestPyPI — https://packaging.python.org/en/latest/guides/using-testpypi/
- Trusted Publishing — https://docs.pypi.org/trusted-publishers/ ; action — https://github.com/pypa/gh-action-pypi-publish ; PyPA CI/CD guide — https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/
- PyPI immutability / yanking (PEP 592) — https://pypi.org/help/ , https://peps.python.org/pep-0592/ , https://docs.pypi.org/project-management/yanking/
- Nightly-to-index caveats — https://discuss.python.org/t/publishing-nightly-builds-on-test-pypi-org-with-a-time-based-retention-policy/3152
