---
diagram: docs/images/zorg-zettel-vision-infographic.png
embedding_docs:
  - docs/index.md
  - docs/blog (placeholder — image is not yet linked from any committed doc)
  - docs/series (placeholder — image is not yet linked from any committed doc)
critique_phase_bead: sase-2s.10
regen_phase_bead: sase-2s.20
critique_date: 2026-05-10
pdf: false
---

# Critique: `zorg-zettel-vision-infographic.png`

This diagram is the "vision" picture for the Zorg-flavored zettelkasten that SASE wants to consume
as a curated memory source. Per the epic plan (`sdd/epics/202605/diagram_review.md` row 10) it is
intended to embed in `docs/index.md` and the blog/series surfaces. There is no `.prompt.md` sidecar,
so intent has to be inferred from `sdd/research/202605/zettel_sase_shared_memory.md` (the most
direct prior art in this repo) and from the user's `~/org` zorg notes (`zorg_term.zo`,
`zorg_ideas_2503.zo`, `zorg_ideas_2504.zo`, `zorg_v2_design.zo`, `lit/system_for_writing.zo`,
`lit/zettel_method.zo`).

A grep across the repo confirms that as of 2026-05-10 no committed doc, blog post, or series page
links the PNG. The image exists in `docs/images/` and is referenced only by `sdd/beads/issues.jsonl`
and the epic plan itself. Whatever the regen produces will essentially be greenfield — there is no
inline prose to anchor the image against.

## What the diagram currently shows

- Title bar: **Zorg Zettel Vision**.
- Left column **CAPTURE** with four pill rows: `Fleeting notes`, `Literature notes`, `Todos`,
  `Refs`.
- An arrow labeled **develop** running from the CAPTURE column into the central panel.
- Center panel **Org Folder as Zettelkasten** — a small node graph containing `@foo`, `@foo/bar`,
  `query`, `child`, `sibling`, `backlink`, with the labels `file zettel`, `dir zettel`,
  `note zettel` underneath.
- An arrow labeled **navigate** running from the central panel into the right column.
- Right column **USE & NAVIGATE** with five rows: `Jumpers`, `Tree view`, `Backlinks`,
  `Query zettel`, `LSP actions`.
- Bottom strip of four pills: `Atomic ideas`, `Typed notes`, `Inherited links`, `Graph navigation`.

## Accuracy issues (graded against `~/org` and the SASE research note)

### A1. The diagram is silent about SASE — yet it lives in the SASE doc set

This is the single biggest accuracy problem. The image's whole reason to live in `docs/` is that
SASE wants to project a curated zettelkasten into agent memory
(`sdd/research/202605/zettel_sase_shared_memory.md`). None of that bridge is shown: no projection
arrow into `memory/*.md`, no `keywords`-frontmatter step, no inbox/promotion box, no `APPLIES:` /
`TRIGGERS:` / `PROVENANCE:` labels, no runtime injection step. A reader of `docs/index.md` will look
at this and reasonably ask "why is the SASE site showing me a generic zettelkasten with no SASE in
it?" The image is currently a personal-tool vision picture, not a SASE doc-set asset.

### A2. `@foo/bar` is presented as the canonical ID syntax, but zorg has two competing syntaxes

