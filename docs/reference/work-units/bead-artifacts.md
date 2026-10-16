---
title: Bead artifacts
description: How beads refer to plans, research, and other artifacts.
---

# Bead artifacts

This page describes artifact references attached to bead records.

## Artifact References

Every bead can carry a `refs` list: an ordered, deduplicated set of canonical artifact
references. This is distinct from `design`. `design` points to the one plan that
produced the bead; `refs` can point to many supporting artifacts such as research
reports, explicit files, related beads, agents, Patches, stitches, or configured
document roles.

Reference entries are stored without the prompt-time `@` sigil:

```bash
research:202607/artifact_capture_and_retention/artifact_capture_and_retention.md
file:default:0123456789abcdef01234567
bead:sase-b7
```

Write commands parse and normalize references before storing them, deduplicate repeated
entries while preserving first-write order, and do not require the reference to resolve
on the current machine. That matches the durable, cross-machine purpose of the field: a
reference may be valid even when this checkout does not have the sidecar, artifact row,
or agent history needed to resolve it locally. `sase bead doctor` performs the
resolution audit and reports references with unknown namespaces, missing targets, or
ambiguous targets.

Use typed artifact links, not free-text `RELATED:` notes, when one bead should carry
relationship context to another:

```bash
sase artifact link add bead:<task-id> related bead:<other-bead-id> "<why>"
```

Use `sase bead dep add` only when the relationship blocks work scheduling.

## Related

- [Beads](beads.md)
- [Bead attachments](bead-attachments.md)
