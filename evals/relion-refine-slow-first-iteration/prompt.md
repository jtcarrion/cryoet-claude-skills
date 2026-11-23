---
max_turns: 25
allowed_tools: [Read, Glob, Grep, Skill, Bash]
timeout_seconds: 900
tags: [relion-refine]
---

My relion_refine_mpi auto-refine (RELION 5, particle series from WarpTools, 30k particles, 4 GPUs) has been on iteration 1 for 20 hours. I used an EMDB map of the same complex, resampled to my pixel size, as the reference. The log says "Estimated accuracy angles= 30 degrees" and the ETA keeps growing. Is this an I/O problem? Should I switch from preread to scratch or change the MPI layout?
