# Data for the folk software census

The released corpus contains 50,396 public GitHub repositories and 37 columns.
Each row represents one repository carrying a builder-tool provenance signal.
The data was collected on 12 September 2026 and assembled at 05:41 UTC.
It describes repositories visible through these search methods. A tool marker
alone cannot establish the maker's occupation.

## Files and reproduction

| File | Contents |
|---|---|
| [processed/corpus.csv](processed/corpus.csv) | The repository corpus used throughout the analysis. |
| [processed/wayback_census.csv](processed/wayback_census.csv) | A separate table of 59,175 archive hosts. |
| [processed/alignment/](processed/alignment/README.md) | Final human labels, task metadata, saved model predictions and evaluation results. |
| `processed/validation_sheet.csv` | The earlier 105-row dictionary-validation sample, with no completed human answers. |
| `processed/validation_machine_answers.csv` | Dictionary answers for that earlier sample. |

The [notebook](../notebooks/01_folk_software_census.ipynb) reads these saved files.
Install the root `requirements.txt`, then run `python tools/run_notebook.py`
from the repository root. Reproduction requires no API keys or private collection
files. The acquisition scripts are retained in
[research/C-scripts/collect](../research/C-scripts/collect/). Running those scripts
would collect new observations from services whose records may have changed.

## Sources and sampling

GitHub repository searches supplied names, dates and activity counts. Account
attributes came from its REST and GraphQL APIs. The liveness stage checked the
application addresses declared by repositories. Internet Archive CDX queries
supplied the separate host table and the sparse archive fields in the corpus.
The collection scripts record the queries and transformations.

| Stratum | Rows | Search signal |
|---|---:|---|
| `lovable` | 42,264 | The default “Welcome to your Lovable project” README heading. |
| `replit` | 2,797 | `.replit` files and Replit-related README markers. |
| `v0_bolt` | 2,776 | v0 and Bolt README markers. |
| `claude` | 2,559 | Claude Code README markers. |

The Lovable queries used 112 one-day windows, the 3rd, 10th, 17th and 24th of
each month from June 2024 through September 2026. Of these, 96 contributed rows
to the saved corpus. Four windows reached the API's 1,000-result cap. Results
were ordered by update time, so capped windows are not random samples.
`window_total_count` and `sample_weight` retain the information about those caps.

The comparison searches used quarterly README windows. Replit code search also
used file-size slices, because that endpoint did not support the same creation-date
filter. This explains the 373 Replit rows created before June 2024. The date
ranges of the four groups therefore differ.

The notebook reports the composition of the saved sample. It does not expand
sampled days into estimated monthly population totals. Search indexing, README
editing and the choice to publish on GitHub all affect inclusion. The template
check and search evidence are described in
[the feasibility record](../research/C-data-source-feasibility.md).

## Cleaning and coverage

Repository identifiers are unique and all retained rows have `is_fork = 0`.
Missing fields remain missing. The classification code separates auto-generated
and unreadable names from names assigned to one of 23 dictionary families.
The project name supplies the main text signal, supplemented by a page title
where one was available. No missing application address was guessed from a
repository name.

There are 12,763 non-empty homepage fields in the released corpus, or 25.3% of
rows. Liveness results cover 6,017 repository rows, or 11.9%. Some repositories
share an address, so the row count differs from the number of requests.

| Recorded class | Rows | Interpretation |
|---|---:|---|
| `live` | 4,584 | A response classified as an available application. |
| `dead_404` | 1,252 | A missing-page response, recognized platform error page, or DNS failure. |
| `indeterminate` | 162 | The response or transport result did not establish availability. |
| `blocked` | 19 | Access was denied or challenged. |

The dead-address shares use the 5,836 determinate live/dead rows. Blocked and
indeterminate results are excluded from those denominators. A single check
cannot show when an application failed or why. Page-title rules can also
misclassify an unusual title. Requests respected robots.txt and a per-host delay.

Public repository counts are available for 49,018 rows, or 97.3%. Other account
fields have slightly different coverage. Their denominators are calculated
from available observations. Counts and profile-field presence describe an
account's public footprint, without identifying its owner's occupation.

Only 31 corpus rows have an archive date. The archive-host table is consequently
an independent view of captured hosting domains. It contains 33,530
`lovable.app`, 14,192 `replit.app`, 9,294 `base44.app`, 1,729 `bolt.host` and
430 `lovableproject.com` hosts. Its first-seen date records an archive observation.
Publication may have occurred earlier, and changes in crawling can affect the
monthly series. These hosts are neither a complete application population nor
a subset of the GitHub corpus.

## Released identifiers and private records

`repo_id` and `owner_hash` are salted SHA-256 identifiers truncated to 32
hexadecimal characters. `repo_slug` retains the repository name, with known
owner handles redacted. The release contains account counts and booleans for
profile-field presence. It excludes profile names, biography text, location
text and the private identifier lookup files.

A later redaction pass replaced known owner handles found in repository names,
addresses and page metadata with `[owner]`, and removed profile URLs. Application
addresses and short page metadata remain where retained by that pass. They can
still provide routes to identifying a public project. The hashes therefore
reduce direct identification without guaranteeing anonymity.

Raw API responses, the salt, identifier lookups and private evaluator evidence
are excluded from version control. They are unnecessary for rerunning the
published analysis. The collection terms assessment is documented in
[research/G-github-terms-check.md](../research/G-github-terms-check.md).

## Evaluation data

