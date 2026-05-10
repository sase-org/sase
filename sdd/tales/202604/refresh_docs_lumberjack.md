---
create_time: 2026-04-30 23:38:35
status: done
prompt: sdd/prompts/202604/refresh_docs_lumberjack.md
---
# Plan: Dedicated `refresh_docs` Lumberjack for SASE Repos

## Goal

Move the existing `sase_refresh_docs` scheduled agent chop out of the shared `run_every` lumberjack and into a dedicated
`refresh_docs` lumberjack. Expand that lumberjack so it can run documentation-refresh checks for each canonical sibling
`sase-*` repo, with a threshold of 25 commits for those repos.

## Current State

- The chop lives in the chezmoi config at `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` under
  `axe.lumberjacks.run_every.chops`.
- The chop invokes `#gh:sase #!sase/refresh_docs`.
- The workflow implementation is in this repo at `xprompts/refresh_docs.yml`.
- That workflow currently assumes the main `sase` repo in two places:
  - marker file: `~/.sase/projects/sase/refresh_docs_marker`
  - nested docs agent prompt: `#gh:sase #sase/docs`
- Canonical local sibling repos matching `sase-*` are:
  - `sase-core`
  - `retired chat plugin`
  - `sase-github`
  - `retired Mercurial plugin`
  - `sase-nvim`
  - `sase-telegram`
- Workspace clones like `retired Mercurial plugin_100` and `sase-telegram_100` are not source repos for this config.

## Design

### 1. Parameterize `#sase/refresh_docs`

Update `xprompts/refresh_docs.yml` to accept repo-specific inputs:

- `project`: marker/project directory name, defaulting to `sase` for backward compatibility.
- `gh_ref`: GitHub workflow reference, defaulting to `sase` for backward compatibility.
- `threshold`: keep the workflow default at 50 so the existing main-repo behavior is unchanged unless a caller opts in.

Use those inputs as follows:

- marker path becomes `~/.sase/projects/{{ project }}/refresh_docs_marker`
- nested docs agent becomes `#gh:{{ gh_ref }} #sase/docs`

This keeps the current main `sase` invocation working while allowing the same workflow to serve every sibling repo.

### 2. Restructure Chezmoi Lumberjack Config

Update `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`:

- Remove `sase_refresh_docs` from the existing `run_every` lumberjack.
- Add a new sibling lumberjack named `refresh_docs`.
- Give it an interval matching the existing scheduled-chop cadence (`interval: 60`).
- Add the original main-repo chop under this lumberjack, still using the workflow default threshold of 50:
  - `sase_refresh_docs`: `#gh:sase #!sase/refresh_docs`
- Add one chop per canonical `sase-*` repo, passing `threshold=25` explicitly:
  - `sase_core_refresh_docs`
  - `retired_chat_plugin_refresh_docs`
  - `sase_github_refresh_docs`
  - `retired_mercurial_plugin_refresh_docs`
  - `sase_nvim_refresh_docs`
  - `sase_telegram_refresh_docs`

Use `#gh:sase-org/<repo>` for the outer VCS ref and for the workflow `gh_ref` input. This is more robust than bare
`#gh:<repo>` because several of these repos do not currently have project files; the GitHub resolver can create/update
project files from the owner/repo form.

Example chop shape:

```yaml
- name: sase_core_refresh_docs
  description: "Run the #!sase/refresh_docs xprompt workflow for sase-core"
  agent: "#gh:sase-org/sase-core #!sase/refresh_docs(project=sase-core, gh_ref=sase-org/sase-core, threshold=25)"
  run_every: 60m
```

### 3. Validation

Run checks in the repos that change:

- In `sase`: `just install` if needed, then `just check` because `xprompts/refresh_docs.yml` changes.
- In chezmoi: `just check` because the chezmoi config changes.

Also run lightweight config/workflow sanity checks:

- `sase axe lumberjack list` or equivalent config-loading command to confirm the new lumberjack and chops parse.
- If available, `sase xprompt explain 'sase/refresh_docs(...)'` or a dry parser command to confirm the workflow input
  syntax is accepted.

Do not run `chezmoi apply --force` unless a commit is made in the chezmoi repo; the memory specifically requires apply
after committing, and this task does not request a commit.

## Risks and Notes

- The docs prompt remains `#sase/docs`, intentionally reusing the main `sase` documentation-review prompt for sibling
  repos that do not define their own `#docs`.
- The marker file must be per repo, otherwise a refresh in one repo suppresses refreshes in another.
- The outer `#gh:sase-org/<repo>` gives the chop-launched wrapper agent the target repo workspace; the workflow's nested
  docs agent also receives the same target via `gh_ref`.
