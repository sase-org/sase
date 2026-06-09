---
create_time: 2026-06-09
updated_time: 2026-06-09
status: research
---

# New-User Onboarding Recommendations For SASE

## Question

Bryan is preparing to publish a blog post about SASE. What are the few highest-priority improvements that would make
SASE easier for cold readers to digest, install, and use?

## Bottom Line

The product story is strong, and several previously identified launch blockers have been fixed (`sase doctor`,
`sase version`, published `sase-core-rs` wheels). The remaining new-user problem is mostly packaging the on-ramp:

1. **Publish the current `sase` package and make the README install path true.**
2. **Publish and route all beginner CTAs to one tested 15-minute quickstart.**
3. **Make provider readiness explicit before the first `sase run`.**
4. **Compress first-contact vocabulary to a three-concept mental model.**
5. **Fix terminal self-discovery papercuts that make the product feel unfinished.**

Do these before pointing blog readers at SASE. Larger orchestration features can wait; they do not decide whether a new
reader reaches a first successful run.

## Verification Notes

This consolidates two independent research notes created on 2026-06-09:

- `sdd/research/202606/new_user_digestibility_improvements.md`
- `sdd/research/202606/new_user_onboarding_improvements.md`

I rechecked the highest-leverage facts against the current checkout, live CLI output, and current PyPI metadata because
the two notes conflicted on public package state.

Current state as verified on 2026-06-09:

| Area | Verified state | Onboarding implication |
| --- | --- | --- |
| Public `sase` package | PyPI latest is still `0.1.0`; metadata is sparse and does not include the current Rust-core dependency. | `uv tool install sase` installs old February behavior unless a new release is published. |
| Local checkout | `pyproject.toml` says `0.1.3`; local `sase version` reports `0.1.3+...` with `sase-core-rs 0.1.2`. | Docs and local CLI describe newer behavior than public install delivers. |
| `sase-core-rs` | PyPI latest is `0.1.2`, with current platform/Python classifiers and wheels. | The old "core package not published" blocker is resolved. |
| `sase-github` / `sase-telegram` | Both exist on PyPI at `0.1.0`; Telegram was published on 2026-06-09. | Optional integrations exist, but they should not be on the first path. |
| CLI diagnostics | `sase doctor`, `sase doctor -C llm.default`, and `sase version` exist. | Lean on them in onboarding instead of speccing new diagnostics from scratch. |
| CLI help | Bare `sase` exits with an argparse required-command error; `sase --help` lists 40 flat commands; `sase run --help` omits the prompt positional. | Users who test the terminal surface before reading docs hit unnecessary doubt. |
| Plugin guidance | Current `sase plugin doctor` no longer recommends the stale `sase[github]` extra. | Drop that older finding; keep plugin install guidance as a lower-priority smoke-test item. |
| License file | `pyproject.toml` declares MIT, but no root `LICENSE`/`COPYING` file is tracked. | Small credibility issue for an OSS launch. |

## High-Priority Recommendations

### P0. Publish current `sase` and split user install from contributor setup

The README still routes everyone through a contributor install:

```bash
uv venv .venv
source .venv/bin/activate
just install
sase core health
sase ace
```

That path requires a checkout, `uv`, `just`, and the `[dev]` toolchain. It is the wrong first instruction for a blog
reader. Meanwhile, the package meant for a one-command install is stale on PyPI.

Concrete work:

- Publish current `sase` after verifying the `sase-core-rs>=0.1.1,<0.2.0` dependency resolves cleanly.
- Smoke-test a clean install with:

  ```bash
  uv tool install sase --python 3.12
  sase version
  sase doctor
  sase run --help
  ```

- Make the README headline path a user install:

  ```bash
  uv tool install sase --python 3.12
  sase version
  sase doctor
  ```

- Move `uv venv` / `just install` under "Install from source" or "Contributors".
- Add release metadata before publishing if feasible: README, project URLs, classifiers, maintainers, and keywords.

Success criteria:

