---
plan: sdd/tales/202606/unify_auto_directive.md
---
 Can you help me migrate the `%plan`, `%tale`, and `%epic` directives to a single `%auto` directive?

- The new `%auto` directive should take an enum / string value with the following valid options: "plan", "tale", and "epic" (it should default to "plan" if no argument is provided).
- Make sure you update all references so these directives are not referenced anywhere (except for plan / research / misc historical files). Make sure you check all external / linked repos and my chezmoi repo.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Back-compat

> Back-compat: should the old %plan/%tale/%epic (and their %p/%t aliases) keep parsing as hidden deprecated aliases of %auto, or be removed entirely? You said "not referenced anywhere", which implies full removal — but full removal means any saved prompt-stash pins / history / personal xprompts still using %plan etc. will stop being recognized (the token is left as literal text).

- [x] **Remove entirely** — No aliases kept. %plan/%tale/%epic become unknown tokens. Matches 'not referenced anywhere' literally. (my default)
- [ ] **Keep hidden deprecated aliases** — %plan/%tale/%epic still resolve to the matching %auto mode but are hidden from completion/docs (like today's %approve). Safer for existing pins/history.

#### Q2: %auto alias

> Short alias for %auto? Today %a/%p map to plan (deprecated/canonical), %t maps to tale. Repurposing %a to %auto is natural and frees %p and %t.

- [x] **%a means %auto** — Use %a as the short alias; drop %p and %t entirely. e.g. %a:tale, bare %a = plan. (my default)
- [ ] **No short alias** — Only the full %auto spelling; drop %p/%t/%a.
- [ ] **Other** — Tell me which letter you want.

#### Q3: Internal repr

> Internal PromptDirectives representation: replace the three booleans (approve/tale/epic) with a single field (e.g. auto_mode = plan|tale|epic|None), or keep the three booleans and just have the new %auto parser populate them?

- [x] **Single field** — Cleaner; auto_mode enum. Touches the one consumer (run_agent_directives.py). (my default)
- [ ] **Keep three booleans** — Minimal churn; %auto:tale sets tale=True, etc. Field names stay but are no longer 1:1 with a directive.

#### Q4: Blog posts

> Docs scope: I will definitely update reference docs (xprompt.md, ace.md, beads.md, workflow_spec.md). Should I also rewrite the published blog posts under docs/blog/ that mention %plan/%tale/%epic, or leave those as dated historical content?

- [x] **Update blog posts too** — Rewrite the 3 blog posts to use %auto. Fully removes references everywhere. (my default)
- [ ] **Leave blog posts as historical** — Treat docs/blog as dated published content; only update reference docs.

%xprompts_enabled:true