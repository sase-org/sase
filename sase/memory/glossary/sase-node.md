---
keyword: Sase Node
aliases:
  - node
---

A sase node is one row of the Agents tab's agent tree: an agent clan node, an agent node
(with its member sase turn nodes), an agent step node — a workflow `python`, `bash`, or
`parallel` step — or a stand-alone named proc node. Every sase node is a nav item, but
nodes exist only on the Agents tab: Services and Artifacts nav items are not nodes.
Grouping banners (including selectable collapsed ones) and tribe-panel titles are not
nodes.

A node's status is the word its row shows, including render-time overlays such as
`FINALIZING`; a container node derives its status from its members, and an agent clan
node with exactly one running member node shows that node's status.
