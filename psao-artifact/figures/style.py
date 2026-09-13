"""style.py -- shared matplotlib style, the scenario palette, and the watermark guard.

THREE JOBS
==========
1. One visual language across all seven figures. A reviewer comparing figure 3
   with figure 6 must be able to trust that the same colour means the same
   scenario, so the palette lives here and nowhere else.

2. Vector PDF output only. Raster figures in a systems paper lose the tail of a
   latency distribution the moment anyone zooms in, and camera-ready pipelines
   resample them badly.

3. THE WATERMARK GUARD. Any figure built from synthetic example data is stamped
   diagonally with "SYNTHETIC EXAMPLE DATA - NOT FOR PUBLICATION". This is not
   decoration: it is the mechanism that stops a pipeline-test figure from being
   dropped into a manuscript. finalize() is the only supported way to save a
   figure, and it refuses to save at all if the guard cannot be evaluated.

STYLE RULES ENFORCED HERE
-------------------------
  * sans-serif labels
  * a deliberately chosen palette, never matplotlib's default cycle
  * no 3-D, ever
  * no burned-in numeric data labels: a figure states a shape, the text states
    the number, and the number comes from generated_macros.tex so it cannot
    drift. Annotating values onto the axes is how a figure and its caption end
    up disagreeing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
# Agg: the figures are files, never windows. Set before pyplot is imported.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARTIFACT_ROOT = Path(__file__).resolve().parent.parent
if str(ARTIFACT_ROOT) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_ROOT))

from analysis import io as psao_io  # noqa: E402

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
# Derived from the Okabe-Ito colourblind-safe set, with two substitutions: a
# neutral slate for the S1 baseline (a baseline should not shout), and darker
# variants where Okabe-Ito's yellow would be illegible on white at line width.
# Every hue is distinguishable in greyscale by lightness as well as by hue,
# because a printed proof is often greyscale.
SCENARIO_COLORS = {
    "S1": "#555F6B",  # slate      -- baseline, plain HTTP
    "S2": "#E69F00",  # orange     -- Edge TLS
    "S3": "#56B4E9",  # sky blue   -- + Istio mTLS
    "S4": "#009E73",  # green      -- app JWT HS256
    "S5": "#D55E00",  # vermillion -- full stack (the paper's reference point)
    "S6": "#CC79A7",  # pink       -- RS256
    "S7": "#0072B2",  # blue       -- PSAO: verification in the sidecar
    "S8": "#8E6C1F",  # ochre      -- token cache
    "S9": "#6A3D9A",  # purple     -- cluster mode
}

# CPU components, used by the stacked figures. Deliberately outside the scenario
# palette so a component can never be mistaken for a scenario.
COMPONENT_COLORS = {
    "ingress": "#B9C2CC",
    "app": "#4C6E91",
    "sidecar": "#8FB8DE",
}

# Microbenchmark stages, likewise distinct from both sets above.
STAGE_COLORS = {
    "primitive_raw": "#2E4A62",
    "signing_input_assembly": "#5E8CA8",
    "decode_only": "#A8C6D8",
    "library_overhead": "#DCE6ED",
    "unattributed": "#C0392B",
}

MODEL_STYLES = {
    "mm1": dict(linestyle="--", linewidth=1.4, label="M/M/1 fit"),
    "md1": dict(linestyle="-", linewidth=1.6, label="M/D/1 fit"),
}

WATERMARK_TEXT = psao_io.WATERMARK_TEXT


def scenario_color(scenario: str) -> str:
    return SCENARIO_COLORS.get(scenario, "#000000")


def scenario_label(scenario: str) -> str:
    """'S5 - Full stack (...)'. Identity, not data: safe to burn into a figure."""
    description = psao_io.SCENARIO_DESCRIPTIONS.get(scenario, "")
    return f"{scenario} – {description}" if description else scenario


def short_label(scenario: str) -> str:
    return scenario


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

def apply_style() -> None:
    plt.rcParams.update({
        # -- output ---------------------------------------------------------
        "savefig.format": "pdf",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
        "savefig.transparent": False,
        # Type 42 embeds TrueType outlines, so the text stays selectable and
        # searchable in the camera-ready PDF. Type 3 (the default) is rejected
        # by several publishers' checkers.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,

        # -- typography -----------------------------------------------------
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial",
                            "DejaVu Sans", "sans-serif"],
        "font.size": 8.5,
        "axes.titlesize": 9.5,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "figure.titlesize": 10,

        # -- axes -----------------------------------------------------------
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#D8DCE0",
        "grid.linewidth": 0.5,
        "grid.alpha": 0.9,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,

        # Never matplotlib's default cycle: an unmapped series must look
        # obviously foreign so it gets noticed rather than silently coloured.
        "axes.prop_cycle": plt.cycler(color=list(SCENARIO_COLORS.values())),

        # -- legend ---------------------------------------------------------
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.edgecolor": "#D8DCE0",
        "legend.borderpad": 0.4,
        "legend.handlelength": 1.8,

        "figure.dpi": 150,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "errorbar.capsize": 2.5,
    })


# Single-column and double-column widths for a two-column paper, in inches.
COLUMN_WIDTH = 3.4
DOUBLE_WIDTH = 7.0


def new_figure(width: float = COLUMN_WIDTH, height: float = 2.4, **kwargs):
    apply_style()
    return plt.subplots(figsize=(width, height), **kwargs)


# ---------------------------------------------------------------------------
# The watermark guard
# ---------------------------------------------------------------------------

def add_watermark(fig, text: str = WATERMARK_TEXT) -> None:
    """Stamp the figure diagonally. Drawn last, above every artist."""
    # No bounding box: a box large enough to hold this string spans the whole
    # figure and hides the data it is supposed to be stamped across. Alpha is
    # set high enough to be unmissable on screen and in a greyscale proof, low
    # enough to read the plot through it.
    fig.text(
        0.5, 0.5, text,
        transform=fig.transFigure,
        fontsize=12, color="#C0392B", alpha=0.32,
        ha="center", va="center", rotation=30,
        fontweight="bold", zorder=1000,
    )


def is_synthetic(data_dir) -> bool:
    """Whether figures from this data directory must be watermarked."""
    return psao_io.data_is_synthetic(Path(data_dir))


def finalize(fig, out_path, data_dir, *, tight: bool = True) -> Path:
    """Watermark if required, then save as vector PDF. The only save path.

    Refuses to write anything but .pdf, and refuses to write at all if the
    synthetic check itself fails -- an unevaluable guard must not be treated as
    "not synthetic".
    """
    out_path = Path(out_path)
    if out_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"figures are vector PDF only; refusing to write {out_path.name}")

    try:
        synthetic = is_synthetic(data_dir)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"could not determine whether {data_dir} is synthetic ({exc}); refusing "
            "to save an unguarded figure"
        ) from exc

    if synthetic:
        add_watermark(fig)
        # Verify the stamp is actually on the figure before writing. matplotlib
        # embeds PDF text as subset glyph indices, so the watermark cannot be
        # grepped out of the finished file -- this assertion is the only place
        # the guard can be checked mechanically, so it is checked here and the
        # save is abandoned if it fails.
        if not any(WATERMARK_TEXT in t.get_text() for t in fig.texts):
            raise RuntimeError(
                f"watermark was not applied to {out_path.name} despite synthetic "
                "data; refusing to write an unmarked figure")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  {out_path}{'  [WATERMARKED: synthetic]' if synthetic else ''}")
    return out_path


def add_data_provenance(fig, data_dir) -> None:
    """A small footer naming the data directory the figure was built from.

    Not a data label -- it is provenance, and it is what lets a reader of a draft
    tell which run a figure came from.
    """
    fig.text(0.995, 0.005, f"data: {data_dir}", ha="right", va="bottom",
             fontsize=5.0, color="#98A2AC")


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def scenario_legend_handles(scenarios, *, marker="o"):
    from matplotlib.lines import Line2D
    return [Line2D([0], [0], color=scenario_color(s), marker=marker,
                   linestyle="-", markersize=3.5, linewidth=1.4,
                   label=scenario_label(s))
            for s in scenarios]


def ci95_halfwidth(values):
    """t-based 95% CI half-width of a mean. None when n < 2."""
    import numpy as np
    from scipy import stats
    values = np.asarray([v for v in values if v is not None and np.isfinite(v)],
                        dtype=float)
    if len(values) < 2:
        return None
    return float(stats.t.ppf(0.975, len(values) - 1)
                 * values.std(ddof=1) / np.sqrt(len(values)))
