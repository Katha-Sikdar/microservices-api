#!/usr/bin/env python3
"""psao_controller.py -- Predictive Security-Aware Offloading, as running code.

The manuscript describes PSAO in pseudocode. That was the first reason it was
desk-rejected, and this file is the answer: the policy, closed-loop, against a
real Prometheus and a real Kubernetes API, with every decision and every
actuation latency written to disk as it happens.

WHAT IT DOES
------------
Once per control interval it observes the service, estimates the effective
service rate mu_eff, forms rho = lambda / mu_eff, and evaluates

    offload  if  rho > rho_trigger
             or  cpu > cpu_trigger
             or  predicted_latency(rho, mu_eff) > sla

Predicted latency is the M/D/1 waiting time,

    W = 1/mu + rho / (2 * mu * (1 - rho)),

which is the model this artifact argues for over M/M/1: token verification is a
fixed-cost operation, so deterministic service time is the more defensible
assumption, and M/D/1 predicts exactly half the queueing delay of M/M/1 at the
same rho. Using the predicted rather than the observed latency is the
"predictive" in PSAO -- the controller acts on where the queue is heading, which
is the only way to actuate BEFORE the elbow rather than after it.

On trigger it applies an Istio RequestAuthentication plus a matching
AuthorizationPolicy (see policy_template.yaml for why both are required), moving
verification into the Envoy sidecar. It reverts when load falls back below a
lower threshold.

WHAT IT MEASURES ABOUT ITSELF
-----------------------------
Actuation latency: the wall time from the decision instant to the policy being
*observed in effect*. With actuation.confirm=probe that means an actual request
carrying an invalid token is rejected by the sidecar -- data-plane truth, not an
API-server acknowledgement. This is a number the paper needs and does not have,
because a policy that takes longer to take effect than the elbow takes to form
is not a solution.

SAFETY
------
--dry-run performs no cluster writes at all. Ctrl-C reverts to the
application-layer configuration before exiting: leaving a cluster with
verification pinned in the sidecar after the controller has died would be a
silent change to the enforcement point.

Usage:
  python controller/psao_controller.py --config controller/config.yaml
  python controller/psao_controller.py --config controller/config.yaml --dry-run
  python controller/psao_controller.py --config controller/config.yaml --dry-run \
      --replay data/example/controller_trace.csv --out /tmp/replay_trace.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import signal
import string
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

import yaml

LOG = logging.getLogger("psao")

ARTIFACT_ROOT = Path(__file__).resolve().parent.parent

MODE_APP = "app"
MODE_SIDECAR = "sidecar"

DECISION_HOLD = "hold"
DECISION_OFFLOAD = "offload"
DECISION_REVERT = "revert"

TRACE_COLUMNS = [
    "t_unix", "t_rel_s", "lambda_rps", "eventloop_lag_p99_ms", "mu_eff_rps",
    "rho", "latency_mean_ms", "mode", "decision", "actuation_latency_ms",
    "trigger_reason",
]


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """One poll of the service. Any field may be None: a metric that could not
    be read is missing, and a missing metric is never replaced by a default."""
    t_unix: float
    lambda_rps: Optional[float] = None
    eventloop_lag_p99_ms: Optional[float] = None
    latency_mean_ms: Optional[float] = None
    eventloop_utilization: Optional[float] = None
    cpu_millicores: Optional[float] = None

    def missing(self) -> list[str]:
        return [
            name for name in (
                "lambda_rps", "eventloop_lag_p99_ms", "latency_mean_ms",
                "eventloop_utilization", "cpu_millicores",
            ) if getattr(self, name) is None
        ]


class PrometheusUnreachable(RuntimeError):
    """Prometheus could not be contacted at all.

    Distinct from "the query returned nothing": an empty result is a missing
    measurement the controller can honestly record and hold through, whereas an
    unreachable Prometheus means every future observation is blind. The
    controller stops on this rather than logging the same warning forever, which
    is what it used to do -- for as long as you left it running, producing a
    trace full of empty rows that looked like a run.
    """


class PrometheusSource:
    """Instant-query source. One HTTP round trip per configured query."""

    #: Consecutive polls in which EVERY query failed at the transport layer
    #: before the controller gives up. One or two is a restarting port-forward
    #: and is worth riding out; sustained total failure is not.
    MAX_CONSECUTIVE_TRANSPORT_FAILURES = 3

    def __init__(self, url: str, queries: dict, timeout_s: float = 5.0):
        # Imported here so that --replay works on a machine without `requests`
        # installed; the analysis pipeline should not need the controller's deps.
        import requests  # noqa: PLC0415

        self._requests = requests
        self.url = url.rstrip("/")
        self.queries = queries
        self.timeout_s = timeout_s
        self.session = requests.Session()
        self._consecutive_transport_failures = 0
        # Set by _query for the duration of one poll(); see poll().
        self._poll_transport_failures = 0
        self._poll_queries = 0

    def preflight(self) -> None:
        """Fail fast, before any load is applied, if Prometheus is not usable.

        Checks two separate things, because they fail for different reasons and
        need different fixes:
          1. Is Prometheus reachable at all?  (port-forward down, wrong URL)
          2. Does each configured query actually select any series right now?
             (wrong metric name or wrong label selector -- the failure mode this
             controller shipped with)
        Only (1) is fatal. (2) is reported loudly but allowed, because a query
        can legitimately be empty before any traffic has been offered.
        """
        try:
            response = self.session.get(
                f"{self.url}/api/v1/query", params={"query": "1"},
                timeout=self.timeout_s)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise PrometheusUnreachable(
                f"cannot reach Prometheus at {self.url}: {exc}\n"
                f"  The controller needs Prometheus for every observation it makes, "
                f"so it will not start blind.\n"
                f"  If Prometheus runs in the cluster, open the port-forward:\n"
                f"    kubectl -n istio-system port-forward svc/prometheus 9090:9090\n"
                f"  The experiment runners under experiments/ do this for you."
            ) from exc

        empty = []
        for key, promql in self.queries.items():
            if promql and self._query(promql) is None:
                empty.append(key)
        if empty:
            LOG.warning(
                "preflight: %d of %d configured queries return no data right now: %s",
                len(empty), len(self.queries), ", ".join(sorted(empty)))
            LOG.warning(
                "preflight: this is expected before traffic starts, but if it persists "
                "under load the metric name or label selector is wrong -- check "
                "%s/api/v1/targets and the label set the exporter actually emits.",
                self.url)
        else:
            LOG.info("preflight: all %d configured queries return data", len(self.queries))

    def _query(self, promql: str) -> Optional[float]:
        self._poll_queries += 1
        try:
            response = self.session.get(
                f"{self.url}/api/v1/query",
                params={"query": promql},
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # noqa: BLE001 - any failure is "not measured"
            self._poll_transport_failures += 1
            LOG.warning("prometheus query failed (%s): %s", exc, promql.strip()[:80])
            return None

        if body.get("status") != "success":
            LOG.warning("prometheus returned status=%s", body.get("status"))
            return None

        data = body.get("data", {})
        result = data.get("result", [])
        if data.get("resultType") == "scalar":
            raw = data.get("result", [None, None])[1]
        elif result:
            raw = result[0].get("value", [None, None])[1]
        else:
            return None  # empty result: the series does not exist right now

        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        # Prometheus renders division by zero as NaN; that is "no data", not 0.
        return None if math.isnan(value) else value

    def _optional(self, key: str) -> Optional[float]:
        """Query a metric the controller can operate without. An absent query is
        configuration ("we do not collect this"); an absent result is a missing
        measurement. Both yield None, and both are reported in the trace."""
        promql = self.queries.get(key)
        return self._query(promql) if promql else None

    def poll(self) -> Observation:
        self._poll_transport_failures = 0
        self._poll_queries = 0
        observation = Observation(
            t_unix=time.time(),
            lambda_rps=self._query(self.queries["arrival_rate_rps"]),
            eventloop_lag_p99_ms=self._query(self.queries["eventloop_lag_p99_ms"]),
            latency_mean_ms=self._query(self.queries["latency_mean_ms"]),
            eventloop_utilization=self._optional("eventloop_utilization"),
            cpu_millicores=self._optional("cpu_millicores"),
        )

        # Every query in this poll failed to reach Prometheus at all -- not
        # "returned nothing", but "could not ask". Count consecutive occurrences
        # and stop rather than emitting the same warning every poll_interval_s.
        if self._poll_queries and self._poll_transport_failures == self._poll_queries:
            self._consecutive_transport_failures += 1
            if self._consecutive_transport_failures >= self.MAX_CONSECUTIVE_TRANSPORT_FAILURES:
                raise PrometheusUnreachable(
                    f"Prometheus at {self.url} has been unreachable for "
                    f"{self._consecutive_transport_failures} consecutive polls; stopping.\n"
                    f"  Every observation since then was blind, so continuing would only "
                    f"produce a trace of empty rows.\n"
                    f"  Re-open the port-forward and restart:\n"
                    f"    kubectl -n istio-system port-forward svc/prometheus 9090:9090"
                )
        else:
            self._consecutive_transport_failures = 0
        return observation


class ReplaySource:
    """Replay observations from a CSV, for offline testing of the policy.

    Accepts any CSV carrying `lambda_rps`, `eventloop_lag_p99_ms` and
    `latency_mean_ms` -- notably a controller_trace.csv from an earlier run, so a
    recorded load profile can be replayed against a changed policy.

    Note what a replay CANNOT provide: controller_trace.csv has no CPU column and
    no utilisation column, so the CPU trigger term is unavailable and the online
    mu_eff estimator has no occupancy input. The controller reports both facts
    rather than filling them in. Replay exercises the decision logic, hysteresis,
    dwell accounting and trace writing; it does not exercise the CPU term.
    """

    def __init__(self, path: Path, speed: float = 0.0):
        self.path = path
        self.speed = speed  # 0 = as fast as possible; 1.0 = real time
        self._warned_missing: set[str] = set()

    def _column(self, row: dict, name: str) -> Optional[float]:
        raw = (row.get(name) or "").strip()
        if not raw:
            if name not in self._warned_missing:
                self._warned_missing.add(name)
                LOG.info("replay: column %r absent or empty; treated as not measured", name)
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        return None if math.isnan(value) else value

    def observations(self) -> Iterator[Observation]:
        with self.path.open(newline="") as fh:
            lines = [line for line in fh if not line.startswith("#")]
        rows = list(csv.DictReader(lines))
        if not rows:
            raise SystemExit(f"replay file has no rows: {self.path}")

        previous_rel: Optional[float] = None
        for row in rows:
            rel = self._column(row, "t_rel_s")
            if self.speed > 0 and previous_rel is not None and rel is not None:
                delay = (rel - previous_rel) / self.speed
                if delay > 0:
                    time.sleep(delay)
            previous_rel = rel

            lam = self._column(row, "lambda_rps")
            utilization = self._column(row, "eventloop_utilization")
            if utilization is None:
                # controller_trace.csv has no utilisation column, but it does
                # record the mu_eff that was in force. Reconstructing
                # utilization = min(1, lambda/mu_eff) hands the online estimator
                # the same operating point the original run was at, so a replay
                # exercises the estimator instead of silently disabling it.
                #
                # This is a REPLAY CONVENIENCE, not a measurement: it reproduces
                # what the recorded trace already implies. It is why replay is
                # for testing the policy, and why the paper's numbers come from
                # live runs.
                mu_recorded = self._column(row, "mu_eff_rps")
                if lam is not None and mu_recorded and mu_recorded > 0:
                    utilization = min(1.0, lam / mu_recorded)

            yield Observation(
                t_unix=self._column(row, "t_unix") or time.time(),
                lambda_rps=lam,
                eventloop_lag_p99_ms=self._column(row, "eventloop_lag_p99_ms"),
                latency_mean_ms=self._column(row, "latency_mean_ms"),
                eventloop_utilization=utilization,
                cpu_millicores=self._column(row, "cpu_millicores"),
            )


# ---------------------------------------------------------------------------
# Service-rate estimation
# ---------------------------------------------------------------------------

class MuEffEstimator:
    """Maintains mu_eff, the effective service rate of the single server.

    Two modes:

    fixed   Take the value from config. Reproducible and auditable, but it is
            only as good as the fit it came from, and it does not track a
            configuration change (adding mTLS changes mu_eff).

    online  mu_eff = lambda / utilization, EWMA-smoothed.

            Event-loop utilisation is the fraction of wall time the loop was
            busy, measured directly by perf_hooks in the instrumentation module.
            Busy time per request is therefore utilization/lambda, and its
            reciprocal is the service rate the loop is currently achieving. No
            queueing model is inverted to obtain it, which matters: rho computed
            from this mu_eff is an observation, not a restatement of the latency
            the controller is trying to predict.

            Guarded on both inputs. Near idle, utilization is dominated by
            timers and GC rather than request work, and lambda/utilization
            explodes; below the guards the estimate is simply not updated.
    """

    def __init__(self, mode: str, fixed_rps: Optional[float], ewma_alpha: float,
                 min_lambda_rps: float, min_utilization: float):
        if mode not in ("fixed", "online"):
            raise SystemExit(f"control.mu_eff.mode must be 'fixed' or 'online', got {mode!r}")
        if mode == "fixed" and not fixed_rps:
            raise SystemExit(
                "control.mu_eff.mode is 'fixed' but control.mu_eff.fixed_rps is not set.\n"
                "Fill it in from your own elbow fit (analysis/elbow_fit.py reports the\n"
                "fitted mu for M/M/1 and M/D/1). The controller will not invent one."
            )
        self.mode = mode
        self.fixed_rps = fixed_rps
        self.alpha = ewma_alpha
        self.min_lambda_rps = min_lambda_rps
        self.min_utilization = min_utilization
        self.value: Optional[float] = fixed_rps if mode == "fixed" else None
        self.updates = 0
        self.skipped = 0

    def update(self, obs: Observation) -> Optional[float]:
        if self.mode == "fixed":
            return self.value

        lam = obs.lambda_rps
        util = obs.eventloop_utilization
        if lam is None or util is None or lam < self.min_lambda_rps or util < self.min_utilization:
            self.skipped += 1
            return self.value

        instantaneous = lam / util
        if self.value is None:
            self.value = instantaneous
        else:
            self.value = self.alpha * instantaneous + (1.0 - self.alpha) * self.value
        self.updates += 1
        return self.value


def md1_wait_ms(lambda_rps: float, mu_rps: float) -> float:
    """M/D/1 mean response time in milliseconds. inf at or beyond saturation.

    W = 1/mu + rho / (2 * mu * (1 - rho)), with rho = lambda/mu.
    The first term is the deterministic service time, the second the queueing
    delay. At rho >= 1 the queue is unstable and the model has no finite answer;
    returning inf makes the trigger fire, which is the correct behaviour.
    """
    if mu_rps <= 0:
        return math.inf
    rho = lambda_rps / mu_rps
    if rho >= 1.0:
        return math.inf
    return 1000.0 * (1.0 / mu_rps + rho / (2.0 * mu_rps * (1.0 - rho)))


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    decision: str
    reason: str
    rho: Optional[float]
    mu_eff: Optional[float]
    predicted_latency_ms: Optional[float]


@dataclass
class FlapRecord:
    t_unix: float
    would_be: str
    reason: str
    suppressed_by: str


class PolicyEngine:
    """Trigger evaluation plus hysteresis, dwell and flap accounting.

    WHY HYSTERESIS
    --------------
    A single threshold on a noisy signal produces chattering: load hovering at
    rho = 0.70 crosses it on alternate samples, and each crossing is an Istio
    configuration push that moves the enforcement point of a production service.
    Chattering is therefore not merely inelegant, it is a security-relevant
    failure -- during a transition the set of requests being verified where is
    briefly ambiguous.

    Three independent brakes, because they fail differently:

      band          rho_revert < rho_trigger. Handles slow drift around the
                    threshold. Costs responsiveness only inside the band.
      consecutive   The condition must hold for N polls. Handles a single noisy
                    scrape. Costs N * poll_interval of latency on a real change.
      dwell         No opposite transition within min_dwell_s of the last one.
                    Bounds the transition RATE regardless of what the signal
                    does, which is the only one of the three that is robust to a
                    pathological input.

    Every would-be transition that a brake suppresses is logged and counted, and
    lands in controller_trace.csv with trigger_reason 'suppressed:...'. The flap
    count is part of the result: a controller that suppressed forty flaps in a
    ten-minute run is reporting something the paper needs to say out loud.
    """

    def __init__(self, thresholds: dict, hysteresis: dict):
        self.rho_trigger = float(thresholds["rho_trigger"])
        self.rho_revert = float(thresholds["rho_revert"])
        self.cpu_trigger = thresholds.get("cpu_trigger_millicores")
        self.cpu_revert = thresholds.get("cpu_revert_millicores")
        self.sla_latency_ms = float(thresholds["sla_latency_ms"])
        self.latency_revert_margin = float(thresholds.get("latency_revert_margin", 0.8))

        if self.rho_revert >= self.rho_trigger:
            raise SystemExit(
                "control.thresholds.rho_revert must be strictly below rho_trigger; "
                "equal thresholds are what hysteresis exists to prevent."
            )

        self.consecutive_trigger = int(hysteresis["consecutive_trigger_samples"])
        self.consecutive_revert = int(hysteresis["consecutive_revert_samples"])
        self.min_dwell_s = float(hysteresis["min_dwell_s"])

        self.mode = MODE_APP
        self._trigger_streak = 0
        self._revert_streak = 0
        self._last_transition_monotonic: Optional[float] = None
        self.flaps: list[FlapRecord] = []
        self.transitions = 0

    # -- trigger terms -------------------------------------------------------

    def _offload_terms(self, rho, cpu, predicted_ms) -> list[str]:
        reasons = []
        if rho is not None and rho > self.rho_trigger:
            reasons.append(f"rho={rho:.3f}>{self.rho_trigger:g}")
        if cpu is not None and self.cpu_trigger is not None and cpu > float(self.cpu_trigger):
            reasons.append(f"cpu={cpu:.0f}m>{float(self.cpu_trigger):g}m")
        if predicted_ms is not None and predicted_ms > self.sla_latency_ms:
            shown = "inf" if math.isinf(predicted_ms) else f"{predicted_ms:.2f}"
            reasons.append(f"predicted_latency={shown}ms>{self.sla_latency_ms:g}ms")
        return reasons

    def _revert_terms(self, rho, cpu, predicted_ms) -> list[str]:
        """Revert requires ALL available terms to be back inside the lower band.

        Conjunction, not disjunction: offloading is triggered by any one signal
        going bad, so reverting must require every signal to be good. Reverting
        on one signal alone would put verification back on an event loop that
        another signal says is still in trouble.
        """
        checks, reasons = [], []
        if rho is not None:
            ok = rho < self.rho_revert
            checks.append(ok)
            reasons.append(f"rho={rho:.3f}{'<' if ok else '>='}{self.rho_revert:g}")
        if cpu is not None and self.cpu_revert is not None:
            ok = cpu < float(self.cpu_revert)
            checks.append(ok)
            reasons.append(f"cpu={cpu:.0f}m{'<' if ok else '>='}{float(self.cpu_revert):g}m")
        if predicted_ms is not None:
            limit = self.sla_latency_ms * self.latency_revert_margin
            ok = predicted_ms < limit
            checks.append(ok)
            shown = "inf" if math.isinf(predicted_ms) else f"{predicted_ms:.2f}"
            reasons.append(f"predicted_latency={shown}ms{'<' if ok else '>='}{limit:.2f}ms")
        if not checks:
            return []  # nothing measurable: cannot justify a revert
        return reasons if all(checks) else []

    # -- main entry point ----------------------------------------------------

    def evaluate(self, obs: Observation, mu_eff: Optional[float],
                 now_monotonic: float) -> Decision:
        rho = None
        predicted_ms = None
        if mu_eff is not None and mu_eff > 0 and obs.lambda_rps is not None:
            rho = obs.lambda_rps / mu_eff
            predicted_ms = md1_wait_ms(obs.lambda_rps, mu_eff)

        if rho is None:
            # Without rho there is no PSAO decision to make. Say so explicitly
            # rather than falling back to the observed latency, which would be a
            # different controller than the one the paper describes.
            missing = ",".join(obs.missing()) or "mu_eff"
            self._trigger_streak = 0
            self._revert_streak = 0
            return Decision(DECISION_HOLD, f"no_rho(missing:{missing})", None, mu_eff, None)

        dwell_ok, dwell_remaining = self._dwell(now_monotonic)

        if self.mode == MODE_APP:
            reasons = self._offload_terms(rho, obs.cpu_millicores, predicted_ms)
            self._revert_streak = 0
            if not reasons:
                self._trigger_streak = 0
                return Decision(DECISION_HOLD, f"below_trigger(rho={rho:.3f})",
                                rho, mu_eff, predicted_ms)
            self._trigger_streak += 1
            joined = "|".join(reasons)
            if self._trigger_streak < self.consecutive_trigger:
                return self._suppress(obs, DECISION_OFFLOAD, joined,
                                      f"consecutive({self._trigger_streak}/{self.consecutive_trigger})",
                                      rho, mu_eff, predicted_ms)
            if not dwell_ok:
                return self._suppress(obs, DECISION_OFFLOAD, joined,
                                      f"dwell({dwell_remaining:.1f}s_remaining)",
                                      rho, mu_eff, predicted_ms)
            return Decision(DECISION_OFFLOAD, joined, rho, mu_eff, predicted_ms)

        # mode == sidecar
        reasons = self._revert_terms(rho, obs.cpu_millicores, predicted_ms)
        self._trigger_streak = 0
        if not reasons:
            self._revert_streak = 0
            return Decision(DECISION_HOLD, f"above_revert(rho={rho:.3f})",
                            rho, mu_eff, predicted_ms)
        self._revert_streak += 1
        joined = "|".join(reasons)
        if self._revert_streak < self.consecutive_revert:
            return self._suppress(obs, DECISION_REVERT, joined,
                                  f"consecutive({self._revert_streak}/{self.consecutive_revert})",
                                  rho, mu_eff, predicted_ms)
        if not dwell_ok:
            return self._suppress(obs, DECISION_REVERT, joined,
                                  f"dwell({dwell_remaining:.1f}s_remaining)",
                                  rho, mu_eff, predicted_ms)
        return Decision(DECISION_REVERT, joined, rho, mu_eff, predicted_ms)

    def _dwell(self, now_monotonic: float) -> tuple[bool, float]:
        if self._last_transition_monotonic is None:
            return True, 0.0
        elapsed = now_monotonic - self._last_transition_monotonic
        remaining = self.min_dwell_s - elapsed
        return remaining <= 0, max(0.0, remaining)

    def _suppress(self, obs, would_be, reason, suppressed_by,
                  rho, mu_eff, predicted_ms) -> Decision:
        record = FlapRecord(obs.t_unix, would_be, reason, suppressed_by)
        self.flaps.append(record)
        LOG.info("SUPPRESSED FLAP: would %s (%s) but blocked by %s [suppressed so far: %d]",
                 would_be, reason, suppressed_by, len(self.flaps))
        return Decision(DECISION_HOLD, f"suppressed:{would_be}:{suppressed_by}:{reason}",
                        rho, mu_eff, predicted_ms)

    def commit(self, decision: str, now_monotonic: float) -> None:
        """Record that a transition actually completed."""
        self.mode = MODE_SIDECAR if decision == DECISION_OFFLOAD else MODE_APP
        self._last_transition_monotonic = now_monotonic
        self._trigger_streak = 0
        self._revert_streak = 0
        self.transitions += 1


# ---------------------------------------------------------------------------
# Actuation
# ---------------------------------------------------------------------------

@dataclass
class ActuationResult:
    ok: bool
    latency_ms: Optional[float]
    detail: str


class Actuator:
    """Base class. Subclasses apply and revert the offload policy."""

    def apply(self, reason: str) -> ActuationResult:
        raise NotImplementedError

    def revert(self, reason: str) -> ActuationResult:
        raise NotImplementedError

    @property
    def applied(self) -> bool:
        raise NotImplementedError


class DryRunActuator(Actuator):
    """Performs no cluster writes.

    It still renders the manifests (so a template error is caught) and still
    TIMES the code path it executes. The recorded actuation_latency_ms is the
    genuine wall time of that local path -- typically well under a millisecond.
    It is NOT an estimate of what a real cluster would take, and the trace marks
    every dry-run row so nobody can mistake it for one.
    """

    def __init__(self, manifests: Callable[[str], list[dict]]):
        self._manifests = manifests
        self._applied = False

    @property
    def applied(self) -> bool:
        return self._applied

    def apply(self, reason: str) -> ActuationResult:
        started = time.perf_counter()
        rendered = self._manifests(reason)
        self._applied = True
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        kinds = ",".join(m.get("kind", "?") for m in rendered)
        LOG.info("[dry-run] would apply %s (%s); local path took %.3f ms "
                 "-- this is NOT a cluster actuation latency", kinds, reason, elapsed_ms)
        return ActuationResult(True, elapsed_ms, f"dry-run:apply:{kinds}")

    def revert(self, reason: str) -> ActuationResult:
        started = time.perf_counter()
        # Render the manifests here too: the real revert has to render them to
        # know what to delete, so timing the same work keeps the dry-run path
        # comparable with the live one instead of reporting a bare 0.000 ms.
        rendered = self._manifests(reason)
        self._applied = False
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        names = ",".join(m["metadata"]["name"] for m in rendered)
        LOG.info("[dry-run] would delete %s (%s); local path took %.3f ms "
                 "-- this is NOT a cluster actuation latency", names, reason, elapsed_ms)
        return ActuationResult(True, elapsed_ms, f"dry-run:revert:{names}")


class KubernetesActuator(Actuator):
    """Applies and removes the Istio policy through the Kubernetes API.

    ACTUATION LATENCY: what is being timed
    --------------------------------------
    The clock starts at the decision, not at the API call. It stops when the
    policy is *observed in effect*, and `confirm` chooses what that means:

      resource  the API server returns the object. This is the control plane's
                write latency and nothing more. Envoy has not necessarily been
                reconfigured yet, so this UNDERSTATES the real number, usually by
                seconds. Available everywhere; useful as a lower bound.
      probe     a request carrying a deliberately malformed token is rejected by
                the sidecar. This is the data plane actually enforcing, which is
                the only definition that supports the paper's claim about acting
                before the elbow.
      none      no confirmation; latency is left empty rather than guessed.

    On revert with confirm=probe the condition inverts: we wait until the same
    malformed-token request is no longer rejected by the sidecar, i.e. until it
    reaches the application again.
    """

    ISTIO_GROUP = "security.istio.io"
    ISTIO_VERSION = "v1"
    PLURALS = {
        "RequestAuthentication": "requestauthentications",
        "AuthorizationPolicy": "authorizationpolicies",
    }

    def __init__(self, manifests: Callable[[str], list[dict]], namespace: str,
                 context: Optional[str], actuation: dict):
        from kubernetes import client, config as kube_config  # noqa: PLC0415

        self._manifests = manifests
        self.namespace = namespace
        self.confirm = actuation.get("confirm", "resource")
        self.probe_url = actuation.get("probe_url")
        self.probe_verify_tls = bool(actuation.get("probe_verify_tls", False))
        self.probe_interval_s = float(actuation.get("probe_interval_s", 0.25))
        # A real, currently-valid token, used for the positive half of the
        # confirmation. Read from a file so it stays out of the process table.
        self._probe_token = ""
        token_file = actuation.get("probe_token_file")
        if token_file:
            # Relative paths resolve against the ARTIFACT ROOT, not the process
            # cwd. The controller is launched from wherever the operator happens
            # to be standing, and a path that silently fails to resolve here
            # downgrades the actuation confirmation to its one-sided form --
            # which is the exact weakness probe_token_file exists to remove.
            candidate = Path(token_file)
            if not candidate.is_absolute():
                candidate = Path(__file__).resolve().parent.parent / candidate
            try:
                self._probe_token = candidate.read_text().splitlines()[0].strip()
                LOG.info("actuation probe token loaded from %s", candidate)
            except (OSError, IndexError) as exc:
                LOG.warning("could not read actuation.probe_token_file %s: %s", candidate, exc)
        self.timeout_s = float(actuation.get("timeout_s", 30.0))
        self._applied = False

        try:
            kube_config.load_kube_config(context=context)
            LOG.info("loaded kubeconfig (context=%s)", context or "current")
        except Exception as kubeconfig_error:  # noqa: BLE001
            try:
                kube_config.load_incluster_config()
                LOG.info("loaded in-cluster configuration")
            except Exception as incluster_error:  # noqa: BLE001
                # This is the most likely first-run failure, so it gets a real
                # message rather than a traceback from deep inside the client.
                raise SystemExit(
                    "cannot reach a Kubernetes cluster.\n"
                    f"  kubeconfig : {kubeconfig_error}\n"
                    f"  in-cluster : {incluster_error}\n"
                    "Set kubernetes.context in the config, point KUBECONFIG at a "
                    "working file, or run with --dry-run to exercise the policy "
                    "without a cluster."
                ) from incluster_error
        self.api = client.CustomObjectsApi()

        if self.confirm == "probe":
            if not self.probe_url:
                raise SystemExit("actuation.confirm is 'probe' but actuation.probe_url is unset")
            import requests  # noqa: PLC0415
            self._requests = requests
            self._probe_session = requests.Session()

    @property
    def applied(self) -> bool:
        return self._applied

    # -- cluster writes ------------------------------------------------------

    def _plural(self, kind: str) -> str:
        try:
            return self.PLURALS[kind]
        except KeyError:
            raise SystemExit(f"policy_template.yaml contains unsupported kind {kind!r}")

    def _put(self, manifest: dict) -> None:
        kind = manifest["kind"]
        name = manifest["metadata"]["name"]
        kwargs = dict(group=self.ISTIO_GROUP, version=self.ISTIO_VERSION,
                      namespace=self.namespace, plural=self._plural(kind))
        try:
            self.api.create_namespaced_custom_object(body=manifest, **kwargs)
            LOG.info("created %s/%s", kind, name)
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "status", None) != 409:
                raise
            # Already present (a previous run, or a partial apply). Replace so
            # the cluster ends up in the state we intend rather than an unknown
            # mixture of the two.
            existing = self.api.get_namespaced_custom_object(name=name, **kwargs)
            manifest["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
            self.api.replace_namespaced_custom_object(name=name, body=manifest, **kwargs)
            LOG.info("replaced existing %s/%s", kind, name)

    def _delete(self, manifest: dict) -> None:
        kind = manifest["kind"]
        name = manifest["metadata"]["name"]
        try:
            self.api.delete_namespaced_custom_object(
                group=self.ISTIO_GROUP, version=self.ISTIO_VERSION,
                namespace=self.namespace, plural=self._plural(kind), name=name)
            LOG.info("deleted %s/%s", kind, name)
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "status", None) == 404:
                LOG.info("%s/%s already absent", kind, name)
            else:
                raise

    # -- confirmation --------------------------------------------------------

    def _probe_rejected_by_sidecar(self) -> Optional[bool]:
        """True when the sidecar rejects a deliberately invalid token.

        Envoy's jwt_authn filter answers 401 with a body beginning 'Jwt'
        ('Jwt is not in the form of Header.Payload.Signature',
        'Jwt verification fails'). The application answers 403 for a bad token
        and 401 only for a missing one, so the two enforcement points are
        distinguishable from the response alone. Returns None if the probe
        itself failed, which is not evidence either way.
        """
        try:
            response = self._probe_session.get(
                self.probe_url,
                headers={"Authorization": "Bearer not-a-valid-token"},
                timeout=2.0,
                verify=self.probe_verify_tls,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.debug("probe request failed: %s", exc)
            return None
        body = (response.text or "")[:64]
        return response.status_code == 401 and body.strip().startswith("Jwt")

    def _probe_valid_token_accepted(self) -> Optional[bool]:
        """True when a VALID token still gets a 2xx.

        The malformed-token probe alone is one-sided. A misconfigured jwksUri
        makes Envoy reject EVERY token, valid ones included, with exactly the
        401/'Jwt...' the malformed probe is looking for -- so a uniformly broken
        endpoint confirms as a successful offload, and the trace records an
        actuation latency for an outage. That is not hypothetical: the shipped
        config pointed jwksUri at a domain that does not resolve.

        Offload is 'in effect' only when BOTH hold: bad tokens are stopped at
        the sidecar, and good ones still reach the application. Returns None if
        the probe itself failed, which is not evidence either way.
        """
        if not self._probe_token:
            return None
        try:
            response = self._probe_session.get(
                self.probe_url,
                headers={"Authorization": f"Bearer {self._probe_token}"},
                timeout=2.0,
                verify=self.probe_verify_tls,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.debug("valid-token probe failed: %s", exc)
            return None
        return 200 <= response.status_code < 300

    def _probe_offload_in_effect(self) -> Optional[bool]:
        """Both halves, combined, for use as the apply-confirmation predicate."""
        rejected = self._probe_rejected_by_sidecar()
        if rejected is not True:
            return rejected
        if not self._probe_token:
            # No valid token configured: fall back to the one-sided check rather
            # than blocking, but say so, because the confirmation is weaker.
            LOG.warning("actuation.probe_token is unset: confirming offload on the "
                        "malformed-token check alone. A uniformly rejecting endpoint "
                        "would be indistinguishable from a working offload.")
            return True
        accepted = self._probe_valid_token_accepted()
        if accepted is None:
            return None
        if not accepted:
            LOG.error("offload applied but a VALID token is being rejected: the "
                      "endpoint is broken, not offloaded. Check the JWKS, the "
                      "issuer and the audience against the tokens in use.")
            return False
        return True

    def _await_condition(self, predicate: Callable[[], Optional[bool]], want: bool,
                         started: float) -> tuple[bool, str]:
        deadline = started + self.timeout_s
        polls = 0
        while time.perf_counter() < deadline:
            polls += 1
            observed = predicate()
            if observed is want:
                return True, f"confirmed after {polls} polls"
            time.sleep(self.probe_interval_s)
        return False, f"timed out after {self.timeout_s:g}s ({polls} polls)"

    def _resource_present(self, manifests: list[dict]) -> Optional[bool]:
        for manifest in manifests:
            try:
                self.api.get_namespaced_custom_object(
                    group=self.ISTIO_GROUP, version=self.ISTIO_VERSION,
                    namespace=self.namespace, plural=self._plural(manifest["kind"]),
                    name=manifest["metadata"]["name"])
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "status", None) == 404:
                    return False
                return None
        return True

    # -- public API ----------------------------------------------------------

    def apply(self, reason: str) -> ActuationResult:
        started = time.perf_counter()
        manifests = self._manifests(reason)
        applied: list[dict] = []
        try:
            for manifest in manifests:
                self._put(manifest)
                applied.append(manifest)
        except Exception as exc:  # noqa: BLE001
            # A half-applied offload is the dangerous state: a
            # RequestAuthentication without its AuthorizationPolicy leaves the
            # endpoint reachable without a token. Roll back before re-raising.
            LOG.error("apply failed (%s); rolling back %d object(s)", exc, len(applied))
            for manifest in reversed(applied):
                try:
                    self._delete(manifest)
                except Exception:  # noqa: BLE001
                    LOG.exception("rollback of %s failed -- CLUSTER MAY BE INCONSISTENT",
                                  manifest["metadata"]["name"])
            return ActuationResult(False, None, f"apply-failed:{exc}")

        self._applied = True
        if self.confirm == "none":
            return ActuationResult(True, None, "applied (no confirmation configured)")
        if self.confirm == "probe":
            ok, detail = self._await_condition(self._probe_offload_in_effect, True, started)
        else:
            ok, detail = self._await_condition(lambda: self._resource_present(manifests), True, started)
        latency_ms = (time.perf_counter() - started) * 1000.0
        # A timeout still gets its measured latency recorded, flagged as
        # unconfirmed. Dropping it would hide the worst actuations from the
        # very distribution the paper needs to report.
        return ActuationResult(ok, latency_ms, f"{self.confirm}:{detail}")

    def revert(self, reason: str) -> ActuationResult:
        started = time.perf_counter()
        manifests = self._manifests(reason)
        failures = []
        for manifest in reversed(manifests):
            try:
                self._delete(manifest)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{manifest['metadata']['name']}:{exc}")
        if failures:
            LOG.error("revert incomplete: %s", "; ".join(failures))
            return ActuationResult(False, None, "revert-failed:" + ";".join(failures))

        self._applied = False
        if self.confirm == "none":
            return ActuationResult(True, None, "reverted (no confirmation configured)")
        if self.confirm == "probe":
            ok, detail = self._await_condition(self._probe_rejected_by_sidecar, False, started)
        else:
            ok, detail = self._await_condition(lambda: self._resource_present(manifests), False, started)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return ActuationResult(ok, latency_ms, f"{self.confirm}:{detail}")


# ---------------------------------------------------------------------------
# Manifest rendering
# ---------------------------------------------------------------------------

def build_manifest_renderer(config: dict, template_path: Path) -> Callable[[str], list[dict]]:
    kube = config["kubernetes"]
    jwt = kube["jwt"]
    jwks_uri = jwt.get("jwks_uri")
    jwks_inline = jwt.get("jwks_inline")
    if bool(jwks_uri) == bool(jwks_inline):
        raise SystemExit(
            "kubernetes.jwt: set exactly one of jwks_uri or jwks_inline. "
            "Envoy needs keys from one source or the other, and the choice is a "
            "trust-boundary decision (see config.yaml)."
        )
    if jwks_uri:
        jwks_field = f'jwksUri: "{jwks_uri}"'
    else:
        # yaml.safe_dump of the inline JWKS keeps the quoting correct for what is
        # a JSON document embedded in a YAML string field.
        jwks_field = "jwks: " + yaml.safe_dump(
            jwks_inline if isinstance(jwks_inline, str) else yaml.safe_dump(jwks_inline)
        ).strip()

    template = string.Template(template_path.read_text())

    def render(reason: str) -> list[dict]:
        text = template.substitute(
            policy_name=kube["policy_name"],
            namespace=kube["namespace"],
            selector_key=kube["selector_key"],
            selector_value=kube["selector_value"],
            issuer=jwt["issuer"],
            audience=jwt["audience"],
            jwks_field=jwks_field,
            payload_header=jwt.get("payload_header", "x-psao-jwt-payload"),
            # Truncated and quote-stripped: this lands in a Kubernetes
            # annotation, where a stray quote would produce an invalid object.
            reason=reason.replace('"', "'")[:200],
            applied_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        documents = [d for d in yaml.safe_load_all(text) if d]
        if len(documents) != 2:
            raise SystemExit(
                f"policy_template.yaml rendered {len(documents)} documents; expected 2 "
                "(RequestAuthentication + AuthorizationPolicy). Both are required; see "
                "the header comment in that file."
            )
        return documents

    return render


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

class TraceWriter:
    """Appends one row per poll and flushes immediately.

    Flushing every row costs a syscall per control interval and buys the ability
    to inspect a run in progress, and to keep every row up to the moment of a
    crash. For a 2 s interval that trade is not close.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("w", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=TRACE_COLUMNS)
        self._writer.writeheader()
        self._fh.flush()
        self.rows = 0

    @staticmethod
    def _fmt(value: Optional[float], digits: int = 4) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "inf" if value == math.inf else ""
        return f"{value:.{digits}f}"

    def write(self, obs: Observation, t_rel_s: float, decision: Decision,
              mode: str, actuation_latency_ms: Optional[float]) -> None:
        self._writer.writerow({
            "t_unix": f"{obs.t_unix:.3f}",
            "t_rel_s": f"{t_rel_s:.3f}",
            "lambda_rps": self._fmt(obs.lambda_rps, 3),
            "eventloop_lag_p99_ms": self._fmt(obs.eventloop_lag_p99_ms, 4),
            "mu_eff_rps": self._fmt(decision.mu_eff, 3),
            "rho": self._fmt(decision.rho, 4),
            "latency_mean_ms": self._fmt(obs.latency_mean_ms, 4),
            "mode": mode,
            "decision": decision.decision,
            "actuation_latency_ms": self._fmt(actuation_latency_ms, 3),
            "trigger_reason": decision.reason,
        })
        self._fh.flush()
        self.rows += 1

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass
class RunSummary:
    polls: int = 0
    transitions: int = 0
    suppressed_flaps: int = 0
    actuation_latencies_ms: list[float] = field(default_factory=list)
    missing_observations: int = 0
    # Per-metric counts. "900 polls had a missing metric" is alarming and
    # uninformative; "cpu_millicores missing on all 900 polls, everything else
    # present" tells the operator exactly what is not wired up.
    missing_by_metric: dict = field(default_factory=dict)


