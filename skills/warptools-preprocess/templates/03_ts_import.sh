#!/bin/bash
# Step 3 - build .tomostar files from the MDOCs (seconds, CPU).
# --tilt_exposure is per TILT. ts_import ignores the MDOC ExposureDose and orders dose by DateTime x --tilt_exposure,
# so every MDOC needs DateTime. Default (TS_IMPORT_DONT_INVERT=0) = Warp's default: angles inverted to IMOD's
# convention, the frame standard Warp projects and external coordinates/maps assume. --dont_invert HERE
# (TS_IMPORT_DONT_INVERT=1) keeps the MDOC sign and mirrors the geometry: only to match a project imported that way. It is NOT the contrast flag of ts_reconstruct. The defocus-hand check
# (step 5) follows whichever convention you pick; imported .tlt files later overwrite the angles, so they must share
# this sign and offset. Record the choice and never mix tomostars imported both ways in one comparison.
# --override_axis only when the MDOC axis is wrong: a transposed MDOC ImageSize (inspect_mdoc.py warns), a weighted
# residual many times the usual ~1 nm, or IMOD's "rotation angle seems to be closer to ..." in align.log.
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
cd "$PROJ" || exit 1
[[ -n "$(ls -A "$TOMOSTAR_DIR" 2>/dev/null)" ]] && { echo "ERROR: $TOMOSTAR_DIR is not empty" >&2; exit 1; }
AX=(); [[ "$OVERRIDE_AXIS" == "1" ]] && AX=(--override_axis "$TILT_AXIS")
OFF=(); [[ "${TILT_OFFSET:-0}" != "0" ]] && OFF=(--tilt_offset "$TILT_OFFSET")
INV=(); [[ "${TS_IMPORT_DONT_INVERT:-0}" == "1" ]] && INV=(--dont_invert)
set -x
WarpTools ts_import --mdocs "$MDOC_DIR" --pattern "*.mdoc" --frameseries "$FS_PROC" --tilt_exposure "$DOSE_PER_TILT" \
    --min_intensity "$MIN_INTENSITY" "${INV[@]}" "${AX[@]}" "${OFF[@]}" --output "$TOMOSTAR_DIR" "$@"
rc=$?
set +x
[[ $rc -eq 0 ]] || { echo "ERROR: ts_import failed (rc=$rc)" >&2; exit $rc; }
n=$(find "$TOMOSTAR_DIR" -maxdepth 1 -name '*.tomostar' | wc -l)
echo "--- check: $n tomostar files; tilts per series (should match the MDOCs minus dropped tilts):"
for f in $(find "$TOMOSTAR_DIR" -maxdepth 1 -name '*.tomostar' | sort | head -5); do
  printf "  %-28s %s tilts\n" "$(basename "$f")" "$(awk 'NF>2 && $1!~/^_/ && $1!~/^(loop_|data_)/' "$f" | wc -l)"; done
