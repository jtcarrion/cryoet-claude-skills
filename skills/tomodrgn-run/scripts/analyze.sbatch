#!/bin/bash
#SBATCH --job-name=tdrgn_analyze
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
# =============================================================================
# analyze.sbatch - tomodrgn analyze at one epoch for every k in KS, each into its own folder
# <WORKDIR>/analyze.<EPOCH>_k<k> (one shared analyze.<EPOCH> folder would mix the k values). analyze writes PCA/UMAP,
# kmeans<k>/labels.pkl + centers.txt + one volume per class centre (vol_000.mrc ...), and per-class particle images.
# Submit with submit_tomodrgn.sh analyze ..., or locally: bash analyze.sbatch WORKDIR=<train outdir> EPOCH=latest
# Parameters (KEY=VALUE args or exported env):
#   WORKDIR   train_vae output directory (required)
#   EPOCH     0-based weights.N index, or 'latest' (default latest; resolved to a number for the folder name)
#   KS        k values (default: config TOMODRGN_KMEANS, else "50 100"; tomoDRGN's own default is 20)
#   VOLFLAGS  e.g. "--invert" / "--invert --flip": contrast/hand of the generated volumes only
#   EXTRA     any other analyze flags
# Picking the epoch: the loss is not a convergence test (tomodrgn convergence_vae is). Class IDs are not reproducible
# across runs or epochs, so analyse the epoch you will select from and never reuse class numbers from another run.
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
: "${WORKDIR:?WORKDIR required}"
EPOCH=${EPOCH:-latest}
KS=${KS:-${TOMODRGN_KMEANS:-50 100}}
[[ -f "${WORKDIR}/config.pkl" ]] || { echo "ERROR: ${WORKDIR} has no config.pkl (not a train_vae output?)" >&2; exit 2; }
if [[ "${EPOCH}" == latest ]]; then
  EPOCH=$(ls "${WORKDIR}"/weights.*.pkl 2>/dev/null | sed -n 's/.*weights\.\([0-9][0-9]*\)\.pkl$/\1/p' | sort -n | tail -1)
  [[ -n "${EPOCH}" ]] || { echo "ERROR: no weights.N.pkl in ${WORKDIR}" >&2; exit 2; }
fi
echo "=== analyze job ${SLURM_JOB_ID:-local:$$} on $(hostname): ${WORKDIR} epoch ${EPOCH}, k in ${KS}  $(date)"
fail=0
for k in ${KS}; do
  out="${WORKDIR}/analyze.${EPOCH}_k${k}"
  if [[ -e "${out}/kmeans${k}/labels.pkl" ]]; then echo "skip k=${k}: ${out} exists"; continue; fi
  echo "--- analyze epoch ${EPOCH} k=${k} -> ${out}  $(date)"
  rc=0
  # shellcheck disable=SC2086
  tomodrgn analyze "${WORKDIR}" --epoch "${EPOCH}" --ksample "${k}" -o "${out}" ${VOLFLAGS:-} ${EXTRA:-} || rc=$?
  if [[ $rc -ne 0 ]]; then echo "k=${k}: analyze FAILED rc=${rc}"; fail=$rc; continue; fi
  echo "k=${k}: $(ls "${out}/kmeans${k}"/vol_*.mrc 2>/dev/null | wc -l) class volumes"
done
echo "done rc=${fail}  $(date)"; exit "${fail}"
