---
plan: sdd/tales/202605/notification_panel_sort_within_groups.md
---
 Notifications in the notification panel are currently grouped by severity. Can you help me start sort those groups by the time they were received, with the most recently received notification showing up at the top? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


%xprompts_enabled:false
### Questions and Answers

#### Q1: Sort behavior

> How should the notification panel be sorted?

- [ ] **Sort groups by recency + within groups by recency** — Keep severity grouping (priority/errors/inbox/muted), but reorder groups so the one with the most recent notification appears first, and sort notifications within each group by timestamp descending.
- [x] **Sort within groups only; keep fixed group order** — Keep current group order (priority then errors then inbox then muted), but sort notifications within each group by timestamp descending.
- [ ] **Drop grouping; flat list sorted by time** — Abandon severity grouping entirely; show one flat list sorted by timestamp descending.

%xprompts_enabled:true