- A public install gets the current command surface, not `0.1.0`.
- The README no longer asks normal users to clone the repo or install dev tooling.
- A clean-machine install can reach `sase doctor` without source checkout knowledge.

Why this is first: if the launch post sends interested users to stale behavior, the project loses trust before the
docs or feature set can help.

### P0. Publish one tested 15-minute quickstart and route every CTA to it

`docs/blog/posts/hello-sase-your-first-15-minutes.md` is the strongest existing onboarding asset: it is practical,
gentle with vocabulary, and end-to-end. It is also `draft: true`, absent from `mkdocs.yml`, absent from the README, and
not surfaced from the docs home.

Concrete work:

- Undraft the quickstart only after the public install path is true.
- Add a top-level "Getting Started" nav section above "The Basics".
- Link the quickstart from:
  - README first screen or immediately after the install block;
  - docs home first CTA row;
  - blog index;
  - series hub;
  - launch essay.
- Replace source-install setup in the quickstart with the public install plus `sase doctor`.
- Make the first run low-risk and explicit about the target workspace:

  ```bash
  sase run "#cd:$(pwd) summarize what this repository does; do not change files"
  sase agents status
  ```

- Put the first edit task after the user has seen an agent record:

  ```bash
  sase run "#cd:$(pwd) make a tiny documentation-only improvement and explain the diff"
  ```

Success criteria:

- A reader can find exactly one beginner path from README, docs home, and the blog post.
- The quickstart starts with install, readiness, one safe run, and one visible artifact.
- Reference pages remain available but are no longer the first path.

Adjacent tools follow this pattern: Claude Code's quickstart walks prerequisite, install, login, first session, first
question, and first change; Codex CLI docs lead with install, run, sign-in, and upgrade; Gemini CLI and OpenCode put
quick install/configuration before reference material.

### P0. Make provider readiness visible before the first run

SASE orchestrates existing agent CLIs; it is not itself an LLM runtime. The README lists supported providers, but the
onboarding path does not clearly tell a beginner to install and authenticate at least one provider before `sase run`.

Current `sase doctor -C llm.default` can report the selected provider and executable path. That is useful, but onboarding
should make it the explicit gate before first run and should make the failure path actionable.

Concrete work:

- Add a short "Bring one coding-agent CLI" prerequisite to README and the quickstart.
- Keep it minimal: one install/auth smoke command or link each for Claude Code, Codex, Gemini CLI, Qwen Code, and
  OpenCode.
- In `sase doctor`, make "no usable provider detected" a clear beginner warning with the next command or docs link.
- If auth can be checked without making an LLM call for a provider, surface that; otherwise say "executable found,
  auth not verified" rather than implying readiness.

Success criteria:

- Before running `sase run`, a user knows which provider SASE selected.
- If no provider is ready, `sase doctor` tells them exactly what to install or authenticate.
- The quickstart can say "do not continue until the provider row is OK or understood."

## P1 Digestibility Work

### Compress the mental model to three concepts

The current first-contact surfaces are accurate but noun-heavy: ACE, AXE, XPrompts, ChangeSpecs, Memory, SDD, Beads,
ProjectSpecs, mentors, chops, workflows, and plugins appear before a beginner has a successful run.

Use this beginner model before the full glossary:

1. **Workspace target**: where the agent works, such as `#cd:$(pwd)` or a known project ref.
2. **Agent record**: the durable run artifact SASE tracks while the provider CLI works.
3. **Work record**: the review/planning object when work becomes durable engineering state, such as a ChangeSpec or
   bead.

Concrete work:

- Add a "Three concepts to start" box near the top of README and docs home.
- Move the full "Core pieces" inventory below install/quickstart links.
- Create `docs/glossary.md` with one-line user-facing translations for the core dozen terms.
- For whimsical/internal terms, translate first and name second:
  - ACE = terminal control surface;
  - AXE = background automation daemon;
  - XPrompt = reusable prompt/workflow spec;
  - ChangeSpec = durable CL/PR-sized work record;
  - Beads = dependency-aware work items;
  - SDD tiers = sized planning artifacts.

