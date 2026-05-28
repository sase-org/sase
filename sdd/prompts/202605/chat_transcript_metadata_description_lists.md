---
plan: sdd/tales/202605/chat_transcript_metadata_description_lists.md
---
 We currently render the timestamp, model, and agent name in the following form in sase agent chat transcript
files (i.e. in markdown files in the ~/.sase/chats/ directory):

```
**Timestamp:** 2026-05-28 09:16:41 EDT **MODEL:** codex/gpt-5.5 **AGENT:** reads.final-2
```

Can you help me start using the following description-list format instead (note the two spaces after the field names)?
Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
**Timestamp**
2026-05-28 09:16:41 EDT

**MODEL**
codex/gpt-5.5

**AGENT**
reads.final-2
```