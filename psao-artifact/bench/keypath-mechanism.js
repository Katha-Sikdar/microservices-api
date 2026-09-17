/**
 * keypath-mechanism.js -- what does a string key actually cost, and why?
 *
 * Runs EXACTLY ONE condition per process invocation. That is the point of the
 * file. Measuring every condition inside one process lets the first condition's
 * compilation, inline caches and heap layout follow the later ones, and reports
 * a single sample as though it were a population. The runner invokes this once
 * per (condition, round) and analysis/keypath_stats.py aggregates ACROSS
 * invocations, so the reported interval covers between-process variation rather
 * than only within-loop variation.
 *
 * Conditions decompose jwt.verify() on the string-key path:
 *
 *   jwt_hs_string        stock jsonwebtoken, HS256, string secret  <- what services do
 *   jwt_hs_preparsed     stock, HS256, KeyObject                   <- the recommended form
 *   jwt_hs_string_safe   safe-patched library, HS256, string secret
 *   jwt_rs_pem_string    stock, RS256, PEM string (probe SUCCEEDS)
 *   jwt_rs_preparsed     stock, RS256, KeyObject
 *   probe_throws         createPublicKey(hmac secret), which throws
 *   probe_succeeds       createPublicKey(rsa pem), which does not
 *   create_secret_key    createSecretKey(Buffer.from(secret))
 *   hmac_string          createHmac('sha256', string) -> digest
 *   hmac_keyobject       createHmac('sha256', KeyObject) -> digest
 *   decode_only          structural decode, no signature check
 *   timer_overhead       empty body: the floor this clock can resolve
 *
 * Usage:
 *   node bench/keypath-mechanism.js --condition jwt_hs_string \
 *        --iterations 40000 --warmup 20000 --invocation 1 --out run.csv
 */
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const patch = require('./keypath-patch.js');

const args = { iterations: 40000, warmup: 20000, invocation: 0, out: null, condition: null };
for (let i = 2; i < process.argv.length; i += 2) {
  const k = process.argv[i].replace(/^--/, '');
  if (!(k in args)) { console.error(`unknown argument: ${process.argv[i]}`); process.exit(2); }
  args[k] = /^(iterations|warmup|invocation)$/.test(k) ? Number(process.argv[i + 1]) : process.argv[i + 1];
}
if (!args.condition) { console.error('--condition is required'); process.exit(2); }

// --- fixtures, all built outside every timing loop ---------------------------
const jwtStock = require(patch.PKG);
const HMAC_SECRET = 'your-super-secret-key-that-is-long';
const HMAC_KEYOBJECT = crypto.createSecretKey(Buffer.from(HMAC_SECRET));
const RSA = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const RSA_PUBLIC_PEM = RSA.publicKey.export({ type: 'spki', format: 'pem' });
const RSA_PUBLIC_KEYOBJECT = crypto.createPublicKey(RSA_PUBLIC_PEM);
const CLAIMS = { sub: 'user0', name: 'Load User 0' };
const HS_TOKEN = jwtStock.sign(CLAIMS, HMAC_SECRET, { algorithm: 'HS256', expiresIn: '24h' });
const RS_TOKEN = jwtStock.sign(CLAIMS, RSA.privateKey, { algorithm: 'RS256', expiresIn: '24h' });
const SIGNING_INPUT = Buffer.from(HS_TOKEN.slice(0, HS_TOKEN.lastIndexOf('.')), 'ascii');
const DOT1 = HS_TOKEN.indexOf('.');
const DOT2 = HS_TOKEN.indexOf('.', DOT1 + 1);

// Patched libraries are built lazily: an invocation measuring a stock condition
// must not pay to construct them, and must not have them in its module graph.
let jwtSafe = null;
const safeLib = () => (jwtSafe || (jwtSafe = require(patch.build('safe'))));

