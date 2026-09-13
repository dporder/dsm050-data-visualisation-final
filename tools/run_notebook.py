"""Execute the analysis on a fresh kernel and save all notebook outputs.

Run from any directory with: python tools/run_notebook.py
Uses frozen local data. No collection or model API calls are made.
"""
from pathlib import Path
import sys

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "notebooks" / "01_folk_software_census.ipynb"


def main():
    notebook = nbformat.read(PATH, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=600,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
    )
    # Use the interpreter that runs this command, not an unrelated installed kernel.
    client.create_kernel_manager()
    client.km.kernel_spec.argv = [
        sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"
    ]
    client.execute()
    nbformat.write(notebook, PATH)
    count = sum(cell.cell_type == "code" for cell in notebook.cells)
    print(f"Executed and saved all {count} code cells: {PATH}")


if __name__ == "__main__":
    main()
