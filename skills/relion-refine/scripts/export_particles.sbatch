#!/bin/bash
#SBATCH --job-name=ts_export
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=256G
#SBATCH --time=06:00:00
# =============================================================================
# export_particles.sbatch - WarpTools ts_export_particles --2d (particle series) with checks.
#
# Submit (settings via environment; site resources via cryoet_submit; nothing edited in this file):
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   CRYOET_SBATCH_OPTS="--chdir=<PROJECT> -o <LOGDIR>/export_%j.out -e <LOGDIR>/export_%j.err" \
#   SETTINGS=.. INPROC=.. INPUT_STAR=.. COORDS_ANGPIX=.. ANGPIX=.. BOX=.. DIAM=.. OUTSTAR=.. EXPECTED_N=.. \
#     cryoet_submit gpu 2 06:00:00 "${CLAUDE_SKILL_DIR}/scripts/export_particles.sbatch"
# Required: SETTINGS (tilt-series .settings), INPROC (--input_processing), COORDS_ANGPIX, ANGPIX, BOX, DIAM, OUTSTAR,
#           and either INPUT_STAR (one STAR) or INDIR + PATTERN (per-series STARs).
# Optional: OUTPROC (--output_processing: where particleseries/ is written; REQUIRED for a second particle set at an
#           already-used pixel size, see below), EXPECTED_N (exact particle count to assert), EXPECTED_TS,
#           MAX_MISSING (--max_missing_tilts, default 5), PREMULT (1 = RELION default; 0 adds --dont_premultiply for
#           tomoDRGN), DEVICES (default: every visible GPU, "0 1 ..."), PERDEVICE (default 2), SERIES (comma list ->
#           --input_data <TOMOSTAR_DIR>/<id>.tomostar, for a one-series test), TOMOSTAR_DIR, EXTRA_FLAGS.
#
# Why each guard exists:
#  * Own GPU allocation: inside another GPU job Warp dies with cuFFT CUFFT_ALLOC_FAILED (= GPU OOM, not a Warp bug).
#  * Job-unique --task_dir: Warp locks its queue dir; a crashed-looking earlier run can still hold the default one
#    ("Another manager is already using queue dir"). It is placed under OUTPROC (or INPROC).
#  * Warp embeds the pixel size in stack names, so different --output_angpix coexist; the SAME pixel size with a
#    different particle set clobbers stacks by index and silently corrupts the older STAR -> use OUTPROC.
#  * --input_data lists must be on shared storage (compute nodes cannot see the login node's /tmp).
#  * Some WarpTools 2.x builds write an EMPTY _rlnTomoParticlesFile in their optimisation set -> make_optset.py
#    writes our own with absolute paths.
# Coordinates in the OUTPUT STAR are in export pixels (_rlnImagePixelSize), not tilt-series pixels.
# =============================================================================
set -eo pipefail
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then sed -n '/^# ====/,/^# ====/p' "$0"; exit 0; fi
CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "$0")" && pwd)/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
SCRIPTS="${CRYOET_LIB%/_lib}"
: "${SETTINGS:?}" "${INPROC:?}" "${COORDS_ANGPIX:?}" "${ANGPIX:?}" "${BOX:?}" "${DIAM:?}" "${OUTSTAR:?}"
cryoet_require CRYOET_PYTHON || exit 3
PY="${CRYOET_PYTHON}"
MAX_MISSING=${MAX_MISSING:-5}; PREMULT=${PREMULT:-1}; PERDEVICE=${PERDEVICE:-2}

echo "=== ts_export_particles --2d  job ${SLURM_JOB_ID:-local$$} on $(hostname)  $(date)"
cryoet_activate warp >/dev/null || exit 2   # no `set -u` in this script: conda activate breaks under it
if [[ -z "${DEVICES:-}" ]]; then
    if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then NVIS=$(awk -F, '{print NF}' <<< "${CUDA_VISIBLE_DEVICES}")
    else NVIS=$({ nvidia-smi -L 2>/dev/null || true; } | grep -c '^GPU' || true); fi
    (( ${NVIS:-0} >= 1 )) || { echo "ERROR: no GPU visible - request one via cryoet_submit gpu N" >&2; exit 1; }
    DEVICES=$(seq -s' ' 0 $((NVIS - 1)))
fi
command -v nvidia-smi >/dev/null 2>&1 && { nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true; }
[[ -f "${OUTSTAR}" ]] && { echo "ERROR: ${OUTSTAR} exists - refusing to overwrite (pick a new name)" >&2; exit 1; }

IN_ARGS=()
if [[ -n "${INPUT_STAR:-}" ]]; then IN_ARGS=(--input_star "${INPUT_STAR}")
else : "${INDIR:?set INPUT_STAR or INDIR+PATTERN}" "${PATTERN:?}"; IN_ARGS=(--input_directory "${INDIR}" --input_pattern "${PATTERN}"); fi
SER_ARGS=()
if [[ -n "${SERIES:-}" ]]; then : "${TOMOSTAR_DIR:?SERIES needs TOMOSTAR_DIR}"; SER_ARGS=(--input_data); for s in ${SERIES//,/ }; do SER_ARGS+=("${TOMOSTAR_DIR}/${s}.tomostar"); done; fi
OUTP_ARGS=(); TASKROOT="${INPROC}"
if [[ -n "${OUTPROC:-}" ]]; then mkdir -p "${OUTPROC}"; OUTP_ARGS=(--output_processing "${OUTPROC}"); TASKROOT="${OUTPROC}"; fi
PM_ARGS=(); [[ "${PREMULT}" == "0" ]] && PM_ARGS=(--dont_premultiply)
TASK_DIR="${TASKROOT}/tasks_${SLURM_JOB_ID:-local$$}"
mkdir -p "$(dirname "${OUTSTAR}")"

echo "settings ${SETTINGS} | input_processing ${INPROC} | output_processing ${OUTPROC:-<same>}"
echo "coords_angpix ${COORDS_ANGPIX} -> output ${ANGPIX} A/px, box ${BOX}, diameter ${DIAM}, max_missing ${MAX_MISSING}, premultiplied=${PREMULT}, devices ${DEVICES}"
RC=0
# shellcheck disable=SC2086
WarpTools ts_export_particles \
    --settings "${SETTINGS}" --input_processing "${INPROC}" "${OUTP_ARGS[@]}" \
    "${IN_ARGS[@]}" "${SER_ARGS[@]}" \
    --coords_angpix "${COORDS_ANGPIX}" --output_star "${OUTSTAR}" \
    --output_angpix "${ANGPIX}" --box "${BOX}" --diameter "${DIAM}" \
    --max_missing_tilts "${MAX_MISSING}" --2d "${PM_ARGS[@]}" \
    --relative_output_paths --task_dir "${TASK_DIR}" \
    --device_list ${DEVICES} --perdevice "${PERDEVICE}" ${EXTRA_FLAGS:-} || RC=$?
echo "WarpTools rc=${RC}"
(( RC == 0 )) || exit "${RC}"

# own optimisation set + absolute image paths + checks (counts, premultiplied flag, units, Cs, stale optics)
CHK=(--star "${OUTSTAR}" --premult "${PREMULT}" --angpix "${ANGPIX}" --box "${BOX}")
[[ -n "${EXPECTED_N:-}" ]] && CHK+=(--expected-n "${EXPECTED_N}")
[[ -n "${EXPECTED_TS:-}" ]] && CHK+=(--expected-ts "${EXPECTED_TS}")
"${PY}" "${SCRIPTS}/make_optset.py" "${CHK[@]}"
echo "Done: $(date)"
