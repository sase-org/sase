---
keyword: Patch
---

A Patch is SASE's local unit of change. Every PR created or managed by SASE is
associated with exactly one Patch, but a Patch may exist without a PR, represented by an
absent `PR:` field. Active Patches live in ProjectSpec `<key>.sase` (directory key
`<key>`; see Project, Repo, and Workspace); terminal ones (Submitted, Archived,
Reverted) live in `<key>-archive.sase`. Sections: NAME, DESCRIPTION, PARENT, PR, STATUS,
STITCHES, HOOKS, COMMENTS, MENTORS. Status lifecycle: WIP -> Draft -> Ready -> Mailed ->
Submitted.
