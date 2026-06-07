# SASE Install, Use, Understand Readiness Research

Date: 2026-06-07

## Question

What parts of SASE most need work before a public blog post so that interested readers can install, use, and understand
the project without already knowing Bryan's workflow?

This consolidates two same-day research notes from independent agents. I verified the highest-impact claims directly and
corrected the main conflict: today's public PyPI package can install, but it is stale and not the current SASE described
by the repo/docs.

## Bottom Line

SASE's biggest launch risk is not the essay premise. The risk is that a curious reader reaches the project and cannot
get a current, confidence-building first run.

The release funnel has to be fixed before a broad post points strangers at an install command:

1. Publish a coordinated current release: `sase`, `sase-core-rs`, and first-party plugins such as `sase-github`.
2. Make the documented "normal install pulls a prebuilt wheel" path true, then smoke-test it in clean environments.
3. Split the public user install from the contributor/source install.
4. Publish and link the 15-minute quickstart, using an explicit workspace target.
5. Add a single readiness path that reports versions, Rust-core status, init drift, provider CLI availability, and plugin
   environment guidance.

SASE already has strong pieces for this: `sase core health`, `sase init -c`, `sase validate`, `sase plugin doctor`,
`sase plugin list --verbose`, a good docs home, an overview image, and a draft first-15-minutes post. The work is mostly
release hygiene, first-run routing, and concept compression.

## Verification Notes

### Corrected PyPI finding

Both prior notes identified the install/release state as the key blocker, but one overstated the live public install
failure. Current ground truth on 2026-06-07:

| Check | Result | Implication |
| --- | --- | --- |
| `https://pypi.org/pypi/sase/json` | `sase` latest is `0.1.0`; metadata has empty description, no project URLs, no classifiers, no keywords, and no `sase-core-rs` dependency. | `uv pip install sase` succeeds today, but installs an old command surface. |
| Clean PyPI smoke: `uv pip install sase` then `sase core health` | Installs `sase==0.1.0`; `core` is not a valid command. | Public PyPI does not provide current SASE. |
| Local `pyproject.toml` | Current source requires `sase-core-rs>=0.1.1,<0.2.0`. | A current release cannot resolve unless `sase-core-rs` is published. |
| `https://pypi.org/pypi/sase-core-rs/json` | HTTP 404. | The current documented wheel dependency is not on PyPI. |
| Clean source smoke: `uv pip install --no-cache --no-sources -e .` | Fails because `sase-core-rs` is not found. | A single-repo source install fails unless `../sase-core` plus `cargo` is available or the wheel exists. |
| `https://pypi.org/pypi/sase-github/json` | `sase-github==0.1.0` exists but has similarly sparse metadata. | Plugin release/metadata should be coordinated with core. |
| `https://pypi.org/pypi/sase-telegram/json` | HTTP 404. | Telegram should be framed as optional/local until published. |

So the precise P0 is: public PyPI is stale today, and releasing current SASE without publishing `sase-core-rs` would make
the install dependency-unsatisfiable. Do not use a `pip install sase` or `uv tool install sase` blog CTA until the
current release is published and smoke-tested.

### Local checkout checks

Verified in this workspace:

- `.venv/bin/python -m sase --help` shows the current command surface.
- `.venv/bin/python -m sase core health` succeeds and reports the Rust extension path, probes, Python, and platform.
- `.venv/bin/python -m sase init -c` says SASE is initialized and checked `amd`, `memory`, `sdd`, and `skills`.
- `.venv/bin/python -m sase validate` reports `ok init --check` and `ok sdd validate`.
- `.venv/bin/python -m sase --version` fails because there is no top-level version flag.
- `.venv/bin/python -m sase lsp --version` works, but only for the xprompt LSP server.
- `.venv/bin/python -m sase run --help` omits the prompt positional and only shows flags.
- `.venv/bin/python -m sase plugin doctor` is useful, but still recommends `uv tool install "sase[github]"` while
  local `pyproject.toml` does not define a `github` extra.

## Findings

### I-1. Public install is not launch-ready. Severity: blocker.

The README and Rust backend docs describe a normal install where a prebuilt `sase-core-rs` wheel is pulled
automatically. That is the right user story, but it is not true on public indexes today. Current PyPI `sase==0.1.0`
installs an old CLI with no `core` command, while current source requires a `sase-core-rs` package that PyPI does not
have.

Fix:

- Publish `sase-core-rs` wheels first.
- Bump and publish `sase`; PyPI cannot replace the existing `0.1.0`.
- Publish/update `sase-github` alongside it, and decide whether `sase-telegram` is public or explicitly optional.
- Smoke-test `uv tool install sase --python 3.12`, `pip install sase`, `sase --help`, `sase core health`, `sase init -c`,
  and one read-only `sase run` setup check in clean Linux and macOS environments.

### I-2. User install and contributor install are mixed. Severity: high.

