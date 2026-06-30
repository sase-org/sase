---
plan: sdd/tales/202606/model_alias_at_prefix.md
---
 Can you help me start requiring that `@` be used in front of model aliases when they are used? For example, `%m:@other` should be used instead of `%m:other`. Make sure to update all references in my chezmoi repo accordingly. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Bare-alias behavior

> When a %model/%m value has NO @ prefix but the token exactly matches a configured/reserved alias (e.g. legacy %m:other, %m:#agy->agy_flash, internal %model:worker), what should happen?

- [x] **Hard error w/ migration hint** — Raise DirectiveError: "Model aliases must be prefixed with @ — did you mean @other?". Cleanest; catches every stale reference (including internal emitters) loudly. Recommended.
- [ ] **Silent literal fallthrough** — Treat the bare token as a literal model id; skip alias resolution. It then falls back to the default provider (today's no-match behavior). Quiet but can silently mis-route.
- [ ] **Keep resolving (warn only)** — Still resolve bare aliases but log a deprecation warning. Soft migration, both spellings work for now.

#### Q2: Scope of @

> Confirm scope: which tokens require @? Aliases = entries in llm_provider.model_aliases PLUS reserved worker/other. NON-aliases (bare known models like opus/sonnet/gpt-5.5, explicit provider/model like claude/opus, and display short-aliases) stay WITHOUT @.

- [x] **Yes — aliases only** — @ required only for model_aliases + reserved worker/other. opus, claude/opus, codex/gpt-5.5, etc. stay bare. Recommended.
- [ ] **No — @ on everything** — Require @ in front of every %model value, including bare known models and provider/model.

#### Q3: @ vs xprompt refs

> For aliases reached through an xprompt reference (your chezmoi has m_agy: %model:#agy where #agy -> agy_flash alias), where should the @ live?

- [x] **On the directive: %model:@#agy** — Keep xprompt values as bare alias names (agy:"agy_flash"); @ sits on the directive and survives xprompt expansion. #agy/#gem/#pro stay reusable as prose. Recommended.
- [ ] **Bake into xprompt value: agy:"@agy_flash"** — Put @ inside the xprompt target so #agy expands to @agy_flash. Directive stays %model:#agy.

#### Q4: Cutover style

> Migration style for the cutover (mirrors your recent feat(ace)! keymap change which kept no back-compat)?

- [x] **Hard BREAKING cutover** — New @ syntax required immediately; old bare-alias spelling stops resolving. Update all sase tests/docs/internal-emitters + chezmoi in the same change. Recommended for consistency with your recent breaking changes.
- [ ] **Deprecation window** — Both spellings work for a release; bare-alias logs a deprecation warning; remove later.

#### Q5: agy_* tokens

> Research finding: your llm_provider.model_aliases has ONLY `other: claude/opus`. The agy_flash / agy_pro / agy_sonnet / etc. tokens that your #agy-family xprompts expand to are NOT in model_aliases and are NOT registered known models (the agy provider only knows verbose names like "Gemini 3.5 Flash (High)" with short aliases like flash35h). So today %model:#agy already falls back to the default provider, and your config.model_xprompts doctor check warns about exactly this. Given Q2 (aliases = model_aliases keys + worker/other) defines what needs @, how should the migration treat these agy_* tokens?

- [x] **Aliases: add to model_aliases + require @** — Add agy_flash: agy/Gemini 3.5 Flash (High) (and the rest) to llm_provider.model_aliases, AND write the directives as %model:@#agy. This both fixes the latent routing bug and honors your Q3. The agy_* family becomes real aliases that require @.
- [ ] **Not aliases: keep them bare (no @)** — Take Q2 literally. agy_* are not model_aliases entries, so they stay bare (no @), exactly like opus/sonnet/gpt-5.5. Consequence: since NO chezmoi directive references other/worker, your chezmoi %model/%m directives would need ZERO @ changes; Q3 effectively does not apply. The agy routing stays as-is (still falls back).
- [ ] **Aliases via @ only, leave model_aliases untouched** — Write %model:@#agy per Q3 but do not add anything to model_aliases. Only works if @<token> for a non-alias falls through leniently to normal model resolution (otherwise @agy_flash would error). Honors Q3 spelling without fixing routing.

#### Q6: @ on non-alias

> Symmetric design choice: when @ is put in front of a token that is NOT a known alias (e.g. %model:@opus where opus is a bare known model, or %model:@claude/opus), what should happen? (This is the mirror of your Q1 hard-error-for-bare-aliases choice.)

- [x] **Hard error (strict)** — @ is ONLY valid in front of a real alias (model_aliases key / worker / other). %model:@opus or %model:@claude/opus raises DirectiveError. Most consistent with your Q1 strict stance; catches misuse loudly.
- [ ] **Lenient passthrough** — Strip the @ and resolve normally, so @opus == opus. Permissive; lets @ be harmless decoration on any token. Required if you pick option C above.

%xprompts_enabled:true