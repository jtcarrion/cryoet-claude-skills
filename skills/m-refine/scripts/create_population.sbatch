#!/bin/bash
#SBATCH --job-name=m_create
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=300G
#SBATCH --time=04:00:00
# =============================================================================
# create_population.sbatch - an ISOLATED M population seeded from a RELION refinement, then MCore --iter 0.
#
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   CRYOET_SBATCH_OPTS="--output=<NEWROOT>.create_%j.out" \
#     cryoet_submit gpu 4 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/create_population.sbatch" <create.env>
#   (workstation: SCHEDULER=none runs the same script with bash in the background)
#
# <create.env> is a bash KEY=VALUE file (sourced; keep it next to the population as provenance). Variables already
# exported in the environment work too; the file wins. Using a file avoids `sbatch --export`, which splits on commas.
# Required:
#   NEWROOT       new population folder (must not exist)        POP_NAME  SPECIES_NAME
#   SEED_XMLS     tilt-series XML folder to COPY (never pointed at directly - MCore rewrites the XMLs it is given)
#   SETTINGS_SRC  the tilt-series .settings; copied and rewired to the private XML copy
#   PARTICLES     RELION run_data.star (coords in _rlnImagePixelSize units, shifts in A), or an M table (PARTICLES_M=1)
#   HALF1 HALF2   RELION unfiltered half-maps    MASK_BIN  tight binary mask on the half-map grid (make_binary_mask.py)
#   TRUE_ANGPIX   nominal pixel of half-maps/mask (restaged into the headers: RELION may write a slightly different one)
#   DIAMETER (A)  SYM  ANGPIX_RESAMPLE (species pixel, e.g. the tilt-series pixel)  LOWPASS (A, just past RELION's res.)
# Optional:
#   TEMPORAL (1; 3 = pose trajectories as in the M paper)   DENOISER (0 = --dont_use_denoiser, default; 1 = on)
#   EXPECT_N (assert particle count)   RELION_MASK (soft mask to measure iter 0 on)
#   GUARD_REF + REF_APIX (+ GUARD_REF_KIND external|relion) cross-FSC guard map - see mcore_round.sbatch; REF_MAP is the
#     legacy name (= GUARD_REF with kind relion). Measure iter 0 against the SAME guard map the rounds will use.
#   RELION_RES (A, RELION FSC0.143 on RELION_MASK: transfer-check reference and the 'relion' guard cutoff)
#   TRANSFER_MAX_GAP (A, default 0.5: iter-0 FSC0.143 may be this much worse than RELION_RES)
#   CS_MM (nominal Cs; default MICROSCOPE_CS_MM, else the XMLs' own <OptionsCTF> Cs)
#   RESET_SEED (1 = reset Cs + odd Zernikes in the private copy if a previous M run changed them; 0 = keep and warn)
#   DEVICES ("0 1 ..", default: every visible GPU)   PERDEVICE (1; raise only with VRAM to spare)
# Isolation: private XML copy + processed_items.json, settings rewired and verified, a population lock, XML snapshot
# before iter 0, and xml_diff --expect none after it (iter 0 must change no parsed value).
# After iter 0, check_transfer.py (positions vs RELION, count, iter-0 resolution) runs even if the audit flags.
# Exit: MCore rc | 5 transfer check failed | 3 audit flagged (transfer OK) | 1 measurement/setup failure.
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
for b in MTools MCore; do command -v "$b" >/dev/null || { echo "ERROR: $b not on PATH after activation" >&2; exit 4; }; done
: "${NEWROOT:?}" "${POP_NAME:?}" "${SPECIES_NAME:?}" "${SEED_XMLS:?}" "${SETTINGS_SRC:?}" "${PARTICLES:?}"
: "${HALF1:?}" "${HALF2:?}" "${MASK_BIN:?}" "${TRUE_ANGPIX:?}" "${DIAMETER:?}" "${SYM:?}" "${ANGPIX_RESAMPLE:?}" "${LOWPASS:?}"
HERE="$(cd "$CRYOET_LIB/.." && pwd)"; PY="$CRYOET_PYTHON"
PERDEVICE=${PERDEVICE:-1}; RESET_SEED=${RESET_SEED:-1}
die() { echo "ERROR: $*" >&2; exit 1; }

