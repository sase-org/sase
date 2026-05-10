---
plan: sdd/epics/202604/agent_image_notifications.md
---
  Can you help me make it so anytime an agent modifies or adds a new image file (ex: PNG or JPEG), we attach that image file to the agent completion notification message? 

- we should update the sase-telegram repo to attach that image file to the agent completion message. 
- we should update the retired chat plugin repo to do something similar. 
- we should add support for viewing images in the TUI when running inside the kitty terminal (see recent related sase chats). This functionality should be used to show the image in the notifications file panel and in the agent entry file panel (on the agents tab).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `sase-telegram`)