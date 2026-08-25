---
keyword: Memory Web
---

A memory web is a keyed note collection: one flat descriptor note
(`sase/memory/<web>.md`, marked `web: true`) plus a sibling directory of strand files.
The descriptor body renders as Core Memory or Reference Memory per its `type:` and
carries a roster naming every strand; strand bodies never inline, and are read on demand
with `sase memory read <web>:<keyword>`.
