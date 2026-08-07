---
type: short
parent: AGENTS.md
---

# SASE = Structured Agentic Software Engineering

## Ephemeral `sase_<N>` Workspace Directories

SASE runs agents (like you) from ephemeral workspace directories, which are full clones
of the sase repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories, since
they have their own isolated virtual environments.

IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory)
in any plan files that you generate using your `/sase_plan` skill. The agent(s) that
implement the plan might not run in the same workspace directory as you!

## Repositories

Configured linked and sidecar repositories for this context:

- `sase-github`: GitHub VCS and workspace provider plugin for repository, issue, and PR
  workflows.
- `sase-telegram`: Telegram integration plugin for chat-driven SASE workflows and
  notifications.
- `sase-nvim`: Neovim integration plugin for SASE syntax, completion, and editor
  support.
- `sase--research`: Durable SASE research reports and generated media.

When you need to read or modify files in any repository other than your own workspace
checkout, agents MUST use your `/sase_repo` skill first. This includes configured linked
repos and sidecars, another SASE project's repo, and any GitHub repo not linked to the
current project. Open different-project and unlinked GitHub repos as external repos
through the skill. Use the path it prints as the only path for reads and writes.

This rule applies regardless of transport. Fetching a repository's files or history over
the web — github.com file/blob/raw URLs, raw.githubusercontent.com, repo tarballs, or
GitHub-API/`gh` file-content reads — counts as reading that repo: open it with
`/sase_repo` (unlinked GitHub repos open as external repos, e.g. `gh:<owner>/<repo>`)
and read the local checkout instead. Web tools remain appropriate only for content a
checkout does not contain, such as blog posts, docs sites, and GitHub issue/PR
discussions.

IMPORTANT REMINDER: Do NOT locate, clone, or web-fetch another repo's contents any other
way than by using `/sase_repo`!

## File Discovered Work As Task Beads

Unless your prompt explicitly forbids creating beads (epic phase workers, for example,
must record `PROPOSED FOLLOW-UP:` notes on their own bead instead), you can and SHOULD
capture discovered follow-up work as sase task beads:

- A linter or test is flaky or failing and you did not cause it: file a task bead
  instead of ignoring the failure.
- A sase memory file or skill contains out-of-date information that should be updated:
  file a task bead proposing the update.
- A tool, command, or script this project is responsible for has a bug or a clear,
  objective improvement that would help future agents: file a task bead to fix or
  improve it.

Before creating any task bead, you MUST use `/sase_new_task`. That skill checks every
task status for semantic duplicates, checks in-progress epics for a credible causal
link, and records the issue in the right place. Only a genuinely new task becomes an
`open` draft, and every new task requires an intentional `--size`. Ready task beads are
proposed to the project owner, who either launches an agent to work them or closes them
with a reason.
