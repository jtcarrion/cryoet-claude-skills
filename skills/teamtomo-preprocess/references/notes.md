# teamtomo-workflows: notes, traps, lessons

Read from `teamtomo_workflows/` at repo commit caf1f46. Re-check after upgrading the checkout.

## How batch.py behaves
- `load_config`: DEFAULTS <- YAML <- CLI overrides; unknown keys are errors; relative `warp_project`/`output.root`
  resolve against the CONFIG FILE's folder. Exactly one of `input.warp_project` / `input.stacks`.
- Discovery (Warp project): every `warp_tiltseries/*.xml` -> name = stem; images = `warp_frameseries/average/<movie>.mrc`
  (movie names from the XML), stack = `warp_tiltseries/tiltstack/<name>/<name>.st`, angles/dose/axis prior from
  `tomostar/<name>.tomostar`, pixel size + Tomo dims from `warp_tiltseries.settings`.
  It reads ImageDimensionsAngstrom for EVERY requested series - one bad XML aborts discovery for the whole batch.
- Resume: `is_done` = `<root>/<series>/run.json` status `done`. A killed job leaves `running` -> redone next time.
- A failing series is logged (run.json status failed + error) and the batch continues; batch.py exits 1 if any failed.
- `batch_summary.csv` is appended once per batch at its END (killed batches leave no rows) - use status.py instead.
- Batch log name = `logs/batch_<YYYYmmdd_HHMMSS>.log` - two workers started in the same second would share it
  (run_shards staggers 3 s).
- Tomograms are written float32 (`write_mrc`), voxel size in the header.
- TSA writes `<series>.xml` = the input XML with AxisOffsetX/Y, AxisAngle, Angles (and VolumeDimensionsAngstrom Z)
  replaced; CTF, dose, movie list, UseTilt and EVERY Grid* (image warp, stage angles, volume warp) kept from the template.

## Traps
- **Pre-2.0 Warp XMLs** lack `ImageDimensionsAngstrom` -> `TypeError: 'NoneType' object is not iterable` in discovery.
  Check: `grep -L ImageDimensionsAngstrom <proj>/warp_tiltseries/*.xml`. project_view.py adds it (average W,H x
  PixelSize) and `VolumeDimensionsAngstrom` (settings Dimensions x PixelSize) - the values a current MCore writes
  itself. The volume canvas may be transposed relative to the image; the view copies Warp's convention, not a guess.
- **Series without averages** (an XML but no tomostar/averages) are left out of a view, with a warning.
- **Variant folders** are not projects: teamtomo needs the fixed folder names -> project_view.py `--processing`.
- **Hand**: TSA cannot tell axis from axis + 180 deg (repo README). Check with WarpTools ts_defocus_hand after
  importing, and check map hand against a reference downstream. A series whose TSA axis differs ~180 deg (or > 5 deg)
  from the batch median is flagged by status.py.
- **Inherited M products ride along in TSA XMLs** (template copy) and are frame-locked to the OLD alignment. Symptom:
  a map refined with them is far worse than without. make_warp_arm.py zeroes GridMovement/GridAngle/GridVolumeWarp by
  default. Cs/odd Zernikes are reported, not changed: make a clean copy with
  `scripts/_lib/reset_ctf_cs.py <XMLs> --out_dir <copy> --zero_zernike_odd [--cs_mm N]` and pass it as `--clean-template`.
- **xml_to_tomograms applies GridMovement** (`apply_local_shifts: true`) like ts_reconstruct, so an M image warp in the
  XMLs is used. `make_config.py --no-local-shifts` reconstructs without it.
- **compare_tomograms.py is only a teamtomo check when the XML is unchanged since ts_reconstruct**: if M or an import
  rewrote the XMLs after the Warp tomogram was made, a low |corr| says nothing about teamtomo. Negative corr =
  opposite contrast convention (e.g. the Warp tomogram was made inverted).

