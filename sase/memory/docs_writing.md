---
type: reference
parent: AGENTS.md
description:
  Read before adding, moving, or editing anything under `docs/`, `mkdocs*.yml`, or a
  sase.sh link in code.
---

# Writing Docs (Change-to-Docs Routing)

Route every docs change to its tier before writing. The full contract lives in
`docs/contribute/writing-docs.md`; the generated docs map (`docs/README.md`) lists every
page with its one-line description.

## The routing table

- **A CLI flag, config key, keybinding, directive, or model:** regenerate with
  `just fix`. Write no prose unless the generated description is insufficient — then
  improve the source description.
- **The behavior of an existing feature:** update its Reference page (today, the legacy
  root page that owns the fact). If a tutorial or guide step is now wrong, fix that step
  and nothing more.
- **A new user-visible capability:** add a Reference entry (a new `reference/` page if
  the nearest one is at its ceiling). If it serves a new user goal, note a "guide
  candidate" `PROPOSED FOLLOW-UP:` instead of appending narrative to a Guide page.
- **A design decision:** write a decision record; it appears on the generated
  design-decisions page.
- **Internals, contracts, or runbooks:** `contribute/`.

## Budget rule

Legacy pages may not grow. Guide pages take facts by linking the Reference, never by
restating them.

## Never move pages

Moving pages between tabs is a human decision with an approved plan, never a side effect
of a feature change.