README "Quick start" and the draft 15-minute post lead with:

```bash
uv venv .venv
source .venv/bin/activate
just install
```

That is a source/contributor workflow. For strangers arriving from a blog post, the first install path should be a tool
install after the release exists:

```bash
uv tool install sase --python 3.12
```

Keep `just install` in development docs and source fallback sections. If the wheel is not published by launch time, the
blog CTA must explicitly say this is a source checkout path and document the `../sase-core` plus Rust-toolchain
requirement.

### I-3. Package metadata undersells the project. Severity: medium.

The old PyPI releases render as nearly empty package pages. Local `pyproject.toml` has project URLs now, but still lacks
`readme`, authors, classifiers, and keywords. This matters because PyPI is often the second click after a launch post.

Fix before release:

- Add `readme = "README.md"`.
- Add Python, license, console/developer-tools, OS, and typing classifiers.
- Add search keywords such as `ai-agents`, `coding-agents`, `devtools`, `cli`, `tui`, `agentic-workflows`, and
  `prompt-workflows`.

### I-4. First-run readiness checks are strong but fragmented. Severity: high.

The building blocks are good, but new users should not have to discover them independently:

- `sase core health` checks the Rust extension well.
- `sase init -c` gives a concise initialization drift check.
- `sase validate` combines init and SDD validation.
- `sase plugin doctor` explains same-environment plugin inspection.

Missing is one launch-friendly command, probably `sase doctor`, that runs the above plus:

- top-level `sase` version, `sase-core-rs` version, Python, platform, executable path, and config path;
- provider CLI/auth detection for Claude Code, Codex, Gemini, Qwen, and OpenCode;
- a short "next command to run" success path.

### I-5. Plugin install guidance has a concrete mismatch. Severity: medium.

`sase plugin doctor` recommends `uv tool install "sase[github]"`, but no `github` extra exists in local
`pyproject.toml`. Either add the extra or change the recommendation to the uv tool pattern for same-environment
packages:

```bash
uv tool install sase --python 3.12 --with sase-github
```

The uv docs specifically support `--with` for installing related packages into the same tool environment.

### U-1. The right quickstart exists, but it is not public. Severity: high.

`docs/blog/posts/hello-sase-your-first-15-minutes.md` is the right conversion artifact, but it is marked `draft: true`
and is absent from `mkdocs.yml` nav. The blog index points at the launch essay, not the hands-on quickstart.

Fix:

- Make the quickstart live when the install path is real.
- Link it from README, docs home, blog home, and the launch essay.
- Put it one click from the first viewport of the docs home.

### U-2. The first `sase run` example should name the workspace. Severity: high.

Bare prompts are normalized to `#git:home`. That is useful for Bryan's workflow, but surprising for a new user reading
"this repo" in a quickstart. The first public example should make the target visible:

```bash
sase run "#cd:$(pwd) explain what this repository does without changing files"
```

or, for a managed workspace demo:

```bash
sase git init sase-demo --existing /path/to/repo --clone-dir /tmp/sase-demo
sase run "#git:sase-demo explain the project structure"
```

The exact demo can change, but the principle should not: the first run should not depend on implicit `#git:home`.

### U-3. `sase run --help` hides the most important argument. Severity: medium.

The help output for the command most readers will try shows `-d`, `-l`, and `-r`, but not `[PROMPT]`, even though the
top-level help example says `sase run "Your question here"`. This is small but high-friction.

Fix the argparse/help surface so `sase run [PROMPT]` is visible, with examples for `#cd:<path>`, `#git:<project>`, and
`--resume`.

### U-4. ACE has help; it needs first-launch discoverability. Severity: medium.

One prior agent claimed there was no in-app help. That is incorrect. `?` is bound to `show_help`, and the per-tab
`HelpModal` exists. The issue is discoverability on an empty/cold TUI.

Fix:

- Add empty-state text on the PRs/Agents/AXE tabs with the first useful action and "press ? for help".
- Consider a first-launch banner after `sase ace` if no ChangeSpecs or agents exist.

### UN-1. The vocabulary arrives too early. Severity: high.

The README explains SASE using many project-specific names before a user has seen a win: ACE, AXE, XPrompt,
ChangeSpec, SDD, Beads, AMD, mentors, chops, memories, workspaces, and more. That vocabulary is real product surface,
but it should be layered.

Fix:

- Put a "three concepts to start" box above deeper docs: workspace target, agent run, ChangeSpec.
- Publish a complete `docs/glossary.md` generated from or aligned with `memory/short/glossary.md`.
- Link glossary anchors from README, docs home, quickstart, and major reference pages.

### UN-2. The docs are strong references, but the on-ramp is steep. Severity: medium-high.

Docs home is much better than a raw reference dump, and the overview image is already surfaced on README and docs home.
The issue is the next click: several Basics pages are large reference documents (`ace.md`, `xprompt.md`,
`configuration.md`, `llms.md`) that expect commitment.

