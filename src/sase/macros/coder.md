---
name: coder
description: Ask an agent to implement an approved plan file.
input:
  - name: plan_file
    type: path
    description: Path to the approved plan the agent should implement.
---

The {{ plan_file | plan_ref_path }} plan file has been reviewed and approved. Implement
it now.
