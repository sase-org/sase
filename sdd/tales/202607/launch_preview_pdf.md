---
create_time: 2026-07-07 01:06:50
status: done
prompt: sdd/prompts/202607/launch_preview_pdf.md
---
# Plan: Beautiful, full-prompt launch-preview PDFs

## Problem & product context

When SASE requests **launch approval**, it sends a Telegram message with a `launch_preview.pdf` attached so the approver
can review _exactly_ what will be launched from their phone. Today that PDF is not useful:

- **The prompt is truncated** to a 500-char snippet and its **line structure is destroyed** (`_prompt_snippet` does
  `" ".join(prompt.split())`, then cuts at ~500 chars with a trailing `...`). The approver literally cannot read the
  full instructions they are approving.
- **No syntax highlighting.** SASE prompts carry meaningful control tokens — name/wait/model directives (`%n:…`,
  `%wait(…)`, `%m(…)`), xprompt & workspace references (`#gh:…`, `#plan`, `#if_not_plan`, `#fork`), agent separators
  (`---`) and inline code — none of which stand out.
- **The layout is bland** — a flat bullet list of metadata with the (truncated) prompt dumped in a plain box. For a
  multi-agent fan-out it does not make the "N agents, here is each one" structure obvious.

Goal: make the launch-preview PDF **intuitive, reliable, and beautiful** — it should show the _complete_ prompt for
every agent, with SASE-aware syntax highlighting, in a clean mobile-friendly layout.

## How the preview is produced today (context for implementers)

1. `src/sase/agent/launch_preview.py` builds the request payload (full prompt is already stored per slot as
   `slot["prompt"]`) and `_render_launch_preview_markdown()` writes `launch_preview.md`.
2. `notify_launch_approval()` (`src/sase/notifications/senders.py`) posts a `LaunchApproval` notification with
   `files=[launch_preview.md, launch_request.json]`.
3. Two consumers read that **same** `launch_preview.md`:
   - **TUI**: `LaunchApprovalModal` shows it as source with `rich.syntax.Syntax(md, "markdown", "monokai")`.
   - **Telegram** (the `sase-telegram` linked repo): `sase_tg_outbound.py` converts each `.md` attachment to PDF at send
     time via `pdf_convert.md_to_pdf` → `sase.attachments.markdown_pdf.render_markdown_pdf` (pandoc → `wkhtmltopdf`,
     page 4.25in×7in, `--highlight-style=tango`, `--css=pdf_style.css`). Pre-rendered `.pdf` attachments are sent
     directly.

Because both surfaces read one file, the `.md` must stay **clean markdown** (raw HTML would show as tag noise in the
TUI). This shapes the design below.

## Design decisions

### D1 — Fix the data, not just the display: render the full prompt

The full prompt is already captured in the request payload. The renderer simply must stop using `prompt_snippet` and
instead emit the complete `slot["prompt"]` with its **original line breaks preserved**, inside a fenced code block. This
one change fixes the #1 complaint on **both** the TUI and the PDF. `prompt_snippet` (the whitespace-collapsed 500-char
field) stays in the JSON payload for other consumers but is no longer what the human-facing preview shows.

### D2 — Highlight via a declarative pandoc syntax definition (no new parser)

Add a KDE/skylighting **syntax definition** `sase.xml` and render the prompt in a ` ```sase ` fenced block. Pandoc's
`--syntax-definition=sase.xml` tokenizes it into semantic classes we then colour with CSS:

| Construct                   | Example                                         | skylighting class |
| --------------------------- | ----------------------------------------------- | ----------------- |
| `%`-directive               | `%n:actstat-…`, `%wait(time=20m)`, `%m(claude)` | `kw`              |
| `#`-xprompt / workspace ref | `#gh:gh_sase-org__sase`, `#plan`, `#fork`       | `fu`              |
| inline code                 | `` `actstat --repo …` ``                        | `st`              |
| agent separator line        | `---`                                           | `co`              |

**Why declarative, not a Python/Rust tokenizer:** this is _presentation_ highlighting, directly analogous to the
existing `saseproject.vim` syntax file and the TUI's Rich xprompt colouring — both live in frontends. Encoding it as a
static syntax file keeps prompt-parsing logic out of Python and therefore does **not** cross the Rust-core backend
boundary (no `sase-core` change). It is an approximate highlighter; the authoritative grammar remains the Rust xprompt
LSP. _(Decision point for review: if you'd rather this highlighting be shared with a future web frontend via
`sase-core`, say so and we route it through a binding instead — but that is a larger, separate effort and not needed for
parity with the TUI today.)_

This approach was validated end-to-end by rendering real and multi-agent requests to PDF (see "Validation" below).

### D3 — Dedicated launch-preview styling, scoped so nothing else regresses

The beautiful layout (accent title rule, per-agent section headers, prompt card, token palette, the wkhtmltopdf
wrap-fix) lives in a **dedicated CSS** (`launch_preview.css`) and a small helper `render_launch_preview_pdf()` in the
main repo's `sase.attachments` package. Telegram routes only `launch_preview.md` through this helper; all other Telegram
documents (chat responses, plans) keep using the generic renderer/CSS unchanged. The main repo owns the appearance and
its tests; `sase-telegram` gains only a one-line routing branch.

### D4 — Keep the shared `.md` clean; degrade gracefully