Fix:

- Add short "Quick overview" intros to ACE, AXE, XPrompts, Beads, memory, and configuration.
- Keep the detailed references, but make the first screen answer: what problem, minimal command, what to read next.
- Keep `docs/architecture.md` in "Beyond the Basics", but echo its one-screen mental model earlier in the Basics path.

### UN-3. Optional personal integrations should read as optional. Severity: medium.

Chezmoi, Telegram/mobile, and Bob-vault references are useful for power users, but they can make SASE read like one
person's private system. The public path should be provider- and dotfile-manager-agnostic.

Fix:

- Label chezmoi, Telegram, mobile, and Bob-related workflows as optional integrations.
- Keep them out of the first install/use/understand path unless the reader explicitly opts in.

## Prioritized Work Queue

### P0 before a public launch post

1. Publish `sase-core-rs` wheels and a bumped current `sase`; smoke-test the real install path on Linux and macOS.
2. Update package metadata before publishing.
3. Choose the launch CTA based on reality: `uv tool install sase --python 3.12` only after the release is green;
   otherwise a clearly labeled source checkout path.
4. Make the 15-minute quickstart public and linked from README, docs home, blog home, and the essay.
5. Change the first quickstart run to use an explicit workspace reference.

### P1 within launch week

1. Add top-level `sase --version`.
2. Fix `sase run --help`.
3. Add `sase doctor` or make `sase core health` route users to init, provider, and plugin checks.
4. Fix plugin doctor install guidance or add a real `github` extra.
5. Add ACE empty-state guidance and advertise `?`.
6. Publish/link a glossary.

### P2 follow-up polish

1. Add provider setup/readiness docs for each supported agent CLI.
2. Add a minimal config section that says what can be ignored on day one.
3. Add a concise comparison/differentiation page for SASE vs. direct agent CLIs, tmux/worktrees, OpenHands, and similar
   tools.
4. Consider `musllinux` wheels for container/Alpine users once the normal wheel release exists.
5. Add uninstall/reset/support sections: tool uninstall, SASE state locations, config locations, generated workspaces,
   and what to include in bug reports.

## Strong Existing Surfaces To Preserve

- `sase core health`: excellent Rust-extension readiness check.
- `sase init -c` and `sase validate`: concise drift/readiness checks.
- `sase plugin doctor` and `sase plugin list --verbose`: useful same-environment diagnostics.
- `docs/index.md` and `docs/images/sase_overview.png`: already provide a better front door than most internal tools.
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`: the right public conversion artifact once live and aligned with
  release reality.
- ACE `?` help modal: exists and should be promoted, not rebuilt.

## Open Questions

- Are `sase-core-rs` wheels already built in `sase-core` CI and only unpublished, or does the release matrix still need
  implementation work?
- Should `sase doctor` live as a new command, or should `sase core health` grow a broader "first-run" mode?
- Which first-party plugins should be part of the launch install story: only `sase-github`, or also Telegram/mobile?
- What exact read-only first-run prompt best demonstrates value without risking a noisy diff?

## Sources

Local verification:

- Transcripts: `~/.sase/chats/202606/sase-ace_run-260607_061708.md` and
  `~/.sase/chats/202606/sase-ace_run-260607_061716.md`
- `README.md`
- `pyproject.toml`
- `Justfile`
- `mkdocs.yml`
- `docs/index.md`
- `docs/blog/index.md`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- `docs/rust_backend.md`
- `docs/development.md`
- `docs/xprompt.md`
- `docs/workspace.md`
- `docs/llms.md`
- `src/sase/default_config.yml`
- `src/sase/main/parser_commands.py`
- `src/sase/ace/tui/bindings.py`
- `src/sase/ace/tui/modals/help_modal/`
- Commands: `sase core health`, `sase init -c`, `sase validate`, `sase --version`, `sase lsp --version`,
  `sase run --help`, `sase plugin doctor`, clean PyPI install smoke, and clean source install smoke.

External checks on 2026-06-07:

- PyPI `sase`: https://pypi.org/project/sase/ and https://pypi.org/pypi/sase/json
- PyPI `sase-core-rs`: https://pypi.org/project/sase-core-rs/ and https://pypi.org/pypi/sase-core-rs/json
- PyPI `sase-github`: https://pypi.org/project/sase-github/ and https://pypi.org/pypi/sase-github/json
- PyPI `sase-telegram`: https://pypi.org/project/sase-telegram/ and https://pypi.org/pypi/sase-telegram/json
- uv tool docs: https://docs.astral.sh/uv/concepts/tools/
- Claude Code setup docs: https://code.claude.com/docs/en/getting-started
- Gemini CLI docs: https://google-gemini.github.io/gemini-cli/
- OpenHands CLI install docs: https://docs.openhands.dev/openhands/usage/cli/installation
