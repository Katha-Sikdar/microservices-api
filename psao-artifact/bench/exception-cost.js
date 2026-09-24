/**
 * exception-cost.js -- what does constructing and discarding an exception cost
 * in V8, with no OpenSSL anywhere on the path?
 *
 * Node's failed createPublicKey() ends in ThrowCryptoError (src/crypto/
 * crypto_util.cc): v8::Exception::Error(message) -- a plain Error, which
 * captures a stack trace at construction -- then error::Decorate sets
 * `library`, `reason` and `code` (ERR_OSSL_...) on it, and the isolate throws
 * it through the createPublicKey() JS frame into the caller's catch. The
 * conditions below rebuild that object in JavaScript, at a comparable stack
 * depth, so its cost can be measured apart from the parse that precedes it.
 *
 * Same protocol as keypath-mechanism.js: ONE condition per process, the
 * runner interleaves conditions within rounds, analysis aggregates across
 * processes.
 *
 *   exc_plain            new Error(msg), thrown and caught in the same frame
 *   exc_node_like        Error with the OpenSSL message, library/reason/code
 *                        properties, thrown DEPTH frames below the catch
 *   exc_node_like_nostack  as exc_node_like with Error.stackTraceLimit = 0
 *   exc_node_internal    a Node-internal ERR_INVALID_ARG_TYPE from
 *                        crypto.createPublicKey(42): Node's own error class,
 *                        thrown from JS validation before any OpenSSL call
 *   probe_throws         crypto.createPublicKey(<hmac secret>), as in Table 1
 *   probe_throws_nostack probe_throws with Error.stackTraceLimit = 0
 *   timer_overhead       empty body
 *
 * Usage:
 *   node bench/exception-cost.js --condition exc_node_like \
 *        --iterations 40000 --warmup 20000 --invocation 1 --out run.csv
 */
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const args = { iterations: 40000, warmup: 20000, invocation: 0, out: null, condition: null,
               environment: 'host', depth: 8 };
for (let i = 2; i < process.argv.length; i += 2) {
  const k = process.argv[i].replace(/^--/, '');
  if (!(k in args)) { console.error(`unknown argument: ${process.argv[i]}`); process.exit(2); }
  args[k] = /^(iterations|warmup|invocation|depth)$/.test(k) ? Number(process.argv[i + 1]) : process.argv[i + 1];
}
if (!args.condition) { console.error('--condition is required'); process.exit(2); }

const HMAC_SECRET = 'your-super-secret-key-that-is-long';

// The message and properties Node attaches, captured from a real failure on
// THIS runtime rather than typed, so the string lengths match what V8 builds.
let REAL = null;
try { crypto.createPublicKey(HMAC_SECRET); } catch (e) { REAL = e; }
const MSG = REAL.message;
const PROPS = { library: REAL.library, reason: REAL.reason, code: REAL.code };

function makeNodeLike() {
  const e = new Error(MSG);
  e.library = PROPS.library;
  e.reason = PROPS.reason;
  e.code = PROPS.code;
  return e;
}
function throwAtDepth(d) {
  if (d <= 0) throw makeNodeLike();
  return throwAtDepth(d - 1) + 1; // not a tail call: keeps the frames live
}

const CONDITIONS = {
  exc_plain:            () => { try { throw new Error(MSG); } catch (_) { /* discarded */ } },
  exc_node_like:        () => { try { throwAtDepth(args.depth); } catch (_) { /* discarded */ } },
  exc_node_like_nostack: () => { try { throwAtDepth(args.depth); } catch (_) { /* discarded */ } },
  exc_node_internal:    () => { try { crypto.createPublicKey(42); } catch (_) { /* discarded */ } },
  probe_throws:         () => { try { crypto.createPublicKey(HMAC_SECRET); } catch (_) { /* discarded */ } },
  probe_throws_nostack: () => { try { crypto.createPublicKey(HMAC_SECRET); } catch (_) { /* discarded */ } },
  timer_overhead:       () => {},
};
const fn = CONDITIONS[args.condition];
if (!fn) { console.error(`unknown condition: ${args.condition}`); process.exit(2); }
if (/_nostack$/.test(args.condition)) Error.stackTraceLimit = 0;

for (let i = 0; i < args.warmup; i += 1) fn();
const samples = new Float64Array(args.iterations);
for (let i = 0; i < args.iterations; i += 1) {
  const t0 = process.hrtime.bigint();
  fn();
  samples[i] = Number(process.hrtime.bigint() - t0) / 1000;
}
let overhead = 0;
{
  const n = 20000, s = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const t0 = process.hrtime.bigint();
    s[i] = Number(process.hrtime.bigint() - t0) / 1000;
  }
  overhead = Array.from(s).sort((a, b) => a - b)[n >> 1];
}
const sorted = Array.from(samples).sort((a, b) => a - b);
const n = sorted.length;
const mean = sorted.reduce((p, c) => p + c, 0) / n;
const sd = Math.sqrt(sorted.reduce((p, c) => p + (c - mean) ** 2, 0) / (n - 1));
const q = (p) => sorted[Math.min(n - 1, Math.floor(n * p))];
const row = {
  environment: args.environment, condition: args.condition, invocation: args.invocation, n,
  mean_us: mean.toFixed(4), median_us: q(0.5).toFixed(4), p90_us: q(0.9).toFixed(4),
  p99_us: q(0.99).toFixed(4), min_us: sorted[0].toFixed(4), max_us: sorted[n - 1].toFixed(4),
  stddev_us: sd.toFixed(4), timer_overhead_us: overhead.toFixed(4), depth: args.depth,
  error_code: PROPS.code, node_version: process.version, openssl_version: process.versions.openssl,
  v8_version: process.versions.v8, platform: `${process.platform}/${process.arch}`,
};
const header = Object.keys(row).join(','), line = Object.values(row).join(',');
if (args.out) {
  const exists = fs.existsSync(args.out);
  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.appendFileSync(args.out, (exists ? '' : header + '\n') + line + '\n');
}
console.log(header); console.log(line);
