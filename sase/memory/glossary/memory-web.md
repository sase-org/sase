---
keyword: Memory Web
---

A memory web is a keyed note collection: one flat descriptor note
(`sase/memory/<web>.md`, marked `web: true`) plus a sibling directory of strand files.
The descriptor must not declare `type:` or `parent:`; a web's kind, not a rendering
declaration, decides its placement, so its body always renders in the generated
document's Memory Webs section and carries a roster naming every strand. Strand bodies
never inline, and are read on demand with `sase memory read <web>:<keyword>`.
