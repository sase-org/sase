---
keyword: Instruction Manifest
aliases:
  - instruction manifest
---

An instruction manifest is the JSON sibling of an [[glossary:instruction-bundle]]: it
records which sections were included and their digests, plus the delivery status, so an
agent's intended context can be compared with what the provider actually loaded. Unlike
a [[glossary:receipt]], which proves one settled tool run, a manifest records intent,
never observed delivery — use `sase instructions verify` for the observed side.
