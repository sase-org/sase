---
plan: sdd/tales/202606/remove_model_directive_multi_arg.md
---
 Can you help me completely remove support for using multiple arguments with the `%m`/`%model` directive?

- This functionality should be handled by our `%alt` directive, which makes supporting multiple arguments with
  `%m`/`%model` confusing and unnecessary.
- You should update any xprompts that start with `#m_` that are defined in any of sase's repos or in my chezmoi repo to
  start using the new syntax demonstrated in the ~/tmp/new_sase_multi_model_syntax.md file.
- Make sure you completely remove support for all forms of passing multiple argument to this `%m` / `%model` directives. No legacy support should be provided.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Repeated %model

> Besides the %m(a, b) paren form, the code ALSO turns *repeated* model directives into a multi-model fan-out: e.g. "%model:opus\n%model:sonnet" (two separate single-arg directives) collapses into one agent per model. Should this repeated-directive fan-out be removed too, so multi-model is ONLY ever expressed via %alt / %{...}?

- [x] **Yes, remove it too (recommended)** — Treat repeated %model like any other duplicate single-value directive. After this change, %m/%model resolves to exactly one model; ANY multi-model fan-out must use %alt / %{...}. Matches your phrase "all forms of passing multiple arguments".
- [ ] **No, keep repeated-directive fan-out** — Only remove the comma/paren multi-arg form (%m(a,b)); leave the repeated-directive collapse working as today.

#### Q2: On misuse

> When someone uses a now-removed multi-model form (e.g. %m(opus, sonnet) or, if removed, repeated %model), how should sase behave?

- [x] **Raise a clear error with migration hint (recommended)** — Fail fast like the existing %wait:5m -> "use %time:5m instead" precedent, e.g. "%m(opus, sonnet) is no longer supported; use %{%m:opus | %m:sonnet}". No legacy/best-effort behavior.
- [ ] **Silently treat as a single literal model value** — e.g. %m(opus, sonnet) becomes the literal model string "opus, sonnet" (which will then fail later at model resolution). No explicit migration error.

%xprompts_enabled:true