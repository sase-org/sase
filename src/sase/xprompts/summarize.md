---
name: summarize
description: Summarize a file in a short phrase for a specified use.
input:
  target_file:
    type: path
    description: File whose contents should be summarized.
  usage:
    type: line
    description: Context where the summary will be used.
---

Can you help me summarize the @{{ target_file }} file in <=30 words (preferably <=25 or
even <=15 words)? This summary will be used as {{ usage }}.

#json:`{ summary: line }`
