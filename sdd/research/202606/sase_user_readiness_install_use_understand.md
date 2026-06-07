# SASE User Readiness Research: Install, Use, Understand

Date: 2026-06-07

## Question

What parts of SASE need work before a public blog/HN push so new users can install it, try it, and understand why it
matters without already knowing Bryan's workflow?

This note complements:

- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/making_sase_popular_hn_launch_research.md`
- `sdd/research/202605/public_release_process_and_install_research.md`
- `sdd/research/202605/sase_init_onboarding.md`

## Executive Summary

SASE's biggest launch risk is not the blog argument. The argument is credible. The biggest risk is that an interested
reader clicks through and cannot confidently install or run the current project.

P0 before serious public promotion:

1. Publish a current package or remove public `pip install sase` / `uv tool install sase` claims from primary
   quickstarts.
2. Split "user install" from "contributor source install" in README, docs home, and the 15-minute quickstart.
3. Add a visible first-run doctor path: `sase core health`, `sase init -c`, provider/plugin checks, and a version report.
4. Make the first useful workflow explicit about its workspace target, for example `#cd:<path>` or `#git:<project>`.
5. Publish a live try-it page before submitting the essay. The draft `hello-sase-your-first-15-minutes.md` is the right
   shape, but it currently uses the contributor install path and a bare `sase run` that may not target the repo a new
   user expects.

SASE already has strong onboarding building blocks: `sase init -c`, `sase validate`, `sase core health`, `sase plugin
doctor`, rich docs, a working MkDocs site, and real differentiators. The work is to tighten the first 10 minutes.

## Current Public Install State

The current public package state is launch-blocking.

PyPI JSON checks on 2026-06-07:

| Package | Status | Latest | Notes |
| --- | --- | --- | --- |
| `sase` | 200 | `0.1.0` | Old command surface; no project URLs in JSON metadata; no project description on PyPI. |
| `sase-github` | 200 | `0.1.0` | Depends on `sase>=0.1.0`; no project URLs in JSON metadata; no project description on PyPI. |
| `sase-core-rs` | 404 | none | Current local `sase` requires this package, but it is not published. |
| `sase-telegram` | 404 | none | Not publicly installable from PyPI. |

Temporary PyPI smoke test:

```text
uv venv --python 3.12 /tmp/sase-public-smoke.../venv
uv pip install --python /tmp/sase-public-smoke.../venv/bin/python sase
/tmp/.../bin/sase core health
```

Result: install succeeds, but `sase core health` is an invalid command because PyPI installs stale `sase==0.1.0`.
`uv pip show` confirms no `sase-core-rs` package in that environment. The installed top-level commands are the old
surface: `ace`, `axe`, `amend`, `commit`, `init-git`, `notify`, `path`, `plan-approve`, `restore`, `search`, `revert`,
`run`, `user-question`, and `xprompt`.

Implication: before a public launch, either:

- publish a coordinated fresh release, including `sase-core-rs`; or
- make every public quickstart use an explicit source install and warn that PyPI is not current yet.

The first option is much better for traction.

## Local Checkout Observations

Checked in workspace `sase_12` on 2026-06-07.

| Check | Result | User-readiness implication |
| --- | --- | --- |
| `.venv/bin/python -m sase --help` | Works on Python 3.12.11 and shows the current command surface. | The source checkout is usable when the right Python is active. |
| `PYTHONPATH=src python -m sase --help` with ambient Python 3.10 | Fails before help with `ImportError: cannot import name 'UTC' from datetime`. | The docs say Python 3.12+, but a user who misses the `uv --python 3.12` detail gets an opaque traceback. Prefer `uv tool install ... --python 3.12` or a wrapper check. |
| `.venv/bin/python -m sase core health` | OK, including Rust extension probes. | This is a strong install-health primitive. Promote it. |
| `.venv/bin/python -m sase init -c` | `SASE is initialized. No init subcommands need to run.` | Bare init onboarding is now useful and should be part of the first-run flow. |
| `.venv/bin/python -m sase validate` | `ok init --check`, `ok sdd validate`. | Good repo readiness check for contributors. |
| `.venv/bin/python -m sase --version` | Fails with "the following arguments are required: command". | Missing basic support/reporting surface. |
| `.venv/bin/python -m sase run --help` | Shows only `-d`, `-l`, `-r`; does not show the prompt positional. | The command users most need has misleading help because the real prompt handling is pre-argparse. |
| `.venv/bin/python -m sase plugin doctor` | Useful diagnostics, but recommends `uv tool install "sase[github]"`. | That extra is not declared in local `pyproject.toml`; either add the extra or recommend `uv tool install sase --with sase-github`. |

