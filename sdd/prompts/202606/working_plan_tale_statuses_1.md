---
plan: sdd/tales/202606/working_plan_tale_statuses_1.md
---
 Can you help me start using new `WORKING TALE/PLAN` statuses for "code" agents?

- This way we can give "plan" agents the `PLAN APPROVED` status when the plan is approved, which is the status it should keep from that point forward (similar to what we do with the `ANSWERED` status for agents that asked questions that were answered by the user).
- This is useful in that it will allow us to show the user a new status (plan approved, but the coder agent hasn't been started / rendered yet--it can take a few seconds).
- Make sure you give these new statuses good, distinct colors.
- See #sshot for an example of what agent statuses look like now so you can compare that against the requirements above.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Core gap

> I found PLAN APPROVED and TALE APPROVED statuses already exist, and an optimistic override is ALREADY set on the plan row the instant a plan is approved (mirroring the ANSWERED flow). The plan/root row lifecycle today is PLAN then PLAN APPROVED (while coder runs) then PLAN DONE. What is the specific gap you want fixed?

- [x] **Sticky approved status on plan row** — After approval the plan/root agent should reliably show and KEEP PLAN APPROVED / TALE APPROVED through the few-second gap before the coder agent renders, rather than briefly showing PLAN / DONE / something else.
- [ ] **Brand-new transitional status** — Introduce a NEW separately-named status meaning approved-but-coder-not-yet-started, distinct from the existing PLAN APPROVED, shown during that gap only.
- [ ] **Mostly just colors** — Behavior is basically fine; the real ask is giving the approved statuses good, distinct colors.

#### Q2: Status names

> What status TEXT should be displayed? Your title said WORKING TALE/PLAN, but the bullets reference PLAN APPROVED.

- [ ] **Reuse PLAN APPROVED / TALE APPROVED** — Keep the existing status strings; just make them apply and stick correctly + distinct colors.
- [x] **New: WORKING PLAN / WORKING TALE** — Introduce new status text like WORKING PLAN and WORKING TALE for the approved-coder-pending state.
- [ ] **Other new names** — Use different new status text (I will specify in notes).

#### Q3: Colors

> Distinct colors: PLAN APPROVED and TALE APPROVED currently render in the SAME teal (#00D7AF). How do you want colors handled?

- [ ] **Pick good distinct colors for me** — Choose visually-distinct colors that fit the palette and avoid collisions (RUNNING gold #FFD700, ANSWERED azure #5FD7FF, EPIC/LEGEND, etc.).
- [ ] **I will specify colors** — I will provide exact hex values / preferences in notes.
- [x] **Other:** "Make them distinct, but similar. Also, make sure to do the same for the new `WORKING PLAN/TALE` agent statuses."

%xprompts_enabled:true