# Eval baseline

`claude plugin eval . --runs 1 --ablation none --scaffold --trust-plugin --no-publish -j 4 --judge-model sonnet`
Mode: read-only tools (no Bash), generic fixture config (evals/_fixtures), no cluster data. Tests routing and the
quality of the advice/plan; execution is covered by tools/lint.py and the end-to-end test.

| date | commit | skill fired | behaviours passed | cost |
|---|---|---|---|---|
| 2026-11-21 | 652f1b2 | 33/33 | 129/150 (86%) | $10.45 |

Per skill: relion-refine 23/23, warptools-preprocess 24/27, cryoet-workflow 12/14, tomodrgn-run 17/19,
m-refine 17/21, teamtomo-preprocess 21/26, chimerax-figures 15/20. Single run per case: expect +-5% noise.
After this run: teamtomo stop rule narrowed (hand-off/status don't need TeamTomo installed).

Edit rubrics in `graders/criteria.md.src`, then `python3 tools/split_rubrics.py`. Fixture config:
`evals/_fixtures/config-generic.sh`, then `tools/make_eval_scaffolds.sh`.
