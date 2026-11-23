#!/bin/bash
#SBATCH --job-name=r5_refine
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
# =============================================================================
# refine3d.sbatch - RELION 5 particle-series gold-standard auto-refine, with auto-continue and a watchdog.
#
# Submit (settings via environment; site resources via cryoet_submit; nothing edited in this file):
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   G=2; CRYOET_SBATCH_OPTS="--chdir=<PROJECT> --ntasks=$((G+1)) --cpus-per-task=12 --mem=<from estimate_ram.py>G \
#       -o <OUT>/slurm_%j.out -e <OUT>/slurm_%j.err" \
#   IOS=<..._abspath_optimisation_set.star> REF=<ref> OUT=<Refine3D/jobNNN> MODE=preread|scratch DIAM=<A> [MASK=..] \
#     cryoet_submit gpu $G 48:00:00 "${CLAUDE_SKILL_DIR}/scripts/refine3d.sbatch"
# Workstation (SCHEDULER=none): same variables, plus NGPU=<n> if CUDA_VISIBLE_DEVICES is unset; run from <PROJECT>.
# The job cwd must be the directory relative STAR paths resolve against; with make_optset.py's _abspath files any cwd
# works. Resubmitting the SAME command continues from the newest COMPLETE iteration (a timeout/crash loses <= 1 iter).
#
# Required env: IOS (abspath optimisation set), REF (on the export grid, prep_reference.py), OUT (job dir; run root is
#   $OUT/run), MODE (preread | scratch, from estimate_ram.py), DIAM (particle diameter, A).
# Optional env (new runs only - a continue inherits everything from the checkpoint except runtime flags):
#   MASK          solvent mask on the export grid; also turns on --solvent_correct_fsc (without it the mask does not
#                 drive sampling: RELION refines against the unmasked FSC, often half the masked resolution)
#   EXTERNAL_REF=1  reference not reconstructed from these particles (EMDB, other dataset, other software):
#                 adds --firstiter_cc --scale. Run bench_iter1.sbatch first.
#   INI_HIGH (40; 60 for external refs, 12-20 from your own good map), SYM (C1), HEALPIX (2 = 15 deg global start),
#   LOCALHP (4; 3 = faster coarse refine), OFFRANGE/OFFSTEP (EXPORT PIXELS, default 5/1), AUTOFLAGS (empty; e.g.
#   "--auto_ignore_angles --auto_resol_angles" for a quick coarse run), POOL (10), PAD (2), EXTRA_FLAGS,
#   STALL_MIN (90: minimum stall timer; it grows to 2.5x the slowest recent iteration),
#   NGPU / NMPI (override GPU and rank detection), CRYOET_LIB (set by cryoet_submit).
# Never: --delete_intermediate (continue needs the iterations), --maxsig (truncates a flat posterior into arbitrary,
#   reference-biased poses), --preread_images together with --scratch_dir, relion_refine_mpi for --denovo_3dref.
# Layout: 1 leader + 1 follower per GPU => ranks = GPUs + 1, which must be ODD (gold-standard halves split followers
#   evenly). If one node crashes twice (CUDA error 700, rank "Aborted", MPI deadlock), exclude it
#   (SLURM_EXTRA_ARGS / CRYOET_SBATCH_OPTS --exclude=<node>) or fall back to 2 GPUs / 3 ranks.
# Linux only (find, sort -V, seq, df -P, pkill).
# =============================================================================
set -eo pipefail
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then sed -n '/^# ====/,/^# ====/p' "$0"; exit 0; fi
CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "$0")" && pwd)/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
: "${IOS:?}" "${REF:?}" "${OUT:?}" "${MODE:?preread|scratch}" "${DIAM:?}"

