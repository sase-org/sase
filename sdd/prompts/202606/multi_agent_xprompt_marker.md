---
plan: sdd/tales/202606/multi_agent_xprompt_marker.md
---
 #fork:9d.cld The line "and multi-agent xprompts" seems off since multi-agent xprompts (see the pick_plan.md file in my chezmoi repo for an example) can be expanded inline, right? When additional user text is added to a prompt that invokes a multi-agent xprompt, we just add the text to the appropriate part of the first agent prompt in the multi-agent prompt. If multiple multi-agent prompts are invoked in the same prompt, the latter multi-agent prompt should have its agent prompts appended to the previous multi-agent prompts (i.e. each multi-agent prompt's agents will be launched in sequence).

Can you help me ensure that what I've said above is accurate and make it so if not? Also, make sure the error messages / user guidance around when to use `#` vs `#!` is clear and accurate. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Canonical marker

> I confirmed multi-agent xprompts (---bodies) already expand inline when embedded, and the #/#! marker is functionally a no-op for them (both work identically in sole and embedded positions). The current code/docs still push #! for them. What should the CANONICAL displayed/inserted marker for a multi-agent xprompt be (picker, completion, catalog, LSP)?

- [x] **# (inline) (Recommended)** — Treat multi-agent xprompts as inline-capable like other xprompts. Matches their real inline behavior and the original epic intent (standalone_xprompt_bang_prefix.md said they remain #name). #! stays accepted for back-compat. Cost: touches Rust (sase-core xprompt_catalog.rs + tests) AND Python reference_display.py, plus many docs.
- [ ] **Keep #! as canonical** — Leave picker/completion inserting #!name, but fix docs/error messages to clearly state # also works and embeds inline. #! acts as a visual signal that the entry fans out into multiple agents. Smaller change: no Rust/insertion changes, docs + error-message wording only.

#### Q2: Multi-ref order

> You want multiple multi-agent xprompts in one prompt to launch their agents in sequence (latter appended to previous). This is currently an explicit ERROR. Consider: "Review #a then #b" where #a fans to [a1,a2] and #b fans to [b1,b2]. Which result matches your intent?

- [ ] **[Review a1 then b1, a2, b2] (Recommended)** — Agent 1 = surrounding prose with EACH refs first segment inlined in place; then each refs remaining segments appended in reference order (a2, then b2). Generalizes the single-embed rule and matches latter-appended-to-previous + launched-in-sequence.
- [ ] **[Review a1 then b1, b2, a2]** — What the current recursive code would produce if the >1 guard were simply removed: prose+first-segments form agent 1, but #b is fully resolved before #a contributes its follow-ups, so b2 lands before a2. Cheaper but ordering is interleaved, not strictly a-then-b.
- [x] **[Review a1, a2, b1, b2]** — Each ref fans out fully and independently in order; prose attaches only to the very first segment. Loses the text between/after refs ("then", trailing prose) for later agents.

#### Q3: Scope

> Scope of this change. The guidance/docs/error-message accuracy fixes are clearly in-scope. Should I ALSO implement the multi-agent-refs-in-sequence behavior change (replacing the current error) as part of this same plan?

- [x] **Both in one plan (Recommended)** — Fix guidance/docs/errors AND implement multiple-multi-agent-refs sequential fan-out. Matches your make it so if not. Larger, riskier (touches the expansion algorithm + many tests).
- [ ] **Guidance/docs/errors only now** — Make all the #/#! documentation + error messages accurate (including that multi-agent xprompts embed inline), but keep the one-multi-agent-ref-per-segment limit for now and track the multi-ref sequencing as a separate follow-up bead.

%xprompts_enabled:true