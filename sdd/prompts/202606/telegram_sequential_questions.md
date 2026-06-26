---
plan: sdd/tales/202606/telegram_sequential_questions.md
---
 The way that sase's Telegram integration works currently, when an agent asks multiple questions at once, only the first question gets asked via a Telegram message. Can you help me make it so that when the first question is answered in a multi-question request, the next question message is sent in Telegram and so on and so forth until we're out of questions? Make sure that each question message is numbered clearly so the user understands how many questions there are and what question they are looking at. I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 