#!/bin/bash
# Project constants for the WarpTools preprocessing chain. Written by the warptools-preprocess skill's
# scripts/init_project.sh; edit here, not in the step scripts. Sourced by every step script.
# Every acquisition value must come from the MDOC / image headers (inspect_mdoc.py), never from memory.
# Site values (partition, account, GPU format, software paths) are NOT here: they come from the cryoet-skills
# config, loaded by warp_env.sh through the copy of the shared library in scripts/_lib/.

export PROJ=__PROJ__                       # project root (absolute)
export RAW_FRAMES=__RAW_FRAMES__           # folder of movies/tilt images (absolute); for pre-split stacks, the split tilts
export FRAME_EXT="__FRAME_EXT__"           # e.g. "*.tif", "*.eer", "*.mrc"
export MDOC_DIR=__MDOC_DIR__               # folder of .mdoc files (absolute; copies if they needed rewriting)
export HAVE_FRAMES=__HAVE_FRAMES__         # 1 = movies (fs_motion_and_ctf); 0 = single images per tilt (fs_ctf only)

# --- acquisition (inspect_mdoc.py; confirmed with the user) ---
export ANGPIX=__ANGPIX__                   # unbinned A/px (PixelSpacing; confirm against the image header)
export VOLTAGE=__VOLTAGE__                 # kV
export CS=__CS__                           # mm (from the data / facility; Cs-corrected scopes are ~0.01)
export AMPLITUDE=__AMPLITUDE__             # amplitude contrast
export DOSE_PER_FRAME=__DOSE_PER_FRAME__   # e/A^2 per FRAME, positive here; create_settings gets it NEGATED
                                           # (negative --exposure = per frame; positive = TOTAL dose -> silent under-weight)
export DOSE_PER_TILT=__DOSE_PER_TILT__     # e/A^2 per TILT, for ts_import --tilt_exposure
export NFRAMES=__NFRAMES__                 # frames (or EER groups) per movie -> temporal nodes of M_GRID
export TILT_AXIS=__TILT_AXIS__             # deg, passed to ts_import --override_axis when OVERRIDE_AXIS=1
export OVERRIDE_AXIS=__OVERRIDE_AXIS__     # 1 if the MDOC axis is wrong (references/pitfalls.md, "tilt axis")
export TILT_OFFSET=__TILT_OFFSET__         # deg pre-tilt to subtract (ts_import --tilt_offset), 0 if none
export TS_IMPORT_DONT_INVERT=__TS_IMPORT_DONT_INVERT__  # 0 = Warp default (invert to IMOD's convention; standard frame);
                                           # 1 = ts_import --dont_invert (keep MDOC sign; mirrors the geometry) ONLY to match
                                           # an existing project imported that way. Never mix the two in one comparison
export GAIN_PATH="__GAIN_PATH__"           # absolute, or empty
export GAIN_FLAGS="__GAIN_FLAGS__"         # e.g. "--gain_flip_y" / "--gain_transpose"; verify on one averaged movie
export EER_FLAGS="__EER_FLAGS__"           # e.g. "--eer_ngroups 8" for EER, else empty
export TOMO_DIM=__TOMO_DIM__               # XxYxZ in UNBINNED px; X,Y = true image dims (header), Z = generous thickness

# --- choices (the questions in SKILL.md; record the answer and why) ---
export DEFOCUS_MIN=__DEFOCUS_MIN__         # um; bracket the MDOC TargetDefocus range
export DEFOCUS_MAX=__DEFOCUS_MAX__
export CTF_RANGE_HIGH=__CTF_RANGE_HIGH__   # A; 7 (the 4 A default is fragile on low-dose tilts)
export CTF_RANGE_LOW=__CTF_RANGE_LOW__     # A; ts_ctf --range_low
export CTF_WINDOW=__CTF_WINDOW__           # px; ts_ctf --window
export M_GRID=__M_GRID__                   # fs motion grid, 1x1xNFRAMES
export C_GRID=2x2x1                        # fs defocus grid; ts_defocus_hand needs >= 2x2x1
export MIN_INTENSITY=__MIN_INTENSITY__     # ts_import: drop tilts darker than this x cos(angle) x 0-tilt (0.3 = grid bars)
export ALIGN_METHOD=__ALIGN_METHOD__       # patches | fiducials | aretomo3 | import
export ALIGN_ANGPIX=__ALIGN_ANGPIX__       # A/px of the alignment stacks (10 usual)
export PATCH_SIZE=__PATCH_SIZE__           # A, patches only (Warp default 500)
export FIDUCIAL_NM=__FIDUCIAL_NM__         # nm, fiducials only (MEASURE the beads)
export N_BEADS_TARGET=__N_BEADS_TARGET__   # fiducials only
export ARETOMO_ALIGNZ=__ARETOMO_ALIGNZ__   # A, aretomo3 only (~ sample thickness; 0 = AreTomo3 estimates it)
export ARETOMO_DELETE_INTERMEDIATE=__ARETOMO_DELETE_INTERMEDIATE__  # 1 = --delete_intermediate (stacks: tens of GB/run)
export MIN_FOV=__MIN_FOV__                 # drop tilts left with < this fraction of the FOV after shifts
export RECON_ANGPIX=__RECON_ANGPIX__       # A/px of tomograms (10 usual)
export INVERT_TOMOGRAMS=__INVERT_TOMOGRAMS__  # 0 = --dont_invert (dark density, for looking); 1 = inverted (template matching)

# --- layout (do not change after the first run) ---
export WARP_DIR=$PROJ/warp
export FS_SETTINGS=$WARP_DIR/warp_frameseries.settings
export TS_SETTINGS=$WARP_DIR/warp_tiltseries.settings
export FS_PROC=$WARP_DIR/warp_frameseries
export TS_PROC=$WARP_DIR/warp_tiltseries   # the BASELINE processing folder; variants live at $PROJ/<name>/
export TOMOSTAR_DIR=$WARP_DIR/tomostar
