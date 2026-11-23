#!/bin/bash
#SBATCH --job-name=m_round
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=400G
#SBATCH --time=04:00:00
# =============================================================================
# mcore_round.sbatch - ONE M round (= one MCore invocation = one species version), optionally preceded by
# EstimateWeights, with snapshot, box-128 guard, term audit and measurement on the fixed RELION mask (+ cross-FSC).
#
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   CRYOET_SBATCH_OPTS="--output=<popdir>/round_<LABEL>_%j.out" \
#     cryoet_submit gpu 4 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/mcore_round.sbatch" <popdir>/round_<LABEL>.env
#
# <round.env> (bash KEY=VALUE, sourced; it stays in the population as the round's record):
#   POPULATION=/abs/pop.population  LABEL=r1  RELION_MASK=/abs/soft_mask.mrc        (required)
#   FLAGS="--refine_imagewarp 5x5 --refine_stageangles --refine_particles"         (MCore refinement flags)
#   EXPECT="GridMovement:GridAngle"   XML term prefixes this round may change, ':'-separated (see xml_diff.py);
#                                     empty = poses only (no XML term may move)
#   GUARD_REF=/abs/map.mrc REF_APIX=..  cross-FSC guard map; REQUIRED when FLAGS/WEIGHTS fit shared per-tilt-series
#                                     terms (image/volume warp, stage angles, CTF, mag, weights). Default choice: an
#                                     EXTERNAL map not built from these particles (EMDB entry of the same complex,
#                                     hand- and pixel-matched to the half-maps; GUARD_REF_KIND=external, all
#                                     frequencies). Else RELION's run_class001.mrc with GUARD_REF_KIND=relion and
#                                     RELION_RES=<RELION FSC0.143, A>: same particles = shared noise, so only
#                                     resolutions coarser than RELION_RES count and a caveat is printed.
#                                     REF_MAP=.. is the legacy name (= GUARD_REF with kind relion). Use the SAME guard
#                                     map for iter0 and every round (re-measure iter0 on it if you switch).
#                                     # NEEDS AUTHOR REVIEW: external-map default + RELION cutoff is a proposed rule change.
#   ITER (3)  MIN_PARTICLES (50)  FIRST_ITER_FRACTION (e.g. 0.7 when a grid is introduced)
#   WEIGHTS="--resolve_items"         run EstimateWeights first (per-series weights; "--resolve_frames" = per tilt,
#                                     averaged over series). Needs *_fsc.mrc from a previous MCore round in
#                                     <popdir>/refinement_temp/<source>/. WEIGHTS_MIN_RES (A, default 20).
#   ALLOW_RESIZE=1                    the user approved a NEW warp-grid size this round (xml_diff --allow_resize)
#   DEVICES ("0 1 ..", default: all visible)  PERDEVICE (1)
# FLAGS must repeat the EXISTING image/volume-warp grid size: MCore resamples the stored field to whatever is requested.
# Exit codes: MCore/EstimateWeights failure -> its rc (after the audit has run); unexpected XML change or lossy grid
#   resize -> 3 (the round is still measured first, so the numbers are there to judge it); measurement failure -> 1.
#   The cross-FSC GUARD verdict is printed, never an exit code: the agent/user decides whether to keep the round.
#   Revert = restore snapshots/before_<LABEL>/*.xml + the previous species version.
# =============================================================================
set -o pipefail
export PYTHONUNBUFFERED=1
if [ -n "${1:-}" ]; then
  [ -f "$1" ] || { echo "ERROR: env file $1 not found" >&2; exit 2; }
fi
: "${CRYOET_LIB:?run via cryoet_submit, or export CRYOET_LIB=<skill>/scripts/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
if [ -n "${1:-}" ]; then set -a; source "$1"; set +a; fi
cryoet_require CRYOET_PYTHON || exit 3
cryoet_have m || { echo "ERROR: M (MTools/MCore) is not configured - set WARP_ENV_SCRIPT or put MCore on PATH" >&2; exit 4; }
cryoet_activate m || exit 4
command -v MCore >/dev/null || { echo "ERROR: MCore not on PATH after activation" >&2; exit 4; }
: "${POPULATION:?}" "${LABEL:?}" "${RELION_MASK:?fixed soft mask to measure on}"
HERE="$(cd "$CRYOET_LIB/.." && pwd)"; PY="$CRYOET_PYTHON"
PERDEVICE=${PERDEVICE:-1}; ITER=${ITER:-3}; MIN_PARTICLES=${MIN_PARTICLES:-50}
POPDIR=$(cd "$(dirname "${POPULATION}")" && pwd); POPULATION="${POPDIR}/$(basename "${POPULATION}")"
die() { echo "ERROR: $*" >&2; exit 1; }

