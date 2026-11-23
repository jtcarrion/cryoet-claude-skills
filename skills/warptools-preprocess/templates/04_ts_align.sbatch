#!/bin/bash
#SBATCH --job-name=w_align
#SBATCH --cpus-per-task=32
#SBATCH --mem=200G
#SBATCH --time=12:00:00
# Step 4 - tilt-series alignment (builds tiltstack/ itself; no separate ts_stack needed). One script, four methods:
#   04_ts_align.sbatch [--method patches|fiducials|aretomo3|import] [--variant NAME] [--series a,b] [--dry-run]
#   import: --alignments DIR (DIR/<series>/<series>.xf + .tlt, Warp series names) --alignment-angpix A
# Submit through submit_chain.sh (it passes the SAME --variant to 05/06/07 and gets partition/GPUs from the config).
# A variant folder is seeded from the baseline XMLs first. Then 05/06/07 MUST get the same --variant.
# Import traps: --alignment-angpix = pixel size the .xf SHIFTS were computed at; .xf rows are positional (a file
# written in the opposite tilt order looks like a terrible alignment); fewer .xf lines than tilts = dropped tilts
# (needs cutviews); ts_ctf is MANDATORY afterwards (defocus is fit against the geometry).
# Software: patches/fiducials need IMOD (config IMOD_DIR), aretomo3 needs AreTomo3 (config ARETOMO3_BIN).
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
source "$PROJ/scripts/warp_common.sh"
cd "$PROJ" || exit 1
parse_common_args "$@"; resolve_processing; resolve_series
banner "Step 4 - alignment (method: $METHOD)"
case "$METHOD" in
  patches|fiducials) cryoet_have imod || { echo "ERROR: --method $METHOD needs IMOD (config IMOD_DIR); not configured" >&2; exit 3; }
                     command -v tiltalign >/dev/null 2>&1 || { echo "ERROR: IMOD's tiltalign not on PATH after activation" >&2; exit 3; } ;;
  aretomo3) cryoet_have aretomo3 || { echo "ERROR: --method aretomo3 needs AreTomo3 (config ARETOMO3_BIN); not configured" >&2; exit 3; } ;;
esac
resolve_devices
[[ -n "$VARIANT" ]] && seed_variant_from_baseline "$PROC_OUT"

