---
plan: sdd/epics/202606/automated_semver_releases.md
---
 Can you help me implement a GitHub Actions automated release process for sase, sase-core, sase-github, and sase-telegram? Use the research in the sdd/research/202606/automated_semver_releases.md file, which was created by a previous agent, for context and inspiration. Make sure that GitHub Actions uses release-please / release-plz for each of these repos to release the next appropriate version (depending on the repo and any existing versions that have been published) for each of these repos the next time a PR is submitted for that repo.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

