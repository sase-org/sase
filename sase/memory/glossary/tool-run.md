---
keyword: Tool Run
---

A Tool Run is the durable, machine-local record `sase tool run` writes for one execution
of a [[glossary:tool-catalog]] entry (or an ad-hoc argv): owner, lifecycle, exit or
signal, stage timeline, and before/after fingerprints. It records what a command did; it
is not the Agents-tab [[glossary:llm-calls]] card, and it is not a
[[glossary:sase-monitor]] or [[glossary:proc]] (those may own the run). The execution
runs in the foreground or is handed off to a monitor or proc that owns it
(`sase tool run -H` outside agents, `sase monitor start` inside them); either way the
run keeps one durable id that stays followable (`show -F`), waitable (`wait`), and
stoppable (`stop`) until it settles to an outcome or a typed uncertainty.
