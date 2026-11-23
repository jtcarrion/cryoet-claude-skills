# Setup reference

Config file: `~/.config/cryoet-skills/config.sh` (override `CRYOET_SKILLS_CONFIG`). Every key is documented inline in
`scripts/config.template.sh`. Empty = not installed / not used.

## Questions worth asking about a site
- Which partition for GPU work, which for CPU-only work? Is there a separate data-transfer partition for bulk copies?
- GPU request syntax: generic `--gres=gpu:N` or typed `gpu:<type>:N`? (`SLURM_GPU_GRES_FMT`). On some clusters a
  typed request on a partition that advertises GPUs differently pends forever; on others an untyped one is rejected.
- Is an `--account` / `--qos` required? Max walltime per partition?
- Node-local scratch for RELION/M (`SCRATCH_ROOT`, e.g. `/tmp`, `$TMPDIR`, `/scratch/$USER`) and how big it is.
- MPI launcher inside jobs: `mpirun` or `srun` (`RELION_MPI_LAUNCHER`).
- Shared nodes? Then per-job ports for MCore are essential (the skills use `cryoet_port`).
- Home-directory quotas: keep projects, conda caches and Warp temp files on project storage.

## Install pointers (only if the user asks)
- WarpTools / M (Warp 2.0): https://warpem.github.io/warp/ - a build that runs on the site's glibc/CUDA; set
  `WARP_ENV_SCRIPT` to the script that puts WarpTools/MTools/MCore on PATH.
- RELION 5: https://relion.readthedocs.io/ - `RELION_ENV_SCRIPT` or `module:relion/5...`.
- IMOD (for etomo aligners): https://bio3d.colorado.edu/imod/ - `IMOD_DIR`.
- AreTomo3: https://github.com/czimaginginstitute/AreTomo3 - `ARETOMO3_BIN`.
- tomoDRGN: https://github.com/bpowell122/tomodrgn - `TOMODRGN_ENV`.
- TeamTomo workflows: https://github.com/jtcarrion/teamtomo-workflows - `TEAMTOMO_REPO`, `TEAMTOMO_ENV`
  (teamtomo-preprocess's `env/install_env.sh` builds it).
- ChimeraX: https://www.cgl.ucsf.edu/chimerax/ - usually on the user's own computer; `CHIMERAX_BIN`.
- calc_level_ChimeraX (contour levels): https://github.com/mariacarreira/calc_level_ChimeraX - `CALC_LEVEL_REPO`.
- Helper Python (`CRYOET_PYTHON`): any Python 3.8+ with numpy, scipy, mrcfile, matplotlib, e.g.
  `conda create -n cryoet-helpers -c conda-forge python=3.11 numpy scipy mrcfile matplotlib`.
