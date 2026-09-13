# Saved model prompts

These files preserve the wording used in the recorded model runs. Version
numbers identify changes made during development. They are retained unchanged
so the evaluation can be checked against the instructions each model received.

The selected versions are Kind v3, Audience v3, Maker v2 and Name style v3.
Their model and selection records are in
`data/processed/alignment/accepted.json`. The first 40 reference items supported
development, with the final ten scored for the selected version. The methods
note explains the limits of that evaluation.

The notebook reads saved predictions. `src/align_judge.py` and `src/scale_label.py`
remain as acquisition code. Running them requires the appropriate private task
files and API credentials, and can incur model charges.
