---
plan: sdd/epics/202604/markdown_pdf_attachments.md
---
  Can you help me add support for creating PDFs from any markdown files sase agents create or modify?

- This functionality should work a lot like our new image integration. We should attach the PDF file to the agent completion notification and attach the PDF to the corresponding telegram/gchat message.
- This should obsolete the existing special treatment for the sdd/research/ directory that our Telegram integration has.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

