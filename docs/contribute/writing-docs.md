---
title: Writing docs
description: The sase.sh documentation contract for humans and agents.
---

# Writing docs

This page is the documentation contract for humans and agents. It says where a change
goes, how long a page may be, and what keeps links working. The `check_docs` lint
(`just docs-lint`) enforces the mechanical half; judgment stays with the author.

## Tabs and types

sase.sh has six tabs, and the directory is the type. A page never declares its kind;
where it sits declares it:

- `start/` — Tutorials. One walked path, no options, alternatives, or why.
- `guides/` — How-to guides, titled with the reader's goal.
- `concepts/` — Explanations. Study without performing.
- `reference/` — Lookup. Facts generated from the code that owns them where possible,
  hand-written where not.
- `contribute/` — Contributor material: setup, internals, contracts, runbooks, and this
  process.
- `blog/` — Dated essays. Drafts stay out of the public site.

Legacy root pages predate the split and are allowlisted with shrinking word ceilings.
New root pages fail the lint. Never bulk-reflow a legacy page: new Guide content goes in
new files.

## The placement test

Diátaxis is a two-question compass. Ask both before writing:

1. Action or cognition? Doing goes to `start/` or `guides/`; understanding goes to
   `concepts/` or `reference/`.
2. Study or work? Learning goes to `start/` or `concepts/`; doing the job goes to
   `guides/` or `reference/`.

Tutorials teach one path with no options. Guides answer one goal; anything longer than
one goal is two guides. Concepts explain with at most one diagram. Reference titles name
the thing; Guide titles name the goal ("Get automated code review", not "Mentors").

IA is a human decision: never move pages between tabs without an approved plan. Moving
content is a move-only commit first, content edits after.

## Templates

Copy the nearest template from `docs/_templates/` and keep its shape:

- `tutorial.md` — Opening sentence, "Before you start", ordered steps, an outcome line
  ("You have ..."), closing "Next" links.
- `how-to.md` — Goal title, prerequisites, steps with confirmations, one failure
  section, "Related" links.
- `concept.md` — What the idea is for, one picture, how it works, when it matters,
  "Related" links.
- `reference.md` — Facts in tables and lists; generated values in marked blocks that are
  never hand-edited.
- `hub.md` — One orientation sentence plus grouped links, at most 400 words.

Every page opens with one sentence saying what it is for and closes with a "Next" or
"Related" link. Tutorial and concept templates carry `search: {boost: 2}`.

## Frontmatter and budgets

Typed pages need `title` and a one-line `description` of at most 160 characters. Unknown
frontmatter keys fail the lint; `covers:` is allowed only under `reference/`.

Words are counted outside frontmatter, fenced code, HTML comments, and generated blocks:

| Tier                        | Per-page words                     | Tier total |
| --------------------------- | ---------------------------------- | ---------- |
| `start/`                    | ≤ 2,500                            | ≤ 10K      |
| `guides/`                   | target ≤ 1,500, hard ≤ 2,500       | —          |
| `concepts/`                 | ≤ 3,000                            | ≤ 25K      |
| Hubs (`*/index.md`)         | ≤ 400                              | —          |
| `reference/` (hand-written) | ≤ 6,000                            | —          |
| `contribute/`               | ≤ 8,000 (warning only)             | —          |
| Legacy root pages           | ceiling = size at lint landing +1% | —          |

Generated pages and blocks are exempt. Legacy ceilings live in `docs/_meta/budgets.yml`
and only shrink: `just fix` lowers a ceiling when its page shrinks and never raises one.
Propose a split instead of growing an over-budget page; Guide pages take facts by
linking the Reference, never by restating it.

## Guide hygiene

`start/`, `guides/`, and `concepts/` pages stay timeless and reader-facing. These are
forbidden there:

- bead IDs;
- `src/` paths;
- epic or phase labels such as "E3";
- history phrases ("formerly", "no longer", "legacy", "renamed", "still mentions").

History goes to the CHANGELOG, decision records, and `reference/upgrading.md`.

## Tests and portability

Tests do not pin Guide prose. A test may not read files under `docs/start/`,
`docs/guides/`, or `docs/concepts/`; the only exceptions are the tutorial runner and the
lint's own tests. When code and docs disagree, file the disagreement instead of
documenting it.

The site builds on any Zensical-compatible host: add no MkDocs `hooks:`, `gen-files`, or
plugins beyond search, redirects, blog, rss (and exporter in the PDF config only).
Generation happens in `tools/` before the build, with `--check` drift detection.

## Routing table

Match the change to its row before writing:

- **A CLI flag, config key, keybinding, directive, or model:** regenerate with
  `just fix`. Write no prose unless the generated description is insufficient — then
  improve the source description.
- **The behavior of an existing feature:** update its Reference page. If a tutorial or
  guide step is now wrong, fix that step and nothing more.
- **A new user-visible capability:** add a Reference entry (a new `reference/` page if
  the nearest one is at its ceiling). If it serves a new user goal, note a "guide
  candidate" follow-up instead of appending narrative to a Guide page.
- **A design decision:** write a decision record; it appears on the generated
  design-decisions page.
- **Internals, contracts, or runbooks:** `contribute/`.

Legacy pages may not grow, whatever the row says.

## Link compatibility

Inbound links are an interface: README links ship in every released PyPI long
description, and TUI onboarding widgets link sase.sh URLs.

- The source of truth is `docs/_meta/moves.yml`: one entry per moved page (`from`, `to`)
  plus an optional `anchors:` map.
- Whole-page moves become generated `docs/_redirects` 301 lines. Browsers carry the
  original `#fragment` across the redirect, so same-page anchors keep working.
- Split pages and pages cited by path in text this project may not edit get a generated
  stub page at the old path instead: where the content went, a small fragment-to-URL
  map, excluded from search and nav. No redirect rule may shadow a stub.
- The URL contract test resolves every frozen URL and anchor in the built site: every
  page URL that exists today, every `https://sase.sh/...` URL in `src/`, `README.md`,
  and the latest released README, and every `_redirects` target. A deep link is never
  "kept compatible" by redirecting it to a generic section index.

## Style and accuracy

Use present tense and plain words. Teach the seven core nouns before using any other
term: project, workspace, agent, prompt/macro, Patch, bead/plan, TUI. Any other term
appears only on the page that needs it, linked to the glossary.

Verify every command, flag, and output against current master: run `--help`, and run the
command in a temporary `HOME`. Screenshots and GIFs come from `demos/` tapes or the TUI
screenshot tooling, never by hand. When code and docs disagree, record a follow-up note
on your work item — never add a sentence to the docs explaining the disagreement.

Verify with `sase tool run check`. Once the links phase lands, `just docs-check` also
runs the strict build and URL contract. Never run `just check-full` unless explicitly
told to.

## Related

- [Contribute](index.md) — The contributor hub this page belongs to.
- [Development](../development.md) — Setup, verification, and source layout.