echo "=== M round ${LABEL}: job ${SLURM_JOB_ID:-local:$$} on $(hostname) $(date)"
echo "FLAGS: ${FLAGS:-<none>}  WEIGHTS: ${WEIGHTS:-<none>}  ITER ${ITER}  MIN_PARTICLES ${MIN_PARTICLES}"
if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then NVIS=$(echo "$CUDA_VISIBLE_DEVICES" | tr ',' '\n' | grep -c .)
else NVIS=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU'); fi
[ "${NVIS:-0}" -gt 0 ] || die "no GPU visible"
DEVICES=${DEVICES:-$(seq -s ' ' 0 $((NVIS - 1)))}
for d in $DEVICES; do [ "$d" -lt "$NVIS" ] || die "DEVICES '$DEVICES' asks for GPU $d but only $NVIS are visible"; done
nvidia-smi --query-gpu=index,name,memory.total,ecc.errors.uncorrected.volatile.total --format=csv,noheader 2>/dev/null
[ -f "${RELION_MASK}" ] || die "RELION_MASK ${RELION_MASK} not found"
ls -d "${POPDIR}/rounds/${LABEL}_"* >/dev/null 2>&1 && die "round ${LABEL} already saved in ${POPDIR}/rounds"
SHARED='(imagewarp|stageangles|volumewarp|ctf_|refine_mag|tiltmovies)'
GREF=${GUARD_REF:-${REF_MAP:-}}
if [ -n "${GUARD_REF:-}" ]; then GKIND=${GUARD_REF_KIND:-external}; else GKIND=${GUARD_REF_KIND:-relion}; fi
if { [[ "${FLAGS:-}" =~ $SHARED ]] || [ -n "${WEIGHTS:-}" ]; } && [ -z "${GREF}" ]; then
  die "this round fits shared per-tilt-series terms - set GUARD_REF (external map, or RELION map + GUARD_REF_KIND=relion RELION_RES=..) for the cross-FSC overfitting guard"
fi
[ -z "${GREF}" ] || [ -f "${GREF}" ] || die "guard reference ${GREF} not found"
[ -n "${GREF}" ] && echo "cross-FSC guard: ${GREF} (kind ${GKIND}${RELION_RES:+, RELION_RES ${RELION_RES} A})"
[ "${GKIND}" = relion ] && [ -n "${GREF}" ] && echo "CAVEAT guard map is RELION's reconstruction of the same particles:" \
  "cross-FSC counts only coarser than RELION_RES; prefer an external map (GUARD_REF + GUARD_REF_KIND=external)"
[ "${FLAGS:-}" != "${FLAGS/--port/}" ] && die "do not put --port in FLAGS; the script assigns a per-job port"

LOCK="${POPDIR}/.m_lock"
mkdir "$LOCK" 2>/dev/null || die "population locked ($LOCK): another M job is using it; remove the dir only if none is"
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
cryoet_use_scratch "mcore_${LABEL}" || die "no scratch under $SCRATCH_ROOT"   # sets $SCR, chained cleanup
TD="$SCR"
[ -n "${1:-}" ] && [ "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" != "${POPDIR}/round_${LABEL}.env" ] \
  && cp "$1" "${POPDIR}/round_${LABEL}.env"

# processing folder = the source file's folder; source name from the .source file
read -r SRC SRCNAME < <("${PY}" - "${POPULATION}" <<'EOF'
import os, sys, xml.etree.ElementTree as ET
pop = sys.argv[1]; d = os.path.dirname(pop)
srcs = [s.get("Path") for s in ET.parse(pop).getroot().iter("Source") if s.get("Path")]
if len(srcs) != 1:
    sys.exit("expected exactly one source in %s, found %d" % (pop, len(srcs)))
p = os.path.normpath(os.path.join(d, srcs[0]))
name = next((q.get("Value") for q in ET.parse(p).getroot().iter("Param") if q.get("Name") == "Name"), "")
print(os.path.dirname(p), name)
EOF
)
[ -d "${SRC:-}" ] || die "could not resolve the processing folder from ${POPULATION}"
echo "processing folder: ${SRC}  (source '${SRCNAME}')"
STATUS=$("${PY}" "${HERE}/m_status.py" --population "${POPULATION}") || die "m_status failed"
echo "${STATUS}"
grep -q "SILENT NO-OP" <<< "${STATUS}" && die "refinement box would be 128 px - nudge GlobalResolution first (ask the user)"

