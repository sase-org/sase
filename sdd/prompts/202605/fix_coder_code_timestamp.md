---
plan: sdd/tales/202605/fix_coder_code_timestamp.md
---
 Why are we using ".coder" instead of ".code" (see the `sase ace` snapshot in the ~/tmp/scratch/snapshot.txt
file)? Also, the "CODE" timestamp entry in the agent metadata panel on the "Agents" tab of the `sase ace` TUI is
missing. I think we may have missed something when reverting the "Independent Plan-Chain Agents" feature (see related
sase chats and the sase-1s and sase-1t epic beads for context--make sure changes associated with these have been
reverted thoroughly). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
