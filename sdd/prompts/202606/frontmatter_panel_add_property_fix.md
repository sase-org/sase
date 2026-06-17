---
plan: sdd/tales/202606/frontmatter_panel_add_property_fix.md
---
 When I use the new xprompt Property Panel above the prompt input widget to add a new property, what I tried was
adding a local X prompt, it seems to work but then one of the prompt input widgets that I had open completely
disappeared. When I typed into the TUI, nothing was appearing in the other prompt input widget (the only one that was
visible after adding the `xprompts` xprompt property). I had to hit `<ctrl+c>` twice in order to close both prompt input
widgets to get back to a normal state. Can you help me diagnose the root causes of this issue and fix it?

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Focus target

> After you finish authoring a property (e.g. a local xprompt) in the Frontmatter Property Panel sub-form modal and it saves, where should keyboard focus land? (This is the core of why typing went nowhere — focus currently stays trapped on the panel, which silently reinterprets your keystrokes as nav/edit commands and where Ctrl+C does nothing.)

- [x] **Back to the prompt pane** — Saving returns focus to the active prompt input pane so you can keep typing immediately. Re-open the panel with g= to add more. Best matches what you expected here.
- [ ] **Stay in the panel (current), but fix the trap** — Keep focus in the panel for adding several properties in a row, but make Ctrl+C / Esc reliably exit back to the prompt and stop keystrokes from silently mutating the model.
- [ ] **Stay, only if added from the panel** — If you opened the picker from inside the panel keep focus there; otherwise return to the prompt pane. More nuanced but more complex.

#### Q2: Layout fix scope

> For the disappearing-pane (layout) fix, how aggressive should the scope be?

- [x] **Full fix** — Correct the panel reserved-height accounting (the missing margin row) AND make the prompt stack keep the active pane visible (scroll into view / never render a pane off-screen) when the panel + panes exceed the available height. Most robust.
- [ ] **Accounting-only** — Just fix the reserved-height undercount so the bar sizes correctly. Lighter, but a pane can still be clipped on very short terminals with many panes.

%xprompts_enabled:true