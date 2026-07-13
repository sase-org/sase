---
pdf: false
---

# Memory Directory Map Prompt

## Target

Packaged source asset: `src/sase/memory/assets/memory-directory-map.png`.

Copied generated asset: `memory/assets/memory-directory-map.png`.

Embedded in the generated `memory/README.md` immediately after the opening introductory paragraph.

## Intended Alt Text

Memory architecture showing short notes always in context, long notes read on demand, generated provider shims, and
drift checks.

## Final Asset Status

The committed PNG is the final Phase 3 infographic. It uses a GPT-generated text-free structural base with deterministic
ImageMagick labels overlaid afterward. Both committed PNG copies must remain byte-identical.

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: documentation PNG for a generated memory/README.md, 16:9 landscape around 1600x900.

Primary request: Create a completely text-free structural base for a software architecture infographic explaining how
markdown memory notes become agent context and generated documentation. The result should be a polished, crisp
documentation diagram, not marketing art.

Scene/backdrop: light neutral warm-gray background with subtle paper-like panels, strong contrast, plenty of whitespace,
clean flat vector-like geometry.

Composition/framing: left-to-right architecture flow with a bottom freshness-loop band. Leave generous blank rectangular
label zones inside every major shape. No words, letters, numerals, pseudo text, fake UI text, logos, watermarks, or
terminal screenshots anywhere.

Left zone: a stack of 4 markdown note-card shapes, slightly offset, with small blank frontmatter tag strips near the top
of the cards. Use a teal accent for source notes.

Middle zone: split into two horizontal swimlanes. Upper lane for always-loaded short notes: a compact source block flows
into a central generated-file block, then fans out to four small output document cards. Use blue and amber accents.
Lower lane for long notes: a reference-note block flows through a small audit/check gate and then into an agent context
block. Use green and slate accents. The two lanes should clearly belong to one system but be visually distinct.

Right zone: show a larger agent working-context panel containing two nested blank content cards, and a separate
generated README document panel. Connect the short-note and long-note lanes into the agent context, and connect the
system to the README panel.

Bottom band: show a low horizontal freshness loop with two rounded command blocks, a circular arrow motif, and a small
gate/checkpoint motif. It should visually imply regeneration and drift checking without containing any text.

Style/medium: flat vector-like illustration rendered as a high-resolution raster; crisp thin outlines; softly rounded
rectangles; restrained multi-accent palette (teal, blue, amber, green, slate, small purple accent); minimal shadows; no
dark mode; no decorative gradients that reduce label contrast.

Constraints: absolutely no generated text, no glyphs, no letters, no numbers, no fake lorem ipsum lines, no logos. Make
all label areas blank and light enough for dark deterministic labels to be added later. Avoid dense detail, tiny
elements, or decorative clutter. Do not imply that image generation runs during the memory init loop.

## Deterministic Labels

Final labels are added locally with `magick` and `FiraCode-Regular`. Some labels are wrapped across lines to keep the
image readable at GitHub Markdown width, but the terminology matches the memory system exactly.

Required labels:

- `memory/*.md`
- `frontmatter`
- `type: short | long`
- `parent:`
- `description:`
- `Tier 1: short notes`
- `always in context`
- `AGENTS.md`
- `provider shims`
- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md`
- `OPENCODE.md`
- `Tier 2: long notes`
- `reference, loaded when relevant`
- `sase memory read`
- `audited`
- `agent context`
- `memory/README.md`
- `sase memory init`
- `regenerate`
- `sase validate`
- `drift gate`

Supplemental labels:

- `inlined`
- `short notes present`
- `long notes fetched`
- `self-updating docs`
- `README`

## Post-Processing Notes

Use ImageMagick 7 from the repository root. `BASE_PNG` is the selected GPT-generated text-free base.

```bash
magick "$BASE_PNG" -resize 1600x900! -strip -colorspace sRGB \
  -font FiraCode-Regular -fill '#172033' -draw "$DRAW" \
  src/sase/memory/assets/memory-directory-map.png
cp src/sase/memory/assets/memory-directory-map.png memory/assets/memory-directory-map.png
cmp src/sase/memory/assets/memory-directory-map.png memory/assets/memory-directory-map.png
```

The `DRAW` MVG block below records the deterministic backing boxes, font sizes, and label coordinates:

```text
stroke "none"
fill "rgba(255,255,255,0.86)"
roundrectangle 76,94 233,133 8,8
roundrectangle 72,148 228,288 8,8
roundrectangle 385,141 503,242 8,8
roundrectangle 600,146 785,235 8,8
roundrectangle 912,55 1030,83 6,6
roundrectangle 925,103 1016,128 5,5
roundrectangle 925,188 1018,213 5,5
roundrectangle 925,276 1010,301 5,5
roundrectangle 922,365 1024,390 5,5
roundrectangle 394,490 532,632 8,8
roundrectangle 622,526 763,621 8,8
roundrectangle 835,527 995,617 8,8
roundrectangle 1146,226 1260,260 7,7
roundrectangle 1150,375 1276,426 7,7
roundrectangle 1150,530 1276,581 7,7
roundrectangle 1364,238 1532,324 7,7
roundrectangle 400,748 574,820 7,7
roundrectangle 868,748 1054,820 7,7
roundrectangle 1140,744 1306,828 7,7
fill "#172033"
font "FiraCode-Regular"
font-size 26
text 83,122 "memory/*.md"
font-size 18
text 82,174 "frontmatter"
font-size 15
text 84,216 "type: short | long"
text 84,242 "parent:"
text 84,268 "description:"
font-size 21
text 395,170 "Tier 1:"
text 395,198 "short notes"
font-size 17
text 395,230 "always in context"
font-size 24
text 620,176 "AGENTS.md"
font-size 17
text 642,220 "inlined"
font-size 16
text 918,75 "provider shims"
font-size 15
text 932,122 "CLAUDE.md"
text 932,207 "GEMINI.md"
text 932,295 "QWEN.md"
text 929,384 "OPENCODE.md"
font-size 21
text 405,518 "Tier 2:"
text 405,546 "long notes"
font-size 15
text 405,575 "reference,"
text 405,598 "loaded when"
text 405,621 "relevant"
font-size 18
text 635,552 "sase memory"
text 664,577 "read"
font-size 16
text 654,615 "audited"
font-size 22
text 846,556 "agent context"
font-size 16
text 864,590 "reference fetched"
font-size 23
text 1160,250 "agent context"
font-size 17
text 1160,397 "short notes"
text 1160,419 "present"
text 1160,552 "long notes"
text 1160,574 "fetched"
font-size 22
text 1374,263 "memory/"
text 1374,291 "README.md"
font-size 16
text 1374,317 "self-updating docs"
font-size 22
text 412,775 "sase memory"
text 455,803 "init"
font-size 15
text 427,828 "regenerate"
font-size 22
text 879,775 "sase validate"
font-size 15
text 922,828 "drift gate"
font-size 16
text 1164,773 "README"
text 1164,798 "AGENTS.md"
text 1164,823 "provider shims"
```