case "$METHOD" in
  patches)
    run_warp WarpTools ts_etomo_patches --settings "$TS_SETTINGS" --angpix "$ALIGN_ANGPIX" --patch_size "$PATCH_SIZE" \
      --min_fov "$MIN_FOV" --device_list $DEVICE_LIST --perdevice "$PERDEVICE" --task_dir "$(task_dir align)" \
      "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}" ;;
  fiducials)
    run_warp WarpTools ts_etomo_fiducials --settings "$TS_SETTINGS" --angpix "$ALIGN_ANGPIX" \
      --fiducial_size "$FIDUCIAL_NM" --n_beads_target "$N_BEADS_TARGET" \
      --device_list $DEVICE_LIST --perdevice "$PERDEVICE" --task_dir "$(task_dir align)" \
      "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}" ;;
  aretomo3)
    EXE=(); [[ -n "${ARETOMO3_BIN:-}" ]] && EXE=(--exe "$(basename "$ARETOMO3_BIN")")   # its dir is on PATH (cryoet_activate)
    DEL=(); [[ "${ARETOMO_DELETE_INTERMEDIATE:-1}" == "1" ]] && DEL=(--delete_intermediate)
    run_warp WarpTools ts_aretomo3 --settings "$TS_SETTINGS" --angpix "$ALIGN_ANGPIX" --alignz "$ARETOMO_ALIGNZ" \
      --min_fov "$MIN_FOV" "${EXE[@]}" "${DEL[@]}" --device_list $DEVICE_LIST --perdevice "$PERDEVICE" \
      --task_dir "$(task_dir align)" "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}" ;;
  import)
    [[ -d "$ALIGNMENTS_DIR" ]] || { echo "ERROR: --method import needs --alignments DIR (existing)" >&2; exit 1; }
    [[ -n "$IMPORT_ANGPIX" ]] || { echo "ERROR: --method import needs --alignment-angpix (pixel size of the .xf shifts)" >&2; exit 1; }
    echo "--- import pre-check: .xf / .tlt / tomostar row counts (must agree, or tilts were dropped -> cutviews)"
    nbad=0; nseen=0; nmiss=0
    for t in "$TOMOSTAR_DIR"/*.tomostar; do
      s=$(basename "$t" .tomostar)
      [[ -z "$SERIES" || ",$SERIES," == *",$s,"* ]] || continue
      d="$ALIGNMENTS_DIR/$s"; nseen=$((nseen + 1))
      if [[ ! -f "$d/$s.xf" ]]; then echo "  $s: no $d/$s.xf (layout must be DIR/<series>/<series>.xf)"; nmiss=$((nmiss + 1)); continue; fi
      nxf=$(grep -c . "$d/$s.xf"); ntlt=$([[ -f "$d/$s.tlt" ]] && grep -c . "$d/$s.tlt" || echo none)
      nts=$(awk 'NF>2 && $1!~/^_/ && $1!~/^(loop_|data_)/' "$t" | wc -l)
      if [[ "$nxf" != "$nts" || "$ntlt" != "$nts" ]]; then
        echo "  $s: xf $nxf  tlt $ntlt  tomostar $nts  <- MISMATCH"; nbad=$((nbad + 1)); fi
    done
    echo "  $nseen series checked: $nmiss without .xf, $nbad with a row-count mismatch (tilts dropped by ts_import"
    echo "  --min_intensity also show up here). The .tlt angle ORDER must match the stack's tilt order as well."
    [[ $nseen -gt 0 && $nmiss -eq $nseen && "$DRY_RUN" -eq 0 ]] && { echo "ERROR: no series has an .xf under $ALIGNMENTS_DIR" >&2; exit 1; }
    run_warp WarpTools ts_import_alignments --settings "$TS_SETTINGS" --alignments "$ALIGNMENTS_DIR" \
      --alignment_angpix "$IMPORT_ANGPIX" --min_fov "$MIN_FOV" "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}" ;;
  *) echo "ERROR: unknown --method $METHOD" >&2; exit 1 ;;
esac
rc=$?; echo "rc=$rc"
[[ $rc -eq 0 ]] && record_arm "$METHOD"
if [[ -d "$PROC_OUT/tiltstack" && "$DRY_RUN" -eq 0 ]]; then
  echo "--- IMOD weighted-mean residual per series (nm; compare WITHIN a method only; many x the median = check the axis)"
  find "$PROC_OUT/tiltstack" -maxdepth 2 -name align.log 2>/dev/null | sort | while read -r L; do
    printf "  %-14s %s\n" "$(basename "$(dirname "$L")")" "$(grep -m1 'Residual error weighted mean' "$L" | awk '{print $(NF-1), $NF}')"
  done | head -200
  echo "--- IMOD tilt-axis warnings (the --override_axis signal):"
  grep -h -m1 'rotation angle seems' "$PROC_OUT"/tiltstack/*/align.log 2>/dev/null | sort | uniq -c | head -5
  if [[ "$METHOD" != aretomo3 || "${ARETOMO_DELETE_INTERMEDIATE:-1}" != 1 ]]; then
    echo "--- series with no .xf (alignment failed - exclude before CTF):"
    for d in "$PROC_OUT"/tiltstack/*/; do s=$(basename "$d"); [[ -f "$d/$s.xf" ]] || echo "  $s"; done
  fi
fi
[[ "$METHOD" == aretomo3 && "$DRY_RUN" -eq 0 ]] && echo "--- aretomo3: intermediates deleted=${ARETOMO_DELETE_INTERMEDIATE:-1}; confirm geometry changed with qc_summary.py --compare"
exit $rc
