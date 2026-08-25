---
keyword: Artifact Markdown File
aliases:
  - artifact md file
  - artifact md
---

An artifact markdown file is the Markdown document that carries one artifact's typed
links. A Markdown artifact is its own artifact md file. A non-Markdown file uses a
sibling `<stem>.md`; beads, agents, and Patches use their generated page, which is a
projection of the artifact's own store. A commit has none — links to a stitch render on
the other artifact. The file is created the first time the artifact acquires a link.
SASE renders those links as a table of hyperlinks near the top of the file. Agents write
links with `sase artifact link` and read artifacts with `sase artifact read`; they never
hand-edit a generated page.
