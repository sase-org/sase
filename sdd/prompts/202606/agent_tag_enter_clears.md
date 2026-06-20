---
plan: sdd/tales/202606/agent_tag_enter_clears.md
---
 When I use the `N` keymap on the agents tab to delete an agent's group (i.e. move it to the `(untagged)` group), it doesn't seem to work (nothing happens). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Modal?

> When you press N on the tagged agent, does a "Tag: <agent>" modal pop up?

- [x] **Yes, a modal appears** — The tag input modal opens; the problem is what happens after.
- [ ] **No, nothing appears** — No modal at all — the keypress seems to be swallowed.

#### Q2: Modal action

> Once the modal is open, what do you do to remove the tag?

- [x] **Press Enter** — The tag name is pre-filled and selected; I just press Enter expecting it to clear.
- [ ] **Ctrl+D / clear then Enter** — I clear the field (Ctrl+D or delete) and submit an empty value.
- [ ] **N/A — no modal opens** — Pick this if you answered "No" above.

#### Q3: Row type

> Is the selected row a top-level agent or a revealed child/sub-entry of a workflow/family?

- [x] **Top-level (root) agent** — A normal root entry shown by default.
- [ ] **A revealed child entry** — A child step/family member shown after pressing l to reveal children.
- [ ] **Not sure** — I don't know / it varies.

%xprompts_enabled:true