echo "=== create_population job ${SLURM_JOB_ID:-local:$$} on $(hostname) $(date)"
if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then NVIS=$(echo "$CUDA_VISIBLE_DEVICES" | tr ',' '\n' | grep -c .)
else NVIS=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU'); fi
[ "${NVIS:-0}" -gt 0 ] || die "no GPU visible"
DEVICES=${DEVICES:-$(seq -s ' ' 0 $((NVIS - 1)))}
for d in $DEVICES; do [ "$d" -lt "$NVIS" ] || die "DEVICES '$DEVICES' asks for GPU $d but only $NVIS are visible"; done
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null
[ ! -e "${NEWROOT}" ] || die "${NEWROOT} exists"
for f in "${PARTICLES}" "${HALF1}" "${HALF2}" "${MASK_BIN}" "${SETTINGS_SRC}"; do [ -f "$f" ] || die "missing $f"; done
ls "${SEED_XMLS}"/*.xml >/dev/null 2>&1 || die "no *.xml in ${SEED_XMLS}"
# cross-FSC guard reference: GUARD_REF (+ GUARD_REF_KIND external|relion) > legacy REF_MAP (= kind relion)
GREF=${GUARD_REF:-${REF_MAP:-}}
if [ -n "${GUARD_REF:-}" ]; then GKIND=${GUARD_REF_KIND:-external}; else GKIND=${GUARD_REF_KIND:-relion}; fi
[ -z "${GREF}" ] || [ -f "${GREF}" ] || die "guard reference ${GREF} not found"

mkdir -p "${NEWROOT}" || die "cannot create ${NEWROOT}"
NEWROOT=$(cd "${NEWROOT}" && pwd)
LOCK="${NEWROOT}/.m_lock"; mkdir "$LOCK" || die "lock $LOCK held"
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
cryoet_use_scratch "mcore_create" || die "no scratch under $SCRATCH_ROOT"   # sets $SCR, chained cleanup
TD="$SCR"
[ -n "${1:-}" ] && cp "$1" "${NEWROOT}/create.env"

PROCDIR=${NEWROOT}/warp_tiltseries_m; SETTINGS=${NEWROOT}/$(basename "${SETTINGS_SRC%.settings}")_m.settings
mkdir -p "${PROCDIR}"
cp -p "${SEED_XMLS}"/*.xml "${PROCDIR}/" || die "XML copy failed"
[ -f "${SEED_XMLS}/processed_items.json" ] && cp -p "${SEED_XMLS}/processed_items.json" "${PROCDIR}/"
echo "XMLs copied: $(ls "${PROCDIR}"/*.xml | wc -l)"

# nominal Cs: CS_MM > MICROSCOPE_CS_MM > the XMLs' own <OptionsCTF> Cs (the value ts_ctf was run with)
CHECK=$("${PY}" - "${PROCDIR}" "${CS_MM:-${MICROSCOPE_CS_MM:-}}" <<'EOF'
import glob, sys, xml.etree.ElementTree as ET
proc, nominal = sys.argv[1], sys.argv[2]
opt, bad = set(), 0
rows = []
for p in sorted(glob.glob(proc + "/*.xml")):
    r = ET.parse(p).getroot()
    o = r.find("OptionsCTF"); c = r.find("CTF")
    get = lambda e, n: next((q.get("Value") for q in e.iter("Param") if q.get("Name") == n), None) if e is not None else None
    if get(o, "Cs"): opt.add(round(float(get(o, "Cs")), 4))
    rows.append((p, get(c, "Cs"), get(c, "ZernikeCoeffsOdd")))
if not nominal:
    if len(opt) != 1:
        print("NOMINAL? %s" % sorted(opt)); sys.exit(0)
    nominal = str(opt.pop())
for p, cs, odd in rows:
    odd_nz = any(abs(float(x)) > 0 for x in (odd or "").replace(",", ";").split(";") if x.strip())
    if cs is None or abs(float(cs) - float(nominal)) > 0.01 or odd_nz:
        bad += 1
print("%s %d" % (nominal, bad))
EOF
) || die "Cs check failed"
read -r NOMINAL_CS NBAD <<< "$CHECK"
[ "$NOMINAL_CS" != "NOMINAL?" ] || die "seed XMLs disagree on <OptionsCTF> Cs ($NBAD); set CS_MM"
echo "nominal Cs ${NOMINAL_CS} mm; XMLs with a fitted Cs or non-zero odd Zernikes: ${NBAD}"
if [ "${NBAD}" -gt 0 ]; then
  if [ "${RESET_SEED}" = 1 ]; then
    [ -f "$CRYOET_LIB/reset_ctf_cs.py" ] || die "reset_ctf_cs.py missing from $CRYOET_LIB (re-vendor the skill's _lib)"
    "${PY}" "$CRYOET_LIB/reset_ctf_cs.py" "${PROCDIR}" --in_place --cs_mm "${NOMINAL_CS}" --zero_zernike_odd \
      || die "Cs reset failed"
  else
    echo "WARN RESET_SEED=0: ${NBAD} XMLs keep a previous run's fitted Cs / odd Zernikes (inherited into this population)"
  fi
fi

"${PY}" - "${SETTINGS_SRC}" "${SETTINGS}" "${PROCDIR}" <<'EOF' || die "settings rewire failed"
import os, re, sys
src, dst, proc = sys.argv[1:]
s = open(src).read()
s2, n = re.subn(r'(<Param Name="ProcessingFolder" Value=")[^"]*(")', lambda m: m.group(1) + proc + m.group(2), s)
assert n == 1, "ProcessingFolder param not found exactly once"
# relative paths in a .settings resolve against the SETTINGS FILE's folder; the copy lives elsewhere -> make them absolute
base = os.path.dirname(os.path.abspath(src))
def absify(m):
    v = m.group(2)
    return m.group(1) + (v if (not v or os.path.isabs(v)) else os.path.normpath(os.path.join(base, v))) + m.group(3)
s2 = re.sub(r'(<Param Name="(?:DataFolder|GainPath|DefectsPath)" Value=")([^"]*)(")', absify, s2)
open(dst, "w").write(s2); print("settings rewired ->", proc)
print("  " + "  ".join(re.findall(r'<Param Name="(?:DataFolder|ProcessingFolder)" Value="[^"]*"', s2)))
EOF
grep -q "Value=\"${PROCDIR}\"" "${SETTINGS}" || die "ProcessingFolder rewrite did not take"

H1=${NEWROOT}/ref_${SPECIES_NAME}_half1.mrc; H2=${NEWROOT}/ref_${SPECIES_NAME}_half2.mrc; MB=${NEWROOT}/mask_${SPECIES_NAME}_binary.mrc
"${PY}" - "${HALF1}" "${H1}" "${HALF2}" "${H2}" "${MASK_BIN}" "${MB}" "${TRUE_ANGPIX}" <<'EOF' || die "staging maps failed"
import sys, numpy as np, mrcfile
a = sys.argv[1:]; apix = float(a[6])
for src, dst in ((a[0], a[1]), (a[2], a[3]), (a[4], a[5])):
    with mrcfile.open(src, permissive=True) as m:
        d = np.array(m.data, np.float32); old = float(m.voxel_size.x)
    with mrcfile.new(dst, overwrite=False) as m:
        m.set_data(d); m.voxel_size = apix
    print("  staged %s: %.5f -> %s A/px, %s" % (src.split('/')[-1], old, apix, d.shape))
EOF
NPART=$("${PY}" -c "import sys; sys.path.insert(0, sys.argv[1]); import starlite
print(len(starlite.particles(starlite.read(sys.argv[2])).rows))" "$CRYOET_LIB" "${PARTICLES}") || die "cannot read ${PARTICLES}"
echo "particles: ${NPART}"
[ -z "${EXPECT_N:-}" ] || [ "${NPART}" = "${EXPECT_N}" ] || die "expected ${EXPECT_N} particles"

POP=${NEWROOT}/${POP_NAME}.population
MTools create_population --directory "${NEWROOT}" --name "${POP_NAME}" || die "create_population failed"
MTools create_source --population "${POP}" --name "${POP_NAME}" --processing_settings "${SETTINGS}" || die "create_source failed"
PFLAG=(--particles_relion "${PARTICLES}"); [ "${PARTICLES_M:-0}" = 1 ] && PFLAG=(--particles_m "${PARTICLES}")
DN=(--dont_use_denoiser); [ "${DENOISER:-0}" = 1 ] && DN=()
MTools create_species --population "${POP}" --name "${SPECIES_NAME}" --diameter "${DIAMETER}" --sym "${SYM}" \
    --temporal_samples "${TEMPORAL:-1}" --half1 "${H1}" --half2 "${H2}" --mask "${MB}" "${PFLAG[@]}" \
    --angpix_resample "${ANGPIX_RESAMPLE}" --lowpass "${LOWPASS}" "${DN[@]}" || die "create_species failed"
MTools list_species -p "${POP}"

SNAP=${NEWROOT}/snapshots/before_iter0; mkdir -p "${SNAP}"; cp -p "${PROCDIR}"/*.xml "${SNAP}/"
PORT=$(cryoet_port)
echo "=== MCore --iter 0 (reconstruct only; refines nothing) port ${PORT} devices ${DEVICES} $(date)"
# shellcheck disable=SC2086
MCore --population "${POP}" --iter 0 --devicelist ${DEVICES} --perdevice "${PERDEVICE}" --task_dir "${TD}" --port "${PORT}"
rc=$?
echo "MCore rc=${rc}"
# audit + transfer check run whatever the other returned: a false audit alarm must not hide whether iter 0 is valid
"${PY}" "${HERE}/xml_diff.py" --before "${SNAP}" --after "${PROCDIR}" --expect none; drc=$?
mrc=0; trc=0
if [ "${rc}" -eq 0 ]; then
  "${PY}" "${HERE}/m_status.py" --population "${POP}" --save-round iter0 \
      ${RELION_MASK:+--mask "${RELION_MASK}"} ${GREF:+--ref "${GREF}"} ${GREF:+--ref-kind "${GKIND}"} \
      ${REF_APIX:+--ref-apix "${REF_APIX}"} ${RELION_RES:+--relion-res "${RELION_RES}"}
  mrc=$?
  "${PY}" "${HERE}/check_transfer.py" --population "${POP}" --particles "${PARTICLES}" --species "${SPECIES_NAME}" \
      ${RELION_RES:+--relion-res "${RELION_RES}"} ${TRANSFER_MAX_GAP:+--max-gap "${TRANSFER_MAX_GAP}"}
  trc=$?
fi
echo "=== iter 0 summary: MCore rc ${rc} | XML audit $([ "${drc}" -eq 0 ] && echo ok || echo "FLAGGED (rc ${drc})")" \
     "| measurement $([ "${mrc}" -eq 0 ] && echo ok || echo "FAILED")" \
     "| transfer check $([ "${rc}" -ne 0 ] && echo "not run" || { [ "${trc}" -eq 0 ] && echo PASS || echo "FAIL (rc ${trc})"; })"
[ "${rc}" -ne 0 ] && { echo "FAILED: MCore rc ${rc} (logs: ${NEWROOT}/refinement_temp/logs)" >&2; exit "${rc}"; }
[ "${trc}" -ne 0 ] && { echo "FAILED: transfer check (positions/count/iter-0 resolution) - stop and look" >&2; exit 5; }
[ "${drc}" -ne 0 ] && { echo "FAILED: iter 0 changed parsed XML values (see above; transfer check PASSED, so" \
  "iter 0 itself is valid if the flagged terms are benign) - investigate before refining" >&2; exit 3; }
[ "${mrc}" -ne 0 ] && { echo "FAILED: measurement" >&2; exit "${mrc}"; }
echo "done $(date)"
