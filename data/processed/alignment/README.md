# Reproducing the evaluation

`evaluation_labels.csv` is the frozen label snapshot used for the published alignment results. It contains exactly 200 final judgments, 50 each for `kind`, `audience`, `maker`, and `namestyle`. Its only columns are `task_id`, `item_id`, `position`, `human_label`, and `verdict`. Positions preserve the evaluator's fixed sample order. The snapshot contains no rater identifiers, project names, profile information, notes, evidence URLs, or judgment timestamps.

From the repository root, with the project dependencies installed, run the following command.

```sh
python3 src/alignment_history.py
```

This reads the snapshot, the model checkpoint CSV files in this directory, and `accepted.json`. It makes no model calls. It writes `history.csv` and `figures/fig11_alignment_history.png` and `.pdf`. Use `--no-figure` to generate only the table. The script always prefers the published snapshot when it exists, even if private evaluator files are available. Private `tools/evaluator/tasks/*.json` and `data/processed/human_labels/*.csv` files are only a fallback when the snapshot is absent. Neither is required to reproduce the published scores.

## Scoring and selection

The headline agreement includes every final `label` judgment, including each task's **Cannot tell** option. It is exact label agreement, with a 95% Wilson interval using z = 1.96 and unweighted Cohen's kappa. Reject verdicts are excluded. There are none in this snapshot. Missing model predictions are excluded from the score denominator and counted explicitly in `missing`. `agreement_firm` is a supplementary measure excluding human Cannot tell judgments; it must not replace the headline agreement.

Positions 1–40 form the development set, displayed in four consecutive blocks of ten. These are summaries of predictions from the same prompt version, **not independently refitted cross-validation folds**. Prompts were developed using this working set, so its scores describe development agreement, not an unbiased estimate on new items. The original selection criterion was mean agreement across the four blocks of at least 0.80, with no block below 0.70. After unsuccessful revisions, the best available versions for Kind and Audience were selected below that threshold. `accepted.json` records the selected versions and decisions.

| Task | Model | Version | Development agreement | Minimum block | Final ten |
|---|---|---:|---:|---:|---:|
| Maker | claude-sonnet-5 | 2 | 33/40 (82.5%) | 70% | 6/10 (60%) |
| Namestyle | claude-sonnet-5 | 3 | 37/40 (92.5%) | 80% | 6/10 (60%) |
| Kind | claude-sonnet-5 | 3 | 31/40 (77.5%) | 60% | 3/10 (30%) |
| Audience | claude-sonnet-5 | 3 | 31/40 (77.5%) | 70% | 5/10 (50%) |

The final ten are positions 41–50. The history reports these scores only for the model/version selected in `accepted.json`. All selected checkpoints contain all 50 predictions. Earlier imported Kind v0 checkpoints already contain predictions for 9 of these ten items for Sonnet and all ten for GPT-4.1-mini. Their final-item scores are withheld from the generated history by the version-selection rule. This reporting restriction does not establish that those items were never previously evaluated, so the Kind result must not be described as an entirely untouched holdout. Earlier versions of the other tasks contain no final-ten predictions.

The figure plots pooled development agreement and its Wilson interval for each version, plus the selected version's final-ten score. The four-block selection statistic is also retained separately in `history.csv`. An incomplete historical checkpoint can have unequal block denominators.

## Public task configuration

`evaluation_tasks.json` preserves the executed option lists, sampling seeds,
stratification columns, allocations and sample sizes. It omits private evidence
links, item names, rater events and obsolete task-design notes. Item order and
final labels are preserved separately in `evaluation_labels.csv`. Both files
are sufficient for the notebook's evaluation and coverage tables.

The completed production runs are Kind v3 and Audience v3, each with 1,000 rows.
The Name-style v3 production checkpoint has 874 rows and is explicitly partial.
All four 50-item evaluation checkpoints are complete. These evaluation sets
and the larger production samples serve different purposes.
