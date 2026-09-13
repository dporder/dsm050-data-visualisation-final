# What account footprints reveal about makers

Repository metadata describes public activity. Its relationship to occupation
is uncertain. A professional may keep work private, while a beginner may have
an old account or several public projects. The study uses these fields as
proxies, meaning indirect indicators whose interpretation needs validation.

## The indicators used

| Indicator | Recorded measure | Limitation |
|---|---|---|
| Account age | Days between account and repository creation | An old account can be dormant |
| Public repositories | Count at collection | Private and organization-owned work is absent |
| Followers | Count at collection | Visibility can reflect factors besides programming experience |
| Biography | Whether the field is filled | The released data omits its text |
| Brief activity | Last push within one day of creation | This measures elapsed time, without reconstructing commit history |
| Work visible in this corpus | Sampled repositories per hashed owner against the public count | The sample observes only selected tools and dates |

The end-user programming literature supplies the conceptual distinction between
professional and non-professional making (Nardi, 1993; Ko et al., 2011;
Scaffidi, Shaw and Myers, 2005). It does not validate a threshold over these
particular GitHub fields. Munaiah et al. show why repository selection requires
care when the intended construct is engineered software
(2017, [doi:10.1007/s10664-017-9512-6](https://doi.org/10.1007/s10664-017-9512-6)).

## How the study uses them

The notebook compares the account distributions across tool groups. It also
reports the exploratory equal-weight score saved by `src/maker_score.py`.
The deterministic terms are standardized within the Lovable group, and a model
label supplies one further term for the 50 evaluation items.

Of those 50 human labels, 35 are Cannot tell. None identifies a non-programmer.
The score comparison groups professional or technical labels against uncertainty.
Its area under the ROC curve measures how well it separates those answers.
It cannot establish discrimination between professionals and non-programmers.
The final ten contain four professional labels and six Cannot tell labels.

The report's footprint sensitivity table uses explicit descriptive definitions.
A light footprint has no biography, at most one follower and fewer than ten
public repositories. A heavy footprint has a biography and either at least ten
followers or at least thirty repositories. The strictest group has a new account
and a single project. These definitions allow a sensitivity comparison while
leaving occupation unresolved.

A future study would need makers' own accounts of their experience, occupation
and work, linked with consent to the artifacts being examined. That design is
outlined in the report's next-phase appendix.
