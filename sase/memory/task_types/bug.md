---
keyword: Bug
summary:
  A defect an agent found while doing unrelated work, not an external tracker bug.
---

File one when you found a defect while doing unrelated work and it is not an external
tracker issue. Record where it lives, how to reproduce it, and who it hurts. Do not use
this for a flake, a confirmed CI failure, or a GitHub-mirrored bug.

- Required fields: `location`, `repro`
- Optional fields: `impact`

Run `sase bead task-type show bug` for the full field list, validators, and body
template.
