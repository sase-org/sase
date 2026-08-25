---
keyword: Flag Bead
aliases:
  - flag bead
---

A flag bead is a task bead of type `flag`: the dedicated top-level removal dossier for
one SASE feature flag. It owns the flag key, kind, both-branch prose, and the
`remove_by_date` and `remove_by_release` thresholds that drive `FlagTriage`. It is not a
fourth issue type and not the epic or task that introduced the behavior.
