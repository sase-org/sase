---
create_time: 2026-06-09
updated_time: 2026-06-09
status: research
---

# New-User Digestibility Improvements For SASE

## Question

What high-priority improvements should SASE make before a near-term blog post so that interested new users can
understand the project, install it, and reach a confidence-building first run?

## Bottom Line

SASE's product story is strong, but the public on-ramp still asks too much of a stranger before the first success.
The highest-priority work is not another feature. It is a narrow conversion path:

1. Publish the current `sase` package and make one public install command true.
2. Promote one tested quickstart as the primary CTA from README, docs home, and the launch essay.
3. Make provider readiness explicit because SASE depends on other agent CLIs.
4. Compress first-contact vocabulary to three concepts before introducing the full SASE noun set.
5. Fix the small CLI and plugin guidance mismatches that make the product feel less finished.

The earlier June 7 readiness note is still mostly right, but the release blocker is now narrower: `sase-core-rs` and
`sase-telegram` exist on PyPI as of 2026-06-09, while the public `sase` package is still stale at `0.1.0`.

## Method

I reviewed current local surfaces:

- `README.md`
- `docs/index.md`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `docs/blog/posts/why-coding-agents-need-orchestration.md`
- `docs/series/agentic-software-engineering.md`
- `docs/cli.md`
- `docs/init.md`
- `docs/llms.md`
- `docs/ace.md`
- `pyproject.toml`
- `mkdocs.yml`
- existing launch/readiness research in `sdd/research/202606/`
- live CLI output from `sase --help`, `sase run --help`, `sase version`, `sase doctor`, and `sase plugin doctor`

I also checked current public package metadata and adjacent tool onboarding docs.

## Current State Observations

### Public package state

As of 2026-06-09:

| Package | Public state | Onboarding implication |
| --- | --- | --- |
| `sase` | PyPI latest is `0.1.0`; no project URLs; no `sase-core-rs` dependency. | `pip install sase` or `uv tool install sase` still installs an old command surface. |
| local `sase` checkout | `pyproject.toml` says `0.1.3`; `sase version` reports `0.1.3+78.g96ed9b068`. | Docs describe newer behavior than public install delivers. |
| `sase-core-rs` | PyPI latest is `0.1.2` with Linux/macOS/Windows and Python 3.12-3.14 classifiers. | Earlier missing-core blocker appears resolved. |
| `sase-github` | PyPI latest is `0.1.0`; sparse metadata. | Plugin packaging exists but should be tested with current `sase`. |
| `sase-telegram` | PyPI latest is `0.1.0`. | Earlier "not published" note is stale; still optional for new users. |

### Local CLI state

Positive:

- `sase doctor` now exists and gives grouped, read-only diagnostics with next steps.
- `sase version` now exists and reports host/core package inventory.
- `sase doctor` sees package versions, paths, VCS, config, LLM registry, plugin doctor, project state, workspace
  registry, and telemetry.

Remaining friction:

- `sase run --help` still prints only flags and hides the prompt positional, even though `docs/cli.md` documents
  `sase run [PROMPT]`.
- `sase plugin doctor` still recommends `uv tool install "sase[github]"`, but local `pyproject.toml` has no `github`
  extra. Either add the extra or recommend `uv tool install --with sase-github sase`.
- The compact `sase doctor` LLM row says providers/model counts and autodetect candidates, but it does not yet give a
  beginner a clear "your default provider is X; this CLI/auth check passed/failed; run Y next" path.

### Docs and blog state

Positive:

- README explains SASE's positioning well.
- Docs home has a polished first screen and useful visual assets.
- The draft 15-minute quickstart is the right artifact to convert launch interest into product trial.
- `docs/cli.md` now includes `sase doctor` and `sase version`.

Remaining friction:

- README Quick start and the draft quickstart still lead with source/contributor setup: `uv venv`, `source`, and
  `just install`.
- The docs homepage first CTAs are PDF, GitHub, and blog series. There is no first-viewport "Install" or "Quickstart"
  action.
- The hands-on quickstart is still `draft: true` and outside `mkdocs.yml` navigation.
- The first `sase run` example is bare:

  ```bash
  sase run "add a one-line docstring to the most recently edited Python function in this repo"
  ```

  For public onboarding, this is both implicit about the workspace target and relatively high-trust because it asks an
  agent to edit files before the user has seen how SASE records a run.
- The first surfaces introduce many nouns before a beginner has a win: ACE, AXE, XPrompt, ChangeSpec, Memory, SDD,
  Beads, Commit finalizer, Plugins, Editor integration, ProjectSpec, mentors, chops, and more.

## External Patterns

Adjacent tool docs are simpler at the point of first contact:

