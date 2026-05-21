---
plan: sdd/tales/202605/agents_refresh_on_notifications.md
---
 Now that we have optimized the way that active agents are loaded from disk (see the sase-3s epic bead), we should be able to refresh the list of agents shown on the agents tab more frequently without blocking the UI thread for too long. Can you help me start refreshing the agents tab on every new notification that comes on every auto-refresh (which I have configured to occur every 10s)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
