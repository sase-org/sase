---
keyword: CI failure
summary: A confirmed true test or lint failure, not a flake.
---

File one when a test or lint failed and you confirmed it is a true failure, not a flake.
Record the pytest node ID, the failing SHA if known, and why this is not intermittent.
Use flake instead when a rerun on the same tree passed.

- Required fields: `node_id`, `why_not_flake`
- Optional fields: `sha`

Run `sase bead task-type show ci` for the full field list, validators, and body
template.
