"""Figure: the failed asymmetric parse issued from C across OpenSSL releases.

Every value is read from ../revision_macros.tex (itself generated from the
committed run files), so no number is typed here. Run from this directory:

    python3 make_fig_openssl_releases.py
"""
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
MACROS = (HERE.parent / "revision_macros.tex").read_text()


def macro(name):
    m = re.search(r"\\newcommand\{\\" + name + r"\}\{([^}]*)\}", MACROS)
    if not m:
        raise KeyError(name)
    return m.group(1)


SUFFIXES = ["VThreeZeroSixteen", "VThreeZeroNineteen", "VThreeOneEight",
            "VThreeTwoSix", "VThreeThreeFive", "VThreeFourThree",
            "VThreeFiveEight", "VThreeSixOne"]

labels = [macro("CVersionLiteral" + s) for s in SUFFIXES]
failed = [float(macro("CFull" + s)) for s in SUFFIXES]
failed_lo = [float(macro("CFull" + s + "CiLo")) for s in SUFFIXES]
failed_hi = [float(macro("CFull" + s + "CiHi")) for s in SUFFIXES]
success = [float(macro("CSpkiOk" + s)) for s in SUFFIXES]

ORANGE = "#E8663A"
BLUE = "#2F6FD0"

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "pdf.fonttype": 42,
})

fig, ax = plt.subplots(figsize=(6.6, 2.7))
x = list(range(len(labels)))

yerr = [[f - lo for f, lo in zip(failed, failed_lo)],
        [hi - f for f, hi in zip(failed, failed_hi)]]
ax.errorbar(x, failed, yerr=yerr, color=ORANGE, marker="o", markersize=5,
            linewidth=1.8, capsize=2, label="failed parse of an HMAC secret "
            "(discarded)", zorder=3)
ax.plot(x, success, color=BLUE, marker="s", markersize=4.5, linewidth=1.4,
        label="successful parse of an RSA-2048 public key", zorder=3)

for xi, (v, w) in enumerate(zip(failed, success)):
    # Label above the point where the failed parse is the upper series,
    # below it where the successful parse lies above.
    dy = 7 if v >= w else -12
    ax.annotate(f"{v:g}", (xi, v), textcoords="offset points", xytext=(0, dy),
                ha="center", fontsize=7.5, color="#3a3a3a")

ax.set_yscale("log")
ax.set_ylim(2.5, 1500)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_xlabel("OpenSSL release (built from source, identical configuration)")
ax.set_ylabel("µs per call (log scale)")
ax.grid(axis="y", color="#e4e4e4", linewidth=0.6, zorder=0)

# Series boundaries of Table 4: 3.0 | 3.1 | 3.2 onward.
for b in (1.5, 2.5):
    ax.axvline(b, color="#555555", linestyle="--", linewidth=0.8, zorder=1)
ax.text(0.5, 1250, "3.0 series", ha="center", va="top", fontsize=8,
        color="#555555")
ax.text(2.0, 1250, "3.1", ha="center", va="top", fontsize=8, color="#555555")
ax.text(5.0, 1250, "3.2 onward", ha="center", va="top", fontsize=8,
        color="#555555")

handles, names = ax.get_legend_handles_labels()
order = [names.index(n) for n in sorted(names, key=lambda n: not n.startswith("failed"))]
ax.legend([handles[i] for i in order], [names[i] for i in order],
          loc="center right", bbox_to_anchor=(1.0, 0.64), frameon=False,
          fontsize=8)
fig.tight_layout()
fig.savefig(HERE / "fig_openssl_releases.pdf")
print("wrote fig_openssl_releases.pdf")
