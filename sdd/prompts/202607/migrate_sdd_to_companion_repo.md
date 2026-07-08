---
plan: sdd/tales/202607/migrate_sdd_to_companion_repo.md
---
 We recently migrated the GitHub VCS provider to use a separate repo for SDD files. Can you help me verify that the sase-org/sdd repo exists, has been properly initialized, will be used to commit future sdd files, and the SDD files that used to be local to this repo have been migrated over to that repo? If not, use your /sase_plan skill to plan the appropriate changes.
 You should be able to create the GitHub repo using the gh command line utility, I think. 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Repo name

> What should the companion SDD repo be named? (Your "sase-org/sdd" needs a `sdd.repo.name: sdd` override; the provider default would otherwise be `sase-org/sase-sdd`.)

- [x] **sase-org/sdd** — The name you gave. Requires adding `sdd.repo.name: sdd` config override.
- [ ] **sase-org/sase-sdd** — Provider default `<repo>-sdd` convention. No override needed.

#### Q2: Remove in-tree

> After copying SDD files into the new repo, should the plan also remove the in-tree sdd/ files from the main sase-org/sase repo?

- [x] **Remove in-tree** — `sase sdd migrate --remove-in-tree`: deletes tracked sdd/ from main repo in a separate commit after migration.
- [ ] **Keep in-tree for now** — Migrate/copy to the new repo but leave the sdd/ copy in the main repo. Safer; clean up later.

#### Q3: Override scope

> If using the `sase-org/sdd` name (Option A), where should the `sdd.repo.name` override live?

- [ ] **Project-local sase.yml** — Scoped to this project only.
- [ ] **Global config** — Applies the `sdd`-name convention to all GitHub projects.
- [ ] **N/A (chose sase-sdd)** — No override needed if you picked Option B above.
- [x] **Other:** "The `<>org/sdd` repo should always be one of the default repos that is checked for sdd files."

---

> **Global Note:** Answered via Telegram

%xprompts_enabled:true