detect_gpus() {
    if [[ -n "${SLURM_GPUS_ON_NODE:-}" ]]; then echo "${SLURM_GPUS_ON_NODE}"
    elif [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then awk -F, '{print NF}' <<< "${CUDA_VISIBLE_DEVICES}"
    elif command -v nvidia-smi >/dev/null 2>&1; then { nvidia-smi -L 2>/dev/null || true; } | grep -c '^GPU' || true
    else echo 0; fi
}
NGPU=${NGPU:-$(detect_gpus)}; NGPU=${NGPU:-0}
NMPI=${NMPI:-${SLURM_NTASKS:-$((NGPU + 1))}}
NJ=${SLURM_CPUS_PER_TASK:-${NJ:-8}}
STALL_MIN=${STALL_MIN:-90}
JOBID=${SLURM_JOB_ID:-local$$}
echo "=== RELION refine: job ${JOBID} on $(hostname)  $(date)"
echo "OUT ${OUT} | IOS ${IOS} | REF ${REF} | MODE ${MODE} | GPUs ${NGPU} | MPI ${NMPI} x ${NJ} threads"
(( NGPU >= 1 )) || { echo "ERROR: no GPUs visible (set NGPU, or request GPUs via cryoet_submit gpu N)" >&2; exit 1; }
(( NMPI == NGPU + 1 )) || { echo "ERROR: MPI ranks ${NMPI} != GPUs+1 ($((NGPU+1))): pass --ntasks=$((NGPU+1))" >&2; exit 1; }
(( NMPI % 2 == 1 && NMPI >= 3 )) || { echo "ERROR: MPI count ${NMPI} must be odd and >= 3 for gold-standard" >&2; exit 1; }
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,name,memory.free,ecc.errors.uncorrected.volatile.total --format=csv || true
    ECC=$({ nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total --format=csv,noheader 2>/dev/null || true; } \
          | awk '{ if ($1 ~ /^[0-9]+$/) s+=$1 } END{print s+0}')
    (( ECC == 0 )) || { echo "ERROR: ${ECC} uncorrectable ECC errors on $(hostname -s) - resubmit excluding this node" >&2; exit 1; }
fi
awk '/^MemTotal/{t=$2} /^MemAvailable/{a=$2} END{printf "node RAM total %.0f GB, available %.0f GB\n", t/1048576, a/1048576}' /proc/meminfo || true
mkdir -p "${OUT}"
if [[ -f "${OUT}/RELION_JOB_EXIT_SUCCESS" ]]; then echo "already finished - nothing to do"; exit 0; fi

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
cryoet_activate relion || exit 2
# fail fast, not seconds into the job, when the env has RELION but no MPI launcher
L="${RELION_MPI_LAUNCHER:-mpirun}"; command -v "${L}" >/dev/null 2>&1 || {
    echo "ERROR: your RELION env does not provide ${L} (RELION_MPI_LAUNCHER=${L}); add the MPI module load to" \
         "RELION_ENV_SCRIPT or point it at a wrapper that loads RELION + MPI" >&2; exit 2; }
export OMP_NUM_THREADS=${NJ}
# srun (Slurm >= 22.05) does not inherit --cpus-per-task from the allocation; mpirun must not pin ranks to one core
export SRUN_CPUS_PER_TASK=${NJ} SLURM_CPU_BIND=none OMPI_MCA_hwloc_base_binding_policy=none
command -v relion_refine_mpi

# newest iteration whose optimiser, data, sampling and both half models + half maps finished writing
CKPT=""
for opt in $(find "${OUT}" -maxdepth 1 -name 'run_it*_optimiser.star' 2>/dev/null | sort -V -r); do
    b="${opt%_optimiser.star}"
    if [[ -s "${opt}" && -s "${b}_data.star" && -s "${b}_sampling.star" && -s "${b}_half1_model.star" \
          && -s "${b}_half2_model.star" && -s "${b}_half1_class001_unfil.mrc" && -s "${b}_half2_class001_unfil.mrc" ]]; then
        CKPT="${opt}"; break
    fi
done

GPU_LIST=$(seq -s: 0 $((NGPU - 1)))
SCRATCH=""; IO=()
case "${MODE}" in
  preread) IO=(--preread_images) ;;
  scratch) SCRATCH=$(cryoet_scratch relion) || { echo "ERROR: cannot create scratch under ${SCRATCH_ROOT}" >&2; exit 1; }
           mkdir -p "${SCRATCH}"   # cryoet_scratch registers no cleanup; this script's own trap removes it
           df -P "${SCRATCH}" | tail -1; IO=(--scratch_dir "${SCRATCH}") ;;
  *) echo "ERROR: MODE must be preread or scratch" >&2; exit 1 ;;
esac
RUNTIME=(--dont_combine_weights_via_disc --pool "${POOL:-10}" --pad "${PAD:-2}" --j "${NJ}" --gpu "${GPU_LIST}" \
         "${IO[@]}" --pipeline_control "${OUT}/")

if [[ -n "${CKPT}" ]]; then
    echo "CONTINUE from $(basename "${CKPT}")"
    ARGS=(--continue "${CKPT}" --o "${OUT}/run" "${RUNTIME[@]}")
