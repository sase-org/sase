---
plan: sdd/epics/202606/auto_approve_menu_and_tale_directive.md
---
 The `a` keymap on the agents tab currently toggles whether or not the currently selected agent has its plan auto-approved as a normal plan or as an epic. We do not currently support auto-approval of tales. Can you help me add a new `%t`/`%tale` directive for this and migrate the `%a`/`%approve` directive to `%p`/`%plan`?

As a part of this change we should also add a new model to the TUI for when the user presses the `a` key. Instead of toggling through the options, the `a` keymap should give the user options via this model, which should be selectable via a single key press. I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 

%xprompts_enabled:false
### Questions and Answers

#### Q1: %plan collision

> %plan/%p already exists in the Rust directive registry meaning "Enable plan mode" (but Python ignores it entirely today — it has no runtime effect). You want %a/%approve renamed to %p/%plan. How should we handle the existing %plan?

- [x] **Repurpose %plan as renamed %approve (Recommended)** — %p/%plan becomes the canonical name for what %approve does today: auto-approve the submitted plan as a normal plan. The dead Rust-only "enable plan mode" meaning is dropped. Gives a clean parallel family: %plan / %epic / %tale.
- [ ] **Keep %plan = enable plan mode; pick a different token** — Preserve the existing (latent) %plan = enable-plan-mode meaning and choose a different name/alias for the renamed approve directive. Avoids overloading but breaks your requested %p/%plan naming.

#### Q2: %approve back-compat

> %a/%approve is emitted by `sase bead work` (src/sase/bead/work.py) and documented widely. After renaming to %p/%plan, what happens to the old %a/%approve spelling?

- [ ] **Keep %a/%approve as a hidden deprecated alias (Recommended)** — %p/%plan becomes canonical/documented; %a/%approve still parses to the same behavior so existing saved prompts and generated xprompts keep working. The bead generator + docs switch to %plan. Lowest-risk, fully reliable.
- [ ] **Hard-remove %a/%approve** — %a/%approve become unknown directives (left as literal text). Cleaner registry, but breaks any saved user prompts still using them. Requires updating the bead generator in lockstep.

#### Q3: %time alias

> %t is currently the alias for %time (multi-value scheduling directive; %t:5m is documented). Giving %t to %tale forces %time to give up its short alias. What should %time use?

- [ ] **Drop %t alias; %time keeps long form only (Recommended)** — %time loses its short alias entirely (still usable as %time:5m). %t cleanly becomes %tale. Simplest; only affects the rarely-typed scheduling shorthand. Docs/examples using %t:... get updated.
- [ ] **Give %time a new short alias** — Reassign %time to a different free letter so it keeps a shorthand. Adds a second migration users must learn; no obvious mnemonic letter is free.

---

> **Global Note:** Answered via Telegram

%xprompts_enabled:true