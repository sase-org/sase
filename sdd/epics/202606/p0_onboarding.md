---
create_time: 2026-06-09 18:41:43
bead_id: sase-4j
tier: epic
status: wip
prompt: sdd/prompts/202606/p0_onboarding.md
---
# Plan: Implement P0 New-User Onboarding Recommendations

## Objective

Implement the P0 recommendations from `sdd/research/202606/new_user_onboarding_recommendations_consolidated.md` before
the SASE blog launch:

1. Make the public install path true by publishing a current `sase` package and moving the README away from contributor
   setup as the first path.
2. Publish one tested 15-minute quickstart and route beginner CTAs to it.
3. Make provider readiness explicit before a user's first `sase run`.

As of the research note and a fresh check on 2026-06-09, PyPI still publishes `sase==0.1.0` while this checkout is
`0.1.3`. The plan below treats that as the main launch blocker. The only P1/P2 item included here is the narrow
`sase run --help` fix, because the P0 release smoke explicitly includes that command and the current help omits the
prompt positional.

## Ground Rules

- Each phase is intended for a distinct agent instance.
- Do not edit canonical memory files.
- Each phase that changes repo files should start with `just install` in its own workspace and finish with `just check`.
- Docs-heavy phases should also run `just docs-check`; run `just docs-pdf-check` when navigation, blog, or PDF-included
  pages change.
- The publish phase must not publish an unmerged local workspace build unless Bryan explicitly chooses a manual local
  release. Prefer the existing GitHub release workflow and PyPI trusted publishing.
- If PyPI/GitHub credentials or environment approval are unavailable, the release phase should stop with the exact
  missing permission or workflow state, not silently declare success.

## Phase 1: Provider Readiness And Minimal CLI Smoke Polish

Goal: make `sase doctor` a trustworthy gate before the first agent launch, and make `sase run --help` suitable for the
release smoke path.

Likely files:

- `src/sase/doctor/checks_providers.py`
- `src/sase/llm_provider/{claude,codex,gemini,qwen,opencode}.py`
- `src/sase/llm_provider/_hookspec.py` and/or `registry.py` only if a metadata hook is needed for install/auth hints
- `src/sase/main/parser.py`
- `src/sase/main/parser_commands.py`
- `tests/doctor/test_checks_providers.py`
- `tests/main/test_doctor_command.py`
- Any existing parser/help tests, or a focused new test if none exists

Work:

- Change provider autodetection so every built-in provider selected for first-run use has a declared executable to
  check. In particular, do not let Gemini report as ready merely because it is the fallback while `gemini` is absent
  from `PATH`.
- Extend `llm.default` output so a beginner can see:
  - selected provider;
  - whether selection came from config, temporary override, or autodetect;
  - executable path when found;
  - exact next step when no usable provider executable is found;
  - "auth not verified" wording unless the provider can be checked without an LLM call.
- Keep doctor read-only: no LLM API calls, no auth prompts, no state mutation.
- Add a small provider setup hint table in code or metadata for Claude Code, Codex, Gemini CLI, Qwen Code, and OpenCode.
  Hints should point to install/auth docs or commands, but avoid long provider-specific workflows in the terminal
  output.
- Fix `sase run --help` so usage shows an optional `PROMPT` positional and includes two copyable examples:
  - safe read-only run using `#cd:$(pwd)`;
  - detached/background run or `sase agents status` follow-up.
- If changing top-level argparse behavior for bare `sase` is low-risk, add a start-here hint. Otherwise leave it for P2.

Acceptance:

- `sase doctor -C llm.default -v` is actionable with no provider executable on `PATH`.
- `sase doctor -C llm.default -j` exposes bounded machine-readable provider readiness fields.
- A selected executable that exists still reports `OK`; a missing selected executable reports `ERROR` with next steps.
- `sase run --help` displays `PROMPT` in usage/help and includes beginner examples.
- Targeted tests pass, then `just check` passes.

Suggested agent prompt:

