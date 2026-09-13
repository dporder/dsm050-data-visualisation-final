# Classifying short project names

A project name provides little text from which to infer purpose. The study uses
two instruments to examine what that text can support. The dictionary applies
ordered word rules, while the model chooses from a fixed set of answers.

## The dictionary

Dictionary-based content analysis requires a stated codebook and validation in
the domain where it is used. Grimmer and Stewart discuss the limits of automatic
text analysis and the need to validate its measures (2013,
[doi:10.1093/pan/mps028](https://doi.org/10.1093/pan/mps028)). The local dictionary
contains 23 adapted software families. Google Play's categories supplied a
starting point, with app-store classification research providing context
(Martin et al., 2017,
[doi:10.1109/TSE.2016.2630689](https://doi.org/10.1109/TSE.2016.2630689)).

The rules and local additions are visible in `src/codebook.py`. The earlier
105-row validation sheet was not completed. Its existence therefore supplies
no accuracy estimate for the dictionary. The report treats its family shares
as descriptive outputs.

## The model evaluation

The four completed tasks concern kind, audience, maker and name style. Each has
50 final human judgments. Audience follows the household and producer sectors
used by von Hippel. Maker categories draw on end-user programming research.
Naming follows the trademark distinctiveness spectrum. The executed option
lists are frozen in `data/processed/alignment/evaluation_tasks.json`.

The first 40 items supported prompt development. The final ten were scored for
the recorded selected version. Kind and Audience remained below the development
target, while Maker and Name style met it. Final agreement fell to 30, 50, 60
and 60 percent respectively. The small final sets give wide uncertainty.

The human could consult application evidence that the model did not receive.
Agreement consequently reflects a difference in evidence as well as the coding
rule. Cannot tell remains a valid answer in the headline score. An earlier Kind
baseline had already predicted final items, which limits the claim that its
final set was untouched.

The completed 1,000-name Kind and Audience runs show how the selected prompts
behaved on more names. Their scale does not resolve weak evaluation results.
The naming run stopped at 874 saved labels and is reported as partial. All
scores are reproduced from the saved files without further model calls.
