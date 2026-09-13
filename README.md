# Folk software: a census of what non-programmers build with AI

DSM050 Data Visualisation final coursework, University of London. Dan Porder.

The analysis describes 50,396 public GitHub repositories carrying AI builder-tool
provenance signals, including 42,264 Lovable repositories. It examines project
names, account footprints, audience signals, URL liveness and public traces of
sharing. Tool provenance does not establish a maker's occupation.

## Submission files

- [Report (PDF)](report/REPORT.pdf)
- [Executed analysis notebook](notebooks/01_folk_software_census.ipynb)
- [Dataset: corpus.csv](data/processed/corpus.csv)
- [Dataset documentation](data/README.md)
- [Final evaluation data and methods](data/processed/alignment/README.md)
- [Assignment specification](DSM050_FINAL_COURSEWORK.pdf)

The repository contains a copy of the data, as required by the assignment.
`data/processed/wayback_census.csv` is the separate archive-host comparison.
The report's AI declaration is in section 6.

## Reproduce the analysis

From the repository root, using Python 3.14.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python tools/run_notebook.py
```

The runner executes the notebook on a fresh kernel using the active Python
interpreter and saves all outputs. Figures are regenerated in `figures/` as
300 dpi PNGs and vector PDFs, alongside numerical verification tables.
The notebook can also be opened in JupyterLab after installing `jupyterlab`.

Reproduction uses frozen local inputs. No API keys, new model calls, private
human-judgment logs, account lookup files or collection caches are required.
Collection and model-calling scripts remain as provenance. Running them would
constitute a new data collection or inference run and is not part of reproduction.

## Evaluation data

Four tasks contain 50 final human judgments each. The selected model versions
are recorded in `data/processed/alignment/accepted.json`. Their final ten-item
agreement is 30% for Kind, 50% for Audience, 60% for Maker and 60% for Name style.
The report and notebook discuss the wide uncertainty and limitations.

The completed larger samples contain 1,000 Kind and 1,000 Audience labels.
The Name-style checkpoint contains 874 of 1,000 requested labels and is partial.
Earlier prompt checkpoints are retained to reproduce development history.

## Supporting material

- `src/`: classification, sampling, evaluation and notebook source.
- `prompts/`: saved model-prompt versions.
- `figures/`: report figures and derived tables.
- `tools/evaluator/`: human-labeling interface and scoring code.
- `research/`: provenance, methodological sources and collection scripts.
- `paper/phase-2-proposal.md`: the future-study appendix cited by the report.

The standalone report source is `report/REPORT.md`. With Pandoc and WeasyPrint
installed, `bash report/build-pdf.sh` rebuilds the PDF.
`bash report/wordcount.sh` counts the rendered main body, including headings,
citations, tables and captions, excluding the title block, references and appendices.
