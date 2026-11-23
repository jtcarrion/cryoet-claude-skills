#!/bin/bash
#SBATCH --job-name=r5_bench
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:30:00
# =============================================================================
# bench_iter1.sbatch - 200-particle, ONE-iteration smoke test BEFORE any full refine.
#
# A greyscale mismatch between reference and particles does not error: posteriors go flat, nearly every coarse pose
# goes into the fine pass, and iteration 1 takes days instead of hours. This finishes in minutes and tells you before
# you burn the GPUs.
#   healthy: median _rlnNrOfSignificantSamples ~1-15, mean _rlnMaxValueProbDistribution ~0.3+
#   flat   : hundreds-thousands significant samples, maxprob ~0.00 -> add --firstiter_cc (and --scale) or use an
#            own-data reference; NOT an I/O or MPI problem.
#   Run the diagnostic arm WITHOUT --firstiter_cc: with it, iteration 1 is a hard CC assignment and EVERY particle shows
#   1 significant sample / MaxValueProb 1.0 whatever the reference (even a wrong-frame map looks perfect).
#   An arm WITH --firstiter_cc only tells you the run's iteration-1 cost, not whether the reference is right.
#   HAND check: run two arms, the reference and its mirror (prep_reference.py --flip z), both WITHOUT --firstiter_cc;
#   the correct hand gives clearly sharper posteriors (fewer significant samples, higher MaxValueProb).
#   If BOTH hands are flat without the flag (greyscale needs --firstiter_cc), iteration 1 cannot tell the hands apart:
#   rerun both hands WITH "--firstiter_cc --scale" and ITER=3 (N=500-1000); compare the last iteration's
#   _rlnCurrentResolution (printed) and posteriors. Clearly better resolution / sharper posteriors = right hand.
#
#   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
#   CRYOET_SBATCH_OPTS="--chdir=<PROJECT> -o <LOG>/bench_%j.out" IOS=<..._abspath_optimisation_set.star> OUTROOT=<dir> \
#     cryoet_submit gpu 1 01:30:00 "${CLAUDE_SKILL_DIR}/scripts/bench_iter1.sbatch" "TAG|REF|INI_HIGH|EXTRA FLAGS" ["TAG2|..."]
# Env: IOS (required; the _abspath optimisation set from make_optset.py - Warp's own set may have an empty
#      _rlnTomoParticlesFile), OUTROOT (required, e.g. Refine3D/bench), N (default 200), DIAM (particle diameter A,
#      required), HEALPIX (2), OFFRANGE / OFFSTEP (pixels of the export, default 6 / 2), ITER (iterations, default 1;
#      3 for the --firstiter_cc hand test).
# =============================================================================
set -o pipefail
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then sed -n '/^# ====/,/^# ====/p' "$0"; exit 0; fi
CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "$0")" && pwd)/_lib}"
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
SCRIPTS="${CRYOET_LIB%/_lib}"
: "${IOS:?}" "${OUTROOT:?}" "${DIAM:?particle diameter in A}"
(( $# >= 1 )) || { echo "ERROR: give at least one arm \"TAG|REF|INI_HIGH|EXTRA FLAGS\"" >&2; exit 1; }
cryoet_require CRYOET_PYTHON || exit 3
PY="${CRYOET_PYTHON}"
N=${N:-200}; ITER=${ITER:-1}; HEALPIX=${HEALPIX:-2}; OFFRANGE=${OFFRANGE:-6}; OFFSTEP=${OFFSTEP:-2}
NJ=${SLURM_CPUS_PER_TASK:-8}
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
cryoet_activate relion || exit 2
command -v nvidia-smi >/dev/null 2>&1 && { nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true; }
mkdir -p "${OUTROOT}"
SUB="${OUTROOT}/bench${N}"
"${PY}" - "${IOS}" "${SUB}" "${N}" "${CRYOET_LIB}" <<'EOF' || exit 1
import sys, random, os
ios, sub, n, lib = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, lib); import starlite
kv = {l.split()[0]: (l.split() + [""])[1] for l in open(ios) if l.startswith("_rln")}
pf = kv.get("_rlnTomoParticlesFile", "")
if not pf or not os.path.exists(pf):
    sys.exit("ERROR: _rlnTomoParticlesFile in %s is empty or missing (%r) - pass the _abspath optimisation set "
             "from make_optset.py" % (ios, pf))
B = starlite.read(pf); P = starlite.particles(B)
random.seed(1); P.rows = random.sample(P.rows, min(n, len(P.rows)))
starlite.write(sub + "_particles.star", B)
open(sub + "_optimisation_set.star", "w").write("\n# version 50001\n\ndata_\n\n"
    "_rlnTomoParticlesFile   %s\n_rlnTomoTomogramsFile   %s\n" % (os.path.abspath(sub + "_particles.star"), kv["_rlnTomoTomogramsFile"]))
print("subset", len(P.rows), "->", sub + "_optimisation_set.star")
EOF
FAILED=0
for spec in "$@"; do
  IFS='|' read -r TAG REF INI EXTRA <<< "${spec}"
  OUT="${OUTROOT}/${TAG}"; mkdir -p "${OUT}"
  echo "=== BENCH ${TAG}  ref=${REF} ini_high=${INI} extra=[${EXTRA}]"; t0=$(date +%s)
  # EXTRA goes BEFORE --gpu so a leading flag in it can never be parsed as --gpu's device string
  # shellcheck disable=SC2086
  relion_refine --ios "${SUB}_optimisation_set.star" --ref "${REF}" --o "${OUT}/run" --iter "${ITER}" --K 1 \
    --ini_high "${INI:-40}" --particle_diameter "${DIAM}" --sym C1 --healpix_order "${HEALPIX}" \
    --offset_range "${OFFRANGE}" --offset_step "${OFFSTEP}" --oversampling 1 --ctf --pad 2 \
    --flatten_solvent --zero_mask --dont_combine_weights_via_disc --preread_images --pool 10 \
    --j "${NJ}" ${EXTRA} --gpu 0
  rc=$?
  echo "BENCH ${TAG} rc=${rc} wall=$(( $(date +%s) - t0 )) s"
  if (( rc != 0 )); then FAILED=$((FAILED + 1)); continue; fi
  IT=$(printf 'it%03d' "${ITER}")
  "${PY}" "${SCRIPTS}/refine_status.py" --posteriors "${OUT}/run_${IT}_data.star" --label "${TAG}"
  RES=$(awk '$1=="_rlnCurrentResolution"{print $2; exit}' "${OUT}/run_${IT}_model.star" 2>/dev/null)
  echo "BENCH ${TAG} ${IT} _rlnCurrentResolution=${RES:-?} A"
done
# standalone relion_refine writes no pipeliner marker; the exit code reflects only whether every arm ran
exit $(( FAILED > 0 ? 1 : 0 ))
