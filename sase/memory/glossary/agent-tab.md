---
keyword: Agent Tab
aliases:
  - agents sub-tab
  - agents sub-tabs
  - agent tabs
---

An agent tab is an exclusive, root-level, presentation-only placement of top-level sase
agents on the Agents tab. The field is always named `agent_tab`, never a bare `tab`. A
named tab is authored with `%tab:<name>`; agents without one land on the default tab,
labeled `main`, or on a derived [[glossary:machine-tab]] when machine tabs are on.
Membership follows the presentation root (session, clan generation, or workflow), so a
container never splits across tabs. The strip shows once two or more tabs exist; `]` /
`[` cycle tabs, and selection, folds, and sticky panels are kept per tab. A tab never
changes where an agent runs, its identity, clan, session, or [[glossary:agent-tribe]].
