---
keyword: Stitch
---

A stitch is the lightweight ordered change record inside a Patch's `STITCHES:` section.
Every VCS commit made through the tracked workflow has an associated numeric stitch, but
a stitch need not have a commit: proposals retain numeric-plus-letter IDs such as
`(2a)`. The `sase stitch create` command and real Git/Mercurial commits are still called
commits.
