"""Keep the study figures consistent.

Colors distinguish tool groups across charts. The helpers apply the shared
fonts, axes and captions, then export PNG and PDF copies."""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from pathlib import Path

FIGDIR = Path(__file__).resolve().parent.parent / "figures"
FIGDIR.mkdir(exist_ok=True)

# Okabe-Ito: colorblind-safe, used consistently for strata and genres.
OKABE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7",
         "#56B4E9", "#D55E00", "#F0E442", "#000000"]
STRATUM_COLOUR = {
    "lovable": "#0072B2",   # the folk population
    "replit":  "#E69F00",
    "v0_bolt": "#009E73",
    "claude":  "#CC79A7",
}
STRATUM_LABEL = {
    "lovable": "Lovable (builder tool)",
    "replit":  "Replit",
    "v0_bolt": "v0 / Bolt",
    "claude":  "Claude Code",
}
INK = "#1a1a1a"
MUTED = "#6b6b6b"
GRID = "#d9d9d9"


def use_house_style() -> None:
    rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 9,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "grid.alpha": 0.7,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": INK,
        "legend.frameon": False,
        "figure.titlesize": 12,
    })


def annotate(ax, text: str, xy, xytext, **kw):
    """Annotate the insight, not the data dump."""
    kw.setdefault("fontsize", 8)
    kw.setdefault("color", INK)
    kw.setdefault("arrowprops", dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.annotate(text, xy=xy, xytext=xytext, **kw)


def caption(fig, text: str, y: float = -0.02):
    """One line under the figure stating n and the source."""
    fig.text(0.0, y, text, ha="left", va="top", fontsize=7.5, color=MUTED, wrap=True)


def save(fig, name: str, caption_text: str | None = None):
    """Save to figures/ as PNG (for the report) and PDF (vector, for the paper)."""
    if caption_text:
        caption(fig, caption_text)
    for ext in ("png", "pdf"):
        fig.savefig(FIGDIR / f"{name}.{ext}")
    print(f"saved figures/{name}.png and .pdf")
    plt.close(fig)
