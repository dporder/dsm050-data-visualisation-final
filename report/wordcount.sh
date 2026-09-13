#!/usr/bin/env bash
# Count rendered main-body text, including headings, citations, tables and captions.
# Exclude the title block, reference list, appendices and count declaration.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import re, pathlib, subprocess
t = pathlib.Path("report/REPORT.md").read_text()
t = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)          # YAML title block
for stop in ("## References", "## Word count", "## Appendices"):
    if stop in t: t = t[:t.index(stop)]
t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                  # images, not captions
plain = subprocess.run(["pandoc", "-f", "markdown", "-t", "plain", "--wrap=none"],
                       input=t, text=True, capture_output=True, check=True).stdout
n = sum(bool(re.search(r"\w", word)) for word in plain.split())
print(f"main body: {n:,} words   (target 3,000 to 3,500; hard cap 3,500)")
PY
