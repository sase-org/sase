---
name: agent_family_improve_plan
description: Improve an approved plan and submit it for review again.
input:
  - name: plan_file
    type: path
    description: Path to the approved plan file to improve.
---

@{{ plan_file }}

Review the approved plan above and improve it before implementation begins. Keep the scope focused on correctness,
missing edge cases, and test coverage.

When the revised plan is ready, submit it for review with `/sase_plan`.
