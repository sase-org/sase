---
plan: sdd/tales/202606/agent_restore_delete_saved_group.md
---
 Can you help me add a new `<ctrl+d>` keymap to the "Agent Restore" panel that is only active when a saved agent group is selected? This keymap should delete the selected saved agent group (after confirming with the user via a nice y/n popup). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  

%xprompts_enabled:false
### Questions and Answers

#### Q1: Delete scope

> The Agent Restore panel has two row categories: "Saved groups" (persisted; group: prefix) and "Recent dismissals" (auto-pruned, cap 10; recent: prefix). Which should ctrl+d be able to delete?

- [x] **Saved groups only** — ctrl+d active only on Saved-groups rows. Matches "saved agent group" literally. Recent dismissals untouched. (Recommended)
- [ ] **Both saved & recent** — ctrl+d deletes whichever is highlighted; recent rows delete from the recent store, saved rows from the saved store. More code (two backend delete paths).

#### Q2: After delete

> After a successful delete, what should happen?

- [x] **Stay in panel, refresh list** — Remove the row in place, re-highlight a sensible neighbor, keep the panel open so the user can delete more. (Recommended)
- [ ] **Close the panel** — Dismiss the whole Agent Restore modal after deleting. Simpler but forces a reopen to delete another.

#### Q3: Confirm popup

> What should the y/n confirmation popup look like?

- [x] **Reuse generic ConfirmActionModal** — Existing y/n modal with title + message + Yes(y)/No(n) buttons. Message includes the group title. Least new code, consistent with quit/kill confirms. (Recommended)
- [ ] **Dedicated styled modal** — New DeleteSavedAgentGroupConfirmModal showing group name, agent count, projects/PRs, and a "cannot be undone" warning. Nicer/safer but more code + CSS + tests.

%xprompts_enabled:true