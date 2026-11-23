#!/bin/bash
#SBATCH --job-name=noise2map
#SBATCH --output=noise2map_%j.log
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
# Denoise ONE map from its two half-maps with Warp's Noise2Map (optional step for comparison figures).
# Every map in a comparison must go through this with the SAME settings; only angpix/lowpass differ per map.
#
#   cryoet_submit gpu 1 01:00:00 noise2map.sbatch RUNDIR HALF1 HALF2 MASK ANGPIX LOWPASS_A [ITERATIONS]
#   SCHEDULER=none:  bash noise2map.sbatch ...   (needs a local CUDA GPU)
# RUNDIR: one folder per map (Noise2Map writes ./denoised/<half1 name>, float16, into the current folder).
# HALF1/HALF2/MASK: paths relative to RUNDIR or absolute. LOWPASS_A: the map's FSC 0.143 resolution (A).
# Flags checked against warpem/warp Noise2Map/Options.cs (2026-11): --half1 --half2 --mask --angpix --lowpass
# --iterations (default 1500; 600-1200 for SPA-style half-maps) --window (multiple of 16) --batchsize
# --overflatten_factor --gpuid_network --gpuid_preprocess (default 1! set to 0 on a 1-GPU job).
CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2

[ $# -ge 6 ] || { echo "usage: noise2map.sbatch RUNDIR HALF1 HALF2 MASK ANGPIX LOWPASS_A [ITERATIONS]" >&2; exit 2; }
RUNDIR="$1"; H1="$2"; H2="$3"; MASK="$4"; ANGPIX="$5"; LOWPASS="$6"; ITER="${7:-1200}"

if cryoet_have noise2map; then
  N2M="$NOISE2MAP_BIN"
elif cryoet_have warp; then
  cryoet_activate warp || exit 3
  N2M="$(command -v Noise2Map)"
fi
[ -n "${N2M:-}" ] || { echo "Noise2Map not configured (set NOISE2MAP_BIN, or WARP_ENV_SCRIPT with Noise2Map on PATH)" >&2; exit 3; }

cd "$RUNDIR" || exit 2
for f in "$H1" "$H2" "$MASK"; do [ -f "$f" ] || { echo "missing input: $RUNDIR/$f" >&2; exit 2; }; done
echo "Noise2Map: $N2M  dir=$(pwd)  iter=$ITER angpix=$ANGPIX lowpass=$LOWPASS job=${SLURM_JOB_ID:-local$$}"
"$N2M" --half1 "$H1" --half2 "$H2" --mask "$MASK" --iterations "$ITER" --window 64 --batchsize 4 \
    --overflatten_factor 1 --angpix "$ANGPIX" --lowpass "$LOWPASS" --gpuid_network 0 --gpuid_preprocess 0
rc=$?
[ $rc -eq 0 ] && ls -l denoised/ 2>/dev/null
echo "Noise2Map exit code $rc"
exit $rc
