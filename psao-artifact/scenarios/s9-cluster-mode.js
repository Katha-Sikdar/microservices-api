#!/usr/bin/env node
'use strict';
/**
 * s9-cluster-mode.js — Scenario S9: the S5 service under Node's cluster module.
 *
 * S9 is the second cheap alternative to PSAO: "the event loop saturates because
 * it is one thread; fork more of them." The artifact has to measure that claim
 * too, and measure it fairly, which is why every worker runs the S5 handler
 * *unmodified* -- same HS256 verification, same middleware, same histogram
 * buckets. The only difference between S5 and S9 is the number of processes.
 *
 * What the measurement is expected to expose (and what the figures must be able
 * to show either way):
 *
 *   - Forking multiplies the *service rate* but does not remove the per-request
 *     verification cost, so amortised CPU per request should be roughly flat
 *     while throughput rises. PSAO's claim is about CPU, not just throughput.
 *   - Each worker has its own event loop, so per-worker lag must be reported
 *     per worker. An average across workers hides an unevenly-loaded one, and
 *     the kernel's SO_REUSEPORT-style distribution is not perfectly even.
 *   - The pod CPU limit does not change. Forking N workers inside a pod capped
 *     at, say, 1000m cannot yield N times the throughput; the cap is where S9's
 *     scaling stops, and run_closedloop_scenario.sh records cpu_limit_millicores
 *     for precisely this comparison.
 *
 * Metrics: workers register with prom-client's cluster AggregatorRegistry and
 * label every series with their worker id, so the primary exposes one merged
 * scrape endpoint in which per-worker series remain distinct (aggregation
 * groups by label set, and the worker label differs). One listener also avoids
 * N metrics ports fighting for the same pod port.
 *
 * Usage:  node scenarios/s9-cluster-mode.js
 * Env:    PORT, METRICS_PORT, JWT_SECRET, WORKERS
 */

const cluster = require('node:cluster');
const os = require('node:os');
const express = require('express');
const jwt = require('jsonwebtoken');
const client = require('prom-client');
const { createEventLoopMetrics } = require('../instrumentation/eventloop-metrics');

const PORT = Number(process.env.PORT || 3000);
const METRICS_PORT = Number(process.env.METRICS_PORT || 9464);
const JWT_SECRET = process.env.JWT_SECRET || 'your-super-secret-key-that-is-long';
// availableParallelism() rather than cpus().length: inside a container with a
// CPU quota, cpus().length reports the *host's* core count and would fork far
// more workers than the pod can run, turning the measurement into a study of
// CFS throttling. availableParallelism respects the effective parallelism.
const WORKERS = Number(process.env.WORKERS || os.availableParallelism());

/**
 * The S5 handler, unmodified. Full-stack scenario: the request has already
 * traversed Edge TLS and the Istio mTLS sidecar by the time it arrives here, so
 * the only work the application does that S1 does not is this HS256
 * verification.
 */
function createS5App(metrics) {
  const products = [
    { id: 1, name: 'Laptop' },
    { id: 2, name: 'Keyboard' },
    { id: 3, name: 'Mouse' },
  ];

  const app = express();
  app.use(metrics.middleware);

  app.get('/products', (req, res) => {
    const authHeader = req.headers.authorization;
    const token = authHeader && authHeader.split(' ')[1];
    if (!token) return res.sendStatus(401);
    try {
      metrics.timeVerify('HS256', () => jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] }));
    } catch (err) {
      return res.sendStatus(403);
    }
    return res.json(products);
  });

  return app;
}

function runPrimary() {
  let shuttingDown = false;

  console.log(`[S9] primary ${process.pid} forking ${WORKERS} workers `
    + `(availableParallelism=${os.availableParallelism()})`);

  for (let i = 0; i < WORKERS; i += 1) cluster.fork();

  cluster.on('exit', (worker, code, signal) => {
    const clean = code === 0 && !signal;
    if (shuttingDown || clean) {
      // A clean exit is our own SIGTERM handler doing its job. Re-forking here
      // would fight the shutdown.
      console.log(`[S9] worker ${worker.id} (pid ${worker.process.pid}) exited cleanly`);
      return;
    }
    // Restarting keeps the load test valid: a dead worker would silently shrink
    // the service rate mid-run and the ramp would attribute that to load.
    console.error(`[S9] worker ${worker.id} (pid ${worker.process.pid}) exited `
      + `code=${code} signal=${signal}; restarting`);
    cluster.fork();
  });

  const aggregator = new client.AggregatorRegistry();
  const app = express();
  app.get('/metrics', async (_req, res) => {
    try {
      const metrics = await aggregator.clusterMetrics();
      res.set('Content-Type', aggregator.contentType);
      res.end(metrics);
    } catch (err) {
      res.status(500).end(String(err));
    }
  });
  app.get('/healthz', (_req, res) => res.status(200).send('ok'));
  const metricsServer = app.listen(METRICS_PORT, () => {
    console.log(`[S9] aggregated metrics on :${METRICS_PORT}/metrics`);
  });

  const shutdown = () => {
    shuttingDown = true;
    metricsServer.close();
    for (const worker of Object.values(cluster.workers)) worker.kill('SIGTERM');
    setTimeout(() => process.exit(0), 500).unref();
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

function runWorker() {
  const workerId = String(cluster.worker.id);
  const m = createEventLoopMetrics({
    defaultLabels: { scenario: 'S9', worker: workerId },
    // No listener in the worker: the primary owns the metrics port and pulls
    // from us over IPC.
  });
  // Tell prom-client's cluster machinery which registry to harvest. Without
  // this it would harvest the global default registry, which our factory does
  // not use.
  client.AggregatorRegistry.setRegistries(m.register);
  // Non-obvious, and prom-client 15.1.3 does not document it: the worker's IPC
  // responder is installed by the AggregatorRegistry CONSTRUCTOR
  // (lib/cluster.js addListeners()), not by requiring the module and not by the
  // static setRegistries() above. Without this line the primary's
  // clusterMetrics() call gets no reply and fails with "Operation timed out",
  // and /metrics silently serves nothing -- an S9 run would look like it had no
  // instrumentation at all. The instance itself is unused; constructing it is
  // the point.
  new client.AggregatorRegistry(); // eslint-disable-line no-new

  const app = createS5App(m);
  // All workers listen on the same port; the primary distributes connections.
  const server = app.listen(PORT, () => {
    console.log(`[S9] worker ${workerId} (pid ${process.pid}) serving :${PORT}`);
  });

  const shutdown = () => {
    server.close();
    m.stop();
    process.exit(0);
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

if (require.main === module) {
  if (cluster.isPrimary) runPrimary();
  else runWorker();
}

module.exports = { createS5App, WORKERS };
