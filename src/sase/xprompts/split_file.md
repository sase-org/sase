---
name: split_file
description: Split a large Python source file into smaller import-safe files.
input:
  file_path:
    type: path
    description: Python source file to split.
---

Can you help me split the `{{ file_path }}` file up into multiple files? Use your best judgement,
but let's aim to keep all files <=500 lines of code.
