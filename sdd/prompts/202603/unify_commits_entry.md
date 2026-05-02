---
plan: sdd/tales/202603/unify_commits_entry.md
---
our recent solution for making sure the CHAT and DIFF commit entry lines are correctly populated is wrong I think. We
need to make sure that the experience of committing (regardless of commit method) is exactly the same for agents and
humans who commit by running 'sase commit' directly. This means that all functionality (including adding COMMITS entries
with the appropriate metadata like the diff file and the chat file) needs to be implemented by 'sase commit'. Can you
help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill.
