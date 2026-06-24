---
plan: sdd/tales/202606/persist_prompt_stash_pin.md
---
 #fork:05m Can you now help me make the `<space>` functionality persist across restarts (of `sase ace` or even this machine)?

- This keymap currently adds a "+" character to the prompt stash entry. Let's start adding a pin emoji / icon instead.
- We will consider a prompt stash entry that has this pin icon to be "pinned".

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Pin vs restore

> When you press <space> on a stash row, should it ALSO restore that prompt into the bar (as the old "restore + keep" did), or is <space> now purely a pin/unpin toggle that does NOT restore?

- [x] **Pure pin toggle (no restore)** — <space> only toggles the persistent pin. Restoring stays on <tab> (restore+pop) and <enter> (restore highlighted). Cleanest separation; pin becomes an organizational flag.
- [ ] **Pin AND restore+keep** — Keep the old behavior (load into bar, stay stashed) AND additionally mark it pinned/persistent. Pin rides along with the existing restore+keep action.

#### Q2: Persist timing

> When should a pin change be WRITTEN to disk?

- [ ] **On <enter> confirm only** — Modal stays presentation-only; pin changes are part of the confirm result and persisted by the app layer. Pressing <esc> discards pin changes. Consistent with current modal design.
- [x] **Immediately on <space>** — Pin persists the instant you press <space>, even if you then <esc>. More "instant pin" feel, but the modal would touch the store directly (breaks current presentation-only contract).

#### Q3: Pinned semantics

> For THIS first step, beyond showing the pin icon and surviving restarts, should "pinned" change any other behavior yet?

- [x] **Icon + persistence only** — Just the pin icon + persistent flag for now. Downstream behavior (protect from delete/pop, sort pinned to top, exclude from cleanup, etc.) is deliberately deferred to a later change.
- [ ] **Also protect/sort pinned now** — Pinned entries should also get protective/sorting behavior in this same change (e.g. cannot be popped/deleted while pinned, or sorted to top). I will follow up to specify exactly which.

%xprompts_enabled:true