---
create_time: 2026-04-23 20:51:33
status: done
prompt: sdd/prompts/202604/telegram_xprompts_pdf.md
---
# Telegram `/xprompts` Catalog: Beautiful PDF + Stats

## 1. Goal

Add a new Telegram slash command that generates a beautifully-formatted PDF catalog of **every xprompt visible to the
sase runtime** — from every source, across every known project — and sends it to the user along with a concise Telegram
message summarising the catalog (total count, per-project breakdown, tag highlights, etc.).

The bar for "beautiful" is real: this PDF should feel like a carefully designed reference document, not a dumped
markdown file. Typography, colour, whitespace, and information hierarchy all need to be deliberate.

## 2. User Experience

### 2.1 Invocation

- User opens the Telegram chat with the bot.
- Types `/xprompts` (appears in the autocomplete menu alongside `/list`, `/listx`, `/kill`, `/resume`).
- Bot immediately replies with an acknowledgement (`"Building your xprompts catalog…"`) so the user knows work is
  underway — generation can take several seconds because pandoc + wkhtmltopdf is invoked.
- When generation finishes, the bot sends **one** message: the stats summary as the caption and the PDF as the
  attachment.

### 2.2 The Stats Message (caption on the PDF)

Rendered in HTML (matching the convention of `_handle_list_command` / `_handle_listx_command`). Intentionally terse —
the PDF is the artefact; the caption is the teaser.

```
📚 <b>xprompts Catalog</b>

<b>42</b> xprompts across <b>7</b> projects

• Built-in:     18
• Project:      16
• Config:        5
• Plugin:        2
• Memory (auto): 1

Top tags: <code>#git</code> · <code>#plan</code> · <code>#review</code>

Generated 2026-04-23
```

Limits: Telegram captions cap at 1024 characters, so the caption must stay short. If we want a richer breakdown, it goes
in the PDF.

### 2.3 Failure modes

- **No PDF engine installed** (neither wkhtmltopdf, xelatex, nor pdflatex): bot replies with a plain text message
  showing the stats + a note that the PDF engine is missing on the host.
- **No xprompts found** (extremely unlikely — built-ins always exist): send a plain text message saying so; do not
  attach an empty PDF.
- **Unexpected exception**: bot sends a short error message, full traceback goes to logs like existing handlers.

## 3. Architecture

Two repos are involved. We keep the boundary clean by placing all the heavy lifting in the `sase` repo (where the
xprompt loader already lives) and keeping the `sase-telegram` change thin.

### 3.1 New module in `sase_103` (this repo)

`src/sase/xprompt/catalog.py` — the single public surface for generating the catalog. Exports:

```python
@dataclass(frozen=True)
class CatalogStats:
    total: int
    by_source: dict[str, int]   # built-in, project, config, plugin, memory
    by_project: dict[str, int]  # project_name -> count
    by_tag: dict[str, int]      # tag -> count (sorted desc)
    with_description: int
    with_inputs: int
    skills: int
    generated_at: datetime

@dataclass(frozen=True)
class CatalogArtifact:
    pdf_path: Path
    stats: CatalogStats

def build_xprompts_catalog(output_dir: Path | None = None) -> CatalogArtifact:
    """Gather every xprompt, compute stats, render a beautiful PDF.

    The PDF path is stable: <output_dir>/xprompts_catalog_<date>.pdf
    Falls back to a tempdir if output_dir is None.
    """
```

Internally `catalog.py` will:

1. Call `get_all_xprompts()` for globally-visible xprompts.
2. Walk `get_known_project_workspaces()` and call `load_project_local_xprompts(ws, project)` for each to capture
   project-local xprompts that `get_all_xprompts()` would not otherwise surface (since that function takes a single
   active project).
3. De-duplicate by `(source_path, name)` so the same built-in isn't counted twice when the user is inside one of the
   enumerated projects.
4. Classify each xprompt into a "source bucket" based on `source_path`:
   - Built-in: path under the installed `sase` package.
   - Project-local: path under a known workspace dir.
   - Config: `source_path == "config"` or under `~/.config/sase/`.
   - Plugin: path inside a site-packages plugin dir (detected via entry point metadata already known by the loader).
   - Memory auto-discovered: path under `memory/long/` in any workspace.
