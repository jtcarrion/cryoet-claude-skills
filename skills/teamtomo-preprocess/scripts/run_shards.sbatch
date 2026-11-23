#!/bin/bash
#SBATCH --job-name=teamtomo
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=04:00:00
# =============================================================================
# run_shards.sbatch - teamtomo-workflows batch.py on every GPU of ONE job, one disjoint shard of series per GPU.
#
#   source <skill>/scripts/_lib/cryoet_config.sh
#   CRYOET_SBATCH_OPTS="-o <root>/slurm/teamtomo_%j.out --cpus-per-task=16 --mem=128G" \
#     cryoet_submit gpu <NGPU> <TIME> <skill>/scripts/run_shards.sbatch <root>/config.yaml [--series "a b"] [--overwrite]
#   (SCHEDULER=none: the same call runs it locally in the background; or `bash run_shards.sbatch <config> ...`)
#
# Options (after the config path):  --series "a b c"  only these series   --overwrite  redo finished series
#   --ngpu N  cap the number of GPUs used (default: every GPU in CUDA_VISIBLE_DEVICES; see below)
# Env fallbacks (older usage): CONFIG, SERIES, OVERWRITE=1, NGPU. PLAIN_BATCH=1 runs the repo's batch.py unpatched.
# Partition / account / gres come from cryoet_submit (site config) - none are set here.
#
# Same outputs as running batch.py serially (the repo is not modified): <root>/<series>/{tomogram,run.json,...},
# <root>/batch_summary.csv, <root>/logs/batch_<stamp>.log (one per shard). Added by this wrapper:
#   <root>/shards/<jobid>/{shard_<i>.txt,manifest.json}   which series ran where, repo commit, package versions
#   <root>/logs/shard<i>_<jobid>.out                       each worker's stdout/stderr
#   <root>/status.csv                                      rebuilt from every run.json at the end (authoritative)
# Resume = resubmit the same config: finished series (run.json status 'done') are skipped and NOT re-sharded.
# =============================================================================
set -eo pipefail

# --- locate the skill: sbatch spools this file, so use CRYOET_LIB (exported by cryoet_submit) when present ---
if [[ -n "${CRYOET_LIB:-}" ]]; then HERE=$(dirname "$CRYOET_LIB"); else HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); fi

# --- arguments (parsed before the config load so --help works anywhere) ---
CONFIG_ARG=""; SERIES_ARG="${SERIES:-}"; OVER="${OVERWRITE:-0}"; NGPU_CAP="${NGPU:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --series) SERIES_ARG="$2"; shift 2 ;;
        --overwrite) OVER=1; shift ;;
        --ngpu) NGPU_CAP="$2"; shift 2 ;;
        -h|--help) sed -n '8,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
        -*) echo "ERROR: unknown option $1" >&2; exit 2 ;;
        *) CONFIG_ARG="$1"; shift ;;
    esac
done
CONFIG="${CONFIG_ARG:-${CONFIG:-}}"
[[ -n "$CONFIG" && -f "$CONFIG" ]] || { echo "ERROR: give the run's config.yaml as the first argument (got '${CONFIG}')" >&2; exit 2; }
CONFIG=$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")

source "${CRYOET_LIB:-$HERE/_lib}/cryoet_config.sh" || exit 2

# --- software ---
if ! cryoet_have teamtomo; then
    echo "ERROR: teamtomo-workflows not configured (TEAMTOMO_REPO='${TEAMTOMO_REPO:-}'). Install with" >&2
    echo "  bash $(dirname "$HERE")/env/install_env.sh --dest <software dir>   and set TEAMTOMO_REPO / TEAMTOMO_ENV" >&2
    exit 3
fi
cryoet_require TEAMTOMO_ENV || exit 3
cryoet_activate teamtomo || { echo "ERROR: could not activate TEAMTOMO_ENV='${TEAMTOMO_ENV}'" >&2; exit 3; }
export TEAMTOMO_REPO
PYTHONPATH="${TEAMTOMO_REPO}${PYTHONPATH:+:$PYTHONPATH}" python -c "import torch, torch_tilt_series, teamtomo_workflows" || {
    echo "ERROR: the teamtomo env cannot import torch / torch_tilt_series / teamtomo_workflows - rebuild it (env/install_env.sh)" >&2
    exit 3; }

