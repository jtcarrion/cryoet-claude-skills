#!/bin/bash
# Step 1 - create the frame-series and tilt-series .settings files (seconds, CPU).
# Paths inside a .settings resolve relative to the SETTINGS FILE's directory, not your cwd -> everything absolute.
# --exposure is NEGATIVE = dose per frame (positive = TOTAL dose: a per-frame value given positive silently
# under-weights the dose by the number of frames).
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
cd "$PROJ" || exit 1
mkdir -p "$WARP_DIR" "$TOMOSTAR_DIR"
for f in "$FS_SETTINGS" "$TS_SETTINGS"; do [[ -f "$f" ]] && { echo "ERROR: $f exists - refusing to overwrite" >&2; exit 1; }; done
GAIN=(); [[ -n "$GAIN_PATH" ]] && GAIN=(--gain_path "$GAIN_PATH" $GAIN_FLAGS)
set -x
WarpTools create_settings --output "$FS_SETTINGS" --folder_processing "$FS_PROC" --folder_data "$RAW_FRAMES" \
    --extension "$FRAME_EXT" --angpix "$ANGPIX" --exposure "-$DOSE_PER_FRAME" "${GAIN[@]}" $EER_FLAGS || exit $?
WarpTools create_settings --output "$TS_SETTINGS" --folder_processing "$TS_PROC" --folder_data "$TOMOSTAR_DIR" \
    --extension "*.tomostar" --angpix "$ANGPIX" --exposure "-$DOSE_PER_FRAME" "${GAIN[@]}" $EER_FLAGS \
    --tomo_dimensions "$TOMO_DIM" || exit $?
set +x
echo "--- check: absolute paths and exposure sign"
grep -hE 'DataFolder|ProcessingFolder|Exposure|PixelSize|GainPath' "$FS_SETTINGS" "$TS_SETTINGS" | sed 's/^ */  /' | head -20