5. Build a structured `CatalogDocument` dataclass (sections, project groups, per-prompt cards) — this in-memory model is
   what the renderer consumes.
6. Render to HTML (templated — Jinja2 is already a dep), then hand off to pandoc via `wkhtmltopdf`.
7. Return the artefact.

### 3.2 New CLI subcommand

`sase xprompt catalog [--out PATH]` — a thin wrapper over `build_xprompts_catalog`. Prints the resulting PDF path on
stdout and a JSON-encoded stats blob on stderr (so scripts can pipe either). Lives next to the existing subcommands in
`xprompt_handler.py` and wires through the argparse tree the same way `list`/`graph`/`explain` do.

Rationale: having a CLI entry point gives us manual testability (`sase xprompt catalog --out /tmp/out.pdf`) independent
of Telegram, matches the existing pattern, and makes the functionality reusable by other plugins later. Short option
`-o` for `--out` (per `memory/short/gotchas.md`).

### 3.3 Changes in `sase-telegram` (external repo)

In `scripts/sase_tg_inbound.py`:

1. Add `("xprompts", "Export the xprompts catalog as a PDF")` to `_SLASH_COMMANDS`.
2. Add `_handle_xprompts_command(chat_id: str) -> None`:
   - Acks with `"📚 Building your xprompts catalog…"`.
   - Imports `build_xprompts_catalog` from `sase.xprompt.catalog`.
   - Calls it; catches the "no PDF engine" case (returned as an explicit sentinel on `CatalogArtifact.pdf_path`, or a
     raised `PdfEngineUnavailable` exception — see §7.3).
   - Builds the HTML caption from `stats`.
   - Calls `telegram_client.send_document(chat_id, pdf_path, caption=...)`.
3. Dispatch in `_handle_command()` alongside the other handlers.

Imports in sase-telegram from the `sase` package are already routine (it uses `sase.agent.running`, etc.), so no new
cross-repo plumbing is needed.

The sase-telegram change is out of scope for _this_ repo's commit — we write the `sase_103` side first (CLI + library),
confirm it works end-to-end via the CLI, then make the matching PR in sase-telegram.

## 4. Data — What Goes in the PDF

For every xprompt we have the following fields from `XPrompt` (see `src/sase/xprompt/models.py:147`):

| Field         | Use in PDF                                              |
| ------------- | ------------------------------------------------------- |
| `name`        | The card title, rendered as `#name` in monospace        |
| `description` | Subheading under the title (italic, muted)              |
| `source_path` | Small label at top-right of card ("built-in", project…) |
| `tags`        | Coloured pill row                                       |
| `inputs`      | Argument signature line: `(plan_file: path, notes?)`    |
| `content`     | Code block, truncated to first ~40 lines + elision      |
| `keywords`    | Small muted row "keywords: foo, bar"                    |
| `skill`       | Badge if truthy                                         |
| `snippet`     | Only a footnote if `snippet is False`                   |

For workflow-style xprompts (`.yml` multi-step), we render the step list (name + kind) rather than raw content, matching
how `_handle_list` does it today.

## 5. PDF Design

The renderer builds an HTML document styled by a new `src/sase/xprompt/catalog_style.css` and converted by pandoc +
wkhtmltopdf. Using HTML/CSS (rather than a Python PDF library like reportlab) is the right call because: (a) the
existing PDF pipeline already uses it; (b) no new dependencies; (c) CSS gives us typography, colour, and layout power
cheaply. wkhtmltopdf supports `@page` rules, headers/footers, page breaks, and subtle gradients — enough for a polished
result.

### 5.1 Document structure

1. **Cover page** (full bleed)
   - Large title: _xprompts Catalog_
   - Subtitle: _A complete reference for this sase environment_
   - Generated date, hostname, total counts (huge numerals in a 3-up grid: `42 prompts · 7 projects · 5 sources`)
   - Subtle diagonal gradient or a single solid accent colour block at the bottom third. No clipart, no emoji.
   - Footer: `sase · <version>`

2. **Table of contents** (one page)
   - Grouped by source bucket, then by project.
   - Each entry: `#name` (left, monospace) ................. page (right).
   - Dot leaders between name and page number.