`launch_preview.md` stays pure markdown (headings, paragraphs, ` ```sase ` fences) so the TUI modal remains readable. If
the syntax-highlighted render fails for any reason (missing `sase.xml`, engine quirk), `render_launch_preview_pdf` falls
back to the generic `render_markdown_pdf`, and Telegram already falls back to sending the raw `.md` — so **the full
prompt is always delivered**, with or without colour.

## Visual / UX design

Single mobile page (4.25in wide), light theme:

- **Title** "Launch Preview" with a coloured accent rule; the redundant pandoc document-title header is suppressed.
- **Summary line**: `**N agents** · source `agent_skill` · all-or-nothing`.
- **Per agent** (one section each, so fan-out reads as "Agent 1 of 3 …"):
  - `## Agent i of N · <project>` with a coloured left-border.
  - a muted meta line: `model … · kind … · name …`.
  - the **full prompt** in a card, syntax-highlighted, wrapping cleanly at word boundaries.
  - a small dim `SHA-256 <short>` integrity line.
- **Palette**: directives = purple (`#8250df`, bold), xprompts = blue (`#0550ae`, bold), inline code = green
  (`#116329`), primary accent indigo (`#6f42c1`). Chosen for contrast/beauty on white; final values tuned against golden
  renders.

Before → after is the difference between a one-paragraph truncated blob and a scannable, complete, colour-coded brief.

## Changes by component

### A. `sase` repo — `src/sase/agent/launch_preview.py`

- Rewrite `_render_launch_preview_markdown()`:
  - emit the **full** `slot["prompt"]` (preserve newlines) in a ` ```sase ` fence instead of the truncated
    `prompt_snippet`.
  - new layout: single title, summary line, `## Agent i of N · project` sections, meta line, prompt fence, short SHA
    line.
  - **Fence-safety**: pick a fence length longer than the longest backtick run in the prompt (or use `~~~~`) so prompts
    containing ` ``` ` can't break out of the block. (Latent bug in the current ` ```text ` code too.)
- Leave the JSON payload/`prompt_snippet` fields as-is (compatibility).

### B. `sase` repo — `src/sase/attachments/`

- Add `sase.xml` (skylighting syntax definition) and `launch_preview.css` (layout + token palette + the
  pandoc/wkhtmltopdf wrap-fix; see Validation).
- Extend `render_markdown_pdf(...)` with an optional `syntax_definitions` parameter that appends
  `--syntax-definition=<path>` and lets the caller pass a no-auto-title option. Keep existing signature/behaviour the
  default.
- Add `render_launch_preview_pdf(md_path, dest) -> Path | None` that calls `render_markdown_pdf` with
  `css=launch_preview.css` + `syntax_definitions=[sase.xml]`, and falls back to a plain render on failure.
- Ship the two asset files in the package data so they're found at runtime.

### C. `sase-telegram` linked repo

- `src/sase_telegram/pdf_convert.py` / `scripts/sase_tg_outbound.py`: when the attachment basename is
  `launch_preview.md`, call `render_launch_preview_pdf` instead of the generic `md_to_pdf`. Everything else unchanged;
  existing raw-`.md` fallback preserved.

### D. (Optional, Phase 3) TUI parity

`LaunchApprovalModal` currently shows the `.md` source. Optionally render the prompt with matching Rich token colouring
(reusing the same token categories) so the desktop review looks as good as the PDF. Nice-to-have; not required for the
user's request.

## Reliability & edge cases

- **Always-complete prompt**: highlighting is additive; failure never drops prompt content (D4).
- **Fence safety** for prompts containing triple backticks (B/A).
- **Multi-agent fan-out**: each slot rendered as its own section with its own prompt and SHA.
- **Engine fallback**: `wkhtmltopdf`→`xelatex`→`pdflatex` already handled; skylighting works for the LaTeX path too.
- **No injection risk**: prompt text lives inside a pandoc code fence (escaped), not raw HTML.
- **Very long prompts** paginate naturally.

## Testing

- Unit tests for `_render_launch_preview_markdown`: full prompt present & untruncated, newlines preserved, one section
  per slot, fence-safety with an embedded ` ``` `, metadata correctness.
- `render_launch_preview_pdf`: asserts pandoc is invoked with the syntax definition + dedicated CSS; falls back on
  failure; returns `None` cleanly when tooling absent (mirror existing `test_markdown_pdf.py` patterns).
- A guarded end-to-end smoke render (skips if `pandoc`/`wkhtmltopdf` absent) producing a non-empty PDF from a
  representative multi-agent request.
- `sase-telegram`: routing test that `launch_preview.md` uses the dedicated renderer while other `.md` attachments use
  the generic path.
- Golden markdown snapshot for the new preview layout.

## Validation already performed (de-risking)

Rendered a **real** single-agent request and a synthetic 3-model fan-out to PDF with a prototype `sase.xml` + CSS via
the exact production pipeline (pandoc + wkhtmltopdf, 4.25in×7in). Confirmed:

- full prompt with preserved line structure;
- directives/xprompts/inline-code each distinctly coloured and consistently classified;
- clean per-agent sections for fan-out.

Two wkhtmltopdf-specific gotchas were found and solved, to bake into `launch_preview.css`:

1. Pandoc wraps each source line in `pre>code.sourceCode>span{display:inline-block;text-indent:-5em;padding-left:5em}`;
   old wkhtmltopdf then breaks **mid-word**. Fix: force those spans
   `display:inline!important; text-indent:0!important; padding-left:0!important` and hide the empty `<a>` line anchors →
   clean space-wrapping.
2. tango colours `kw` and `fu` identically; override each class with `!important` to get the distinct directive/xprompt
   palette.

## Out of scope

- Moving preview rendering into `sase-core` (D2 decision point).
- Redesigning the non-launch Telegram document PDFs.
- Changing the launch-approval request schema.

## Phasing

1. **Full prompt** in `launch_preview.md` (fixes TUI + PDF immediately).
2. **Highlighting + layout + dedicated CSS/`sase.xml` + Telegram routing.**
3. _(optional)_ TUI modal highlighting parity.
