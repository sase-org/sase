---
plan: sdd/epics/202605/init_memory.md
---
 The way that we inform sase about which sibling workspace directories it should use currently is to include the paths of
all of them in every agent prompt. This is not great since every prompt is polluted with this information and the
provided sibling workspace directories are not prepared properly (e.g. by stashing any uncommitted file changes,
checking out the `master` branch, syncing the repo, etc...).

- I want to start generating the memory/short/sase.md file using a new `sase init memory` command. This file should
  start including a section dedicated to sibling repos.
- Each sibling repo listed in the memory/short/sase.md file should have a good description, which should be retrieved by
  reading a new (required for every configured sibling repo) `description` sibling configuration field.
- This sibling section in the memory/short/sase.md file should inform the agent that, if it needs to make changes in one
  of these sibling repos, it MUST run the `sase workspace open -p <sibling_repo> <workspace_num>` command (where
  `<sibling_repo>` is the name of the sibling repo the agent needs to make changes to and `<workspace_num>` is the
  workspace number currently assigned to the agent--this should be the same workspace number that was claimed for this
  agent for the primary repo), which will output the path of the workspace directory the agent MUST use for that sibling
  repo.
- This command should not only re-generate the memory/short/sase.md file, but it should also make sure that the
  memory/long/ directory exists and add a new memory/README.md file that briefly describes the purpose of the memory/
  directory.
- Also, the `sase init memory` command should verify that all memory/short/ and memory/long/ markdown files are
  referenced at least once by either the AGENTS.md file or by a different memory/ markdown file that is itself
  referenced at least once in the AGENTS.md file. If not, the command should (after doing the rest of its work) fail
  with a non-zero exit code and output a helpful message to the user.
- Finally, the `sase init memory` command should ensure that the AGENTS.md file exists (touch it otherwise) and that all
  provider-specific, corresponding markdown files (e.g. CLAUDE.md, GEMINI.md, etc...) exist and contain the contents
  `@AGENTS.md`.
- In addition to initializing whatever project is indicated by the directory we ran the command in, the
  `sase init memory` command should also initialize the user's home directory in the same way. Make sure this command
  reads and supports the `use_chezmoi` configuration option (i.e. if `use_chezmoi: true` is set, we should initialize
  the these files in the chezmoi directory--making sure to apply and commit the changes--instead of the home directory)!
- IMPORTANT: The sibling section we generate for a project-specific memory/short/sase.md file should only contain
  siblings that are defined in that project's local sase.yml file. Conversely, the ~/memory/short/sase.md file that this
  command generates should contain only sibling repos that are defined in a global configuration file (like
  ~/.config/sase/sase.yml, for example).
- Once it is ready, make sure to run the `sase init memory` command on this repo.
- Since all external/sibling repos will now be described in one of the memory/short/sase.md files, we should remove the
  memory/long/external_repos.md file (and its reference in the AGENTS.md file).

Can you help me implement all of these requirements? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



Sibling repos for this project are available in workspace-matched directories:
- chezmoi: /home/bryan/.local/share/chezmoi
- core: /home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10
- github: /home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_10
- telegram: /home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_10
- nvim: /home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_10
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`)