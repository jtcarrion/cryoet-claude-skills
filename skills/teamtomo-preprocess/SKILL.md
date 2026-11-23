---
name: teamtomo-preprocess
description: Run teamtomo-workflows (TeamTomo / PyTorch) tilt-series pipelines on a Slurm cluster or a GPU workstation - XML -> tomograms (reconstruct from an existing Warp/M alignment, WarpTools-compatible) and TSA -> tomograms (TeamTomo tilt-series alignment + CTF + reconstruction, optionally written back as Warp XMLs) - as one multi-GPU job sharded over all GPUs, with install, config generation, Warp-project views for variant folders and pre-2.0 Warp XMLs, resume, per-series status from run.json, provenance manifests, comparison with WarpTools tomograms, and an optional hand-off of TeamTomo alignments into a WarpTools alignment arm. Use this whenever the user mentions teamtomo, teamtomo-workflows, batch.py, TeamTomo/torch alignment or reconstruction, "XML to tomograms", "TSA to tomograms", wants tomograms from Warp XMLs without WarpTools, or wants to align tilt series with TeamTomo - even if they just say "run the teamtomo workflow on this project".
---

# TeamTomo preprocessing (teamtomo-workflows)

Wraps the public repo [teamtomo-workflows](https://github.com/jtcarrion/teamtomo-workflows) (`batch.py`, two workflows)
without ever editing it: this skill adds config generation with data-management rules, one multi-GPU job sharded over
every GPU, resume, status from each series' `run.json`, provenance manifests, a fix for deselected tilts, Warp-project
views, and an optional hand-off of TeamTomo alignments into a WarpTools alignment arm. Sister skill:
warptools-preprocess (Warp project layout, variants, hand, ts_ctf). Read `references/notes.md` before a non-routine
run (TSA hand, old XMLs, variant folders, outputs, timing).

## Setup check

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").


```bash
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh" || exit 2
cryoet_have teamtomo || echo "NOT INSTALLED"
cryoet_require TEAMTOMO_REPO TEAMTOMO_ENV
cryoet_activate teamtomo && export TEAMTOMO_REPO      # helpers read TEAMTOMO_REPO
S="${CLAUDE_SKILL_DIR}/scripts"
```
- **Not installed** (`cryoet_have teamtomo` fails, or - read from the config file - `TEAMTOMO_REPO` or
  `TEAMTOMO_ENV` is empty) and the user wants to RUN a workflow (xml_to_tomograms / tsa_to_tomograms): STOP before
  planning the run. Working on outputs that already exist - `status.py`, `project_view.py`, `make_warp_arm.py`
  (hand-off to warptools-preprocess) - is stdlib-only and does NOT need TeamTomo installed: carry on with those.
  For a run: tell the user how to install, then wait. Do not try another tool instead.
  `bash "${CLAUDE_SKILL_DIR}/env/install_env.sh" --dest <software dir> [--torch-index <PyTorch wheel index>]`
  This clones the repo, builds a uv venv (uv-managed Python 3.12), and prints the two config lines (`TEAMTOMO_REPO`,
  `TEAMTOMO_ENV="venv:<env>"`). Ask which folder (large storage, not a small home quota) and which CUDA wheel index
  (`TORCH_CUDA_INDEX`, empty = pip's default; match the driver's "CUDA Version" in `nvidia-smi`). It needs internet:
  run it where git/pip work, and show the command before running it. Plain `pip install -r requirements.txt` fails
  on conflicting git URLs; the installer works around that (see notes.md).
- Needs a CUDA GPU for the real runs. `SITE_NOTES_FILE` (if set) has site rules: read it before submitting.
- No config at all: the cryoet-workflow skill's setup writes one.

## Inputs / Outputs (handoff)

`<PROJ>` = the dataset's project root as laid out by warptools-preprocess.

| artifact | path pattern | produced / consumed | by / for which skill |
|---|---|---|---|
| Warp project (baseline) | `<PROJ>/warp/` (`warp_tiltseries/*.xml`, `warp_frameseries/average/`, `tomostar/`, `warp_tiltseries.settings`) | consumed (read-only), `--warp-project <PROJ>/warp` | warptools-preprocess |
| Warp variant folder (alignment arm) | `<PROJ>/<variant>/*.xml` (made with `--output_processing <PROJ>/<variant>`) | consumed via a view: `project_view.py --base-project <PROJ>/warp --processing <PROJ>/<variant>` | warptools-preprocess |
| Plain stacks | `<dir>/*.st` + `.rawtlt`/`.tlt` | consumed (`--stacks`) | user |
| Warp-project view | `<PROJ>/teamtomo/views/<name>/` (symlinks + patched XML copies) | produced | this skill |
| Run config | `<PROJ>/teamtomo/<workflow>_<tag>/config.yaml` | produced | this skill |
| Tomograms + per-series record | `<root>/<series>/{<series>_<px>Apx.mrc, run.json, alignment.json, ctf.json, <series>.xml}` | produced | viewing / picking; TSA XMLs -> make_warp_arm |
| Status / provenance | `<root>/status.csv`, `<root>/shards/<job>/manifest.json`, `<root>/logs/` | produced | cryoet-workflow director |
| TeamTomo alignment arm (optional) | `<PROJ>/<arm>/<s>.xml` + `processed_items.json` + `ARM_PROVENANCE.json` (and `<PROJ>/<arm>_ctrl/`) | produced | warptools-preprocess `--input_processing/--output_processing <PROJ>/<arm>` (same `--variant <arm>` for every step), then relion-refine |

`<root>` = `<PROJ>/teamtomo/<workflow>_<tag>`. Director state to keep: the Warp project or view path, the root/tag
per config, job ids, and the arm/control pair if built. If `<PROJ>/cryoet_project.json` exists, record each run:
`python3 "$S/_lib/project_state.py" add <PROJ> teamtomo.runs '{"workflow": "...", "root": "<root>", "job": "<id>"}'`
(and `teamtomo.arms` for a built arm/control pair).

## Which workflow

| input | workflow | what it does | time / series (1 GPU) |
|---|---|---|---|
| Warp project with an alignment in its XMLs (WarpTools, M, imported .xf) | `xml_to_tomograms` | reconstructs with Warp's conventions (should match ts_reconstruct, corr >= 0.99, when the XML is unchanged) | seconds + I/O |
| tilt images + angles, no trusted alignment (Warp project or plain `.st` + angle files) | `tsa_to_tomograms` | blind tilt-axis search, coarse alignment, projection matching, CTF, reconstruction | ~1-2 min |

## Ask before running

1. Input: the Warp project (`<PROJ>/warp`), a variant folder (-> view), or plain stacks (glob + angle files + pixel
   size + thickness). Never guess the pixel size: read it from `warp_tiltseries.settings` or ask.
2. Workflow, series (all or a list), output voxel size (default 10 A), thickness (default: the Warp Tomo Z).
3. TSA only: axis prior (`null` blind / `tomostar` / degrees), `flip_hand` (TeamTomo CANNOT decide the hand), CTF on/off.
4. GPUs and time: number of GPUs (1 worker per GPU, one node; at most `SLURM_MAX_GPUS_PER_JOB`) and wall time
   (default 04:00:00 - the job header's value). Before a maintenance window (site notes, or the user says so) submit a
   shorter time instead: resubmitting resumes, so nothing is lost.
5. Outputs stay in `<PROJ>/teamtomo/`. Building a WarpTools arm from TSA XMLs is OPTIONAL - only on request.

## Data management (why it is laid out this way)

```
<PROJ>/teamtomo/
  views/<name>/                       read-only symlink "projects" (variant folders, patched old-build XMLs)
  <workflow>_<tag>/                   ONE output root per configuration (tag says what differs: tsa_blind, xml_10A ...)
    config.yaml                       the run's config (make_config.py refuses to reuse a tag with a different config)
    <series>/                         teamtomo's own: <series>_<px>Apx.mrc, run.json, alignment.json, ctf.json, <series>.xml
    batch_summary.csv, logs/          teamtomo's own (one batch log + shard<i>_<job>.out per GPU)
    shards/<job>/                     which series ran on which GPU + manifest.json (repo commit, versions, config hash)
    slurm/                            job stdout
    status.csv                        rebuilt from every run.json (authoritative; batch_summary only has finished batches)
```
Never write into a Warp processing folder (`warp_tiltseries*`, `warp_frameseries*`, `tomostar`) - make_config.py
refuses. teamtomo only READS the Warp project, so running it never contaminates Warp metadata.
Resume = resubmit the same config: series whose run.json says `done` are skipped and not re-sharded; `running` means
interrupted (job killed) and is redone. `--overwrite` redoes everything - use a new tag instead when settings change.

## Procedure

1. **Preflight** (seconds; parse-only, fine on a login node):
   - Variant folder or pre-2.0 XMLs -> view:
     `python "$S/project_view.py" --base-project <PROJ>/warp [--processing <PROJ>/<variant>] --out <PROJ>/teamtomo/views/<name>`
     (make_config.py detects a missing `ImageDimensionsAngstrom` and says so).
   - Config: `python "$S/make_config.py" --workflow xml_to_tomograms --warp-project <PROJ>/warp|<view> --project-root <PROJ> --tag <tag> [--series ..] [--recon-px 10]`
     TSA adds `[--axis-prior tomostar] [--flip-hand] [--no-ctf] [--align-px 10]`; plain stacks use
     `--stacks '<glob>' --stack-px <A> --thickness-A <A> [--tilt-angles '<pattern>']`.
   - Plan: `python "$S/plan_shards.py" --config <root>/config.yaml --n-shards <GPUs> --outdir /dev/null --dry-run`
     (series found, already done, disk estimate, shard balance by tilt count).
2. **Smoke** one series first on a new dataset/config (`--series <one>`, 1 GPU) and look at the tomogram + run.json.
3. **Submit** (show the lines to the user first):
   ```bash
   CRYOET_SBATCH_OPTS="-o <root>/slurm/teamtomo_%j.out --cpus-per-task=$((8*NGPU)) --mem=$((SLURM_MEM_PER_GPU_GB*NGPU))G" \
     cryoet_submit gpu <NGPU> 04:00:00 "$S/run_shards.sbatch" <root>/config.yaml [--series "a b"] [--overwrite]
   ```
   Partition, account, QoS and the gres string come from the config (`cryoet_submit`); never type them. With
   `SCHEDULER=none` the same call runs locally in the background on the visible GPUs. The job runs
   `batch_usetilt.py` (= batch.py + a fix for UseTilt=False tilts, which crash the repo's xml_to_tomograms - see
   notes.md; `PLAIN_BATCH=1` runs the unpatched batch.py). One worker per GPU (CUDA_VISIBLE_DEVICES per shard),
   staggered 3 s so batch logs do not collide. If the scheduler does not set CUDA_VISIBLE_DEVICES the job warns and
   uses one GPU (`--ngpu N` to override).
4. **Monitor**: background-wait on `squeue -h -j <id>`; progress = count of `<root>/*/run.json` and
   `tail <root>/logs/shard*_<job>.out`; at the end the job prints `status.py` (done / failed / interrupted, s/series,
   GB, TSA axis outliers). Exit code is non-zero if any series failed.
5. **QC**: `python "$S/status.py" --root <root>`. For xml_to_tomograms vs an existing WarpTools tomogram at the same
   pixel size: `compare_tomograms.py --root <root> --warp-recon <PROJ>/warp/warp_tiltseries/reconstruction` - it
   holds ~6 tomogram copies in RAM, so run it in a CPU job
   (`sbatch $(cryoet_sbatch_args cpu 0 01:00:00) --mem=32G --wrap "python $S/compare_tomograms.py ..."`) or on a
   workstation. Expect >= 0.99 when the XML is unchanged since ts_reconstruct; negative = opposite contrast
   convention. TSA: axis angle spread, thickness, ctf.json flagged fits, and look at the tomograms (hand is undecided).
6. **Optional WarpTools arm** (only when asked) - see `references/notes.md` "Arm hand-off":
   `python "$S/make_warp_arm.py" --root <tsa root> --dest <PROJ>/<arm> [--control-dest <PROJ>/<arm>_ctrl --clean-template <XML folder>] [--cs <mm>] --dry-run`
   then without `--dry-run`. It grafts ONLY Angles/AxisAngle/AxisOffsetX/Y from the TSA XML onto a clean template,
   zeroes the frame-locked M grids (image warp, stage angles, volume warp), sets MagnificationCorrection to identity,
   and (with `--control-dest`) builds a control arm cleaned identically with the original alignment, verified to
   differ only in those four fields. The clean-template check compares Cs with the nominal Cs (`--cs`, else the
   source project's settings, else `MICROSCOPE_CS_MM`); make a clean template with
   `python3 "$S/_lib/reset_ctf_cs.py" <PROJ>/warp/warp_tiltseries --out_dir <PROJ>/teamtomo/clean_xml --zero_zernike_odd`.
   - **Coordinates do not carry over** between alignments (TSA keeps nominal tilt angles; other aligners may refine a
     tilt offset): transfer particles through the projection model or re-pick, per arm.
   - Then warptools-preprocess on BOTH arms identically, same `--variant <arm>` for every step:
     ts_defocus_hand --check (TeamTomo cannot decide the hand; settle it BEFORE ts_ctf) -> ts_ctf (mandatory after a
     new alignment) -> ts_reconstruct -> export -> relion-refine; rank arms by downstream STA resolution. Two series are
     a pipeline smoke only; a real comparison needs ~16+ series.

## General rules

- Wrap, never edit, the teamtomo-workflows checkout; record its commit (plan_shards writes it into manifest.json and
  warns if the checkout is dirty).
- One output root per configuration; a changed setting gets a new `--tag`, never `--overwrite` into a mixed root.
- `status.py` (from run.json) is the truth; `batch_summary.csv` misses killed batches.
- TeamTomo cannot decide the hand: if a series' TSA axis is ~180 deg (or > 5 deg) from the batch median, status.py
  flags it; check the hand with WarpTools ts_defocus_hand and downstream against a reference map.
- Deselected tilts (UseTilt=False) crash upstream xml_to_tomograms with a tensor-size mismatch; the wrapper fixes it
  and stops loudly if the private function it patches changes.
- Pre-2.0 Warp XMLs (`TypeError: 'NoneType' object is not iterable` in discovery) need a view; never patch the source.
- sbatch spools the script at submit time: fixing run_shards.sbatch does not fix a pending job - cancel and resubmit.
- Keep the login node light: preflight only parses XMLs; anything that loads tomograms or averages goes in a job.

## Resources

1 GPU per shard; host RAM ~ (number of tilts x full-size average, float32) per worker during TSA/CTF (a 41-tilt
5760x4092 series is ~4 GB); 8 CPUs and `SLURM_MEM_PER_GPU_GB` per GPU is comfortable. Tomogram disk: float32,
(X/px)(Y/px)(Z/px) x 4 B per series (plan_shards prints the estimate).

## References

- `references/notes.md` - how batch.py behaves, traps, install details, arm hand-off, job-script lessons.
- `references/worked-example-empiar10499.md` - public validation numbers (EMPIAR-10499).
