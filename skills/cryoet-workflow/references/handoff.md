# `cryoet_project.json` -- the hand-off record

One JSON file at the project root, edited only through `scripts/_lib/project_state.py` (vendored into every skill) (atomic writes). Every stage
reads its inputs from here and records its outputs here, so a later stage (or a later session) never has to guess.
Paths are absolute. Keys below are conventions, not enforced; add fields freely.

| key | written by | read by | meaning |
|---|---|---|---|
| `dataset`, `acquisition.{angpix,kv,cs,amp,dose_per_tilt,tilt_axis}` | director init / warptools-preprocess | all | microscope + acquisition facts actually used (after any override, e.g. a corrected tilt axis) |
| `stages.<skill>.status` | each stage | director | `planned` / `submitted` / `running` / `done` / `failed` |
| `stages.<skill>.jobs` | each stage | director | Slurm job ids (or `local:<pid>`) |
| `stages.warptools-preprocess.warp_project` | warptools-preprocess | teamtomo, relion, m | the Warp processing dir (holds `warp_tiltseries/`, settings files) |
| `stages.warptools-preprocess.arms` | warptools / teamtomo | relion, m | list of `{name, processing_dir, aligner}` alignment variants; `default_arm` |
| `stages.warptools-preprocess.tomograms` | warptools / teamtomo | picking, figures | `{arm: {dir, angpix}}` |
| `decisions[]` | any | all | `{what, choice, evidence, date}` e.g. defocus hand, final-map mirror, rejected series |
| `particle_sets[]` | user / picking / tomodrgn-run | relion-refine, m-refine | `{name, star, coords_angpix, n_particles, source, parent}` |
| `refinements[]` | relion-refine | m-refine, tomodrgn-run, figures | `{name, dir, data_star, half1, half2, mask, angpix, box, n_particles, resolution_A, fsc_criterion}` |
| `m_populations[]` | m-refine | relion-refine (postprocess), figures | `{name, population, source_refinement, rounds_dir, best_round, resolution_A}` (always a CLONE) |
| `tomodrgn[]` | tomodrgn-run | relion-refine, m-refine | `{name, train_dir, epochs, analyze_dirs, selected_classes, selection_star}` |
| `references[]` | director intake / relion-refine | relion-refine (hand test), m-refine (`GUARD_REF`, kind external), figures | `{name, path, angpix, source (e.g. EMDB id), hand_vs_ours: same|mirrored|unknown, lowpass_A}` - external maps; an independent guard for M |
| `maps[]` | relion-refine, m-refine | chimerax-figures | `{name, map, half1, half2, locres, angpix, hand_flipped}` |
| `figures[]` | chimerax-figures | - | `{name, bundle_dir, cxc}` |
| `open_questions[]` | any | director (re-asked every turn) | `{q, since, stage}` - unanswered questions and proposed fixes |

Each stage skill's SKILL.md has an "Inputs / Outputs (handoff)" table with its exact files; this table is the union.