3. **Overview / stats dashboard** (one page)
   - Large "At a glance" heading.
   - Three side-by-side cards: counts by source, counts by project, top tags. Simple horizontal bar charts rendered as
     styled `<div>` bars (no JS, no SVG library needed — width: %; background: gradient).
   - Coverage line: _"34 of 42 prompts (81%) have descriptions"_.

4. **Body: section per source bucket**
   - Section divider page: big section name (e.g. _Project xprompts_) with a muted count underneath, centred vertically.
   - Within a section, xprompts are grouped by project (if applicable) and sorted alphabetically.
   - Each group starts with a muted "Project: my-project" banner (`border-left` accent).

5. **xprompt cards**
   - Name (monospace, 18pt, with a leading `#`).
   - Source-path label (top right, uppercase, letterspaced, muted).
   - Description line (italic, 11pt, muted).
   - Metadata row: tag pills + input signature.
   - Code block for content (truncated to ~40 lines, with a "… (N more lines)" line if clipped).
   - Soft horizontal divider between cards; `break-inside: avoid` so we never split a card across pages if it fits.

### 5.2 Typography

- **Headings**: `"Inter", "Helvetica Neue", Arial, sans-serif` (with a fallback chain so we're safe on machines without
  Inter).
- **Body**: same sans-serif, slightly smaller.
- **Monospace** (for names, code, signatures): `"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace`.
- Font sizes scale down from 32pt (cover title) → 18pt (card name) → 11pt (body) → 9pt (footer / metadata).

### 5.3 Colour palette

- Ink: `#1B1F24` (body text)
- Muted: `#6A7380` (subtitles, metadata)
- Paper: `#FBFAF6` (warm off-white page background — signals "document", not "web app")
- Accent: `#3A4AB8` (deep indigo — used for the cover block, TOC dot leaders' tint, section dividers' left border)
- Accent-soft: `#E8EBFA` (tag pill background default)
- Code background: `#F3F1EA` (slight warm grey so it sits naturally on the paper tone)

Tag pills cycle through 4 desaturated background colours (indigo, teal, amber, rose) keyed on `hash(tag)` — gives visual
variety without feeling random. Pills are 10pt, 2px radius, 4/8 padding.

### 5.4 Page chrome

- `@page` margin: 18mm top/bottom, 20mm left/right.
- Running header (pages > 1): xprompt name of the current card on the left, "xprompts Catalog" on the right, 8pt, muted,
  hairline rule beneath.
- Running footer: page N of M, centred, 8pt, muted.
- Cover page suppresses both header and footer.

### 5.5 Preview truncation

Long xprompts (especially workflow YAMLs) will dominate the PDF if included in full. Rule: show at most 40 lines of
content per card; if truncated, append a line like `… (238 more lines — see <source_path>)`. The goal is a browsable
reference, not a full dump.

## 6. Statistics

Computed once during gathering:

- `total` — count of distinct xprompts.
- `by_source` — dict[bucket, count] across the five buckets in §3.1.4.
- `by_project` — dict[project_name, count] for project-local xprompts only.
- `by_tag` — all tags across all xprompts, sorted descending by count.
- `with_description` / `with_inputs` / `skills` — coverage counters.
- `generated_at` — `datetime.now(UTC)`.

These feed both the PDF's overview page and the Telegram caption.

## 7. Technical Considerations

### 7.1 Where does the PDF rendering code actually live?

We put the HTML template + CSS in `src/sase/xprompt/` next to the new module:

- `catalog.py` — logic
- `catalog_template.html.j2` — Jinja2 HTML template
- `catalog_style.css` — companion stylesheet

Pandoc invocation mirrors the existing `pdf_convert.py` pattern, but directly from HTML (not markdown) since we want
tight layout control:

```
pandoc input.html -o out.pdf --pdf-engine=wkhtmltopdf \
    --css catalog_style.css --metadata title="xprompts Catalog"
```

Actually, wkhtmltopdf can be invoked directly (bypassing pandoc) for HTML input, which removes a translation layer and
gives us access to the `--header-html`/`--footer-html`/`--print-media-type` flags. I recommend invoking `wkhtmltopdf`
directly when available, falling back to pandoc otherwise.

