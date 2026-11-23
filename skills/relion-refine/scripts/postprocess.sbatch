#!/bin/bash
#SBATCH --job-name=r5_post
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
# =============================================================================
# postprocess.sbatch - relion_postprocess (+ optional local resolution) on two half-maps, and the mask-honesty
# readout. CPU only (relion_postprocess has no GPU path). Works for RELION refines AND for other half-maps (M/MCore,
# anything) - that is how a second program's maps get measured on the SAME mask.
#
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   CRYOET_SBATCH_OPTS="--chdir=<PROJECT> -o <OUTDIR>/post_%j.out" JOBDIR=<Refine3D/jobNNN> MASK=<mask> \
#     cryoet_submit cpu 0 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/postprocess.sbatch"
#   other half-maps: HALF1=<..half1..mrc> HALF2=<..half2..mrc> ANGPIX=<A> OUTDIR=<dir> MASK=<mask> (no JOBDIR needed)
#   local resolution: LOCRES=1 and add --ntasks=16 --cpus-per-task=1 to CRYOET_SBATCH_OPTS (MPI ranks = allocated
#   tasks; with 1 task it runs the serial relion_postprocess --locres, slower but correct). relion_postprocess refuses
#   --auto_bfac together with --locres, so locres is a SEPARATE call that sharpens with --adhoc_bfac <the B-factor the
#   global run fitted> (_rlnBfactorUsedForSharpening in <TAG>.star); override with LOCRES_BFAC.
# Env: MASK (required); JOBDIR (RELION job dir: HALF1/HALF2 default to run_half{1,2}_class001_unfil.mrc there) or
#      HALF1 + HALF2; OUTDIR (default JOBDIR, else the dir of HALF1); TAG (output rootname, default postprocess);
#      ANGPIX (default: _rlnImagePixelSize from DATA_STAR's optics table, DATA_STAR defaulting to $JOBDIR/run_data.star;
#      NOT the half-map header, which RELION writes rounded, e.g. 2.2526 for 2.25); AUTOB_LOWRES (10); LOCRES (0);
#      LOCRES_BFAC (default: the global run's fitted B-factor); LOCRES_NP (default SLURM_NTASKS).
# Reports FSC 0.143 and fscrand_hi = max |phase-randomised masked FSC| at resolutions finer than FSCRAND_RES (12 A).
# It must be <= 0.05; above that the mask edge is manufacturing correlation (dilate the mask and re-run).
# fscrand_hi cannot see cross-half duplicates - run dedup_audit.py BEFORE refining for that.
# Compare maps only on ONE mask, never a RELION FSC against M's own FSC (M grows its mask) - re-measure here instead.
# =============================================================================
set -eo pipefail
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then sed -n '/^# ====/,/^# ====/p' "$0"; exit 0; fi
CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "$0")" && pwd)/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
: "${MASK:?}"
[[ -s "${MASK}" ]] || { echo "ERROR: mask not found: ${MASK}" >&2; exit 1; }
if [[ -n "${JOBDIR:-}" ]]; then
    HALF1=${HALF1:-${JOBDIR}/run_half1_class001_unfil.mrc}; HALF2=${HALF2:-${JOBDIR}/run_half2_class001_unfil.mrc}
    DATA_STAR=${DATA_STAR:-${JOBDIR}/run_data.star}
fi
: "${HALF1:?set JOBDIR or HALF1+HALF2}" "${HALF2:?set JOBDIR or HALF1+HALF2}"
for h in "${HALF1}" "${HALF2}"; do [[ -s "${h}" ]] || { echo "ERROR: ${h} missing - refine not finished?" >&2; exit 1; }; done
OUTDIR=${OUTDIR:-${JOBDIR:-$(dirname "${HALF1}")}}; mkdir -p "${OUTDIR}"
TAG=${TAG:-postprocess}
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
cryoet_activate relion || exit 2
NP=${LOCRES_NP:-${SLURM_NTASKS:-1}}
if [[ "${LOCRES:-0}" == "1" ]] && (( NP > 1 )); then   # fail fast before the global run, not after it
  L="${RELION_MPI_LAUNCHER:-mpirun}"; command -v "${L}" >/dev/null 2>&1 || {
    echo "ERROR: your RELION env does not provide ${L} (RELION_MPI_LAUNCHER=${L}); add the MPI module load to" \
         "RELION_ENV_SCRIPT or point it at a wrapper that loads RELION + MPI (or run LOCRES with 1 task)" >&2; exit 2; }
