---
name: footprint_review
description: >-
  Turn reviewed Footprint keep, later, and cut decisions into curated overlay reasons
  and well-scoped task beads.
input:
  decisions:
    type: text
    description: Markdown report of the locally marked Footprint decisions.
---

Review the user's marked Footprint decisions below. Treat usage as evidence for review,
never as permission to delete functionality. The report contains allowlisted feature IDs
and aggregate evidence only.

{{ decisions }}

## Work

- For every `keep` decision, add or update that exact feature ID in
  `src/sase/footprint/overlay.yml` with its selected reason under the `keep` key. Keep
  existing `protected` and `retire_with` data intact. Use the reason slug exactly as
  supplied (`rare_by_design`, `safety`, `agent_facing`, `api_contract`, or `other`).
- For every `cut` decision, inspect the implementation and its call sites, tests, docs,
  skills, and recent history. Use `/sase_new_task` before recording a task bead. File
  one well-scoped task per independent cut, or group tightly coupled cuts when one task
  is clearer. The task should describe the review and removal work; do not remove code
  in this run.
- Leave every `later` decision unchanged. It is snoozed locally and is included only as
  context for this report.
- Note when external users may rely on a proposed cut and the existing `sunset` policy
  applies. Do not create or toggle feature flags from this review.

Do not close beads, delete code, open a PR, or edit SASE memory. Report the overlay
changes and task bead IDs, with the evidence and risks that informed each cut.
