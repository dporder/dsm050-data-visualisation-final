#!/usr/bin/env bash
# Build the submission PDF from report/REPORT.md.
# Usage: bash report/build-pdf.sh
set -euo pipefail
cd "$(dirname "$0")/.."
pandoc report/REPORT.md \
  --from=markdown+yaml_metadata_block+implicit_figures \
  --pdf-engine=weasyprint \
  --css=report/report.css \
  --toc --toc-depth=2 \
  --resource-path=.:report \
  -o report/REPORT.pdf
echo "wrote report/REPORT.pdf"
