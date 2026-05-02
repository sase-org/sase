---
create_time: 2026-04-21 21:17:32
status: wip
prompt: sdd/prompts/202604/batman_resume.md
---

# Batman-Themed Resume for Bryan Bugyi

## Goal

Rewrite Bryan's CV at `~/projects/CV/BryanBugyi_CV.tex` as a polished, Batman-themed resume that will resonate with an
AI-company founder who is also a Batman fan. The new version should be:

- **Substantively nicer** — stronger content, tighter language, quantified impact, better hierarchy.
- **Thematically Batman** — tasteful flair, not cosplay. A hiring manager should still take it seriously after one pass.
- **AI-forward** — prominently showcase `sase` (a sophisticated multi-agent software-engineering toolkit), since the
  reader is an AI-company founder.

The current CV is functional but dated: it leads with a generic "systems-oriented" summary, buries a very impressive
open-source portfolio at the bottom, and omits `sase` entirely — which is arguably Bryan's most compelling work for an
AI-company audience.

## Deliverables

Two files in `~/projects/CV/`:

1. `BryanBugyi_Batman_CV.tex` — the new resume source (leaving the original `BryanBugyi_CV.tex` untouched).
2. `BryanBugyi_Batman_CV.pdf` — the compiled PDF (built via `pdflatex`).

The original CV stays in place so Bryan can compare, revert, or keep two versions on hand.

## Design: Theme (tasteful, not kitsch)

The hiring manager needs to read this and think "this is a strong resume" first, "oh nice, Batman" second. Concretely:

- **Color palette** — Bat-black (`#0B0B0F`) for the primary accent bars, Gotham-gold (`#F5C518`) for highlights,
  off-white page, charcoal body text. Use `\definecolor` with the existing `xcolor[svgnames]` package. Reuse the
  existing `\resheading` shaded-box command but recolor the bars in bat-black with gold text.
- **Typography** — Keep the existing serif body font for readability. Promote a single display sans-serif for the name.
  Avoid novelty "Gotham" fonts; they read as gimmicky.
- **Iconography** — One discrete bat-signal glyph (Unicode `🦇` or a tiny TikZ silhouette) used sparingly: once next to
  the name, once as a section divider if it fits. No bat icons peppered throughout.
- **Epigraph** — A short Batman-adjacent pull quote under the header, set in italics. Candidates (pick one):
  - _"It's not who I am underneath, but what I do that defines me."_ — recontextualized as an engineering credo.
  - _"Why do we fall, sir? So that we can learn to pick ourselves up."_ — pairs with an engineering-reliability angle.
    The quote needs to feel earned — one line, no attribution chest-thumping.
- **Section names** — Replace plain headings with _subtle_ Batman-flavored labels, one word only, not punny:
  - Summary → **Dossier**
  - Education → **Training**
  - Industry Experience → **Casework** (Batman investigates cases)
  - Skills → **Utility Belt**
  - Open Source Projects → **Field Work** _(or keep "Open Source" if too cute)_

  If any of these feel too much, fall back to the plain name — the rule is "a founder reading this laughs once, not five
  times."

## Design: Content overhaul

Content changes independent of theme — these are the "way nicer" part:

1. **Lead with a stronger summary.** Replace "systems-oriented skill set" with a 2–3 line pitch that names: Python +
   Linux + distributed systems, ~9 years shipping production software, and current focus on agentic-AI tooling (sase).
   The AI-founder audience will read this first; it has to land.

