# Why the study used public repository data

The source search considered builder galleries, hosted applications and public
repository traces. The main requirement was a source that could be enumerated
with a documented query and that supplied enough fields for the five questions.
Public GitHub metadata offered project dates, names, activity and account
attributes within one repository-level dataset.

## Selecting the main source

The recorded Lovable README search returned 323,065 public repositories on
September 10, 2026. This was the largest usable tool-specific repository source
found in the feasibility work. A check against a separate project-URL marker
supported using the default heading across the sampled creation dates. The
heading remained present in 19 of 22 inspected READMEs, while the project-URL
text changed during the period.

The final collection sampled the third, tenth, seventeenth and twenty-fourth
days of each month from June 2024 to September 2026. Four of the 112 windows
reached the search result cap. The dataset retains the query totals and window
weights. The notebook reports the observed sample rather than extrapolating
those days to all projects made in a month.

## Adding comparisons

Replit, v0 and Bolt, and Claude Code supplied three comparison groups. Their
queries follow the tool traces documented in
[`A-provenance-signals.md`](A-provenance-signals.md). Replit's file search could
not use creation-date windows, so size slices supplied part of that group.
This limits comparisons involving time.

Published application addresses supplied one liveness check. The result records
whether an address answered at collection. Repeated checks would be needed to
study failure dates or survival. Blocked and indeterminate responses are kept
separate from live and dead results.

## The archive's separate role

The Internet Archive supplied a host-level table with 59,175 hosts across five
builder domains. Its 33,530 `lovable.app` hosts include applications that may
never have reached public GitHub. The repository-to-archive join was sparse,
with dates on only 31 repository rows. The notebook therefore uses the host
counts as a separate view of coverage.

Other galleries and directories could have supplied examples, but did not offer
the same combination of enumeration, metadata and permitted acquisition. Their
feasibility samples are outside the submitted analysis. The final dataset and
its collection scripts are described in [`data/README.md`](../data/README.md).
