"""io.py -- loading, schema validation and synthetic-data detection.

Two responsibilities that must not be separated:

1. Load the CSVs described in docs/DATA_SCHEMA.md, validating that the columns
   are the documented ones. A silently renamed column becomes a silently
   wrong figure.

2. Decide whether a data directory holds SYNTHETIC data. This is the guard the
   whole artifact hangs on: figures rendered from synthetic data are watermarked
   and macros derived from it are marked, so example output can never be
   mistaken for a measurement. The check is deliberately redundant -- path AND
   file content -- because a single check is a single point of failure, and the
   failure mode is a fabricated number in a published paper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# Written into the header of every file data/make_example_data.py produces.
SYNTHETIC_MARKER = "SYNTHETIC EXAMPLE DATA"
WATERMARK_TEXT = "SYNTHETIC EXAMPLE DATA — NOT FOR PUBLICATION"

SCENARIO_ORDER = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]

SCENARIO_DESCRIPTIONS = {
    "S1": "Baseline (plain HTTP)",
    "S2": "Edge TLS",
    "S3": "Edge TLS + Istio mTLS",
    "S4": "App JWT (HS256)",
    "S5": "Full stack (Edge TLS + mTLS + app JWT HS256)",
    "S6": "Full stack, RS256",
    "S7": "PSAO: verification in the Envoy sidecar",
    "S8": "Full stack + verified-token LRU cache",
    "S9": "Full stack, Node cluster mode",
}

BASELINE_SCENARIO = "S1"

# ---------------------------------------------------------------------------
# Schemas (docs/DATA_SCHEMA.md is the normative copy; these must agree)
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, list[str]] = {
    "scenarios": [
        "scenario", "environment", "run", "throughput_rps", "throughput_window",
        "latency_mean_ms", "latency_p50_ms", "latency_p90_ms", "latency_p95_ms",
        "latency_p99_ms", "latency_stdev_ms", "cpu_app_millicores",
        "cpu_sidecar_millicores", "cpu_ingress_millicores", "cpu_limit_millicores",
    ],
    "latency_samples": ["scenario", "environment", "run", "latency_ms"],
    "openloop_ramp": [
        "scenario", "environment", "target_rps", "achieved_rps",
        "latency_mean_ms", "latency_p99_ms", "cpu_app_millicores",
        "cpu_sidecar_millicores", "eventloop_lag_p99_ms",
    ],
    "controller_trace": [
        "t_unix", "t_rel_s", "lambda_rps", "eventloop_lag_p99_ms", "mu_eff_rps",
        "rho", "latency_mean_ms", "mode", "decision", "actuation_latency_ms",
        "trigger_reason",
    ],
    "microbench": [
        "algorithm", "stage", "payload_kb", "iterations", "mean_us", "p50_us", "p99_us",
    ],
}

# Columns that must be numeric. Everything else stays a string.
NON_NUMERIC = {
    "scenario", "environment", "throughput_window", "mode", "decision",
    "trigger_reason", "algorithm", "stage",
}

CATEGORICAL_VALUES = {
    "environment": {"local", "eks"},
    "throughput_window": {"steady", "full"},
    "mode": {"app", "sidecar"},
    "decision": {"hold", "offload", "revert"},
}


# ---------------------------------------------------------------------------
# Synthetic-data detection
# ---------------------------------------------------------------------------

def path_looks_synthetic(path: Path) -> bool:
    """True when any component of the resolved path contains 'example'.

    The brief is explicit: a figure rendered from a data path containing
    "example" must be watermarked. Matching on the resolved path means a symlink
    or a relative path cannot smuggle example data past the guard.
    """
    return any("example" in part.lower() for part in Path(path).resolve().parts)


def file_declares_synthetic(path: Path, max_lines: int = 5) -> bool:
    """True when a CSV's opening comment lines declare it synthetic."""
    try:
        with Path(path).open("r", errors="replace") as fh:
            for _ in range(max_lines):
                line = fh.readline()
                if not line:
                    break
                if not line.startswith("#"):
                    break
                if SYNTHETIC_MARKER in line.upper():
                    return True
    except OSError:
        return False
    return False


def data_is_synthetic(data_dir: Path) -> bool:
    """Whether this data directory must be treated as synthetic.

    Redundant on purpose: either the path says so, or a file says so. A data set
    that is synthetic and hides both facts would need someone to have removed the
    marker AND renamed the directory, which is no longer an accident.
    """
    data_dir = Path(data_dir)
    if path_looks_synthetic(data_dir):
        return True
    return any(file_declares_synthetic(csv) for csv in sorted(data_dir.glob("*.csv")))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class SchemaError(ValueError):
    """Raised when a CSV does not match its documented schema."""


