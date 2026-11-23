---
max_turns: 20
allowed_tools: [Read, Glob, Grep, Skill, Bash]
timeout_seconds: 900
tags: [relion-refine]
---

sacct says my RELION refine job FAILED with exit code 134:0 after 14 h. The job dir has run_data.star (12,400 particles, the same number I put in), run_half1_class001_unfil.mrc, run_half2_class001_unfil.mrc, run_class001.mrc and a RELION_JOB_EXIT_SUCCESS file, and the end of the log says "Final resolution (without masking) is: 6.1". Did it work, and what should I do next? Should I resubmit?