The four completed reference tasks contain 50 human labels each. The selected
model checkpoints have predictions for all 200 items. Kind and Audience also
have completed 1,000-row production samples. The naming production checkpoint
contains 874 of 1,000 requested rows and remains partial.

Final agreement is 30% for Kind, 50% for Audience and 60% each for Maker and
Name style. The small final sets produce wide intervals. Development blocks
summarize predictions from the same prompt, and the earlier Kind checkpoints
already contain final-item predictions. These limits are explained in
[the evaluation documentation](processed/alignment/README.md).

## Repository column dictionary

| Column | Type | Source | Meaning |
|---|---|---|---|
| `repo_id` | string (32 hex) | derived | Salted SHA-256 of `owner/repo`. Primary key. The lookup file is private. |
| `stratum` | category | derived | `lovable`, `replit`, `v0_bolt` or `claude`, which provenance signal put the row in the corpus. |
| `created_at` | ISO 8601 UTC | GitHub | Repository creation. It dates the repository, which may differ from the start of work on the application. |
| `pushed_at` | ISO 8601 UTC | GitHub | Last push to any branch. |
| `updated_at` | ISO 8601 UTC | GitHub | Last metadata change. Moves for reasons unrelated to work (stars, renames), so `pushed_at` is the better activity clock. |
| `days_repo_active` | integer | derived | `pushed_at` − `created_at`, in whole days. 0 means the last push was within one whole day of creation. |
| `stars` | integer | GitHub | `stargazers_count`. |
| `forks` | integer | GitHub | `forks_count`. Forks indicate a public copy, without establishing use. |
| `language` | string | GitHub | GitHub's dominant-language guess. Empty when GitHub could not tell. |
| `size_kb` | integer | GitHub | Repository size in KB, as GitHub reports it. |
| `is_fork` | 0/1 | GitHub | Whether the repository is itself a fork. |
| `has_license` | 0/1 | derived | Whether an SPDX license was detected. Mostly 0 in the Lovable stratum, which is why no README or code text is republished here. |
| `has_description` | 0/1 | derived | Whether the repository description is non-empty. |
| `description_len` | integer | derived | Length of the description, **capped at 200**. |
| `repo_slug` | string | derived | The repository **name**, lowercased, hyphens preserved. The primary genre signal. Known owner handles were replaced during redaction. |
| `homepage_url` | URL | GitHub | The published app URL the repository declares, normalized. Empty when none is declared or the value is not a URL. |
| `app_host` | hostname | derived | Host of `homepage_url`. Joins to `processed/wayback_census.csv`. |
| `live_status` | integer | stage 4 | HTTP status of the final response. Empty when not checked. |
| `live_class` | category | stage 4 | `live`, `dead_404`, `parked`, `blocked`, `indeterminate`. The classes distinguish availability from blocked or inconclusive checks. |
| `page_title` | string | stage 4 | `<title>` of the live page, whitespace-collapsed, 200 chars. Genre signal. |
| `page_meta_desc` | string | stage 4 | `description` or `og:description` meta tag, 300 chars. Supplementary text for classification. Default wording may come from the builder template. |
| `wayback_first_seen` | ISO 8601 UTC | Wayback | Earliest capture of `app_host` since 2024. An observation date, which can be later than publication. |
| `wayback_last_seen` | ISO 8601 UTC | Wayback | Latest capture of `app_host`. |
| `wayback_last_status` | integer | Wayback | Status code at the latest capture. `404` here plus `live` in `live_class` means the app came back, and both are true. |
| `owner_hash` | string (32 hex) | derived | Salted SHA-256 of the lowercased owner login. Groups rows by account. Present for every row. |
| `owner_public_repos` | integer | GitHub | Public repository count at collection time. Empty for owners outside the stage 3 sample. |
| `owner_followers` | integer | GitHub | Follower count. |
| `owner_account_created` | ISO 8601 UTC | GitHub | When the account was created. |
| `owner_account_age_days_at_repo` | integer | derived | `created_at` − `owner_account_created`, in days. Small values identify an account created shortly before the repository. They do not establish why it was created. |
| `owner_has_bio` | 0/1 | derived | A bio exists. **Never its text.** |
| `owner_has_location` | 0/1 | derived | A location exists. **Never the place.** |
| `owner_has_company` | 0/1 | derived | A company exists. **Never its name.** |
| `owner_has_blog` | 0/1 | derived | A blog URL exists. **Never the URL.** |
| `window_start` | date or label | derived | The day-window (stage 1) or quarter start (stage 2) the row was enumerated in; `code-search (no date qualifier)` for `.replit` rows, which have no date slice. |
| `window_total_count` | integer | GitHub | `total_count` GitHub reported for that window's query, This records the search result count for that query. |
| `sample_weight` | float | derived | `window_total_count` ÷ rows kept from that window. 1.0 means the window was returned whole. It does not correct for unsampled dates or selection into GitHub. |
| `collected_utc` | ISO 8601 UTC | derived | Timestamp of the assembly run. Identical on every row. |

## Archive-host column dictionary

| Column | Type | Meaning |
|---|---|---|
| `host` | hostname | Captured application host, used for the attempted `app_host` join. |
| `platform` | category | One of the five queried hosting domains. |
| `first_seen` | `YYYYMMDDhhmmss` | Earliest recorded capture since 2024. |
| `last_seen` | `YYYYMMDDhhmmss` | Latest recorded capture in the collection. |
| `last_status` | integer or `-` | Status at the latest capture. A dash means no status was recorded. |
| `n_captures` | integer | Number of captures returned in the collection window. |