## Install (env/install_env.sh)
- `requirements.txt` pins the TeamTomo packages to a teamtomo/teamtomo commit, and two of them
  (`torch-tilt-series`, `torch-cubic-spline-grids`) to a fork until teamtomo/teamtomo#159 (`from_warp_xml`) is merged.
  The fork pin is upstream's, not this skill's: the workflows need `from_warp_xml`. The fork's packages pull their
  siblings by the fork URL, so uv reports "conflicting URLs"; passing every git pin of requirements.txt as an
  `--override` fixes it. The installer derives that list from requirements.txt, so it adapts when the fork goes.
- **uv-MANAGED Python** (`--python-preference only-managed`): a distro Python without Python.h makes triton
  (torch.compile, used in TSA) fail at runtime with "fatal error: Python.h" on every TSA series while
  xml_to_tomograms works. The installer asserts Python.h exists.
- PyTorch wheel: `--torch-index` / `TORCH_CUDA_INDEX`. If `torch.cuda.is_available()` is False on a GPU node, the
  wheel's CUDA is newer than the driver: reinstall with an older `.../whl/cuXXX` index.
- Keep `UV_CACHE_DIR` / `UV_PYTHON_INSTALL_DIR` on large storage (the installer puts them under `--dest`).

## Arm hand-off (make_warp_arm.py)
- **TSA keeps the NOMINAL tilt angles**; eTomo/AreTomo may refine a tilt-angle offset of several degrees. Different
  3D frame -> particle positions from another alignment land tens to hundreds of A off in a TSA arm. Coordinates do
  NOT carry over between alignments; transfer them through Warp's projection model or re-pick.
- A sanity check that the TSA solution matches another aligner's: per-tilt offsets should correlate strongly (>0.95)
  and the axis agree. A sign flip or ~180 deg axis means a mirrored/hand-flipped solution.
- **XML DataDirectory overrides the settings DataFolder** (Warp's TiltSeries.cs). An arm used as a `--variant` inside
  the SAME project can keep it; a standalone arm with its own tomostar/frameseries must rewrite it, or it silently
  reads the original project's frames.
- Clean build: graft only Angles/AxisAngle/AxisOffsetX/Y onto a clean (nominal-Cs, no odd Zernike, no M grids)
  XML of the same series, instead of cleaning the contaminated template - and build the control arm the same way,
  or the production arm keeps an M image-warp advantage the TSA arm cannot have.
- warptools-preprocess order on the arm: ts_defocus_hand --check -> ts_ctf -> ts_reconstruct, with the same
  `--variant <arm>` (i.e. `--input_processing/--output_processing <PROJ>/<arm>`) on every step.

## Upstream bug: deselected tilts (UseTilt=False) crash xml_to_tomograms
- load_images loads one image per XML movie and warp_xml_parameters returns dose/defocus for ALL tilts, while
  from_warp_xml keeps only UseTilt=True tilts -> "size of tensor a (N_used) must match ... (N_all)".
  Affected series are those with any `False` inside the XML's `<UseTilt>` element (tilts excluded in Warp).
- run_shards.sbatch runs scripts/batch_usetilt.py (batch.py + selection by ts.image_indices, as ts_reconstruct skips
  UseTilt=False tilts); identity for series with every tilt enabled. It monkeypatches the PRIVATE
  `teamtomo_workflows.workflows._reconstruct` and checks its name and signature first: if the repo changed, it exits
  with a message instead of running unpatched. `PLAIN_BATCH=1` = the repo's batch.py. Drop the wrapper once fixed upstream.
- TSA on such series: the TSA path aligns ALL images it loads (it does not read UseTilt) - deselected tilts take part
  in the alignment. Untested; check the result before relying on TSA there.

## Job-script lessons
- sbatch spools the script at SUBMIT time: fixing run_shards.sbatch does not fix jobs already pending - cancel + resubmit.
- Some sites cap GPUs per user per QoS: several multi-GPU jobs then queue one after another; prefer one bigger job.
- Typed gres strings (`gpu:<model>:N`) can pend forever on sites whose nodes advertise only `gpu:N`; the gres format
  is the config's `SLURM_GPU_GRES_FMT`, never written by hand.
- Login-node hygiene: building image-warp grids on CPU for every series of a big project takes many CPU-minutes.
  Keep validation light: `plan_shards.py --dry-run` only parses XMLs (seconds).