SNAP=${POPDIR}/snapshots/before_${LABEL}; mkdir -p "${SNAP}"; cp -p "${SRC}"/*.xml "${SNAP}/" || die "snapshot failed"
[ -f "${SRC}/processed_items.json" ] && cp -p "${SRC}/processed_items.json" "${SNAP}/"
EXP="${EXPECT:-}"
rc=0; t0=$(date +%s)

if [ -n "${WEIGHTS:-}" ]; then
  command -v EstimateWeights >/dev/null || die "EstimateWeights not on PATH (ships with Warp 2.0 next to MCore)"
  RT="${POPDIR}/refinement_temp/${SRCNAME}"
  ls "${RT}"/*_fsc.mrc >/dev/null 2>&1 || die "no *_fsc.mrc in ${RT}: run an MCore round first (it writes them)"
  echo "=== EstimateWeights ${WEIGHTS} $(date)"
  # shellcheck disable=SC2086
  EstimateWeights --population "${POPULATION}" --source "${SRCNAME}" ${WEIGHTS} --min_resolution "${WEIGHTS_MIN_RES:-20}"
  rc=$?
  echo "EstimateWeights rc=${rc}"
  EXP="${EXP:+${EXP}:}Bfactor:Weight:GridDose:GridLocation"
fi

if [ "${rc}" -eq 0 ]; then
  FIF=(); [ -n "${FIRST_ITER_FRACTION:-}" ] && FIF=(--first_iteration_fraction "${FIRST_ITER_FRACTION}")
  PORT=$(cryoet_port)
  echo "=== MCore port ${PORT} devices ${DEVICES} $(date)"
  # shellcheck disable=SC2086
  MCore --population "${POPULATION}" --iter "${ITER}" --min_particles "${MIN_PARTICLES}" "${FIF[@]}" ${FLAGS:-} \
      --devicelist ${DEVICES} --perdevice "${PERDEVICE}" --task_dir "${TD}" --port "${PORT}"
  rc=$?
  echo "MCore rc=${rc}  wall $(( ($(date +%s) - t0) / 60 )) min"
fi

# ---- audit: always runs, whatever the tools returned ----
LOGS=$(find "${POPDIR}/refinement_temp" "${SRC}" "${TD}" -maxdepth 3 -name '*refine*.log' -newer "${SNAP}" 2>/dev/null)
if [ -n "${LOGS}" ]; then
  # shellcheck disable=SC2086
  NA=$(grep -h "Final score" ${LOGS} 2>/dev/null | wc -l)
  # shellcheck disable=SC2086
  NZ=$(grep -h "Final score" ${LOGS} 2>/dev/null | grep -vc "Final score: 0$")
  echo "refine-log final scores: ${NZ} non-zero of ${NA}"
  [ "${NA}" -gt 0 ] && [ "${NZ}" -eq 0 ] && echo "WARN every series 'Final score: 0' - box-128 no-op or nothing refined"
  [ "${rc}" -ne 0 ] && { mkdir -p "${POPDIR}/failed_${LABEL}_logs"; cp ${LOGS} "${POPDIR}/failed_${LABEL}_logs/" 2>/dev/null; }
else
  echo "WARN no refine logs newer than the snapshot (names differ between Warp builds; check refinement_temp/logs)"
fi
XD=(--expect "${EXP}"); [ "${ALLOW_RESIZE:-0}" = 1 ] && XD+=(--allow_resize)
"${PY}" "${HERE}/xml_diff.py" --before "${SNAP}" --after "${SRC}" "${XD[@]}"; drc=$?
mrc=0
if [ "${rc}" -eq 0 ]; then
  "${PY}" "${HERE}/m_status.py" --population "${POPULATION}" --save-round "${LABEL}" --mask "${RELION_MASK}" \
      ${GREF:+--ref "${GREF}"} ${GREF:+--ref-kind "${GKIND}"} ${REF_APIX:+--ref-apix "${REF_APIX}"} \
      ${RELION_RES:+--relion-res "${RELION_RES}"}
  mrc=$?
fi
echo "=== round ${LABEL} summary: tool rc ${rc} | XML audit $([ "${drc}" -eq 0 ] && echo ok || echo "FLAGGED (rc ${drc})")" \
     "| measurement $([ "${rc}" -ne 0 ] && echo "not run" || { [ "${mrc}" -eq 0 ] && echo ok || echo FAILED; })" \
     "(GUARD line above: cross-FSC vs the previous row measured on the same guard map)"
if [ "${rc}" -ne 0 ]; then
  echo "FAILED: tool rc ${rc}. XMLs may be partly rewritten - compare with ${SNAP} (xml_diff above) before reverting." >&2
  exit "${rc}"
fi
[ "${drc}" -ne 0 ] && { echo "FAILED: unexpected XML term change or lossy grid resize (see xml_diff) - review/revert" >&2; exit 3; }
[ "${mrc}" -ne 0 ] && { echo "FAILED: the round ran but was not measured" >&2; exit 1; }
echo "done $(date). Compare with the previous rows of ${POPDIR}/rounds_measured.csv before the next round."
