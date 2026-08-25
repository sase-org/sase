---
keyword: Artifact Reference
aliases:
  - ref
---

An artifact reference (ref) is a typed `@<kind>:<argument>` citation in an agent prompt.
Builtin kinds are `@stitch`, `@patch`, `@bead`, `@agent`, and the special `@file`;
artifact repos add document kinds such as `@plan` and `@research` through a project's
`ref:` config, written inline or with `use: <plugin>@<provider>` from an installed
provider plugin listed as a Required Plugin. Every ref expands to prompt text, is
recorded against the agent that used it, and publishes as a `[@kind:arg][N]` link.
