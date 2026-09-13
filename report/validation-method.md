# Validation of the classification instruments

The final evaluation protocol and reproduced scores are documented in
[`data/processed/alignment/README.md`](../data/processed/alignment/README.md).
The four completed tasks are Kind, Audience, Maker and Name style, with 50 final
human judgments each. The frozen 200-row label snapshot is the reference.

The executed category lists, sampling seeds, strata and allocations are in
[`evaluation_tasks.json`](../data/processed/alignment/evaluation_tasks.json).
These preserve the actual task configuration. In particular, Kind used the 23
adapted dictionary families, a generic-name option and Cannot tell, rather than
the full Google Play category list originally considered.

The selected checkpoints are Kind v3, Audience v3, Maker v2 and Name style v3,
all with Claude Sonnet 5. The first 40 items were used for prompt development.
The final ten are scored for the recorded selected version. Development blocks
are not independently refitted cross-validation folds. Imported Kind baselines
already contain final-item predictions, so a wholly untouched Kind holdout
cannot be established. Cannot tell is included in headline agreement.

Final agreement is 3/10 for Kind, 5/10 for Audience, 6/10 for Maker and 6/10 for
Name style. Wilson intervals and Cohen's kappa are reproduced by the notebook.
Small final sets, one human rater, and differing human/model evidence limit what
these scores establish. The separate legacy 105-row dictionary-validation sheet
has no completed answers and does not validate the dictionary.

Completed production samples contain 1,000 Kind labels and 1,000 Audience labels.
The Name-style checkpoint contains 874 of the requested 1,000 labels and is
reported as incomplete. Production files describe instrument outputs, subject
to weak final agreement. They do not establish population category shares.
The maker score is exploratory. Its reference includes no positively identified
non-programmers, and Cannot tell is not evidence of a non-professional maker.

Reproduction reads saved data only. Run `python tools/run_notebook.py` from a
clone after installing `requirements.txt`. No model calls, API credentials,
private evaluator tasks or raw account-lookup files are needed.
