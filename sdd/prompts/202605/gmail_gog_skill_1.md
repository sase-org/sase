---
plan: sdd/epics/202605/gmail_gog_skill_1.md
---
 Can you help me give sase agents access to my email using the `gog` tool, which is already installed, configured, and verified to be working on this machine? See the ~/projects/git/home/sdd/research/202605/sase-gmail-agent-access.md file, which contains research performed by previous agents, for context and inspiration.

- This should be implemented using an xprompt skill that is defined in the sase_athena.yml file in my chezmoi repo.
- That skill should inform agents how to use the `gog` command-line tool to read emails from my personal Gmail account.
- Agents shouldn't need to specify my email address explicitly since I have that all configured already.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `xprompt skill`)