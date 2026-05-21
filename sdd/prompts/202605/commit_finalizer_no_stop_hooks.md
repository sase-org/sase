---
plan: sdd/epics/202605/commit_finalizer_no_stop_hooks.md
---
 Can you help me change the way that sase commits work by removing the need for the sase_commit_stop_hook and
sase_sibling_commit_stop_hook agent stop hook scripts? See the
sdd/research/202605/agent_commit_skill_enforcement_rewrite.md and
sdd/research/202605/sibling_repos_workspace_generalization.md files, which contain research gathered from other agents,
for context and inspiration.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



Make sure to verify your work by running two sase agents, one using the codex/gpt-5.3-codex-spark model and another
using the claude/sonnet model. The first agent should be asked to make some dummy file changes and the second should be
asked to remove those changes. Neither agent should be instructed to commit in the initial prompt (this way we make sure
that we flex sase's new commit infrastructure).

### Additional Requirements

- Make sure to remove the sase hook configuration from agent config files in my chezmoi repo and run the `chezmoi apply --force` command to apply the changes before running the verification agents.
- Make sure that EVERYTHING still works after this project's completion (for example, sase should still commit for all of its supported sibling repos, which should now be defined in configuration).