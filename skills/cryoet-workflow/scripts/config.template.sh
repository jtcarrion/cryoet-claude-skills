# cryoet-skills user/site config  (schema v1)
# Location: ~/.config/cryoet-skills/config.sh  (override: export CRYOET_SKILLS_CONFIG=/path)
# Written by the cryoet-workflow skill's `setup` step; every skill sources it. Plain bash: KEY="value".
# Leave a key empty to mean "not installed / not used" -- skills then skip or ask.

## --- Site / scheduler -------------------------------------------------------
SCHEDULER="slurm"                 # slurm | none (run locally on a workstation)
SLURM_GPU_PARTITION=""            # e.g. gpu
SLURM_GPU_PARTITION_ALT=""        # optional fallback partition
SLURM_CPU_PARTITION=""            # CPU-only work (CTF summaries, STAR prep)
SLURM_ACCOUNT=""                  # --account, if your site needs it
SLURM_QOS=""
SLURM_GPU_GRES_FMT="gpu:{n}"      # some sites need gpu:{type}:{n}; {n} is substituted
SLURM_GPU_TYPE=""                 # only used if FMT contains {type}
SLURM_MAX_GPUS_PER_JOB="4"
SLURM_MAX_WALLTIME="48:00:00"
SLURM_MEM_PER_GPU_GB="64"
SLURM_NODE_MEM_GB=""              # RAM of one GPU node (RELION preread sizing); empty = this machine's RAM, with a warning
SLURM_MAX_MEM_GB=""               # largest --mem to request; empty = SLURM_NODE_MEM_GB
SLURM_EXTRA_ARGS=""               # anything else, e.g. "--exclude=node12"
SCRATCH_ROOT="/tmp"               # node-local scratch for RELION/M (job-unique subdir + trap cleanup)
SITE_NOTES_FILE=""                # optional markdown of site rules the agent must read (e.g. MOTD policy)

## --- Software ---------------------------------------------------------------
CRYOET_PYTHON=""                  # python with numpy scipy mrcfile matplotlib (helper scripts)
WARP_ENV_SCRIPT=""                # script sourced to put WarpTools/MTools/MCore on PATH (or empty if on PATH)
IMOD_DIR=""                       # needed for ts_etomo_* aligners
ARETOMO3_BIN=""
RELION_ENV_SCRIPT=""              # sourced to put relion_refine_mpi etc. on PATH
RELION_MPI_LAUNCHER="mpirun"      # mpirun | srun
TOMODRGN_ENV=""                   # conda env / venv activation for tomodrgn
TEAMTOMO_REPO=""                  # teamtomo-workflows checkout (optional skill)
TEAMTOMO_ENV=""
CHIMERAX_BIN=""                   # optional: only for headless test renders; figures are .cxc bundles opened anywhere
NOISE2MAP_BIN=""                  # optional
MCORE_PORT_BASE="14300"           # skills add an offset per job to avoid collisions on shared nodes
EXTRA_LD_LIBRARY_PATH=""          # appended after Warp activation (e.g. a CUDA lib dir AreTomo3 needs)
TORCH_CUDA_INDEX=""               # PyTorch wheel index for the TeamTomo installer; empty = let pip choose
UV_BIN=""                         # uv binary for the TeamTomo installer; empty = `uv` on PATH
TEAMTOMO_REPO_URL="https://github.com/jtcarrion/teamtomo-workflows"
CALC_LEVEL_REPO=""                # checkout of https://github.com/mariacarreira/calc_level_ChimeraX (optional)
CHIMERAX_VERSION="1.8+"           # only written into figure headers

## --- Optional / unreleased tools -------------------------------------------
JOLT_ENABLED="no"                 # TODO(after JOLT preprint): jolt-picker skill + ts_import_alignments from JOLT

## --- Microscope fallback ---------------------------------------------------
MICROSCOPE_CS_MM=""               # used only when Cs cannot be read from the data (Warp XML / STAR) or a flag

## --- Preferences ------------------------------------------------------------
TOMODRGN_KMEANS="50 100"          # k values for tomodrgn analyze
M_MIN_PTCL_PER_TS="150"           # m-refine warns below this many particles per tilt series
CHIMERAX_STYLE="default"          # styles/<name>.json in chimerax-figures, or a path to your own style JSON
DEFAULT_PROJECT_ROOT=""           # where new processing dirs are created
