<div align="center">

# sase

**One developer. A team of coding agents. Tracked, reviewable, repeatable work.**

[![Docs](https://img.shields.io/badge/docs-sase.sh-3b82f6?logo=readthedocs&logoColor=white)](https://sase.sh/)
[![PyPI](https://img.shields.io/pypi/v/sase?logo=pypi&logoColor=white)](https://pypi.org/project/sase/)
[![Python versions](https://img.shields.io/pypi/pyversions/sase)](https://pypi.org/project/sase/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)

<img src="docs/images/sase_overview.png" alt="One developer using SASE to run parallel coding agents in isolated workspaces with tracked, reviewable results" width="830">

</div>

**sase** (pronounced "sassy") turns Claude Code, Codex, Antigravity, Qwen Code, and OpenCode into a coordinated
engineering team. One developer supervises parallel agents in isolated workspaces, with every run tracked, reviewable,
and repeatable.

## Why sase

- Launch, monitor, resume, and archive agent runs from one keyboard-driven TUI (**ACE**).
- Run agents in parallel, each in an isolated numbered workspace clone.
- Keep prompts and multi-step workflows reusable (**XPrompts**) instead of trapped in shell history.
- Track every PR-sized unit of work with status, commits, comments, and review state (**ChangeSpecs**).
- Schedule background and recurring agent work with the **AXE** daemon.

sase does not replace coding agents; it makes agent-driven engineering dependable.

## See it in action

**One prompt, three agents, three models.** A single prompt fans out to Claude, Codex, and Gemini agents with per-agent
model directives and a launch preview.

<img src="demos/out/sase_ace_multi_model_fanout.gif" alt="SASE ACE previewing one prompt fanning out to three coding agents and models" width="830">

**Supervise every run.** The Agents tab shows live status, retry chains, per-agent diffs, chats, and artifacts from one
control surface.

<img src="demos/out/sase_ace_agents_observability.gif" alt="SASE ACE Agents tab showing live runs, retry chains, diffs, chats, and artifacts" width="830">

**Land tracked changes.** The PRs tab follows the ChangeSpec lifecycle from WIP to Submitted, with grouping, search,
commits, and diffs.

<img src="demos/out/sase_ace_prs_pipeline.gif" alt="SASE ACE PRs tab showing ChangeSpecs moving through the review and submission pipeline" width="830">

## Quick start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), and one authenticated agent CLI: Claude Code, Codex,
Antigravity CLI (`agy`), Qwen Code, or OpenCode.

```bash
uv tool install sase   # add a plugin too: uv tool install sase --with sase-github
sase doctor            # check install, config, and provider authentication
sase run "#git:home summarize what this repository does; do not change files"
sase ace               # open the interactive control surface
```

If `sase doctor` reports a missing provider, install and authenticate it, then run the check again; see
[Agent Providers](https://sase.sh/agent_providers/). For full installation details use [INSTALL.md](INSTALL.md), or
follow [Getting Started](https://sase.sh/getting_started/) for the guided path.

## Works with your agents

| Agent                                                         | Status        |
| ------------------------------------------------------------- | ------------- |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | **Supported** |
| [Antigravity CLI (`agy`)](https://antigravity.google/)        | **Supported** |
| [Codex](https://github.com/openai/codex)                      | **Supported** |
| [Qwen Code](https://github.com/QwenLM/qwen-code)              | **Supported** |
| [OpenCode](https://opencode.ai/)                              | **Supported** |

## Learn more

**The complete documentation lives at [sase.sh](https://sase.sh/).**

- [Getting Started](https://sase.sh/getting_started/) — the guided beginner path
- [ACE TUI](https://sase.sh/ace/) — the interactive control surface
- [XPrompts](https://sase.sh/xprompt/) — reusable prompts and multi-step workflows
- [ChangeSpecs](https://sase.sh/change_spec/) — tracked PR-sized units of work
- [AXE Automation](https://sase.sh/axe/) — scheduled and background agent work
- [Spec-Driven Development](https://sase.sh/sdd/) — plans, epics, and beads
- [Plugins](https://sase.sh/plugins/) — GitHub, Telegram, editor, and provider integrations
- [CLI Reference](https://sase.sh/cli/) — every command

## Development

```bash
git clone https://github.com/sase-org/sase
cd sase
uv venv .venv
source .venv/bin/activate
just install
sase core health
```

Run `just check` before submitting changes. See [Development](https://sase.sh/development/) for the full contributor
guide.

## Acknowledgements

sase builds on [Boris Cherny's parallel-agents demonstration](https://x.com/bcherny/status/2007179832300581177),
[Steve Yegge's beads](https://github.com/steveyegge/beads),
[Agentic Software Engineering](https://arxiv.org/abs/2509.06216), and [PDL](https://arxiv.org/abs/2410.19135). See the
[full acknowledgements](docs/acknowledgements.md).

## License

sase is licensed under the MIT License. See [LICENSE](LICENSE).
