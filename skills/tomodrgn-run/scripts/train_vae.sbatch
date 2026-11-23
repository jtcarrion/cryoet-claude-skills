#!/bin/bash
#SBATCH --job-name=tdrgn_train
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
# =============================================================================
# train_vae.sbatch - tomodrgn train_vae (flags checked against tomoDRGN 1.0.5 `train_vae --help`).
# Submit through submit_tomodrgn.sh (partition/gres/walltime from the config), or run locally (SCHEDULER=none):
#   bash train_vae.sbatch OPTSET=<..._tomodrgn_optimisation_set.star> OUTDIR=<runs/name> ZDIM=8 EPOCHS=20 BATCH=10
# Parameters are KEY=VALUE arguments (or already-exported environment variables):
#   OPTSET, OUTDIR, ZDIM, EPOCHS, BATCH  required - model size is chosen with the user every run, no defaults.
#   UNINVERT=1   add --uninvert-data (tomoDRGN INVERTS the data sign by default; decide from the polarity check)
#   LAZY=1       --lazy (set does not fit in RAM; prep_tomodrgn_star.py prints the in-RAM estimate)
#   MULTIGPU=1   --multigpu (the batch is GLOBAL, split over all visible GPUs)
#   DATADIR      --datadir, only if the particle STAR has relative image paths
#   LOAD         --load weights.N.pkl to continue a run in the same OUTDIR
#   SMOKE=1      1 epoch on the first 200 particles (mechanics test; ZDIM/BATCH default to 8/8)
#   NUM_WORKERS  dataloader workers (default: cpus-per-task/2, at most 8)
#   RUN_ANALYZE=1  on success, run analyze.sbatch in this same job (for SCHEDULER=none, which has no dependencies)
#   EXTRA        any other train_vae flags, passed verbatim
# Always added: --recon-dose-weight --l-dose-mask --recon-tilt-weight (dose/tilt weighting of the loss).
# Refuses to reuse an OUTDIR that already holds a run unless LOAD is given (tomoDRGN would mix two runs).
# Exit code is train_vae's own: a failed training fails the job (and the dependent analyze never starts).
# =============================================================================
set -o pipefail
for kv in "$@"; do
  case "$kv" in
    [A-Z]*=*) export "${kv?}" ;;
    *) echo "ERROR: argument '$kv' is not KEY=VALUE" >&2; exit 2 ;;
  esac
done
source "${CRYOET_LIB:?CRYOET_LIB not set - submit with submit_tomodrgn.sh or export CRYOET_LIB=<skill>/scripts/_lib}/cryoet_config.sh" || exit 2
cryoet_activate tomodrgn || { echo "ERROR: tomoDRGN not available (TOMODRGN_ENV='${TOMODRGN_ENV:-}')" >&2; exit 3; }

if [[ "${SMOKE:-0}" == 1 ]]; then ZDIM=${ZDIM:-8}; EPOCHS=1; BATCH=${BATCH:-8}; fi
: "${OPTSET:?OPTSET required}" "${OUTDIR:?OUTDIR required}"
: "${ZDIM:?ZDIM required - ask the user}" "${EPOCHS:?EPOCHS required - ask the user}" "${BATCH:?BATCH required - ask the user}"
[[ -f "${OPTSET}" ]] || { echo "ERROR: OPTSET not found: ${OPTSET}" >&2; exit 2; }
if [[ -e "${OUTDIR}/config.pkl" && -z "${LOAD:-}" ]]; then
  echo "ERROR: ${OUTDIR} already holds a run - choose a new OUTDIR, or LOAD=weights.N.pkl to continue it" >&2; exit 1
fi
NCPU=${SLURM_CPUS_PER_TASK:-$(nproc)}
NW=${NUM_WORKERS:-$(( NCPU / 2 > 8 ? 8 : (NCPU / 2 < 1 ? 1 : NCPU / 2) ))}

F=(--zdim "${ZDIM}" -n "${EPOCHS}" -b "${BATCH}" --recon-dose-weight --l-dose-mask --recon-tilt-weight
   --num-workers "${NW}" --pin-memory)
[[ "${UNINVERT:-0}" == 1 ]] && F+=(--uninvert-data)
[[ "${LAZY:-0}" == 1 ]] && F+=(--lazy)
[[ "${MULTIGPU:-0}" == 1 ]] && F+=(--multigpu)
[[ -n "${DATADIR:-}" ]] && F+=(--datadir "${DATADIR}")
[[ -n "${LOAD:-}" ]] && F+=(--load "${LOAD}")
[[ "${SMOKE:-0}" == 1 ]] && F+=(--use-first-nptcls 200)

echo "=== train_vae job ${SLURM_JOB_ID:-local:$$} on $(hostname)  $(date)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null || echo "(nvidia-smi not available)"
tomodrgn --version 2>&1 || true
echo "tomodrgn train_vae ${OPTSET} --outdir ${OUTDIR} ${F[*]} ${EXTRA:-}"
rc=0
# shellcheck disable=SC2086
tomodrgn train_vae "${OPTSET}" --outdir "${OUTDIR}" "${F[@]}" ${EXTRA:-} || rc=$?
echo "--- last epochs (run.log):"
grep -E 'Epoch: [0-9]+ Average' "${OUTDIR}/run.log" 2>/dev/null | tail -3 || true
if [[ $rc -ne 0 ]]; then
  echo "--- train_vae FAILED (rc=${rc}); last lines of run.log:"; tail -20 "${OUTDIR}/run.log" 2>/dev/null || true
  echo "rc=${rc}  $(date)"; exit "${rc}"
fi
echo "rc=0  $(date)"
if [[ "${RUN_ANALYZE:-0}" == 1 ]]; then
  WORKDIR="${OUTDIR}" EPOCH="${EPOCH:-latest}" bash "${CRYOET_LIB}/../analyze.sbatch"; exit $?
fi
exit 0
