---
name: summarize
input: { target_file: path, usage: line }
---

Can you help me summarize the @{{ target_file }} file in <=30 words (preferably <=25 or even <=15 words)? This summary
will be used as {{ usage }}.

#json:`{ summary: line }`
