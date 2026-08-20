---
type: short
parent: AGENTS.md
---

# Artifact Relation Registry

Typed artifact links use this closed relation registry. Agents write deliberate links
with `sase artifact link add <source> <relation> <target> "<why>"`; prompt citations and
audited reads use the same row shape.

## Relations

- `cites`: inverse `cited-by`, directed yes, written by `prompt_ref`.
- `read`: inverse `read-by`, directed yes, written by `read`.
- `related`: inverse `related`, directed no, written by `cli`.
- `supersedes`: inverse `superseded-by`, directed yes, written by `cli`.
- `implements`: inverse `implemented-by`, directed yes, written by `cli`.
- `derives-from`: inverse `derived-into`, directed yes, written by `cli`.

## Reserved

The following slugs are scheduling concepts, not artifact-link relations:

- `blocks`: use `sase bead dep` instead.
- `depends-on`: use `sase bead dep` instead.