### 7.2 Dependency policy

No new Python runtime deps. wkhtmltopdf / pandoc are system-level binaries the telegram plugin already depends on via
`pdf_convert.py`. We add a runtime check and surface a clear error if they're missing.

### 7.3 Error surface

Two explicit exception types in `catalog.py`:

- `PdfEngineUnavailable` — no HTML-capable engine on PATH. Caller (Telegram handler or CLI) can catch and render a
  text-only fallback.
- `NoXpromptsFound` — catalog would be empty (essentially unreachable, but guarded so we don't produce a zero-card PDF).

### 7.4 Performance

`get_all_xprompts` + walking projects is already fast (sub-second for realistic sizes). PDF rendering is the dominant
cost; wkhtmltopdf on a modest catalog should finish in <5 s. We don't need async. The Telegram ack message before
generation covers the latency.

### 7.5 Testing

Under `tests/xprompt/test_catalog.py`:

- Unit: `build_xprompts_catalog` against a seeded fixture of fake xprompts covering every bucket; assert stats counts
  and that the output HTML contains each expected section.
- Integration: if `wkhtmltopdf` is available on the test host, actually generate a PDF and assert it's non-zero bytes
  and parseable (`pypdf` is not a dep — we just check magic bytes `%PDF-`).
- Edge cases: empty project (shouldn't crash TOC), xprompt with `snippet: False` (still included in PDF since this is a
  reference, but marked), workflow-style `.yml` xprompt rendered as step list.

No tests modify the user's `~/.sase/` — fixtures inject fake workspaces via the existing `get_known_project_workspaces`
seam (monkeypatch).

Telegram-side tests remain in the sase-telegram repo; not in scope here.

### 7.6 Config / flags

Keep it minimal for v1. The CLI accepts `-o/--out PATH`. No knobs for "include built-ins only", "project filter", "max
content lines" — all useful, all easy to add later, none required now (per the "don't design for hypothetical future
requirements" rule in CLAUDE.md).

## 8. Implementation Outline

Ordered for incremental testability:

1. **`catalog.py` skeleton** — dataclasses, gather-xprompts logic, stats computation, `NoXpromptsFound` error. No
   rendering yet. Unit test the stats.
2. **HTML template + CSS** — Jinja2 template + `catalog_style.css`. Render to a standalone HTML file and eyeball it in a
   browser before involving PDF tooling.
3. **PDF rendering** — `_render_pdf(html_path, pdf_path)` helper using wkhtmltopdf directly, with pandoc fallback and
   `PdfEngineUnavailable`.
4. **CLI wiring** — `sase xprompt catalog [-o PATH]` added to `xprompt_handler.py` and the argparse tree. Manual test:
   run on a real machine, open the PDF, iterate on CSS until it looks right.
5. **`just check`** — lint, type, test must pass.
6. **Commit** in `sase_103` using `/sase_git_commit`.
7. _(Follow-up, separate PR in sase-telegram)_ Add `/xprompts` handler that calls the library, sends the PDF via
   `send_document`.

## 9. Open Questions

1. **Cover graphics.** I'm inclined to keep the cover typographic-only (no SVG hero image, no emoji). If you want a logo
   or a generative motif (e.g. a concentric-rings pattern derived from prompt counts), say so and I'll add an SVG block.
2. **Content truncation threshold.** I've picked 40 lines per card. Happy to go shorter (20) for a more "index-like"
   feel or longer (100) if you want the PDF to serve as a read-everything reference.
3. **Sorting inside sections.** Alphabetical by name is the obvious default. Alternative: group by tag. Alphabetical
   keeps the TOC predictable, so I'd stick with it unless you disagree.
4. **CLI subcommand name.** `sase xprompt catalog` reads naturally to me; alternatives are `report`, `pdf`, or `export`.
   No strong preference.
5. **Scope of `sase-telegram` changes in this change request.** My recommendation is to split: land the library + CLI in
   `sase_103` first, then do the Telegram wiring in a follow-up since it's a separate repo. If you want both in
   lockstep, say so and I'll include the Telegram patch as part of the work (requires commits in two repos).
