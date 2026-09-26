/**
 * crosslib.js -- HS256 verification in three Node.js JWT libraries, with the
 * secret supplied as a string (or the rawest form the library accepts) and as
 * a pre-parsed key. Same protocol as bench/keypath-mechanism.js: ONE condition
 * per process; the runner interleaves; analysis aggregates across processes.
 *
 * What "string" means per library is the form its documentation shows for an
 * HMAC secret, used the way its API is meant to be used:
 *   jsonwebtoken  verify(token, 'secret', {algorithms:['HS256']})     per call
 *   fast-jwt      createVerifier({key:'secret', algorithms:['HS256']}) once,
 *                 then verifier(token) per call (its factory API)
 *   jose          jwtVerify(token, new TextEncoder().encode('secret'))  per call;
 *                 jose refuses a JS string for HS*, a Uint8Array is its rawest form
 * and "pre-parsed" is the same call with crypto.createSecretKey(...) (fast-jwt:
 * a Buffer, since it rejects KeyObject; jose:
 * a CryptoKey imported once).
 *
 * Usage: node crosslib.js --condition <lib>_<string|preparsed> [--iterations N]
 *        [--warmup N] [--invocation i] [--out file.csv] [--environment label]
 */
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const args = { iterations: 20000, warmup: 10000, invocation: 0, out: null, condition: null,
               environment: 'host' };
for (let i = 2; i < process.argv.length; i += 2) {
  const k = process.argv[i].replace(/^--/, '');
  if (!(k in args)) { console.error(`unknown argument: ${process.argv[i]}`); process.exit(2); }
  args[k] = /^(iterations|warmup|invocation)$/.test(k) ? Number(process.argv[i + 1]) : process.argv[i + 1];
}

const SECRET = 'your-super-secret-key-that-is-long';
const KEYOBJ = crypto.createSecretKey(Buffer.from(SECRET));
const CLAIMS = { sub: 'user0', name: 'Load User 0' };
const jsonwebtoken = require('jsonwebtoken');
const TOKEN = jsonwebtoken.sign(CLAIMS, SECRET, { algorithm: 'HS256', expiresIn: '24h' });
const pkgVersion = (n) => require(`${n}/package.json`).version;

async function build(cond) {
  const [lib, form] = cond.split('_');
  if (lib === 'jsonwebtoken') {
    const key = form === 'string' ? SECRET : KEYOBJ;
    return { sync: () => jsonwebtoken.verify(TOKEN, key, { algorithms: ['HS256'] }), version: pkgVersion('jsonwebtoken') };
  }
  if (lib === 'fastjwt') {
    const { createVerifier } = require('fast-jwt');
    // fast-jwt rejects a KeyObject; a Buffer is its pre-converted form. Either way
    // the key is resolved ONCE, at factory time, not per call.
    const v = createVerifier({ key: form === 'string' ? SECRET : Buffer.from(SECRET), algorithms: ['HS256'] });
    return { sync: () => v(TOKEN), version: pkgVersion('fast-jwt') };
  }
  if (lib === 'jose') {
    const jose = await import('jose');
    const bytes = new TextEncoder().encode(SECRET);
    const key = form === 'string' ? bytes
      : await crypto.webcrypto.subtle.importKey('raw', bytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
    return { async: () => jose.jwtVerify(TOKEN, key, { algorithms: ['HS256'] }), version: pkgVersion('jose') };
  }
  throw new Error(`unknown condition ${cond}`);
}

(async () => {
  const b = await build(args.condition);
  const out = b.sync ? b.sync() : await b.async();
  const payload = out.payload || out;
  if (payload.sub !== 'user0') throw new Error('verification returned the wrong payload');
  const samples = new Float64Array(args.iterations);
  if (b.sync) {
    for (let i = 0; i < args.warmup; i += 1) b.sync();
    for (let i = 0; i < args.iterations; i += 1) {
      const t0 = process.hrtime.bigint(); b.sync();
      samples[i] = Number(process.hrtime.bigint() - t0) / 1000;
    }
  } else {
    for (let i = 0; i < args.warmup; i += 1) await b.async();
    for (let i = 0; i < args.iterations; i += 1) {
      const t0 = process.hrtime.bigint(); await b.async();
      samples[i] = Number(process.hrtime.bigint() - t0) / 1000;
    }
  }
  const sorted = Array.from(samples).sort((a, c) => a - c);
  const n = sorted.length, q = (p) => sorted[Math.min(n - 1, Math.floor(n * p))];
  const mean = sorted.reduce((p, c) => p + c, 0) / n;
  const row = {
    environment: args.environment, language: 'JavaScript', library: args.condition.split('_')[0],
    library_version: b.version, condition: args.condition, form: args.condition.split('_')[1],
    invocation: args.invocation, n, mean_us: mean.toFixed(4), median_us: q(0.5).toFixed(4),
    p90_us: q(0.9).toFixed(4), p99_us: q(0.99).toFixed(4),
    runtime: `node ${process.version}`, crypto_backend: `openssl ${process.versions.openssl}`,
    platform: `${process.platform}/${process.arch}`,
  };
  const header = Object.keys(row).join(','), line = Object.values(row).join(',');
  if (args.out) {
    const exists = fs.existsSync(args.out);
    fs.mkdirSync(path.dirname(args.out), { recursive: true });
    fs.appendFileSync(args.out, (exists ? '' : header + '\n') + line + '\n');
  }
  console.log(line);
})().catch((e) => { console.error(e); process.exit(1); });
