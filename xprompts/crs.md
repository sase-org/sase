---
name: crs
input:
  - name: critique_comments_path
    type: path
  - name: cl_name
    type: word
    default: "null"
---

{% if cl_name != "null" %}#hg:{{ cl_name }}

{% endif %}Can you help me address the Critique comments? Read all of the files below VERY carefully to make sure that
the changes you make align with the overall goal of this CL! Make the necessary file changes.

<!-- prettier-ignore -->
+ @{{ critique_comments_path }} - Unresolved Critique comments left on this CL (these are the comments you should address!)

#propose
