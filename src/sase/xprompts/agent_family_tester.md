---
name: agent_family_tester
description: Test or review a completed code-family member.
input:
  - name: source_artifacts
    type: line
    description: Artifacts directory for the completed code member.
---

Review the completed implementation represented by this artifacts directory:

{{ source_artifacts }}

Run the most relevant focused tests, inspect failures, and report any issues clearly. Do not make unrelated changes.