const CONDITIONS = {
  jwt_hs_string:      () => jwtStock.verify(HS_TOKEN, HMAC_SECRET,      { algorithms: ['HS256'] }),
  jwt_hs_preparsed:   () => jwtStock.verify(HS_TOKEN, HMAC_KEYOBJECT,   { algorithms: ['HS256'] }),
  jwt_hs_string_safe: null, // installed below, after the library is built
  jwt_rs_pem_string:  () => jwtStock.verify(RS_TOKEN, RSA_PUBLIC_PEM,       { algorithms: ['RS256'] }),
  jwt_rs_preparsed:   () => jwtStock.verify(RS_TOKEN, RSA_PUBLIC_KEYOBJECT, { algorithms: ['RS256'] }),
  probe_throws:       () => { try { crypto.createPublicKey(HMAC_SECRET); } catch (_) { /* the discarded failure */ } },
  probe_succeeds:     () => crypto.createPublicKey(RSA_PUBLIC_PEM),
  create_secret_key:  () => crypto.createSecretKey(Buffer.from(HMAC_SECRET)),
  hmac_string:        () => crypto.createHmac('sha256', HMAC_SECRET).update(SIGNING_INPUT).digest(),
  hmac_keyobject:     () => crypto.createHmac('sha256', HMAC_KEYOBJECT).update(SIGNING_INPUT).digest(),
  decode_only:        () => {
    const h = JSON.parse(Buffer.from(HS_TOKEN.slice(0, DOT1), 'base64url').toString('utf8'));
    const p = JSON.parse(Buffer.from(HS_TOKEN.slice(DOT1 + 1, DOT2), 'base64url').toString('utf8'));
    return h.alg.length + p.sub.length;
  },
  timer_overhead:     () => {},
};

if (args.condition === 'jwt_hs_string_safe') {
  const lib = safeLib();
  CONDITIONS.jwt_hs_string_safe = () => lib.verify(HS_TOKEN, HMAC_SECRET, { algorithms: ['HS256'] });
}

const fn = CONDITIONS[args.condition];
if (!fn) { console.error(`unknown condition: ${args.condition}`); process.exit(2); }

// --- measure -----------------------------------------------------------------
for (let i = 0; i < args.warmup; i += 1) fn();

const samples = new Float64Array(args.iterations);
for (let i = 0; i < args.iterations; i += 1) {
  const t0 = process.hrtime.bigint();
  fn();
  samples[i] = Number(process.hrtime.bigint() - t0) / 1000;
}

// The clock's own cost, measured in this same process so it can be compared
// against the condition rather than assumed negligible. Never subtracted here:
// subtraction belongs in analysis, where it is visible.
let overhead = 0;
{
  const n = 20000, s = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const t0 = process.hrtime.bigint();
    s[i] = Number(process.hrtime.bigint() - t0) / 1000;
  }
  const sorted = Array.from(s).sort((a, b) => a - b);
  overhead = sorted[n >> 1];
}

const sorted = Array.from(samples).sort((a, b) => a - b);
const n = sorted.length;
const mean = sorted.reduce((p, c) => p + c, 0) / n;
const sd = Math.sqrt(sorted.reduce((p, c) => p + (c - mean) ** 2, 0) / (n - 1));
const q = (p) => sorted[Math.min(n - 1, Math.floor(n * p))];

const row = {
  condition: args.condition,
  invocation: args.invocation,
  n,
  mean_us: mean.toFixed(4),
  median_us: q(0.5).toFixed(4),
  p90_us: q(0.9).toFixed(4),
  p99_us: q(0.99).toFixed(4),
  min_us: sorted[0].toFixed(4),
  max_us: sorted[n - 1].toFixed(4),
  stddev_us: sd.toFixed(4),
  timer_overhead_us: overhead.toFixed(4),
  node_version: process.version,
  platform: `${process.platform}/${process.arch}`,
};

const header = Object.keys(row).join(',');
const line = Object.values(row).join(',');
if (args.out) {
  const exists = fs.existsSync(args.out);
  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.appendFileSync(args.out, (exists ? '' : header + '\n') + line + '\n');
}
console.log(header);
console.log(line);
