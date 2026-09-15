#!/usr/bin/env node
// gap_experiment.js -- what actually drives the rate dependence of jwt.verify().
//
// The in-situ sweep showed verification costing ~950 us at 5 rps and ~455 us at
// 400 rps, on one process, in both an ascending and a descending pass. The
// descending pass is what rules out JIT warmth: by then the process had served
// every higher rate, so if warmth were the driver the low-rate points would
// have been fast. They were not.
//
// This isolates the remaining candidate. One process, one warm code path, no
// HTTP, no server, no cluster, no contention -- the ONLY variable is the delay
// between successive verify calls.
//
// Usage: node gap_experiment.js
const jwt = require('jsonwebtoken');
const SECRET = 'your-super-secret-key-that-is-long';
const token = jwt.sign({ sub: 'user0', name: 'Load User 0' }, SECRET,
  { algorithm: 'HS256', expiresIn: '24h' });

const idle = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // Warm thoroughly: every measurement below runs fully JIT-compiled.
  for (let i = 0; i < 20000; i += 1) jwt.verify(token, SECRET);

  console.log('gap_ms,equivalent_rps,n,mean_us,p50_us,p99_us');
  for (const gap of [0, 1, 2, 5, 10, 20, 50, 100, 200]) {
    const n = gap === 0 ? 20000 : Math.max(60, Math.floor(12000 / gap));
    const samples = [];
    for (let i = 0; i < n; i += 1) {
      if (gap > 0) await idle(gap);
      const started = process.hrtime.bigint();
      jwt.verify(token, SECRET);
      samples.push(Number(process.hrtime.bigint() - started) / 1000);
    }
    samples.sort((a, b) => a - b);
    const mean = samples.reduce((p, c) => p + c, 0) / samples.length;
    console.log([
      gap,
      gap === 0 ? 'tight_loop' : (1000 / gap).toFixed(0),
      n,
      mean.toFixed(2),
      samples[Math.floor(samples.length * 0.5)].toFixed(2),
      samples[Math.floor(samples.length * 0.99)].toFixed(2),
    ].join(','));
  }
})();
