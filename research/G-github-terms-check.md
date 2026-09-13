# Collection terms and the released data

This note records the terms assessment used for the September 2026 collection.
The source was GitHub's
[Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies),
read on September 13, 2026. The policy allowed research use of public,
non-personal information on the condition that resulting publications were
open access. The project adopted that condition.

The collection used authenticated APIs for public repository information.
Application checks followed published addresses and respected robots.txt.
A blocked response was recorded as such. The scripts did not attempt to bypass
access restrictions.

The released corpus uses salted hashes for owner logins and repository full
names. Profile fields are represented by counts or presence flags. The salt,
lookup tables and raw response caches remain private. A later redaction pass
removed owner handles found in published address and title fields. These
measures reduce identifying detail, although project names and public metadata
can still carry information about a person.

The public evaluation snapshot contains task and item identifiers, item order,
final labels and verdicts. It excludes free-text human notes and evidence links.
The notebook reads this snapshot and the saved model checkpoints. It has no
need for the private evaluator event logs.

The data statement documents the released fields. This note describes the
project's collection decisions and should be read alongside that statement.
