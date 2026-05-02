---
plan: sdd/tales/202603/fix_sibling_stop_hook.md
---
I don't think the `sase_sibling_*` hook is working. Can you test it by making some random changes in plug-in repos and
making sure that it fails and, if not, diagnose the root cause of the issue and fix it? This hook should fail if any
changes have been made to sibling repos, but it MUST not force the agent to commit. It should ask the agent if it made
those changes, and tell it to commit them using `/sase_git_comit` if so (this script does NOT need to be VCS-agnostic).
Since agents can decline to commit, we need to make sure this hook runs exactly once per session (You'll need to figure
out how to make this work. I'm thinking some combination of environment variables and having the hook script write
marker / temporary files to track if it has run this session or not.). Think this through thoroughly and create a plan
using your `/sase_plan` skill.

IMPORTANT: This script should only fail when the plugin repos primary workspace directory has changes (we shouldn't
check ephemeral workspace directories like ../sase-telegram_100).