def _coerce(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in NON_NUMERIC:
            frame[column] = frame[column].astype("string").str.strip()
        else:
            # errors="coerce" turns an empty cell into NaN. Empty means "not
            # measured" throughout this artifact, and NaN is how that travels.
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_table(path: Path, schema: str, *, required: bool = False) -> Optional[pd.DataFrame]:
    """Load one CSV against its schema. Returns None if absent and not required."""
    path = Path(path)
    columns = SCHEMAS[schema]
    if not path.exists():
        if required:
            raise FileNotFoundError(f"required input missing: {path}")
        return None

    # comment="#" drops the synthetic-data banner and any provenance comments the
    # runners write above the header row.
    frame = pd.read_csv(path, comment="#", skip_blank_lines=True)
    frame.columns = [c.strip() for c in frame.columns]

    missing = [c for c in columns if c not in frame.columns]
    extra = [c for c in frame.columns if c not in columns]
    if missing:
        raise SchemaError(
            f"{path}: missing column(s) {missing}. Expected exactly the schema in "
            f"docs/DATA_SCHEMA.md: {columns}"
        )
    if extra:
        raise SchemaError(
            f"{path}: unexpected column(s) {extra}. The schemas are fixed so that a "
            f"figure cannot silently plot a different quantity than the one named."
        )

    frame = frame[columns].copy()
    frame = _coerce(frame, columns)

    for column, allowed in CATEGORICAL_VALUES.items():
        if column not in frame.columns:
            continue
        seen = set(frame[column].dropna().unique()) - allowed
        if seen:
            raise SchemaError(
                f"{path}: column {column!r} contains {sorted(seen)}; allowed values "
                f"are {sorted(allowed)}"
            )

    if "scenario" in frame.columns:
        unknown = sorted(set(frame["scenario"].dropna().unique()) - set(SCENARIO_ORDER))
        if unknown:
            raise SchemaError(
                f"{path}: unknown scenario label(s) {unknown}; expected one of "
                f"{SCENARIO_ORDER}"
            )
    return frame


@dataclass
class DataBundle:
    """Everything the analysis and figures read, plus its provenance."""
    data_dir: Path
    synthetic: bool
    scenarios: Optional[pd.DataFrame] = None
    latency_samples: Optional[pd.DataFrame] = None
    openloop_ramp: Optional[pd.DataFrame] = None
    controller_trace: Optional[pd.DataFrame] = None
    microbench: Optional[pd.DataFrame] = None
    missing: list[str] = field(default_factory=list)

    def require(self, name: str) -> pd.DataFrame:
        frame = getattr(self, name)
        if frame is None or frame.empty:
            raise FileNotFoundError(
                f"{name}.csv is absent or empty in {self.data_dir}. Run the "
                f"corresponding experiment, or `make example-data` for synthetic input."
            )
        return frame

    def describe(self) -> str:
        lines = [f"data directory : {self.data_dir}",
                 f"synthetic      : {self.synthetic}"]
        for name in ("scenarios", "latency_samples", "openloop_ramp",
                     "controller_trace", "microbench"):
            frame = getattr(self, name)
            lines.append(f"  {name:<17}: "
                         + ("MISSING" if frame is None else f"{len(frame)} rows"))
        return "\n".join(lines)


def load_bundle(data_dir: Path) -> DataBundle:
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(f"data directory does not exist: {data_dir}")

    bundle = DataBundle(data_dir=data_dir, synthetic=data_is_synthetic(data_dir))
    for name in ("scenarios", "latency_samples", "openloop_ramp",
                 "controller_trace", "microbench"):
        frame = load_table(data_dir / f"{name}.csv", name)
        setattr(bundle, name, frame)
        if frame is None:
            bundle.missing.append(f"{name}.csv")
    return bundle


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def scenarios_present(frame: pd.DataFrame) -> list[str]:
    """Scenario labels present, in canonical S1..S9 order."""
    seen = set(frame["scenario"].dropna().unique())
    return [s for s in SCENARIO_ORDER if s in seen]


def steady(frame: pd.DataFrame) -> pd.DataFrame:
    """The steady-state rows of a scenarios frame."""
    return frame[frame["throughput_window"] == "steady"]


def full_profile(frame: pd.DataFrame) -> pd.DataFrame:
    """The full-profile rows of a scenarios frame."""
    return frame[frame["throughput_window"] == "full"]


def macro_name(key: str) -> str:
    """Turn a snake_case key into a LaTeX-legal macro name.

    LaTeX control sequences may contain only letters, so digits are spelled out
    and separators dropped: 'md1_mu_S5' -> 'PsaoMdOneMuSFive'.
    """
    digits = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four",
              "5": "Five", "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine"}
    parts = re.split(r"[^A-Za-z0-9]+", key)
    out = []
    for part in parts:
        if not part:
            continue
        chunk = "".join(digits[c] if c.isdigit() else c for c in part)
        out.append(chunk[0].upper() + chunk[1:] if chunk else "")
    return "Psao" + "".join(out)
