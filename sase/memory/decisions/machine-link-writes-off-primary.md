---
keyword: Machine Artifact-Link Writes Stay Off the Primary
aliases: [machine link writes off primary, hidden clone machine write lane]
summary:
  Machine artifact-link mutations never target the sidecar clones nested under a
  project's primary checkout; the machine write lane is the hidden host-owned clone, and
  the primary converges only through pull-based auto-sync.
metadata:
  status: accepted
  decided: 2026-09-26
---

**Claim.** SASE machine (background) artifact-link mutations never target the sidecar
clones nested under a project's primary (human) workspace checkout. The machine write
lane is the hidden host-owned clone at `~/.sase/projects/<key>/repos/<role>`
(`hidden_sidecar_clone_dir`), following the agents-sidecar precedent; the primary's
nested `repos/<role>` clones are human-owned and converge only through the existing
pull-based `sync_primary_sidecar_role` auto-sync. Epic plan:
`plan:202609/machine_link_mutations_off_primary.md`. Link-index publication flows
through [[sase_artifacts.md]].

**Why.** Committing from the primary (the pre-epic behavior, reached by a defaulted
`user` mutation origin) makes host background jobs indistinguishable from the human and
strands worktree dirt when the ownership gate refuses an honest `machine` origin.
Rejected alternatives: **relaxing `authorize_store_mutation`'s primary-#0 refusal**
would weaken the fail-closed ownership contract for every caller, not just link
maintenance; **writing to a numbered workspace clone** ties durable host state to an
evictable lease. Implementing code: `src/sase/sdd/_artifact_link_machine_store.py`
(`resolve_machine_artifact_link_store`), `AccessKind.HOST_OWNED_SIDECAR` and
`_hidden_sidecar_machine_context` in `src/sase/workspace_provider/`, and the
`project.primary_sidecar_link_dirt` doctor check.

**Cost.** A second on-disk clone per document sidecar role per project, and machine
writes become visible in the primary only after auto-sync runs.

**Reopens when.** Hidden host-owned clones stop being materializable on demand, or the
ownership contract gains a first-class machine lane into primary-nested clones.
