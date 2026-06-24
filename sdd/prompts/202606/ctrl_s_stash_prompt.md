---
plan: sdd/tales/202606/ctrl_s_stash_prompt.md
---
 Can you help me remove the functionality of the current `<ctrl+s>` keymap in the prompt input widget? Instead, I want the current `gs` / `<ctrl+g>` keymaps to start using this trigger (`<ctrl+s>`) instead. This will make it easier to stash prompts, which I'm doing more and more frequently lately. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Ctrl+S target

> When you press <ctrl+s> in the prompt input, what should it stash?

- [ ] **Current pane (gs equiv)** — Stash only the active/selected pane — direct replacement for today gs. Recommended.
- [ ] **All panes (gS equiv)** — Stash every non-empty pane and dismiss the bar — like today gS.
- [ ] **Context-aware** — Stash all panes when the stack has >1 pane, otherwise stash the current pane.
- [x] **Other:** "Current pane. Move `gS` to `gs too, since `gs` is now available."

#### Q2: Old bindings

> What should happen to the existing g-prefix stash bindings (gs, gS, and the Ctrl+G s / Ctrl+G S insert-mode equivalents)?

- [ ] **Remove them** — <ctrl+s> becomes the only stash trigger; drop gs/gS and Ctrl+G s/S from the g-prefix table and help.
- [ ] **Keep as aliases** — Add <ctrl+s> as a new trigger but keep gs/gS/Ctrl+G working too. Recommended (lower risk).
- [x] **Other:** "Move the `<ctrl+g>S` keymap to `<ctrl+g>s` and the `gS` keymap to `gs`. We need to keep both of these functionalities since the keymap we are adding only stashes the current prompt input widget."

#### Q3: Stash-all key

> Today gS stashes ALL panes and Ctrl+G p opens the stash panel. If <ctrl+s> only covers current-pane stash, do you want a key for stash-all too?

- [ ] **Keep gS / Ctrl+G p as-is** — Leave stash-all and open-panel on the g-prefix; only current-pane stash moves to <ctrl+s>. Recommended.
- [ ] **Add a ctrl chord for stash-all** — e.g. <ctrl+shift+s> or Ctrl+G S stays — give stash-all its own quick chord too.
- [ ] **Not applicable** — Pick this if you chose All panes or Context-aware for <ctrl+s> above.
- [x] **Other:** "See the previous answers."

%xprompts_enabled:true