```bash
sase run "#cd:$(pwd) Implement Phase 1 from sase_plan_p0_onboarding.md only: provider readiness doctor output and minimal sase run help polish. Do not edit README or docs CTAs."
```

## Phase 2: Public Install Contract In README And Package Metadata

Goal: make the repository's first screen match the public install path that blog readers should use.

Likely files:

- `README.md`
- `pyproject.toml`
- `.github/workflows/release.yml` only for metadata/smoke items that belong with package build output
- `docs/development.md` if contributor setup needs a better home

Work:

- Rewrite the README quick start so the headline install path is:

  ```bash
  uv tool install sase --python 3.12
  sase version
  sase doctor
  ```

- Add a short prerequisite before install: Python 3.12+, `uv`, and one authenticated coding-agent CLI.
- Add a first safe run after doctor, but keep it below the readiness gate:

  ```bash
  sase run "#cd:$(pwd) summarize what this repository does; do not change files"
  sase agents status
  ```

- Move the current `uv venv`, `source .venv/bin/activate`, `just install`, `sase core health`, and `sase ace` path under
  "Install from source" or "Development".
- Trim the README's first command block so beginners do not encounter the full command inventory before trying SASE.
- Add package metadata needed for a credible PyPI page before publish:
  - `readme = "README.md"` if absent;
  - maintainers/authors if the project wants them public;
  - classifiers for Python version, license, operating systems, and development status;
  - keywords.
- Do not broaden into the P1 glossary or mental-model rewrite unless needed to make the install section coherent.

Acceptance:

- README first path does not require cloning the repo, `just`, or editable install.
- README clearly says SASE orchestrates an existing provider CLI and that `sase doctor` is the readiness gate.
- Package metadata builds cleanly and improves the PyPI project description.
- `uv build` and `twine check dist/*` pass if run locally.
- `just check` passes.

Suggested agent prompt:

```bash
sase run "#cd:$(pwd) Implement Phase 2 from sase_plan_p0_onboarding.md only: README public install contract and package metadata. Do not undraft the quickstart or change docs navigation."
```

## Phase 3: Publish The 15-Minute Quickstart And Route Beginner CTAs

Goal: make one beginner path visible from README, docs home, blog surfaces, and navigation.

Likely files:

- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `mkdocs.yml`
- `docs/index.md`
- `docs/blog/index.md`
- `docs/series/agentic-software-engineering.md`
- `docs/blog/posts/why-coding-agents-need-orchestration.md`
- Possibly `README.md` only for the quickstart link if Phase 2 left a placeholder

Work:

- Undraft `hello-sase-your-first-15-minutes.md` only after Phase 2's public install contract is in place.
- Replace source-install setup in the quickstart with public install plus `sase version` and `sase doctor`.
- Add an explicit provider readiness step before first run. Keep provider setup compact and link to the provider
  reference instead of duplicating long provider docs.
- Make the first run safe and explicit about workspace target:

  ```bash
  sase run "#cd:$(pwd) summarize what this repository does; do not change files"
  sase agents status
  ```

- Put any first edit task after the user has seen the agent record/status.
- Add a top-level "Getting Started" docs nav section above "The Basics" containing the quickstart and any existing
  beginner page that fits without inventing new scope.
- Route CTAs to the quickstart from:
  - README first screen or immediately after install;
  - docs home first CTA row;
  - blog index;
  - series hub;
  - launch essay.
- Keep the quickstart concise. Do not publish the rest of the draft blog series in this phase.

Acceptance:

- There is exactly one obvious beginner quickstart linked from README, docs home, blog index, series hub, and launch
  essay.
- The quickstart starts with install, provider readiness, safe first run, and visible agent record.
- `mkdocs.yml` includes the quickstart in navigation.
- `just docs-check`, `just docs-pdf-check`, and `just check` pass.

Suggested agent prompt:

```bash
sase run "#cd:$(pwd) Implement Phase 3 from sase_plan_p0_onboarding.md only: publish and route the 15-minute quickstart. Do not touch provider doctor code or release workflow."
```

