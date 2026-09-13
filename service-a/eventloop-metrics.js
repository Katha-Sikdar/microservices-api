'use strict';
/**
 * eventloop-metrics.js — Prometheus instrumentation for the PSAO testbed.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The manuscript reports a service rate (mu) fitted from the open-loop latency
 * curve and a second, different service rate derived from pod CPU. Those two
 * numbers disagree and the paper cannot currently say why, because nothing in
 * the testbed measured where the time inside the Node.js process actually went.
 * This module closes that gap by exporting three things that are measured, not
 * derived:
 *
 *   1. event-loop delay quantiles (the saturation signal itself),
 *   2. end-to-end request duration,
 *   3. the cost of the *synchronous verification call alone*, isolated from
 *      everything else in the handler, via timeVerify().
 *
 * With (3) in hand the CPU-derived service rate can be attributed to a specific
 * synchronous section rather than inferred from a pod-level average.
 *
 * Exports a factory rather than a singleton so that cluster workers (S9) can
 * each build their own registry with a distinct worker label. See
 * scenarios/s9-cluster-mode.js.
 */

const express = require('express');
const { monitorEventLoopDelay, performance } = require('node:perf_hooks');
const client = require('prom-client');

const NS_PER_MS = 1e6;

/**
 * Request-duration buckets, in SECONDS.
 *
 * The population we care about lives between roughly 3 ms and 15 ms: that is
 * the band the layered-enforcement scenarios (S1..S9) occupy below saturation.
 * Prometheus' default buckets place only three edges (5 ms, 10 ms, 25 ms) in
 * that whole band, which makes a p99 interpolated across the 10-25 ms bucket
 * essentially a guess -- and the p99 is exactly the quantity the paper compares
 * across scenarios. So we spend bucket budget where the mass is: ~1 ms edges
 * through the 3-15 ms band, then a coarse tail that still resolves the
 * post-elbow blow-up (queueing beyond the elbow pushes latency into the
 * hundreds of ms, and a saturated run must not simply pile into +Inf).
 */
const DEFAULT_REQUEST_BUCKETS_S = [
  0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.010,
  0.012, 0.015, 0.020, 0.030, 0.050, 0.100, 0.250, 0.500, 1.0, 2.5,
];

/**
 * Verification-call buckets, in SECONDS.
 *
 * A single HS256 jwt.verify() on a small payload costs order 10-40 us; RS256
 * costs order 100-400 us. Both must be resolvable by the same histogram
 * because the paper compares them directly, so the edges start at 5 us and are
 * roughly geometric up to 10 ms (10 ms being "something pathological happened",
 * e.g. a key reparse or a GC pause landing inside the call).
 */
const DEFAULT_VERIFY_BUCKETS_S = [
  0.000005, 0.00001, 0.00002, 0.00004, 0.00008, 0.00015, 0.0003, 0.0006,
  0.0012, 0.0025, 0.005, 0.010,
];

/**
 * @param {object} [opts]
 * @param {number} [opts.port=9464]        Port for the metrics listener. 9464 is
 *   the OpenTelemetry Prometheus-exporter default; keeping metrics off the
 *   application port matters here because the application port is the thing
 *   being saturated -- scraping it would make the scrape compete with the load
 *   under test and contaminate the measurement.
 * @param {string} [opts.prefix='psao_']
 * @param {number} [opts.eventLoopResolutionMs=1]
 * @param {object} [opts.defaultLabels={}]  e.g. { worker: '3' } for S9.
 * @param {boolean} [opts.resetOnScrape=true]
 * @param {boolean} [opts.collectDefaultMetrics=true]
 * @param {number[]} [opts.requestBuckets]  seconds
 * @param {number[]} [opts.verifyBuckets]   seconds
 * @param {client.Registry} [opts.register] Supply your own registry (S9 does).
 */
