---
keyword: Required Plugin
aliases:
  - required plugin
---

A required plugin is a distribution listed under `plugins.required` in project config as
a PEP 508 requirement. A linked or sidecar checkout is not an install: SASE checks the
running environment's distributions. Every non-`builtin` `<plugin>@` prefix used in that
project — including Artifact Reference, file-hook, and Task Type `use:` values — must
appear in the list. `sase memory init` and `sase validate` fail closed when a required
plugin is missing; interactive surfaces may offer to install.