`zorg_term.zo` defines two ID kinds: `FID` (folgezettel IDs of the form `1.a7`, three components)
and `ZID` (`YYMMDD#XX` create-date IDs). `zorg_ideas_2503.zo` line 65 ("Use `@foo` syntax instead of
`ID::foo`...") is the proposal that introduces `@foo` / `^bar` and tags it as accepted but **not yet
shipped** — it lives in `zorg_v2_design` as a v2 idea. Treating `@foo/bar` as the unqualified
canonical node label, with no FID/ZID alongside, overstates how settled the syntax is. Either show
both shapes, label the diagram as "v2 vision", or call out that `@foo/bar` is the proposed v2 path
syntax and not what current `~/org` files use.

### A3. The four CAPTURE inputs are an idiosyncratic mix, not the documented zettel pipeline

`lit/zettel_method.zo` and `lit/system_for_writing.zo` describe the canonical pipeline as **fleeting
→ literature → permanent (main) → hub/structure**, with todos and refs as cross-cutting concerns.
The diagram instead shows `Fleeting`, `Literature`, `Todos`, `Refs` as four peers feeding "develop",
which conflates two orthogonal axes (note maturity vs. note kind) and drops the "permanent / main"
stage that is the _point_ of the slip-box. A new reader cannot recover the maturation pipeline from
this picture.

### A4. The center graph mixes node types and edge types as if they were peers

Inside `Org Folder as Zettelkasten` the labels `@foo`, `@foo/bar`, `query`, `child`, `sibling`,
`backlink` are drawn as graph elements at the same visual level, but `@foo` and `@foo/bar` are _node
IDs_, `query` is a _kind of zettel_ (per `zorg_query.zo` and `zorg_ideas_2503.zo`), and
`child`/`sibling`/`backlink` are _edge kinds_. The bottom-of-panel labels `file zettel`,
`dir zettel`, `note zettel` are _node kinds_. Five different ontological categories share one box
with no visual distinction. This is the part of the image a careful reader will spend the longest
on, and it is the part most likely to mislead.

### A5. The `child` / `sibling` / `backlink` triple under-represents zorg's relation system

`zorg_ideas_2504.zo` enumerates jumpers across explicit, inherited, incoming, and Folgezettel-like
relationships. The research note (`sdd/research/202605/zettel_sase_shared_memory.md` §"Existing
Tools to Learn From") and the local `folgezettel.zo` notes treat `Folgezettel` as a first-class
relation. The diagram surfaces only three relation labels and then re-introduces `Inherited links`
as a separate principle in the bottom strip — so inheritance is mentioned but not drawn. Either drop
the partial enumeration or extend it to (at least) `child`, `sibling`, `backlink`, `inherited`,
`folgezettel`, `tag`.

### A6. `LSP actions` is aspirational, not present

`zorg_ideas_2504.zo` and the v2 design notes mention LSP-style navigation as a target. There is no
shipped Zorg LSP client in `~/org` or `sase-nvim` today. Listing it next to `Jumpers`, `Tree view`,
`Backlinks`, `Query zettel` (which _are_ working concepts in zorg today) flattens shipped vs.
planned features into the same column. The infographic style brief asks for "terminology-aligned
with the target doc" — vision-only items should be visually marked or moved to a "Planned" column.

### A7. `Typed notes` in the bottom strip is unmoored

The research note proposes typed zettel — `&fact`, `&howto`, `&gotcha`, `&decision`, `&episode`,
`&source`, `&index`, `&query` — as the projection contract that makes zettel useful for SASE memory.
The PNG includes a `Typed notes` principle pill but never names the types. Since the _whole_
SASE→zettel value proposition rests on those types, this is an under-investment in the most
load-bearing part of the vision.

### A8. The bottom-strip pills mix principles, features, and a synonym

`Atomic ideas` is a _principle_ (one idea per zettel — Luhmann, repeated through
`lit/system_for_writing.zo` and `lit/zettel_method.zo`). `Typed notes` is a _schema choice_.
`Inherited links` is a _relation kind_ already implied by the center graph. `Graph navigation` is a
_feature_ already covered by the `USE & NAVIGATE` column (Jumpers / Tree view / Backlinks). So the
strip stacks one principle, one schema, one relation, and one duplicated feature, with no indication
of which is which. A reader cannot tell what they are looking at.

### A9. No `provenance` / `inbox` / `trust` boundary

Section "Memory poisoning is a real attack surface" of
`sdd/research/202605/zettel_sase_shared_memory.md` makes inbox-and-promotion _the_ security-critical
step in any human/agent shared memory. The image has no inbox, no promotion arrow, no provenance
box. For a "vision" diagram that sits in the SASE doc set, omitting this is the same mistake the
research note explicitly warns against (treating raw agent writes as canonical memory).

### A10. `Org Folder as Zettelkasten` framing collides with the project's actual framing

`zorg_term.zo` line 25–26 is explicit: "in the context of zorg, we treat the `~/org` directory as a
Zettelkasten". The image header says `Org Folder as Zettelkasten`, which is the right framing — but
the rest of the picture (CAPTURE on the left, USE on the right) makes the org folder look like a
passive store between two columns. Per the same source note, `~/org` is the Zettelkasten _itself_,
not a middle layer. The center panel should be the diagram's hero, not the sandwich filling.

## Clarity issues (would a new user understand this?)

### C1. No legend, no key, no scale

There is no legend explaining shapes (rounded pill vs. square node vs. circle), no key for color
(the central panel uses a different fill than the outer columns), and no indication that `@foo` is a
placeholder ID rather than a literal name. A reader who has never seen Zorg cannot bootstrap from
the picture alone.

### C2. The `develop` and `navigate` arrows are vague verbs

The two big perimeter arrows are labeled with single English verbs that do not say _who_ develops or
navigates. Compare with sister diagrams such as `sase-component-communication.png`, which use
phrases like "launch or schedule work" or "checkout, diff, submit". `develop` and `navigate` could
mean code, or human reading, or agent action — the reader has to guess.

### C3. `@foo` / `@foo/bar` look like random placeholders

Other diagrams in this set anchor abstract concepts with concrete examples, so a reader can map the
picture to a real artifact. Here the central nodes are meta names. Using a real example pair (e.g.
`@sase/memory/audited-read` with a child `@sase/memory/read-evidence`) would make the IDs
self-explanatory and double as a hint about what kind of zettel SASE wants to store.

### C4. CAPTURE/USE column-row labels read as inputs/outputs but are actually feature lists

The visual grammar — left column → center → right column with labeled arrows — strongly implies
"CAPTURE is the input, USE is the output". But `Jumpers` and `Tree view` are not outputs; they are
_tools that operate on_ the slip-box. Similarly, `Refs` on the left are not raw inputs to a
maturation flow; they are a kind of _zettel_ that lives inside the slip-box. The flow metaphor pulls
the labels out of position.

### C5. Bottom strip looks like a footer banner, not a content row

The four pills at the bottom (`Atomic ideas`, `Typed notes`, `Inherited links`, `Graph navigation`)
are visually styled the same as the top columns' rows but with a subtly different background, so
they look like a decorative tagline rather than a fifth content group. Most readers will skim past
them.

### C6. The image is dense for a thumbnail

At GitHub-Markdown width (e.g. on a future `docs/index.md` insert) the central graph nodes and the
CAPTURE/USE icons are small; the `child` / `sibling` / `backlink` text in the middle gets
compressed. The infographic-style-brief asks for "clear arrows, and limited short labels" and
"labels readable at GitHub Markdown width". This image has the labels but they are not big enough at
thumbnail scale.

### C7. No bridge to the rest of the SASE doc set's visual language

Sister infographics (`sase-component-communication`, `commit-workflow`, `xprompt-resolution`,
`workflow-execution`, `bead-epic-work`, `rust-backend-boundary`) share a common look: rounded
blocks, consistent palette, named flow edges, small captions. The Zorg vision image uses a similar
palette but a noticeably different layout grammar (icon pills + mini graph + bottom strip), so it
does not visually slot in next to the others on a docs page. The infographic style brief should be
referenced explicitly in the regen prompt.

## Concrete suggestions for the regenerated diagram

The regen phase (`sase-2s.20`, `codex/gpt-5.6-sol`) should:

1. **Decide first whether this is a SASE doc image or a personal-zorg image.** If it stays in
   `docs/`, add the SASE bridge: a projection arrow from the slip-box into a `memory/*.md` block (or
   into `.sase/memory/zettel/`), an `inbox / promotion` box upstream of the slip-box, and visible
   `APPLIES` / `TRIGGERS` / `PROVENANCE` labels on a sample zettel. The research note in
   `sdd/research/202605/zettel_sase_shared_memory.md` is the source of truth for this layer.
2. **Surface typed notes** (`&fact`, `&howto`, `&gotcha`, `&decision`, `&episode`, `&source`,
   `&index`, `&query`) since they are the projection contract that makes the vision useful for SASE
   memory.
3. **Replace the four-peer CAPTURE column with the maturation pipeline**:
   `Fleeting → Literature → Permanent (main) → Hub / Structure`, with `Todos` and `Refs` shown as
   cross-cutting types rather than peers in the pipeline.
4. **Disambiguate the central graph** by visually separating node IDs (`@foo`, `@foo/bar`), node
   kinds (`file zettel` / `dir zettel` / `note zettel`), and edge kinds (`child`, `sibling`,
   `backlink`, `inherited`, `folgezettel`, `tag`). Edge kinds belong on edges, not floating in the
   box.
5. **Use a concrete pair of example IDs** (e.g. `@sase/memory/audited-read` and
   `@sase/memory/read-evidence`) instead of `@foo` / `@foo/bar` so the placeholder syntax has a
   context.
6. **Mark v2 / aspirational features** (LSP actions, `@foo/bar` v2 syntax) with a distinct fill or a
   "Planned" tag, so a reader can tell shipped from planned. Alternatively split into two columns:
   "Today" vs. "Vision".
7. **Add an inbox + promotion node** showing the agent-write surface separated from canonical zettel
   by a deliberate promotion step. Even a small box labeled
   `.sase/memory/inbox/ → human review → canonical zettel` would carry the security-critical message
   from the research note.
8. **Replace `develop` and `navigate` with action phrases** that name the actor (e.g.
   `human curates and links`, `agent + human navigate / query / project into memory`).
9. **Rework the bottom strip** so it is either dropped or labeled as "Principles" with only true
   principles (`Atomic ideas`, `Contextualized links`, `Append-and-supersede`,
   `Provenance + trust`). Move `Inherited links` and `Graph navigation` out of the strip, since they
   belong to the relation list and the USE column respectively.
10. **Add a small legend** for shapes (node, edge, kind label, principle), color (current vs.
    planned, or human-edited vs. agent-projected), and the `@foo` placeholder convention.
11. **Increase font size of central labels** so the `child` / `sibling` / `backlink` text remains
    legible at GitHub Markdown thumbnail width. Match the infographic-style-brief width/aspect
    contract.
12. **Reference `docs/images/infographic-style-brief.md`** in the regen prompt so the visual
    language matches the rest of the docs diagram set, and write a
    `zorg-zettel-vision-infographic.prompt.md` sidecar (currently missing) that captures the final
    prompt, the intended embedding doc(s), alt text, and any post-processing notes.
13. **Confirm the embedding plan before regen.** Either link the new image from `docs/index.md`
    (e.g. a "Memory and knowledge base" section) or from a blog/series post, _or_ explicitly mark
    the image as internal to the epic and drop it from the doc set. Right now the image exists with
    no embedding, and a regen that does not also wire it in will leave the same dangling state.

A regen that addresses A1, A4, A7, A9 and C1, C2 alone would already turn this from a generic
personal-zorg picture into a SASE-doc-set asset; the remaining items are quality-of-life
improvements.
