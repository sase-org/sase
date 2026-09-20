---
keyword: Tool Run
---

A Tool Run is the durable, machine-local record `sase tool run` writes for one
foreground execution of a [[glossary:tool-catalog]] entry (or an ad-hoc argv): owner,
lifecycle, exit or signal, stage timeline, and before/after fingerprints. It records
what a command did; it is not the Agents-tab [[glossary:llm-calls]] view, and it is not
a [[glossary:sase-monitor]] or [[glossary:proc]] (those may own the run).