## Documentation And Understanding Gaps

### 1. User install is mixed with contributor install

README "Quick start" and the draft 15-minute quickstart currently lead with:

```bash
uv venv .venv
source .venv/bin/activate
just install
sase core health
```

That is a contributor/source checkout workflow, not the simplest public user workflow. `docs/rust_backend.md` already
has the better user install shape:

```bash
pip install sase
# or
uv tool install sase
```

But this is buried in the Rust backend reference, and it is not currently safe while PyPI is stale.

Recommendation:

- README first screen: "Install as a tool" first, "Develop from source" second.
- Use `uv tool install sase --python 3.12` as the default when the release is ready.
- For plugin installs, use `uv tool install sase --python 3.12 --with sase-github` unless an actual `github` extra is
  added.
- Keep `just install` only in `docs/development.md`, `CONTRIBUTING.md`, and source-install fallback sections.

### 2. The first run should not rely on implicit `#git:home`

The current workspace docs and code normalize bare prompt segments to `#git:home` when no workspace reference is
present. That is powerful for Bryan's daily workflow, but surprising for a first-time user.

The draft quickstart says:

```bash
sase run "add a one-line docstring to the most recently edited Python function in this repo"
```

For a new reader, "this repo" is ambiguous and the command does not show the target workspace reference. The safest
quickstart should include an explicit target:

```bash
sase run "#cd:$(pwd) explain what this repository does without changing files"
```

or, for a write-demo:

```bash
sase git init sase-demo --clone-dir /tmp/sase-demo
sase run "#git:sase-demo add a docstring to hello.py"
```

The exact command can be improved, but the principle matters: the first public example should make the target project
visible in the prompt.

### 3. The docs explain everything before proving anything

The docs are deep and technically strong, but the first-time path exposes many names at once: ACE, AXE, ChangeSpecs,
XPrompts, Beads, SDD, memory, providers, workspaces, commit finalizer, plugins.

That is acceptable after the first win. It is too much before the first win.

Recommendation for front-door content:

- One sentence: "SASE coordinates the agent CLIs you already use."
- One minimal workflow: install, health check, initialize, run one explicit workspace prompt, inspect in ACE.
- One translation table:
  - ACE = TUI
  - AXE = background daemon
  - ChangeSpec = review record
  - XPrompt = reusable prompt/workflow
  - Bead = dependency-aware work item
  - SDD = durable plans/research
- Move the full subsystem list below the quickstart.

### 4. Public package metadata is still underpowered

Local `pyproject.toml` now has project URLs, but it still lacks a `readme`, authors, keywords, and classifiers. PyPI
currently renders the public `sase` and `sase-github` pages with no project description because the old releases had no
readme metadata.

Recommendation:

- Add `readme = "README.md"`.
- Add classifiers for Python 3.12/3.13/3.14, MIT, console, developer tools, OS support, and typing if appropriate.
- Add keywords: `ai-agents`, `coding-agents`, `devtools`, `cli`, `tui`, `agentic-workflows`, `prompt-workflows`.
- Release a version that replaces the stale public package story.

## Strong Existing Surfaces To Build Around

These parts should be promoted, not reinvented:

- `sase core health`: clear Rust-extension health report and JSON mode.
- `sase init -c`: read-only initialization drift check with a good no-op message.
- `sase validate`: combines init drift and SDD validation.
- `sase plugin doctor`: useful same-env plugin diagnostics, despite the incorrect extra recommendation.
- `sase plugin list --verbose`: detailed entry point inventory.
- `docs/index.md`: now has role-based entry cards and a coherent project front door.
- `docs/series/agentic-software-engineering.md`: good series hub shape.
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`: right conversion concept, but needs to be made live and aligned
  with the real public install path.

## External Onboarding Benchmarks

Comparable tools make first-run paths more explicit than SASE currently does.

| Tool | What they do well | SASE read-through |
| --- | --- | --- |
| `uv` tools | `uv tool install` creates an isolated tool environment and puts executables on PATH; tool envs should not be mutated manually. | SASE plugin docs should teach same-environment installs with `--with`, not vague `pip install` commands. |
| Claude Code | Install docs include package-manager choices, `claude doctor`, update/uninstall paths, no-`sudo` warning, platform support, and binary integrity notes. | SASE needs `sase doctor` / `sase --version` / uninstall and support details near the install path. |
| Gemini CLI | Front page has npx instant run, npm, Homebrew, system requirements, auth options, release channels, non-interactive examples, and quick examples. | SASE needs a similarly scannable "install, auth/provider, first command" page. |
| OpenHands CLI | CLI docs lead with `uv tool install openhands --python 3.12`, then first-run configuration and saved settings. | SASE should lead with `uv tool install sase --python 3.12` after release and run a first-run config/provider check. |

## Recommended Work Queue

### P0: before public launch

- Publish current `sase`, `sase-core-rs`, and `sase-github`, or explicitly avoid PyPI install instructions.
- Add `readme` and better package metadata before release.
- Add `sase --version`, including `sase`, `sase-core-rs`, Python, platform, and executable path.
- Fix `sase run --help` so `[PROMPT]` is visible and documented.
- Fix `sase plugin doctor` install guidance: add `sase[github]` extra or recommend `uv tool install sase --with
  sase-github`.
- Publish/update the 15-minute quickstart with an explicit workspace target and a tested install path.
- Add a top-level "Install" or "Quickstart" docs page and link it from README, docs home, and the launch essay.

### P1: first follow-up after launch

- Add `sase doctor` as a single command that runs version, core health, init check, provider CLI/auth checks, plugin
  doctor, and a concise next-step summary.
- Add provider readiness checks for configured/autodetected `claude`, `codex`, `gemini`, `qwen`, and `opencode`.
- Add issue templates for install failure, quickstart failure, provider failure, and docs confusion.
- Add a small examples directory or docs page with a deterministic tiny repo workflow.
- Add an uninstall/reset section: tool uninstall, SASE state locations, config locations, generated workspaces.

### P2: understanding and conversion polish

- Add a "SASE vs tmux/worktrees/Vibe Kanban/OpenHands" page that is factual and not dismissive.
- Add a short animated GIF or screenshot path: prompt -> agent row -> ChangeSpec/review record.
- Add an FAQ with the predictable HN objections.
- Add GitHub topics and a current release page before asking strangers to treat the repo as public.
- Consider a hosted static "demo transcript" page for users who cannot run an agent immediately.

## Sources

Local repo and command checks:

- `README.md`
- `docs/index.md`
- `docs/init.md`
- `docs/rust_backend.md`
- `docs/plugins.md`
- `docs/workspace.md`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `src/sase/xprompt/_parsing_vcs_tags.py`
- `.venv/bin/python -m sase --help`
- `.venv/bin/python -m sase core health`
- `.venv/bin/python -m sase init -c`
- `.venv/bin/python -m sase validate`
- `.venv/bin/python -m sase plugin doctor`
- Temporary PyPI install smoke with `uv pip install ... sase`

External sources checked on 2026-06-07:

- PyPI `sase`: `https://pypi.org/project/sase/`
- PyPI `sase-github`: `https://pypi.org/project/sase-github/`
- PyPI JSON API status for `sase`, `sase-core-rs`, `sase-github`, and `sase-telegram`
- uv tool docs: `https://docs.astral.sh/uv/concepts/tools/`
- Claude Code install docs: `https://code.claude.com/docs/en/getting-started`
- Gemini CLI docs: `https://google-gemini.github.io/gemini-cli/`
- OpenHands CLI install docs: `https://docs.openhands.dev/openhands/usage/cli/installation`

