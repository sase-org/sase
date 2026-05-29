---
plan: sdd/tales/202605/amd_home_agents.md
---
 I want to start managing my ~/AGENTS.md file (the source of truth for this file lives in my chezmoi repo) with
the `sase amd init` command.

- We can accomplish this by adding the `amd_h1_title: "athena - Bryan Bugyi's Home Server"` line to the sase_athena.yml
  file in my chezmoi repo.
- We might need to add support for defining the `amd_h1_title` field in a user sase.yml file (i.e. in the
  ~/.config/sase/sase.yml file). If set in a user sase.yml file, the `amd_h1_title` field should only apply to the
  ~/AGENTS.md file (or chezmoi equivalent). Project-local sase.yml files can override this for their own project (the
  default should still be not to fully manage a project's AGENTS.md file).
- As a part of this change, I want to migrate the ~/memory/short/obsidian.md file to long-term memory and expand the
  Obsidian instructions a bit. For one, mention that we use obsidian-headless (i.e. the `ob` command) on this machine to
  support Obsidian Sync. Also, this file should tell agents about the zorg migration, but also tell them that I have
  already fully switched over to using Obsidian (I don't use zorg anymore). Also, instruct agents that all new ~/bob/
  markdown files (i.e. Obsidian notes) should have the `parent` frontmatter field that links to another markdown file in
  the ~/bob/ directory.
- Run the `sase amd init` command when you are done to update the ~/AGENTS.md file accordingly (verify that this works).

Can you help me implement this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