### Trim README from inventory to on-ramp

Recommended README shape:

1. Value proposition.
2. Requirements: Python, `uv`, one authenticated provider CLI.
3. Public install.
4. `sase doctor`.
5. One safe first run.
6. Three to five next links: Quickstart, CLI reference, ACE guide, provider setup, contributing.

Move the current 35-command "Useful first commands" block and long operational-model prose to docs/reference pages. A
launch README should not require readers to triage every subsystem before trying the product.

### Surface a beginner architecture page earlier

`docs/architecture.md` is currently under "Beyond the Basics" and is implementation-boundary oriented. Keep that page,
but add or extract a shorter "How SASE fits together" page next to the quickstart. It should explain the loop:

blog reader -> install SASE -> confirm provider -> launch agent -> inspect agent record -> graduate to ChangeSpec/bead
workflow.

### Give ACE a first-run empty state

If a new user opens `sase ace` before creating projects, ChangeSpecs, or agents, blank tabs make the app feel inert.
Add lightweight coaching in empty states:

- "No agents yet. Try `sase run \"#cd:$(pwd) explain this repo; do not change files\"`."
- "No ChangeSpecs yet. Run a first agent or initialize a project."
- "Press `?` for help."

This can reuse existing help surfaces; it does not need a new tutorial engine.

## P2 Credibility And Terminal Polish

- Add the missing root `LICENSE` file for the declared MIT license.
- Improve `sase run --help` so usage shows the prompt positional and includes copyable examples.
- Make bare `sase` print a start-here hint instead of only an argparse error.
- Group `sase --help` around "start here" commands (`doctor`, `run`, `ace`, `agents status`, `init`) before advanced
  automation and integration commands.
- Add a comparison/FAQ page for predictable launch questions:
  - Why not just use Claude Code/Codex/Gemini directly?
  - Why not tmux plus git worktrees?
  - What does SASE sandbox? Be explicit that workspace clones are concurrency isolation, not a security boundary.

## Suggested Pre-Blog Work Queue

Do before the post:

1. Publish current `sase`; smoke-test clean `uv tool install`.
2. Rewrite README quickstart around public install, `sase doctor`, one provider prerequisite, and one safe first run.
3. Undraft and wire the 15-minute quickstart into nav, README, docs home, blog index, series hub, and launch essay.
4. Improve provider-readiness messaging in docs and `sase doctor`.
5. Fix `sase run --help`; optionally improve bare `sase` and top-level help grouping.
6. Add the three-concept mental model and user glossary.
7. Add `LICENSE`.

Defer until after the post:

- Promoting every blog-series draft.
- Making Telegram/mobile/editor integrations launch pillars.
- Building new orchestration features that do not shorten the first successful run.
- Expanding reference docs before the quickstart and install funnel are real.

## Source Links

Internal evidence:

- `README.md`
- `docs/index.md`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `docs/cli.md`
- `docs/llms.md`
- `mkdocs.yml`
- `pyproject.toml`
- `src/sase/main/parser.py`
- `src/sase/main/parser_commands.py`
- `sdd/research/202606/sase_install_use_understand_readiness_consolidated.md`
- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/sase_blog_series_structure_consolidated.md`
- `sdd/research/202606/sase_doctor_command_consolidated.md`

External evidence:

- PyPI `sase`: https://pypi.org/pypi/sase/json
- PyPI `sase-core-rs`: https://pypi.org/pypi/sase-core-rs/json
- PyPI `sase-github`: https://pypi.org/pypi/sase-github/json
- PyPI `sase-telegram`: https://pypi.org/pypi/sase-telegram/json
- Claude Code quickstart: https://code.claude.com/docs/en/quickstart
- OpenAI Codex CLI docs: https://developers.openai.com/codex/cli
- Gemini CLI README: https://github.com/google-gemini/gemini-cli
- OpenCode docs: https://opencode.ai/docs/
- uv tool docs: https://docs.astral.sh/uv/concepts/tools/
- Diataxis: https://diataxis.fr/
