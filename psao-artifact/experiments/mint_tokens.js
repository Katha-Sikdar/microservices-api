/**
 * mint_tokens.js — regenerate the load-generator token pool.
 *
 * WHY THIS EXISTS
 * ---------------
 * tokens/pool.txt and tokens/hs256.token are inputs, not measurements, but they
 * EXPIRE. An expired pool does not fail loudly: service-a answers 403 for every
 * request, k6 records the 403s as fast responses, and the ramp produces a
 * plausible-looking latency curve for an error path. The first version of this
 * testbed had no minting script, so the pool silently aged out between sessions.
 * Re-mint before a measurement session and record the TTL in run_metadata.json.
 *
 * The tokens are NOT minted inside k6: goja has no HS256 that matches the
 * service's library, and a token minted per iteration would put signing cost in
 * the load generator and make every S8 request a cache miss. See k6/lib/auth.js.
 *
 * Usage:
 *   node experiments/mint_tokens.js [--count 64] [--ttl 24h] [--out-dir tokens]
 *       [--secret ...] [--alg HS256]
 *
 * The default secret is the one hard-coded in the testbed's service-a
 * (microservices-api/service-a/index.js). It is a testbed credential and is
 * already in that repository in clear; it is not a secret in any real sense.
 */
const fs = require('fs');
const path = require('path');
const jwt = require('jsonwebtoken');

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
}

const ISSUER = arg('issuer', '');
const AUDIENCE = arg('audience', '');
const KEYID = arg('kid', '');
const COUNT = Number(arg('count', 64));
const TTL = arg('ttl', '24h');
const ALG = arg('alg', 'HS256');
const SECRET = arg('secret', process.env.PSAO_JWT_SECRET
  || 'your-super-secret-key-that-is-long');
const OUT_DIR = path.resolve(arg('out-dir', path.join(__dirname, '..', 'tokens')));

if (!Number.isInteger(COUNT) || COUNT < 1) {
  console.error(`--count must be a positive integer, got ${arg('count', 64)}`);
  process.exit(1);
}

fs.mkdirSync(OUT_DIR, { recursive: true });

// One distinct sub per token. The pool size is what sets the S8 cache hit rate,
// so it is a parameter of the experiment and is echoed below for the metadata.
const tokens = [];
for (let i = 0; i < COUNT; i += 1) {
  // iss/aud are only added when asked for. The Istio RequestAuthentication the
  // controller applies REQUIRES both to match, so a pool minted without them is
  // rejected wholesale by the sidecar the moment the offload actuates -- while
  // the plain S4..S9 service ignores them entirely.
  const opts = { algorithm: ALG, expiresIn: TTL };
  if (ISSUER) opts.issuer = ISSUER;
  if (AUDIENCE) opts.audience = AUDIENCE;
  if (KEYID) opts.keyid = KEYID;
  tokens.push(jwt.sign({ sub: `user${i}`, name: `Load User ${i}` }, SECRET, opts));
}

const poolPath = path.join(OUT_DIR, 'pool.txt');
const singlePath = path.join(OUT_DIR, `${ALG.toLowerCase()}.token`);
fs.writeFileSync(poolPath, `${tokens.join('\n')}\n`);
fs.writeFileSync(singlePath, `${tokens[0]}\n`);

const { exp, iat } = jwt.decode(tokens[0]);
console.log(JSON.stringify({
  pool: poolPath,
  single: singlePath,
  count: COUNT,
  algorithm: ALG,
  ttl: TTL,
  issuer: ISSUER || null,
  audience: AUDIENCE || null,
  issued_at_utc: new Date(iat * 1000).toISOString(),
  expires_at_utc: new Date(exp * 1000).toISOString(),
}, null, 2));