- Claude Code's official quickstart has a linear beginner path: prerequisites, install, log in, start a first session,
  ask a first question, make a first change, use git, then learn commands and help.
- OpenAI's Codex CLI docs put setup into install, run, sign-in, and upgrade sections with copyable commands.
- Gemini CLI's README puts "Why", then quick install options, including `npx` for no-install trial.
- OpenCode's docs lead with install, provider configuration, and project initialization; the first project setup step
  creates an `AGENTS.md` and explicitly tells users to commit it.
- Diataxis separates tutorials, how-to guides, reference, and explanation. SASE has all four kinds of material, but the
  landing path currently mixes them.
- Google's technical-writing guidance frames documentation around the gap between what the audience already knows and
  what they need for the task. A new SASE user likely knows agent CLIs, git, and terminals, but not SASE-specific nouns.
- MDN's writing guidance emphasizes relevant examples. SASE should prefer one copyable "what you should see" path over
  broad subsystem inventory in the first five minutes.

## Recommendations

### P0. Make the public install path true

Goal: a blog reader can run one command, then `sase doctor`, without landing on stale February behavior.

Concrete work:

- Publish current `sase` after verifying `sase-core-rs==0.1.2` satisfies the runtime dependency.
- Smoke-test `uv tool install sase --python 3.12`, `sase version`, `sase doctor`, and `sase run --help` in a clean
  environment.
- Add/update PyPI metadata before publishing: `readme`, project URLs, classifiers, authors/maintainers, and search
  keywords.
- Decide the public plugin command:
  - either add a real `github` extra and keep `sase[github]`;
  - or change plugin guidance to the uv-supported same-environment form, for example
    `uv tool install --with sase-github sase --python 3.12`.

Success criteria:

- `uv tool install sase --python 3.12` installs current SASE, not `0.1.0`.
- `sase version` reports current `sase` plus `sase-core-rs`.
- `sase doctor` reports no install/runtime errors in a clean repo with one supported provider available.
- The README and quickstart do not need a source checkout for ordinary users.

Why this is first: a launch post that converts interest into a stale CLI loses trust faster than a missing feature.

### P0. Publish one beginner quickstart and route every CTA to it

Goal: new users should have one obvious path from "this sounds useful" to "I saw SASE track a run."

Concrete work:

- Undraft `docs/blog/posts/hello-sase-your-first-15-minutes.md` only after the install path is true.
- Add it to `mkdocs.yml` nav and the series hub.
- Put "Quickstart" or "Install and run SASE" in the first CTA group on `docs/index.md`; demote PDF from the first
  action row.
- Link the quickstart from README near the first screen, the launch essay, and the blog index.
- Rewrite Step 1 as user install, with source install in a "contributing from checkout" aside:

  ```bash
  uv tool install sase --python 3.12
  sase version
  sase doctor
  ```

- Change the first run to be explicit about target and low risk:

  ```bash
  sase run "#cd:$(pwd) summarize what this repository does; do not change files"
  sase agents status
  ```

- Follow with a second optional edit task once the user has seen the agent record:

  ```bash
  sase run "#cd:$(pwd) make a tiny documentation-only improvement and explain the diff"
  ```

Success criteria:

- A reader can find the quickstart from README, docs home, and the launch essay without scanning a long link list.
- The quickstart starts with one install path, one readiness command, one explicit workspace target, and one observed
  artifact.
- The first task is safe for a real repo.

Why this matters: adjacent tools earn trust by getting users to one successful interaction before teaching the whole
system. SASE should do the same.

### P1. Make provider readiness a first-class beginner step

Goal: avoid the failure mode where SASE is installed but no agent runtime is usable.

Concrete work:

- Add a "Choose one agent runtime" quickstart section with the shortest path for Claude Code, Codex, Gemini CLI, Qwen
  Code, and OpenCode. Keep it to one install/auth smoke command per provider, and link `docs/llms.md` for details.
- Extend compact `sase doctor` or add a `sase doctor -C llm.default` quickstart example that reports:
  - selected/default provider;
  - detected CLI path;
  - whether auth appears usable without making an LLM call, if the provider supports a read-only check;
  - the next command if no provider is ready.
- Keep provider docs separate from provider internals. `docs/llms.md` is currently an architecture/reference page; add a
  short beginner provider setup page or a top-level "Before your first run" section.

Success criteria:

- A beginner knows whether SASE will use Claude, Codex, Gemini, Qwen, or OpenCode before `sase run`.
- If provider setup is missing, the error path points to one concrete next command.
- The first quickstart can say "run `sase doctor`; fix any provider warning before continuing."