2. **Add `sase` as the flagship open-source project.** Move it to the top of the Open Source section and give it the
   most real estate. Cover:
   - What it is ("Structured Agentic Software Engineering toolkit — orchestrates Claude Code, Gemini CLI, and Codex into
     a managed pipeline").
   - The scope signals: multi-agent TUI (ACE), daemon (AXE), YAML workflow engine, pluggy-based VCS/workspace plugins,
     Prometheus telemetry (33 metrics), bead-based issue tracking.
   - Inspired by research (Hassan et al. 2025, Vaziri et al. 2024) — demonstrates Bryan reads the AI literature.

3. **Tighten the experience bullets.** The existing Edgestream/Bloomberg bullets are wordy. Rewrite in the form "[verb]
   [what] [measurable impact]":
   - Google: keep concise, add any quantifiable wins Bryan can confirm (team size, product scale). If nothing
     confirmable, leave the current framing.
   - Bloomberg: "Founding engineer on the Compliance SRE team; led most Python projects; maintained the firm-wide Python
     cookiecutter; authored the ChangeLog Driven Release methodology adopted in alpha across Compliance."
   - Edgestream: lead with lint integration on a million-line codebase (strongest signal), then the Django investor
     portal, then the testing framework.
   - Comcast: shrink to one line — it's 10+ years old and carries less weight now.

4. **Fix the Skills section.** The current "lines-of-code" metric is quirky and takes a lot of real estate for a weak
   signal. Replace with a tighter three-band grouping:
   - **Primary:** Python, Linux, TCP/IP networking, Bash.
   - **Working:** C/C++, Rust, Perl, Java, JavaScript, Haskell, Vimscript.
   - **Tools:** Docker, Git, PostgreSQL, Redis, LaTeX, Vim, Prometheus/Grafana.
   - **Frameworks:** Django, FastAPI, Flask, Pluggy, ZeroMQ, Textual (for sase's TUI).

   Drop the LoC meta-commentary. If Bryan wants to keep it, we can restore it — but it's a common "first cut" item
   people later remove.

5. **Add an "AI / Agentic Systems" skills cluster.** Separate from the general tech stack, call out: Claude Code, Gemini
   CLI, Codex, prompt engineering, LLM orchestration, multi-agent workflow design. This is the hook for the reader.

6. **Preserve links** to LinkedIn, email, phone, and GitHub (`github.com/bbugyi200`). Add a GitHub link in the header —
   it's currently missing despite GitHub being where most of the cited work lives.

## Technical plan (LaTeX)

- **Start from** a copy of `BryanBugyi_CV.tex` so we keep the existing `\resheading`, `\ressubheading`, `\resitem`
  commands and the `gutils.tex` include working.
- **Keep** `pdflatex` as the build tool (confirmed installed at `/usr/bin/pdflatex`) — no need for xelatex/lualatex
  unless we want custom fonts, which we don't (see "no novelty fonts" above).
- **Recolor** the `\resheading` shaded boxes by redefining `shadecolor` and `shadecolorB` to bat-black / dark-gray, and
  wrap the heading text in `\color{batgold}\textbf{…}` so the gold pops on black.
- **Name header** — typeset in a slightly larger sans-serif via `\usepackage{helvet}` scoped to the name only, so the
  rest of the document stays in the existing serif.
- **Bat glyph** — use `\usepackage{emoji}` only if it compiles cleanly with pdflatex; otherwise fall back to a TikZ or
  `\faBatman` icon from `fontawesome5`. Verify which package is available before committing to one.
- **Compile** with `pdflatex -output-directory=~/projects/CV ~/projects/CV/BryanBugyi_Batman_CV.tex` (twice, to let
  `tocloft` settle). Clean up the `.aux`/`.log`/`.out` artifacts afterward.

## Risks / open questions

- **Founder tolerance for theme density** — we don't know this person. The plan errs on the side of _restrained_ theming
  (color + one glyph + one epigraph + subtle section names) rather than heavy (bat-signal watermarks, bat-ear bullet
  points, etc.). If Bryan wants more, we can escalate in a follow-up.
- **Content accuracy** — any new claim about Google-scale impact or Bloomberg specifics must come from Bryan, not from
  inference. The plan only sharpens wording on facts already in the existing CV.
- **Fonts / packages** — if `fontawesome5` or `emoji` aren't installed in the user's TeX Live, we'll fall back to the
  Unicode bat glyph (🦇) or omit it. We'll confirm during compile, not guess.
- **Keeping the original CV intact** is a hard requirement — the new file is `BryanBugyi_Batman_CV.tex`, not an in-place
  edit.

## Phases

1. Draft `BryanBugyi_Batman_CV.tex` from a copy of the original, applying all content + theme changes.
2. Compile with `pdflatex` (twice). Fix any missing-package errors by degrading gracefully (see Risks).
3. Clean up build artifacts (`.aux`, `.log`, `.out`).
4. Report back to Bryan with a diff summary + the PDF path, and flag anything that needs his confirmation (e.g., "I
   tightened the Google bullet — verify I didn't overstate anything").
