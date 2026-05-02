---
plan: sdd/plans/202604/init_skills_chezmoi_deploy.md
---
When I run the `sase init-skills` command and I have `use_chezmoi: true` in my sase.yml config, we copy the skill files
to the appropriate chezmoi file paths. Can you help me make it so we also create a git commit, push to the remote (e.g.
GitHub), and run `chezmoi apply` in that case? Think this through thoroughly and create a plan using your `/sase_plan`
skill before making any file changes.

### DYNAMIC MEMORY

- @.sase/memory/long-config.md (matched: `config`, `sase.yml`)
- @.sase/memory/long-external-repos.md (matched: `chezmoi`)
- @.sase/memory/long-generated-skills.md (matched: `init-skills`)