fi
if [[ -z "${ANGPIX:-}" && -n "${DATA_STAR:-}" && -s "${DATA_STAR}" ]]; then
    ANGPIX=$(awk '/^data_optics/{o=1} o&&/^_rlnImagePixelSize/{split($2,a,"#");c=a[2]} o&&c&&NF>=c&&$1!~/^_/&&$1!~/^loop/{print $c; exit}' "${DATA_STAR}")
fi
[[ -n "${ANGPIX:-}" ]] || { echo "ERROR: set ANGPIX (or DATA_STAR / JOBDIR with run_data.star) - the half-map header is rounded" >&2; exit 1; }
NJ=${SLURM_CPUS_PER_TASK:-$(nproc)}; export OMP_NUM_THREADS=${NJ}
printf 'half1 %s\nhalf2 %s\n' "${HALF1}" "${HALF2}"
echo "angpix ${ANGPIX} | mask ${MASK} | out ${OUTDIR}/${TAG}"
# rootname, never a trailing slash: '--o dir/' writes dot-files
RC=0
relion_postprocess --i "${HALF1}" --i2 "${HALF2}" --o "${OUTDIR}/${TAG}" --mask "${MASK}" --angpix "${ANGPIX}" \
    --auto_bfac --autob_lowres "${AUTOB_LOWRES:-10}" > "${OUTDIR}/${TAG}.log" 2>&1 || RC=$?
if (( RC != 0 )) || [[ ! -s "${OUTDIR}/${TAG}.star" ]]; then
    tail -5 "${OUTDIR}/${TAG}.log" >&2; echo "ERROR: relion_postprocess failed (rc ${RC})" >&2; exit "$(( RC ? RC : 1 ))"
fi
if [[ "${LOCRES:-0}" == "1" ]]; then
    BFAC=${LOCRES_BFAC:-$(awk '$1=="_rlnBfactorUsedForSharpening"{print $2; exit}' "${OUTDIR}/${TAG}.star")}
    [[ -n "${BFAC}" ]] || { echo "ERROR: no _rlnBfactorUsedForSharpening in ${OUTDIR}/${TAG}.star; set LOCRES_BFAC" >&2; exit 1; }
    echo "locres: separate call, --adhoc_bfac ${BFAC} (--auto_bfac is refused with --locres)"
    LARGS=(--i "${HALF1}" --i2 "${HALF2}" --o "${OUTDIR}/${TAG}_locres" --mask "${MASK}" --angpix "${ANGPIX}"
           --locres --adhoc_bfac "${BFAC}")
    LRC=0
    if (( NP > 1 )); then export SRUN_CPUS_PER_TASK=1; cryoet_mpirun "${NP}" relion_postprocess_mpi "${LARGS[@]}" > "${OUTDIR}/${TAG}_locres.log" 2>&1 || LRC=$?
    else relion_postprocess "${LARGS[@]}" > "${OUTDIR}/${TAG}_locres.log" 2>&1 || LRC=$?; fi
    if [[ -s "${OUTDIR}/${TAG}_locres_locres.mrc" ]]; then
        echo "local resolution map: ${OUTDIR}/${TAG}_locres_locres.mrc"
        (( LRC == 0 )) || echo "NOTE: --locres returned ${LRC} but wrote the map ('ERROR in executing: gs' only means Ghostscript is missing for the PDF)"
    else
        echo "ERROR: --locres failed (rc ${LRC}); see ${OUTDIR}/${TAG}_locres.log" >&2; exit 1
    fi
fi
awk -v lim="${FSCRAND_RES:-12}" '
/^_rlnFinalResolution/{res=$2}
/^data_fsc/{blk=1; next} /^data_/{blk=0}
blk && /^_rln/{split($2,a,"#"); col[$1]=a[2]; next}
blk && NF>3 && $1!~/^loop/ { r=$col["_rlnAngstromResolution"]; x=$col["_rlnCorrectedFourierShellCorrelationPhaseRandomizedMaskedMaps"];
    if (x<0) x=-x; if (r<lim+0 && x>fr) fr=x }
END{ printf "FSC 0.143: %s A   fscrand_hi: %.3f   -> %s\n", res, fr, (fr<=0.05 ? "mask OK" : "MASK TOO TIGHT - dilate and re-run") }' "${OUTDIR}/${TAG}.star"
