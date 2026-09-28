---
keyword: Machine Tab
aliases:
  - machine tabs
---

A machine tab is the derived default [[glossary:agent-tab]] placement for agents a
remote machine owns, labeled `⌨ <alias>`; the default tab renders as the `⌨ local`
machine tab when machine tabs are on (`ace.agent_tabs.machine_tabs`). Machine tabs are
derived, never authored: `%tab:<alias>` is an ordinary named tab, distinct from
`⌨ <alias>`. The key is the owner's installation id, so renaming an alias relabels the
tab and keeps its selection and memory. A stale host's label turns amber and an invalid
or offline host's turns red.
