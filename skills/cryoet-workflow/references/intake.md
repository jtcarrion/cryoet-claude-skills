# Intake: the questions a new user must answer

Ask in this order. **Detect first, then ask only what detection could not settle**: every question below says where
its answer can come from. Batch questions (AskUserQuestion takes up to 4 per call) and offer the detected value as the
first option, marked "(detected)". Never invent a value for a "must ask" question.

Legend: **auto** = detected, show it and move on unless the user objects; **confirm** = detected but easy to get
wrong, ask the user to confirm; **ask** = cannot be detected.

## Part 1 - site and software -> `~/.config/cryoet-skills/config.sh` (once per user and machine)
Source: `python3 $S/detect_env.py --json`. Write with `python3 $S/setup_config.py` (see SKILL.md §1).

| id | question | how answered | config key(s) |
|---|---|---|---|
| A1 | Which Slurm partition should GPU jobs use? (or: no Slurm, run on this workstation) | confirm: partitions with GPUs from `sinfo` | `SCHEDULER`, `SLURM_GPU_PARTITION` |
| A2 | Which partition for CPU-only jobs (CTF summaries, STAR edits)? | confirm: GPU-less partitions | `SLURM_CPU_PARTITION` |
| A3 | Does your site need `--account` or `--qos`? | confirm: `sacctmgr` accounts if exactly one | `SLURM_ACCOUNT`, `SLURM_QOS` |
| A4 | How do you request GPUs: `--gres=gpu:N` or `--gres=gpu:<type>:N`? | ask (sites differ; a wrong form can pend forever) | `SLURM_GPU_GRES_FMT`, `SLURM_GPU_TYPE` |
| A5 | Max walltime and max GPUs per job you may use? Memory of one GPU node? | confirm: partition limits from `sinfo` | `SLURM_MAX_WALLTIME`, `SLURM_MAX_GPUS_PER_JOB`, `SLURM_NODE_MEM_GB` |
| A6 | Node-local scratch for RELION/M (path, roughly how big)? | ask (default `/tmp`) | `SCRATCH_ROOT` |
| A7 | Any site rules to respect (message of the day, login-node limits, quota file)? | ask; read what they point to | `SITE_NOTES_FILE` |
| B1 | Python with numpy/scipy/mrcfile/matplotlib for helper scripts (exactly these four; the skills ship their own STAR reader, so no starfile/pandas) | auto: first env that imports them | `CRYOET_PYTHON` |
| B2 | How is WarpTools 2.0 (incl. MTools/MCore) put on PATH here? (env script, `module:`, `conda:`) | confirm / ask | `WARP_ENV_SCRIPT` |
| B3 | IMOD (for etomo aligners)? AreTomo3? | auto if on PATH, else ask | `IMOD_DIR`, `ARETOMO3_BIN` |
| B4 | RELION 5: how is it loaded, does that also provide MPI (`mpirun`) or is a separate `module load` needed, and is MPI launched with `mpirun` or `srun` inside jobs? If a module is needed, write a small wrapper env script that sources both and point the key at it. | confirm / ask; `check_config.sh` verifies `mpirun` after activation | `RELION_ENV_SCRIPT`, `RELION_MPI_LAUNCHER` |
| B5 | Optional tools you have: tomoDRGN, TeamTomo workflows, ChimeraX (any machine), calc_level_ChimeraX, Noise2Map | auto (conda env names) + ask; "not installed" is a fine answer | `TOMODRGN_ENV`, `TEAMTOMO_*`, `CHIMERAX_BIN`, `CALC_LEVEL_REPO`, `NOISE2MAP_BIN` |

After writing: `bash $S/check_config.sh` and show the table. A FAIL row goes back to its question.

## Part 2 - the project -> `<PROJECT>/cryoet_project.json` (once per dataset)
Source for D: `"$CRYOET_PYTHON" $S/_lib/inspect_mdoc.py --mdocs <dir> --frames <dir> --json`. Store each answer with
`project_state.py set <PROJECT> intake.<id> '<json>'` and the acquisition values under `acquisition.*`.

| id | question | how answered | used by |
|---|---|---|---|
| C1 | Where should the project live? (needs space: ~1-2x the raw data; not a small home quota) | ask | all |
| C2 | Where are the raw data: movies/frames, MDOCs, gain reference? Or tilt-series stacks (+ .rawtlt)? | ask (then list the dirs to confirm counts) | warptools |
| C3 | Short dataset name (EMPIAR id or your own) | ask | all |
| D1 | Pixel size (A/px, unbinned, as saved) | confirm: MDOC `PixelSpacing` | all |
| D2 | Voltage, Cs, amplitude contrast | confirm: MDOC `Voltage`; Cs/AC usually ask (typical 300 kV, 2.7 mm, 0.07) | warptools, relion |
| D3 | Dose per tilt (and per frame) in e/A^2 | confirm: `ExposureDose`, `FrameDosesAndNumber` | warptools (exposure weighting) |
| D4 | Frames per movie (EER: how many groups) | auto: `NumSubFrames` | warptools (motion grid) |
| D5 | Gain reference file, and does it need a flip/rotation to match the movies? | ask (the facility or a known-good processing knows; otherwise test on one series) | warptools |
| D6 | Tilt-axis angle: trust the MDOC? | confirm; if inspect_mdoc warns "TRANSPOSED", say the axis is probably 90 deg off and plan to verify on one series | warptools |
| D7 | Tilt scheme / range / defocus range | auto | warptools (CTF search range) |
| D8 | Gold fiducials in the sample? Bead size (nm)? | ask | warptools (aligner choice) |
| E1 | Target: what particle, approx. mass (kDa) or size (A), symmetry? | ask | relion (box, mask), figures (contour) |
| E2 | Particle coordinates: do you have a STAR (from which picker, at what pixel size, in which tomogram frame)? | ask - **picking is not part of these skills** | relion |
| E3 | Reference: EMDB id / local map, or de novo? Is it known to be the correct hand? | ask | relion, figures |
| E4 | How far to go: consensus map only / + tomoDRGN cleaning / + M refinement / + figures | ask (offer only stages `check_config` marks ok) | plan |
| E5 | Validate on a small subset first? Which 2-3 series? (pick well-populated, well-aligned ones) | ask (recommend yes) | plan |
| F1 | Compute budget: GPU-hours and disk you are willing to use | ask | plan |
| F2 | Approve each stage before submission, or approve the whole plan once? | ask (default: each stage) | dispatch |

## Part 3 - decisions taken when reached (never up front)
| id | when | question |
|---|---|---|
| G1 | after alignment of the test series | Which alignment (arm) to carry forward? Show residuals / reprojection checks per arm. |
| G2 | after `ts_defocus_hand --check`, before CTF | Correlation and verdict shown: apply the suggested hand? |
| G3 | after particle import | Do the particles sit on density? (counts per tomogram, a slice overlay) |
| G4 | after the first refinement | Is the map the correct hand vs the reference / an atomic model? |
| G5 | after tomoDRGN analyze | Which classes to keep? (review aid; never auto-select) |
| G6 | each M round | Keep the round? (fixed-mask FSC, cross-FSC) Stop? |

Record each answer in `decisions[]` with the evidence shown.