class Controller:
    def __init__(self, config: dict, actuator: Actuator, engine: PolicyEngine,
                 estimator: MuEffEstimator, trace: TraceWriter, dry_run: bool,
                 virtual_time: bool = False):
        self.config = config
        self.actuator = actuator
        self.engine = engine
        self.estimator = estimator
        self.trace = trace
        self.dry_run = dry_run
        # In replay the dwell timer must run on the REPLAYED clock. Against
        # time.monotonic() a 600 s trace replayed in 40 ms would look like one
        # instant, min_dwell_s would suppress every transition after the first,
        # and the replay would be testing the reader's disk speed rather than
        # the policy.
        self.virtual_time = virtual_time
        self.summary = RunSummary()
        self._stop = False
        self._t0_unix: Optional[float] = None

    def _now(self, obs: Observation) -> float:
        return obs.t_unix if self.virtual_time else time.monotonic()

    def request_stop(self, signum, _frame) -> None:
        LOG.warning("signal %s received: finishing this interval, then reverting to "
                    "the application-layer configuration", signal.Signals(signum).name)
        self._stop = True

    def step(self, obs: Observation) -> None:
        if self._t0_unix is None:
            self._t0_unix = obs.t_unix
        t_rel = obs.t_unix - self._t0_unix
        self.summary.polls += 1
        missing = obs.missing()
        if missing:
            self.summary.missing_observations += 1
            for name in missing:
                self.summary.missing_by_metric[name] = \
                    self.summary.missing_by_metric.get(name, 0) + 1

        now = self._now(obs)
        mu_eff = self.estimator.update(obs)
        decision = self.engine.evaluate(obs, mu_eff, now)

        actuation_latency_ms: Optional[float] = None
        effective_decision = decision

        if decision.decision in (DECISION_OFFLOAD, DECISION_REVERT):
            action = self.actuator.apply if decision.decision == DECISION_OFFLOAD else self.actuator.revert
            result = action(decision.reason)
            if result.ok:
                self.engine.commit(decision.decision, now)
                self.summary.transitions += 1
                actuation_latency_ms = result.latency_ms
                if result.latency_ms is not None:
                    self.summary.actuation_latencies_ms.append(result.latency_ms)
                LOG.info("%s -> mode=%s actuation=%s (%s)", decision.decision.upper(),
                         self.engine.mode,
                         "n/a" if result.latency_ms is None else f"{result.latency_ms:.1f}ms",
                         result.detail)
            else:
                # Failed actuation: the mode did NOT change. Record it as a hold
                # with the failure in trigger_reason so the trace never claims a
                # transition that did not happen.
                LOG.error("%s FAILED: %s", decision.decision.upper(), result.detail)
                effective_decision = Decision(
                    DECISION_HOLD, f"actuation_failed:{decision.decision}:{result.detail}",
                    decision.rho, decision.mu_eff, decision.predicted_latency_ms)
                actuation_latency_ms = result.latency_ms

        self.trace.write(obs, t_rel, effective_decision, self.engine.mode, actuation_latency_ms)

        LOG.debug("t=%.1fs lambda=%s mu_eff=%s rho=%s mode=%s decision=%s (%s)",
                  t_rel, obs.lambda_rps, mu_eff, decision.rho, self.engine.mode,
                  effective_decision.decision, effective_decision.reason)

    def run_live(self, source: PrometheusSource, poll_interval_s: float,
                 duration_s: Optional[float]) -> None:
        started = time.monotonic()
        while not self._stop:
            loop_start = time.monotonic()
            self.step(source.poll())
            if duration_s is not None and time.monotonic() - started >= duration_s:
                LOG.info("configured duration reached")
                break
            # Subtract the work we just did so the poll cadence is the interval,
            # not the interval plus however long Prometheus took.
            sleep_for = poll_interval_s - (time.monotonic() - loop_start)
            if sleep_for > 0:
                time.sleep(sleep_for)

    def run_replay(self, source: ReplaySource) -> None:
        for obs in source.observations():
            if self._stop:
                break
            self.step(obs)

    def shutdown(self, revert_on_exit: bool) -> None:
        self.summary.suppressed_flaps = len(self.engine.flaps)
        if revert_on_exit and self.actuator.applied:
            LOG.warning("reverting to the application-layer configuration before exit")
            result = self.actuator.revert("controller shutdown")
            if not result.ok:
                LOG.error("REVERT ON EXIT FAILED: %s -- the cluster is still enforcing "
                          "in the sidecar. Remove the policy manually:\n"
                          "  kubectl delete requestauthentication,authorizationpolicy "
                          "-l app.kubernetes.io/managed-by=psao-controller -n %s",
                          result.detail, self.config["kubernetes"]["namespace"])
        elif self.actuator.applied:
            LOG.warning("--no-revert-on-exit: leaving the offload policy in place")
        self.trace.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ARTIFACT_ROOT / path)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PSAO controller: relocate JWT verification to the Envoy "
                    "sidecar before the event loop saturates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"),
                        help="YAML configuration file")
    parser.add_argument("--dry-run", action="store_true",
                        help="never write to the cluster; render manifests and decide only")
    parser.add_argument("--replay", metavar="CSV",
                        help="replay observations from a CSV (e.g. an existing "
                             "controller_trace.csv) instead of polling Prometheus")
    parser.add_argument("--replay-speed", type=float, default=0.0,
                        help="0 = as fast as possible, 1.0 = original wall-clock pacing")
    parser.add_argument("--out", metavar="CSV",
                        help="controller trace output path (overrides output.trace)")
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after this many seconds (live mode only)")
    parser.add_argument("--no-revert-on-exit", action="store_true",
                        help="leave the offload policy in place on exit. Off by "
                             "default: an orphaned policy silently moves the "
                             "enforcement point of a running service.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S")

    config_path = resolve_path(args.config)
    config = yaml.safe_load(config_path.read_text())

    control = config["control"]
    mu_cfg = control["mu_eff"]
    estimator = MuEffEstimator(
        mode=mu_cfg["mode"],
        fixed_rps=mu_cfg.get("fixed_rps"),
        ewma_alpha=float(mu_cfg.get("ewma_alpha", 0.3)),
        min_lambda_rps=float(mu_cfg.get("min_lambda_rps", 20.0)),
        min_utilization=float(mu_cfg.get("min_utilization", 0.02)))
    engine = PolicyEngine(control["thresholds"], control["hysteresis"])

    renderer = build_manifest_renderer(config, Path(__file__).parent / "policy_template.yaml")

    if args.dry_run:
        actuator: Actuator = DryRunActuator(renderer)
        LOG.warning("DRY RUN: no cluster writes. Recorded actuation latencies are the "
                    "local code path only and must not be published as cluster numbers.")
    else:
        actuator = KubernetesActuator(
            renderer,
            namespace=config["kubernetes"]["namespace"],
            context=config["kubernetes"].get("context"),
            actuation=config["actuation"])

    trace_path = resolve_path(args.out or config["output"]["trace"])
    trace = TraceWriter(trace_path)
    LOG.info("writing controller trace to %s", trace_path)

    controller = Controller(config, actuator, engine, estimator, trace, args.dry_run,
                            virtual_time=bool(args.replay))
    signal.signal(signal.SIGINT, controller.request_stop)
    signal.signal(signal.SIGTERM, controller.request_stop)

    exit_code = 0
    try:
        if args.replay:
            replay_path = resolve_path(args.replay)
            LOG.info("replaying observations from %s", replay_path)
            controller.run_replay(ReplaySource(replay_path, speed=args.replay_speed))
        else:
            source = PrometheusSource(
                url=config["prometheus"]["url"],
                queries=config["prometheus"]["queries"],
                timeout_s=float(config["prometheus"].get("timeout_s", 5.0)))
            source.preflight()
            controller.run_live(source, float(control["poll_interval_s"]), args.duration)
    except KeyboardInterrupt:
        LOG.warning("interrupted")
    except PrometheusUnreachable as exc:
        # One clear error, no traceback: the cause is operational, not a bug,
        # and a stack trace here buries the remediation.
        LOG.error("%s", exc)
        exit_code = 1
    except Exception:  # noqa: BLE001
        LOG.exception("controller failed")
        exit_code = 1
    finally:
        controller.shutdown(revert_on_exit=not args.no_revert_on_exit)

    s = controller.summary
    latencies = s.actuation_latencies_ms
    LOG.info("---- run summary ----")
    LOG.info("polls               : %d", s.polls)
    LOG.info("polls with a missing metric : %d", s.missing_observations)
    for name, count in sorted(s.missing_by_metric.items(), key=lambda kv: -kv[1]):
        LOG.info("    %-24s missing on %d of %d polls", name, count, s.polls)
    LOG.info("transitions         : %d", s.transitions)
    LOG.info("suppressed flaps    : %d", s.suppressed_flaps)
    if latencies:
        LOG.info("actuation latency ms: min=%.1f mean=%.1f max=%.1f (n=%d)%s",
                 min(latencies), sum(latencies) / len(latencies), max(latencies),
                 len(latencies), "  [DRY RUN -- local path only]" if args.dry_run else "")
    else:
        LOG.info("actuation latency ms: none recorded (no transition completed)")
    if estimator.mode == "online":
        LOG.info("mu_eff updates      : %d applied, %d skipped by the input guards",
                 estimator.updates, estimator.skipped)
    LOG.info("trace rows          : %d -> %s", trace.rows, trace_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