JOB=${SLURM_JOB_ID:-local_$$}
echo "=== teamtomo shards job ${JOB} on $(hostname) $(date)"
nvidia-smi --query-gpu=index,name,memory.total,ecc.errors.uncorrected.volatile.total --format=csv,noheader || true

# the config path goes in through argv, never interpolated into code
ROOT=$(python - "$CONFIG" <<'PY'
import os, sys
sys.path.insert(0, os.environ["TEAMTOMO_REPO"])
from teamtomo_workflows import load_config
print(load_config(sys.argv[1])["output"]["root"])
PY
)
[[ -n "$ROOT" ]] || { echo "ERROR: could not read output.root from $CONFIG" >&2; exit 2; }
mkdir -p "${ROOT}/logs" "${ROOT}/slurm"

# --- GPUs: the scheduler's binding if any; otherwise be explicit rather than silently using one GPU ---
if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
    IFS=',' read -r -a GPUS <<< "${CUDA_VISIBLE_DEVICES}"
elif [[ -n "${SLURM_JOB_ID:-}" ]]; then
    echo "WARNING: CUDA_VISIBLE_DEVICES is unset inside a Slurm job (site without gres GPU binding?) - using GPU 0" \
         "only; pass --ngpu N to use more, but only if those GPUs are allocated to you" >&2
    GPUS=(0); [[ -n "$NGPU_CAP" ]] && GPUS=($(seq 0 $((NGPU_CAP - 1))))
else
    GPUS=($(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null || echo 0))
    echo "local run: GPUs found: ${GPUS[*]}"
fi
if [[ -n "$NGPU_CAP" && ${#GPUS[@]} -gt $NGPU_CAP ]]; then GPUS=("${GPUS[@]:0:$NGPU_CAP}"); fi
NG=${#GPUS[@]}

SH=${ROOT}/shards/${JOB}
EXTRA=(); [[ "$OVER" == 1 ]] && EXTRA=(--overwrite)
SER=(); [[ -n "$SERIES_ARG" ]] && read -r -a SER_LIST <<< "$SERIES_ARG" && SER=(--series "${SER_LIST[@]}")
set +e
python "${HERE}/plan_shards.py" --config "${CONFIG}" --n-shards "${NG}" --outdir "${SH}" "${SER[@]}" "${EXTRA[@]}"
rc=$?; set -e
[[ $rc -eq 3 ]] && { echo "nothing to run"; python "${HERE}/status.py" --root "${ROOT}" || true; exit 0; }
[[ $rc -ne 0 ]] && { echo "ERROR: shard planning failed (rc=$rc)" >&2; exit $rc; }

NS=$(find "${SH}" -maxdepth 1 -name 'shard_*.txt' | wc -l)
# batch_usetilt.py = batch.py + selection of UseTilt=True tilts (upstream bug: deselected tilts crash xml_to_tomograms).
RUNNER="${HERE}/batch_usetilt.py"; [[ "${PLAIN_BATCH:-0}" == 1 ]] && RUNNER="${TEAMTOMO_REPO}/batch.py"
echo "runner: ${RUNNER}"
NCPU=${SLURM_CPUS_PER_TASK:-$(nproc)}
export OMP_NUM_THREADS=$(( NCPU / NS )); [[ ${OMP_NUM_THREADS} -lt 1 ]] && OMP_NUM_THREADS=1
PIDS=()
for ((i = 0; i < NS; i++)); do
    S=(); while IFS= read -r line; do [[ -n "$line" ]] && S+=("$line"); done < "${SH}/shard_${i}.txt"
    echo "  shard ${i} -> GPU ${GPUS[$i]}: ${#S[@]} series"
    CUDA_VISIBLE_DEVICES=${GPUS[$i]} python "${RUNNER}" --config "${CONFIG}" --device cuda:0 \
        --series "${S[@]}" "${EXTRA[@]}" > "${ROOT}/logs/shard${i}_${JOB}.out" 2>&1 &
    PIDS+=($!)
    sleep 3   # batch.py names its log by the second; keep shard logs distinct
done
FAIL=0
for i in "${!PIDS[@]}"; do
    rc=0; wait "${PIDS[$i]}" || rc=$?
    if [[ $rc -eq 0 ]]; then echo "  shard ${i}: ok"
    else echo "  shard ${i}: exit ${rc} (see ${ROOT}/logs/shard${i}_${JOB}.out and status)"; FAIL=1; fi
done
python "${HERE}/status.py" --root "${ROOT}" || FAIL=1
echo "done $(date)"
exit ${FAIL}