else
    echo "START new run"
    [[ -s "${IOS}" && -s "${REF}" ]] || { echo "ERROR: missing IOS or REF" >&2; exit 1; }
    NEW=(--ios "${IOS}" --ref "${REF}" --o "${OUT}/run" --auto_refine --split_random_halves
         --particle_diameter "${DIAM}" --sym "${SYM:-C1}" --ctf --flatten_solvent --zero_mask
         --healpix_order "${HEALPIX:-2}" --auto_local_healpix_order "${LOCALHP:-4}"
         --offset_range "${OFFRANGE:-5}" --offset_step "${OFFSTEP:-1}" --oversampling 1)
    if [[ "${EXTERNAL_REF:-0}" == "1" ]]; then NEW+=(--ini_high "${INI_HIGH:-60}" --firstiter_cc --scale)
    else NEW+=(--ini_high "${INI_HIGH:-40}"); fi
    if [[ -n "${MASK:-}" ]]; then
        [[ -s "${MASK}" ]] || { echo "ERROR: mask not found ${MASK}" >&2; exit 1; }
        NEW+=(--solvent_mask "${MASK}" --solvent_correct_fsc)
    fi
    # shellcheck disable=SC2206
    ARGS=("${NEW[@]}" ${AUTOFLAGS:-} ${EXTRA_FLAGS:-} "${RUNTIME[@]}")
fi
for bad in --delete_intermediate --maxsig --denovo_3dref; do
    if [[ " ${ARGS[*]} " == *" ${bad} "* ]]; then echo "ERROR: ${bad} is not allowed here (see header)" >&2; exit 1; fi
done

LOG=${OUT}/relion_${JOBID}.log
echo "relion_refine_mpi ${ARGS[*]}" | tee -a "${LOG}"
RUN_PID=""
stop_run() {   # the launcher runs in a subshell (cryoet_mpirun): signal its children (srun/mpirun) too
    [[ -n "${RUN_PID}" ]] || return 0
    pkill -"$1" -P "${RUN_PID}" 2>/dev/null || true; kill -"$1" "${RUN_PID}" 2>/dev/null || true
}
cleanup() { stop_run TERM; if [[ -n "${SCRATCH}" ]]; then rm -rf "${SCRATCH}"; fi; }
trap cleanup EXIT
cryoet_mpirun "${NMPI}" relion_refine_mpi "${ARGS[@]}" >> "${LOG}" 2>&1 &
RUN_PID=$!
echo "launched via ${RELION_MPI_LAUNCHER} (pid ${RUN_PID}); log ${LOG}"

kill_run() { echo "WATCHDOG: $1 - terminating at $(date)"; stop_run TERM; sleep 30; stop_run KILL; }
# find, never `ls glob | wc -l`: with no match ls exits 2 and set -eo pipefail kills the job
count_ckpt() { find "${OUT}" -maxdepth 1 -name 'run_it*_optimiser.star' 2>/dev/null | wc -l; }
FATAL='KERNEL_ERROR|illegal memory access|Segmentation fault|MPI_ABORT|error-code 700|Aborted|core dumped|srun: error'
last_n=$(count_ckpt); last_t=$(date +%s); slowest=0
while kill -0 "${RUN_PID}" 2>/dev/null; do
    if [[ -f "${OUT}/RELION_JOB_EXIT_SUCCESS" ]]; then
        echo "success marker at $(date); 180 s grace for a clean exit"
        for _ in $(seq 1 18); do kill -0 "${RUN_PID}" 2>/dev/null || break; sleep 10; done
        if kill -0 "${RUN_PID}" 2>/dev/null; then kill_run "launcher alive 180 s after RELION_JOB_EXIT_SUCCESS (teardown hang)"; fi
        break
    fi
    # "Aborted" alone has been the only trace of a crash - keep the pattern list wide
    if grep -qiE "${FATAL}" "${LOG}" 2>/dev/null; then
        { grep -iE "${FATAL}" "${LOG}" || true; } | head -3
        sleep 60; kill_run "fatal GPU/MPI error in the RELION log"; break
    fi
    n=$(count_ckpt); now=$(date +%s)
    if (( n != last_n )); then
        if (( last_n > 0 && now - last_t > slowest )); then slowest=$(( now - last_t )); fi
        last_n=${n}; last_t=${now}
    else
        lim=$(( STALL_MIN * 60 )); if (( slowest * 5 / 2 > lim )); then lim=$(( slowest * 5 / 2 )); fi
        if (( now - last_t > lim )); then kill_run "no new iteration for $(( (now - last_t) / 60 )) min (limit $(( lim / 60 )))"; break; fi
    fi
    sleep 60
done
RC=0; wait "${RUN_PID}" || RC=$?; RUN_PID=""
echo "launcher exit ${RC}  $(date)"
{ grep -h 'Final resolution' "${LOG}" || true; } | tail -1
if [[ -f "${OUT}/RELION_JOB_EXIT_SUCCESS" ]]; then echo "RELION_JOB_EXIT_SUCCESS present -> success"; exit 0; fi
echo "No success marker. Resubmit the same command to continue from the newest complete iteration."
(( RC != 0 )) || RC=1
exit "${RC}"
