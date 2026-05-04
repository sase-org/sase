# Android Pixel PDF Reader Options for Full-width Agent Chats

Date: 2026-05-04

## Question

What Android PDF app is a better default than Kindle for reading agent-chat PDFs on a Pixel phone, especially when the
app should expand pages to the phone's readable width by default or with minimal setup?

## Summary

The best answer depends on whether "full size" means preserving the PDF page or reflowing the document text:

- For agent-chat PDFs with code blocks, tables, and markdown-like formatting, prefer a PDF-page viewer that supports
  fit-width, margin cropping, and continuous scrolling. This keeps layout intact.
- For prose-heavy PDFs, reflow/liquid/text modes can be more comfortable, but they may damage code-block and transcript
  structure.
- If the hard requirement is a persistent default of "fit to width" for every PDF, PDF Viewer Pro by Nutrient is the
  clearest match found, but that setting is behind its Pro advanced settings.
- Best first trial: Xodo. It has Android-specific view-mode and automatic page-cropping docs, strong Play Store
  adoption, and enough PDF tooling to be useful without turning the workflow into an editor subscription.

## Recommendation

### 1. First try: Xodo

Install Xodo and test it on 3 to 5 representative SASE/agent-chat PDFs. In the viewer, set continuous scrolling and use
`View Mode -> Crop Pages -> Automatically Crop Pages` on PDFs with large margins.

Why this is the best first trial:

- Xodo's Android docs describe a continuous view mode: one page, vertical scroll.
- Xodo's Android docs describe automatic page cropping that detects and removes margins from every page.
- It preserves the PDF page layout, which matters for chat transcripts, code blocks, stack traces, and markdown tables.
- The Play Store listing positions it as a phone/tablet PDF reader/editor with 10M+ downloads and a large review base.

Risk: I did not find an Android-specific Xodo source proving a global "always open new PDFs fit-width by default" toggle.
Xodo looks good for fast per-document setup, especially crop margins, but PDF Viewer Pro is a cleaner match if global
default fit-width is non-negotiable.

### 2. Best exact match for default fit-width: PDF Viewer Pro by Nutrient

PDF Viewer Pro's Android advanced settings include `Page Fit`, configurable as `Fit to Screen` or `Fit to Width`. The
same doc says these advanced settings require a Pro subscription.

This is probably the most direct replacement for Kindle if the desired behavior is:

1. Open a PDF.
2. App immediately scales each page to the phone width.
3. No manual pinch zoom for each document.

Tradeoff: lower Play Store adoption than Xodo/Adobe/Foxit, and the key setting appears to be paid.

### 3. Good alternate if reflow is acceptable: Adobe Acrobat Reader

Adobe Acrobat Reader's Android app has Liquid Mode, and the Play Store listing says it can adjust font size or spacing to
fit the screen. Adobe's own Android help describes Liquid Mode as a mobile reading experience that improves PDF layout on
phones and tablets.

Use this for prose PDFs. Do not make it the first choice for agent-chat PDFs unless testing confirms code blocks,
headings, and transcript structure remain readable.

### 4. Other plausible options

| App | Screen-fit mechanism | Fit for agent chats | Notes |
| --- | --- | --- | --- |
| Xodo | Continuous view plus automatic margin cropping | High | Best first trial. Preserves PDF layout. |
| PDF Viewer Pro | Pro `Page Fit` setting: `Fit to Width` or `Fit to Screen` | High | Best exact match for global default behavior, but likely paid. |
| ReadEra | PDF margin cropping, page-margin adjustment, PDF zoom | Medium | More of a book/document reader; worth trying if Xodo feels heavy. |
| Adobe Acrobat Reader | Liquid Mode/reflow | Medium | Good mobile prose reader; may be noisy with AI/subscription prompts. |
| Foxit PDF Editor | PDF reflow | Medium | Similar caveat to Adobe: useful for prose, less certain for code-heavy chats. |
| MJ PDF | Full screen, text mode, no ads, open source | Medium | Privacy-friendly, but not Play Store-first and may require APK install. |
| PDF Reflow - Book Reader | Reflow | Low | Explicitly marketed around reflow, but low rating and ads/data-safety concerns make it a weak default. |

## Markdown Files

For `.md` files, do not route through a PDF viewer if the file is available directly. Use a Markdown-aware Android app:

- Obsidian if the files live in a local synced folder or vault. Its Play Store listing describes it as working on a local
  folder of plain-text Markdown files.
- Markor if a lightweight, offline, file-oriented Markdown/text editor is preferable. Its project page says it supports
  Markdown and works with interoperable plain-text files.

This should be more readable than PDF on a phone because text wraps naturally to the screen.

## Pixel Default-app Setup

On a Pixel, after installing the chosen reader:

1. Open a representative PDF from Files, Downloads, Gmail, or the source app normally used for agent-chat PDFs.
2. When Android asks which app to use, choose the new PDF app and select `Always`.
3. If Kindle or another app keeps opening PDFs, clear that app's default preferences from Pixel Settings.

Google's Pixel help says Android can ask which app to use when multiple apps can handle a task, and choosing `Always`
prevents future prompts for that action. It also documents clearing defaults under `Settings -> Apps -> <app> -> Open by
default -> Clear default preferences`.

## Test Plan

Use the same small PDF set for all candidates:

1. One agent chat PDF with code blocks.
2. One long markdown-rendered transcript PDF.
3. One dense prose PDF.
4. One PDF with large margins.
5. One PDF opened from the actual source used on the phone, such as Gmail, Files, Telegram, or Drive.

Score each app on:

- Opens at readable width without pinch zoom.
- Remembers fit/crop/reading mode across reopen.
- Preserves code blocks and markdown tables.
- Supports vertical continuous scrolling.
- Does not force cloud upload, login, ads, or subscription prompts for basic reading.
- Can be selected as default from the source app that actually opens the PDFs.

## Sources

- Xodo Android changing view modes: https://feedback.xodo.com/support/solutions/articles/35000202742-changing-view-modes
- Xodo Android page cropping: https://feedback.xodo.com/support/solutions/articles/35000202853-cropping-pages
- Xodo Play Store listing: https://play.google.com/store/apps/details?gl=US&hl=en&id=com.xodo.pdf.reader
- PDF Viewer Pro Play Store listing: https://play.google.com/store/apps/details?id=com.pspdfkit.viewer
- PDF Viewer Pro Android advanced settings: https://pdfviewer.io/faq/android-advanced-settings/
- Adobe Acrobat Reader Play Store listing: https://play.google.com/store/apps/details?hl=en_US&id=com.adobe.reader
- Adobe Acrobat Android Liquid Mode help: https://www.adobe.com/devnet-docs/acrobat/android/de/lmode.html
- Foxit PDF Editor Play Store listing: https://play.google.com/store/apps/details?gl=us&hl=us&id=com.foxit.mobile.pdf.lite
- ReadEra Play Store listing: https://play.google.com/web/store/apps/details?hl=en-GB&id=org.readera
- MJ PDF official site: https://www.mjpdf.site/
- Pixel default apps help: https://support.google.com/pixelphone/answer/6271667?hl=en
- Obsidian Play Store listing: https://play.google.com/store/apps/details/Obsidian?hl=en-US&id=md.obsidian
- Markor project page: https://github.com/gsantner/markor
