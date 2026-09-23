---
keyword: Project Tag
aliases:
  - xprompt project tag
  - project tags
---

A project tag is the `+<project>` word naming the [[glossary:sase-project]] an agent
runs in. It resolves by key, name, or alias, case-insensitively, against unique names,
then expands to the project's VCS xprompt ref and shares its backend. It is the default
spelling; `#gh:`/`#git:` remain for Patches, `owner/repo`, `@agent`, and new projects.
An anchored tag (first word on its line) must resolve. It renders in the project's
accent, like the chip.
