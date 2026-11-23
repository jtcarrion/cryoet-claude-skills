#!/usr/bin/env bash
# check_config.sh -- validate the cryoet-skills config and report which pipeline stages can run here.
#   bash check_config.sh            # table: stage | status | reason
#   bash check_config.sh --quiet    # only print available stage names (space separated)
# Cheap and read-only: checks files exist / commands resolve; activation tests run in a subshell.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_lib/cryoet_config.sh" || exit 2
q=0; [ "${1:-}" = --quiet ] && q=1
avail=(); report=()
row() { report+=("$(printf '%-22s %-10s %s' "$1" "$2" "$3")"); [ "$2" = ok ] && avail+=("$1"); }

# scheduler
if [ "$SCHEDULER" = slurm ]; then
  if ! command -v sbatch >/dev/null; then row scheduler FAIL "SCHEDULER=slurm but sbatch not found"
  elif [ -z "${SLURM_GPU_PARTITION:-}" ]; then row scheduler FAIL "SLURM_GPU_PARTITION empty"
  elif ! sinfo -h -p "$SLURM_GPU_PARTITION" -o %P 2>/dev/null | grep -q .; then row scheduler FAIL "partition $SLURM_GPU_PARTITION not visible to sinfo"
  else row scheduler ok "slurm, gpu=$SLURM_GPU_PARTITION gres=$(cryoet_gres 1)"; fi
else row scheduler ok "local (SCHEDULER=none)"; fi
# helper python
if [ -z "${CRYOET_PYTHON:-}" ]; then row python FAIL "CRYOET_PYTHON empty"
elif "$CRYOET_PYTHON" -c "import numpy, scipy, mrcfile, matplotlib" 2>/dev/null; then row python ok "$CRYOET_PYTHON"
else row python FAIL "$CRYOET_PYTHON lacks numpy/scipy/mrcfile/matplotlib"; fi
# stages
probe() { # stage label activation-check
  local st="$1" label="$2"
  if ! cryoet_have "$st"; then row "$label" skip "not configured"; return; fi
  case "$st" in
    relion)
      if ! ( cryoet_activate relion >/dev/null 2>&1 ); then row "$label" FAIL "configured but cryoet_activate relion fails"
      elif ! ( cryoet_activate relion >/dev/null 2>&1; command -v "${RELION_MPI_LAUNCHER:-mpirun}" >/dev/null ); then
        row "$label" FAIL "RELION activates but ${RELION_MPI_LAUNCHER:-mpirun} is not on PATH (add the MPI module to RELION_ENV_SCRIPT or a wrapper)"
      else row "$label" ok "activates, ${RELION_MPI_LAUNCHER:-mpirun} found"; fi ;;
    warp|tomodrgn)
      if ( cryoet_activate "$st" >/dev/null 2>&1 ); then row "$label" ok "activates"; else row "$label" FAIL "configured but cryoet_activate $st fails"; fi ;;
    m) ( cryoet_activate warp >/dev/null 2>&1 && command -v MCore >/dev/null ) && row "$label" ok "MCore found" || row "$label" FAIL "MCore not on PATH after warp activation" ;;

    *) row "$label" ok "configured" ;;
  esac
}
probe warp      warptools-preprocess
probe imod      "  imod (etomo aligners)"
probe aretomo3  "  aretomo3"
probe teamtomo  teamtomo-preprocess
probe relion    relion-refine
probe m         m-refine
probe tomodrgn  tomodrgn-run
row chimerax-figures ok "writes .cxc bundles to open in ChimeraX anywhere${CHIMERAX_BIN:+ (local binary: $CHIMERAX_BIN)}"
probe calc_level "  calc_level (contours)"
probe noise2map "  noise2map"
probe jolt      "  jolt (TODO preprint)"
if [ $q = 1 ]; then echo "${avail[*]}"; else
  echo "config: $CRYOET_SKILLS_CONFIG"; printf '%s\n' "${report[@]}"; fi