## Phase 4: Release Pipeline Hardening And Public Publish

Goal: publish a current `sase` package whose public install path matches the docs.

Likely files:

- `.github/workflows/release.yml`
- A small release-smoke helper under `tools/` only if it prevents shell duplication
- No docs changes unless smoke output reveals a stale command

Work:

- Harden the release workflow's install smoke so the built artifact verifies the P0 path before PyPI publish:

  ```bash
  sase version
  sase doctor
  sase run --help
  ```

- Prefer smoke commands that do not require an authenticated LLM provider. `sase doctor` may warn/error on provider
  readiness depending on the CI image; the workflow should either select a provider-check subset that is expected in CI
  or assert the diagnostic wording intentionally.
- Build the candidate from the merged commit with `uv build` and validate metadata with `twine check`.
- Trigger or shepherd the existing `release-please` flow on `master` so a new version is created and the
  trusted-publishing job uploads to PyPI.
- After publication, verify PyPI JSON and a real clean install:

  ```bash
  uv tool install sase --python 3.12
  sase version
  sase doctor
  sase run --help
  ```

- Confirm the installed package depends on a published compatible `sase-core-rs` and imports the Rust extension
  successfully via `sase core health` or equivalent package inventory.

Acceptance:

- PyPI `sase` latest is newer than `0.1.0` and includes the current command surface.
- `uv tool install sase --python 3.12` installs without source checkout knowledge.
- `sase version` from the tool install reports the published version and compatible `sase-core-rs`.
- The release workflow records a successful build, install smoke, and publish.
- If publish cannot be completed, the phase report names the exact blocker: missing release PR, failed CI, missing PyPI
  trusted-publishing environment, missing GitHub permission, or package-index rejection.

Suggested agent prompt:

```bash
sase run "#cd:$(pwd) Implement Phase 4 from sase_plan_p0_onboarding.md only: harden release smoke and publish/verify the current sase package. Stop with exact blocker if credentials or GitHub environment approval are unavailable."
```

## Phase 5: End-To-End Launch Readiness Audit

Goal: verify that the P0 implementation works as a coherent new-user funnel after the public release.

Likely files:

- No expected file edits. If a small stale-doc fix is found, make only that fix and rerun relevant checks.

Work:

- In a clean environment with no repo checkout on `PYTHONPATH`, run the published install path and record outputs:

  ```bash
  uv tool install sase --python 3.12 --force
  sase version
  sase doctor
  sase run --help
  ```

- Review README, docs home, blog index, series hub, launch essay, and quickstart as a single reader journey.
- Confirm provider-readiness wording is consistent between `sase doctor`, README, quickstart, and provider docs.
- Confirm source-install/contributor setup is still available but is no longer the first path.
- Run `just check`, `just docs-check`, and `just docs-pdf-check` in the final workspace.
- Produce a concise closeout listing:
  - published PyPI version;
  - clean-install command results;
  - docs pages checked;
  - any remaining non-P0 follow-ups intentionally deferred.

Acceptance:

- A cold reader can install, verify provider readiness, run the safe first command, and find the resulting agent record
  from the published docs.
- All P0 success criteria from the research note are met.
- Any remaining issues are explicitly classified as P1/P2 or as external release/account blockers.

Suggested agent prompt:

```bash
sase run "#cd:$(pwd) Execute Phase 5 from sase_plan_p0_onboarding.md only: post-release P0 launch readiness audit. Make only tiny stale-doc fixes if needed."
```

## Overall Completion Criteria

The full effort is complete when:

- Public PyPI install no longer delivers stale `sase==0.1.0` behavior.
- README's first path is `uv tool install`, `sase version`, and `sase doctor`, not contributor setup.
- The 15-minute quickstart is published, navigable, and linked from all beginner CTAs.
- Provider readiness is visible and actionable before first run.
- The public install smoke passes from a clean environment.
- `just check` and strict docs builds pass on the final repo state.
