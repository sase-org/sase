---
plan: sdd/tales/202606/updates_tab.md
---
 #fork:077.w1.w2 Can you now help me rename the "Plugins" tab to "Updates" (so it should be moved to right before the "XPrompts" tab and the numeric keymap should be updated) and add support for a new keymap that runs `sase update` in a way that is plesant in a TUI environment? Also, we should show the installed and latest versions of sase (this repo) and sase-core (sase's Rust core). I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Updates tab scope

> When we rename the "Plugins" tab to "Updates", what happens to the existing plugin catalog browser (browse / install / update / uninstall plugins)? Note: `sase update` (= `uv tool upgrade sase`) already upgrades sase core AND all *already-installed* plugins together, but it does NOT discover/install/uninstall plugins — that only exists in the Plugins browser today.

- [x] **Keep + augment (recommended)** — Updates tab keeps the full plugin catalog/browser AND adds a SASE core section on top: sase + sase-core installed→latest versions plus a key to run `sase update`. One home for keeping core + plugins current; nothing removed.
- [ ] **Slim updates view (replace)** — Updates tab shows ONLY sase + sase-core versions + a key to run `sase update`. Removes TUI plugin discovery/install/uninstall entirely (you would lose the ability to add/remove plugins from the TUI).
- [ ] **Two tabs instead of rename** — Keep a Plugins tab AND add a separate Updates tab (7 tabs total). Contradicts the literal "rename" wording, but offered in case you want both surfaces distinct.

#### Q2: Update run UX

> How should running `sase update` feel inside the TUI (you emphasized pleasant + beautiful)?

- [ ] **Tracked background task (recommended)** — A confirm/preview modal shows the exact `uv tool upgrade sase` command; on confirm it runs as a background task with live streaming output watchable in the Tasks tab, a success/fail toast, and versions refresh in place. Non-blocking; mirrors the existing plugin-update flow.
- [ ] **Focused progress modal** — A dedicated modal opens with a spinner + live log, stays up until the upgrade finishes, then shows a summary (updated X→Y) before you dismiss it. More focused, but blocks interaction with the rest of the TUI while open.
- [ ] **Suspend + inline** — Drop to the terminal and run `sase update` with uv's native output, then resume the TUI. Simplest, full native output, but the TUI is fully suspended during the run.

---

> **Global Note:** Answered via Telegram

%xprompts_enabled:true