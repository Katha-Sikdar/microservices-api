"""Analysis package for the PSAO reproducibility artifact.

Every module here consumes CSVs written by experiments/ and produces numbers,
never the other way round. Nothing in this package fabricates, imputes or
back-fills a measurement: a quantity that was not measured comes out as NaN and
is rendered downstream as a LaTeX \\PLACEHOLDER, in red, in the manuscript.
"""

__all__ = ["io", "elbow_fit", "stats_tests", "amortized_cpu", "run_all"]
__version__ = "1.0.0"