Why this matters: SASE is an orchestration layer, not an agent runtime. That is a strength, but it creates an extra
dependency that the onboarding path must make visible.

### P1. Compress the mental model to three concepts before the full vocabulary

Goal: readers should understand the minimal shape of SASE before meeting every subsystem name.

Suggested first-contact model:

1. **Workspace target**: where the agent works, for example `#cd:$(pwd)` or `#git:project`.
2. **Agent record**: the durable run artifact SASE tracks while the provider CLI works.
3. **Work record**: the durable review/planning object when work becomes code, such as a ChangeSpec or bead.

Concrete work:

- Add a "Three concepts to start" box to README and docs home.
- Move the full "Core pieces" inventory below quickstart links or make it collapsible in docs.
- Publish a concise glossary page generated from or aligned with `memory/short/glossary.md`, but do not require the
  glossary before the first run.
- In the quickstart, introduce product nouns only after the user sees them:
  - first `sase run`;
  - then "this created an agent record";
  - then "ACE is where you inspect it";
  - then "ChangeSpecs and beads matter when work needs review or dependencies."

Success criteria:

- A new reader can explain SASE in one sentence without using every internal noun.
- The first page still has links to ACE, AXE, XPrompts, SDD, Beads, and ChangeSpecs, but they are not the prerequisite
  for trying the product.

Why this matters: the current docs are accurate but noun-heavy. Google-style audience analysis says to teach the delta:
new users already know terminals, git, and coding agents; they need the SASE coordination model.

### P1. Fix CLI self-discovery papercuts before the blog spike

Goal: commands that readers naturally try should confirm the docs instead of creating doubt.

Concrete work:

- Fix `sase run --help` so usage shows `sase run [PROMPT]` and includes examples:

  ```bash
  sase run "#cd:$(pwd) explain this repo"
  sase run -d "#git:my-project fix the failing test"
  sase run --resume <agent-or-history>
  ```

- Add a short success footer to `sase doctor` for clean setups:

  ```text
  Ready for first run: sase run "#cd:$(pwd) explain this repo"
  ```

- Replace or implement the `sase[github]` plugin recommendation.
- Consider a `sase quickstart` or `sase onboard` command that prints the current public path:

  ```bash
  sase version
  sase doctor
  sase run "#cd:$(pwd) summarize this repository; do not change files"
  sase agents status
  ```

Success criteria:

- The terminal help and the quickstart agree.
- Plugin guidance names commands that actually resolve.
- A user who skips docs and runs `--help` can still find the first useful command.

Why this matters: launch traffic includes people who will test with `--help` before reading long docs.

## Suggested Pre-Blog Work Queue

Do these before the post points strangers at SASE:

1. Publish current `sase`; smoke-test clean install.
2. Update README and draft quickstart to user install plus `sase doctor`.
3. Fix `sase run --help`.
4. Fix plugin install guidance or add the advertised extra.
5. Put the quickstart CTA on docs home, README, blog index, series hub, and the launch essay.
6. Add the three-concept mental model to README/docs home.
7. Add beginner provider setup/readiness guidance, even if it is short.

Defer until after launch:

- Promoting all ten blog drafts.
- Making Telegram/mobile/editor integrations launch pillars.
- Expanding reference docs further before the quickstart is real.
- New orchestration features that do not shorten the first successful run.

## Source Links

Internal:

- `README.md`
- `docs/index.md`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `docs/blog/posts/why-coding-agents-need-orchestration.md`
- `docs/series/agentic-software-engineering.md`
- `docs/cli.md`
- `docs/init.md`
- `docs/llms.md`
- `docs/ace.md`
- `pyproject.toml`
- `mkdocs.yml`
- `sdd/research/202606/sase_install_use_understand_readiness_consolidated.md`
- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/sase_blog_series_structure_consolidated.md`

External:

- PyPI `sase`: https://pypi.org/pypi/sase/json
- PyPI `sase-core-rs`: https://pypi.org/pypi/sase-core-rs/json
- PyPI `sase-github`: https://pypi.org/pypi/sase-github/json
- PyPI `sase-telegram`: https://pypi.org/pypi/sase-telegram/json
- Claude Code quickstart: https://code.claude.com/docs/en/quickstart
- OpenAI Codex CLI docs: https://developers.openai.com/codex/cli
- Gemini CLI README: https://github.com/google-gemini/gemini-cli
- OpenCode docs: https://opencode.ai/docs/
- Diataxis: https://diataxis.fr/
- Google Technical Writing - Audience: https://developers.google.com/tech-writing/one/audience
- MDN Writing Style Guide - relevant examples: https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Writing_style_guide#include-relevant-examples
- uv tools docs: https://docs.astral.sh/uv/concepts/tools/