function createEventLoopMetrics(opts = {}) {
  const {
    port = Number(process.env.METRICS_PORT || 9464),
    prefix = 'psao_',
    eventLoopResolutionMs = Number(process.env.PSAO_ELD_RESOLUTION_MS || 1),
    defaultLabels = {},
    // Windowed, not cumulative. A monotonically accumulating event-loop
    // histogram averages the pre-saturation and post-saturation regimes
    // together, which is precisely the transition the controller has to see.
    // Resetting on scrape makes every sample "the last scrape interval", so
    // p99 lag is comparable across the ramp steps. Set false if you scrape the
    // endpoint from more than one collector (they would steal each other's
    // windows).
    resetOnScrape = process.env.PSAO_ELD_RESET_ON_SCRAPE !== 'false',
    collectDefaultMetrics = true,
    requestBuckets = DEFAULT_REQUEST_BUCKETS_S,
    verifyBuckets = DEFAULT_VERIFY_BUCKETS_S,
    register = new client.Registry(),
  } = opts;

  if (Object.keys(defaultLabels).length > 0) {
    register.setDefaultLabels(defaultLabels);
  }
  if (collectDefaultMetrics) {
    // Gives us process_cpu_seconds_total, which is the in-process counterpart
    // to the pod-level CPU that capture_pod_metrics.sh samples. Having both
    // lets the analysis separate application CPU from sidecar CPU without
    // trusting the cgroup split alone.
    client.collectDefaultMetrics({ register, prefix });
  }

  /**
   * resolution: 1 ms.
   *
   * monitorEventLoopDelay defaults to 10 ms, which is useless here: the delay
   * values we need to distinguish (a healthy loop at well under 1 ms versus an
   * elbow forming at 2-8 ms) would land in the first one or two buckets and
   * every quantile would read as the same number. 1 ms is the finest setting
   * that is still meaningful -- the underlying libuv timer cannot be trusted
   * below roughly a millisecond -- so it is both the smallest and the only
   * defensible choice for resolving an elbow that forms in single-digit ms.
   */
  const eld = monitorEventLoopDelay({ resolution: eventLoopResolutionMs });
  eld.enable();

  // eventLoopUtilization() is the controller's online mu_eff input: it reports
  // the fraction of wall time the loop was active, i.e. utilisation rho
  // measured directly rather than inferred from latency. Sampled as a delta
  // against the previous scrape so it, too, is a windowed quantity.
  let eluPrev = performance.eventLoopUtilization();

  const g = (name, help) =>
    new client.Gauge({ name: prefix + name, help, registers: [register] });

  const lagP50 = g('eventloop_lag_p50_ms', 'Event-loop delay p50 over the last scrape window (ms).');
  const lagP90 = g('eventloop_lag_p90_ms', 'Event-loop delay p90 over the last scrape window (ms).');
  const lagP99 = g('eventloop_lag_p99_ms', 'Event-loop delay p99 over the last scrape window (ms).');
  const lagMax = g('eventloop_lag_max_ms', 'Event-loop delay maximum over the last scrape window (ms).');
  const lagMean = g('eventloop_lag_mean_ms', 'Event-loop delay mean over the last scrape window (ms).');
  const lagResolution = g('eventloop_lag_resolution_ms', 'Sampling resolution of the event-loop delay monitor (ms).');
  const elu = g('eventloop_utilization', 'Event-loop utilization over the last scrape window (0..1).');
  lagResolution.set(eventLoopResolutionMs);

  const requestDuration = new client.Histogram({
    name: prefix + 'request_duration_seconds',
    help: 'End-to-end request handling duration (seconds).',
    labelNames: ['method', 'route', 'code'],
    buckets: requestBuckets,
    registers: [register],
  });

  const verifyDuration = new client.Histogram({
    name: prefix + 'verify_duration_seconds',
    help: 'Duration of the synchronous token-verification call alone (seconds).',
    labelNames: ['algorithm', 'result'],
    buckets: verifyBuckets,
    registers: [register],
  });

  const verifyTotal = new client.Counter({
    name: prefix + 'verify_total',
    help: 'Token verification calls, by algorithm and outcome.',
    labelNames: ['algorithm', 'result'],
    registers: [register],
  });

  const inFlight = new client.Gauge({
    name: prefix + 'requests_in_flight',
    help: 'Requests currently being handled. Above the elbow this is the queue depth.',
    registers: [register],
  });

  /**
   * Refresh the event-loop gauges from the delay monitor.
   *
   * Attached below as a prom-client `collect` hook rather than being called
   * from the HTTP handler, because the handler is not the only collection path:
   * in cluster mode (S9) the primary harvests each worker over IPC with
   * getMetricsAsJSON(), which never runs our handler. Sampling from the handler
   * alone made every worker report an event-loop lag of exactly zero -- a
   * plausible-looking number that was simply never measured.
   */
  function sampleEventLoop() {
    // percentile()/mean are in NANOSECONDS.
    lagP50.set(eld.percentile(50) / NS_PER_MS);
    lagP90.set(eld.percentile(90) / NS_PER_MS);
    lagP99.set(eld.percentile(99) / NS_PER_MS);
    lagMax.set(eld.max / NS_PER_MS);
    // eld.mean is NaN until at least one sample has been taken.
    lagMean.set(Number.isFinite(eld.mean) ? eld.mean / NS_PER_MS : 0);

    const eluNow = performance.eventLoopUtilization();
    const delta = performance.eventLoopUtilization(eluNow, eluPrev);
    elu.set(Number.isFinite(delta.utilization) ? delta.utilization : 0);
    eluPrev = eluNow;

    if (resetOnScrape) eld.reset();
  }

  // One collect hook drives all the event-loop gauges. prom-client awaits every
  // metric's collect() before serialising, on both the text and the JSON path,
  // so this fires exactly once per collection however the registry is harvested.
  lagP50.collect = sampleEventLoop;

  /**
   * Wrap the synchronous verification call so it is timed in isolation.
   *
   *   const claims = timeVerify('HS256', () => jwt.verify(token, secret));
   *
   * hrtime.bigint() rather than Date.now(): the call is tens of microseconds,
   * far below millisecond clock granularity. The call is timed even when it
   * throws, because a rejected token still consumes event-loop time and a
   * scenario under attack is mostly rejections.
   */
  function timeVerify(algorithm, fn) {
    const started = process.hrtime.bigint();
    let result = 'ok';
    try {
      return fn();
    } catch (err) {
      result = 'error';
      throw err;
    } finally {
      const seconds = Number(process.hrtime.bigint() - started) / 1e9;
      verifyDuration.labels(algorithm, result).observe(seconds);
      verifyTotal.labels(algorithm, result).inc();
    }
  }

  /** Express middleware recording request duration. Mount before your routes. */
  function middleware(req, res, next) {
    const started = process.hrtime.bigint();
    inFlight.inc();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      inFlight.dec();
      const seconds = Number(process.hrtime.bigint() - started) / 1e9;
      // req.route is only populated once routing has happened; fall back to the
      // raw path but never to req.url with its query string (unbounded
      // cardinality would blow up the registry under load).
      const route = (req.route && req.route.path) || req.path || 'unknown';
      requestDuration.labels(req.method, route, String(res.statusCode)).observe(seconds);
    };
    res.on('finish', finish);
    res.on('close', finish); // client hung up mid-flight: still real work done.
    next();
  }

  /** Handler for GET /metrics, if you want to mount it yourself. */
  async function metricsHandler(_req, res) {
    // No explicit sampleEventLoop() here: the collect hook above runs during
    // register.metrics(). Calling it here as well would reset the delay
    // histogram twice per scrape and report the second, empty window.
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  }

  let server = null;

  /** Start the dedicated metrics listener. Returns the http.Server. */
  function startMetricsServer(listenPort = port) {
    if (server) return server;
    const app = express();
    app.get('/metrics', metricsHandler);
    app.get('/healthz', (_req, res) => res.status(200).send('ok'));
    server = app.listen(listenPort, () => {
      // eslint-disable-next-line no-console
      console.log(`[psao-metrics] listening on :${listenPort}/metrics ` +
        `(event-loop resolution ${eventLoopResolutionMs} ms, ` +
        `resetOnScrape=${resetOnScrape})`);
    });
    return server;
  }

  function stop() {
    eld.disable();
    if (server) {
      server.close();
      server = null;
    }
  }

  return {
    register,
    client,
    middleware,
    metricsHandler,
    timeVerify,
    startMetricsServer,
    sampleEventLoop,
    stop,
    metrics: { requestDuration, verifyDuration, verifyTotal, inFlight },
    buckets: { request: requestBuckets, verify: verifyBuckets },
  };
}

module.exports = { createEventLoopMetrics, DEFAULT_REQUEST_BUCKETS_S, DEFAULT_VERIFY_BUCKETS_S };
