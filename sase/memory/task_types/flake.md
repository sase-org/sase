---
keyword: Flaky test
summary: A test that fails and then passes on an unchanged tree.
---

File one when a test or lint failed, a rerun on the same tree passed, and you did not
cause the failure. Record the fail rate and whether it reproduces serially. Use ci
instead when the failure is confirmed and reproducible.

- Required fields: `node_id`, `evidence`
- Optional fields: `repro_cmd`

Run `sase bead task-type show flake` for the full field list, validators, and body
template.
