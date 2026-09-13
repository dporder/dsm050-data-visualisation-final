# Provenance signals used in the study

The sampling groups follow traces left by tools in public repositories. These
traces provide evidence that a tool was involved. They leave the maker's skill,
occupation and share of the work unresolved. The checks summarized here were
recorded on September 10, 2026, before the corpus was collected.

## Lovable

Lovable's GitHub integration creates a repository with a default README. The
heading "Welcome to your Lovable project" supplied the main search marker.
The recorded search returned 323,065 public repositories. A separate check of
22 READMEs, sampled using a project-URL marker, found the heading in 19. The
heading persisted across the inspected dates, while another part of the template
changed. The collection script records that check in stage 0.

The marker identifies projects that reached public GitHub and retained the
searchable text. Private repositories, changed READMEs and projects published
through other routes fall outside it. The integration is described in
[Lovable's documentation](https://docs.lovable.dev/integrations/git-integration).

## Comparison groups

The other groups provide comparisons under the same broad collection method.
They differ in the tool traces used to find them.

| Group | Recorded search signals | Interpretation |
|---|---|---|
| Replit | `.replit` files and README references to `replit.app` or Replit Agent | Evidence of a Replit connection, including projects that predate its AI features |
| v0 and Bolt | README references to Built with v0, `v0.app`, `v0.dev` or `bolt.new` | Evidence of the named tools in the repository text |
| Claude Code | README references to Generated with Claude Code or its co-author marker | Evidence of tool attribution in searchable text |

The Replit file search used file-size slices because its endpoint did not accept
the creation-date filter used for README searches. Some Replit repositories
therefore predate the main study period. The notebook keeps the monthly analysis
within the Lovable group.

The recorded documentation describes [Replit's project guidance](https://docs.replit.com/replitai/replit-dot-md),
[Bolt's Git integration](https://support.bolt.new/integrations/git.md),
[v0's GitHub integration](https://v0.app/docs/github) and
[Claude Code's project instructions](https://code.claude.com/docs/en/memory.md).
These sources explain the traces. They do not establish the occupation of the
people whose repositories carry them.

## What the traces can support

Default domains and template text can help identify a publishing route. They can
also be copied, retained after a project changes, or removed by an experienced
user. A common web stack provides still weaker evidence because many developers
use the same components. The analysis therefore describes the sampled tool
groups and treats account attributes as separate, uncertain proxies.

The implemented queries are in `research/C-scripts/collect/`. The released data
statement records the sample sizes and remaining coverage limits.
