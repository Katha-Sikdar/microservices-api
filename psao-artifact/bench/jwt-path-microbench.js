#!/usr/bin/env node
'use strict';
/**
 * jwt-path-microbench.js — decompose jwt.verify() into measurable stages.
 *
 * WHY
 * ---
 * The manuscript attributes the per-request cost of application-layer JWT
 * validation to "signature verification". That attribution was never measured:
 * jwt.verify() also splits the compact serialisation, base64url-decodes two
 * segments, JSON.parses them, and runs claim validation. If most of the cost is
 * parsing rather than cryptography then the paper's central claim -- that
 * moving verification to the Envoy sidecar removes a cryptographic cost -- is
 * mis-stated, because the sidecar pays the parsing cost too.
 *
 * So we measure four stages independently, for HS256 and RS256, at three
 * payload sizes:
 *
 *   full_verify         jsonwebtoken.verify(): everything, as the service does it.
 *   decode_only         split on '.', base64url-decode header+payload, JSON.parse.
 *                       No signature check at all. This is the parsing floor.
 *   primitive_preparsed node:crypto performing the signature check over the real
 *                       JWT signing input ("<header>.<payload>"), with the key
 *                       already parsed into a KeyObject outside the loop. This
 *                       is the cryptographic cost as it would be paid by an
 *                       implementation that caches the key.
 *   primitive_raw       the same crypto primitive over a pre-allocated Buffer of
 *                       identical byte length. No JWT structure, no string ->
 *                       bytes conversion. This is the absolute floor of the
 *                       cryptographic operation.
 *
 * primitive_preparsed - primitive_raw therefore isolates signing-input assembly,
 * and full_verify - (decode_only + primitive_preparsed) isolates library
 * overhead (claim validation, option handling, allocation). figures/
 * fig_validation_path.py plots exactly that decomposition, and plots the
 * residual honestly, including when it comes out negative.
 *
 * No cluster, no HTTP, no cluster module: this runs on a laptop.
 *
 * Usage:
 *   node bench/jwt-path-microbench.js [--iterations 1000000] [--out path.csv]
 *                                     [--warmup 0.1] [--algorithms HS256,RS256]
 *                                     [--payload-kb 0.5,2,4]
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const jwt = require('jsonwebtoken');

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = {
    iterations: 1000000,
    out: null,
    warmup: 0.1,
    algorithms: ['HS256', 'RS256'],
    payloadKb: [0.5, 2, 4],
  };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      const v = argv[i + 1];
      if (v === undefined) throw new Error(`missing value for ${a}`);
      i += 1;
      return v;
    };
    switch (a) {
      case '--iterations': args.iterations = Number(next()); break;
      case '--out': args.out = next(); break;
      case '--warmup': args.warmup = Number(next()); break;
      case '--algorithms': args.algorithms = next().split(',').map((s) => s.trim()); break;
      case '--payload-kb': args.payloadKb = next().split(',').map(Number); break;
      case '-h':
      case '--help':
        process.stdout.write(fs.readFileSync(__filename, 'utf8').split('*/')[0]);
        process.exit(0);
        break;
      default:
        throw new Error(`unknown argument: ${a}`);
    }
  }
  if (!(args.iterations > 0)) throw new Error('--iterations must be positive');
  if (!(args.warmup >= 0 && args.warmup < 1)) throw new Error('--warmup must be in [0, 1)');
  return args;
}

function defaultOutPath() {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  return path.join(__dirname, '..', 'data', 'runs', stamp, 'microbench.csv');
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HS_SECRET = crypto.randomBytes(32); // 256-bit key, matching HS256.

// 2048 bits: the smallest modulus still considered acceptable for new
// deployments, and therefore the cheapest RS256 a reviewer would accept. A
// larger modulus only makes the RS256 column worse, so this is the conservative
// choice for the paper's argument.
const RSA = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const RSA_PRIVATE_PEM = RSA.privateKey.export({ type: 'pkcs8', format: 'pem' });
const RSA_PUBLIC_PEM = RSA.publicKey.export({ type: 'spki', format: 'pem' });
// Pre-parsed once, outside every timing loop: this is the whole point of the
// primitive_preparsed stage.
const RSA_PUBLIC_KEYOBJECT = crypto.createPublicKey(RSA_PUBLIC_PEM);
const HS_KEYOBJECT = crypto.createSecretKey(HS_SECRET);

/**
 * Build a token whose *encoded payload segment* is approximately `kb` kilobytes,
 * by padding a filler claim. We size the encoded segment rather than the JSON
 * because the encoded segment is what the base64 decoder and the signature
 * cover.
 */
function makeToken(algorithm, kb) {
  const targetBytes = Math.round(kb * 1024);
  const base = {
    sub: 'user456',
    name: 'Test User',
    iss: 'https://psao.example/issuer',
    aud: 'psao-testbed',
    scope: 'products:read',
  };
  let fill = 0;
  let token;
  // Converge on the target encoded size: base64 of the JSON is ~4/3 of the JSON
  // length, so we correct iteratively rather than solving it analytically.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const payload = { ...base, pad: 'x'.repeat(Math.max(0, fill)) };
    token = jwt.sign(payload, algorithm === 'HS256' ? HS_SECRET : RSA_PRIVATE_PEM, {
      algorithm,
      expiresIn: '1h',
    });
    const encodedPayloadLen = token.split('.')[1].length;
    const delta = targetBytes - encodedPayloadLen;
    if (Math.abs(delta) <= 2) break;
    fill += Math.max(1, Math.round(delta * 0.75)); // 3/4: inverse of base64 growth
    if (fill < 0) fill = 0;
  }
  return token;
}

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------

/**
 * Estimate the cost of the timing instrumentation itself. Two hrtime.bigint()
 * calls plus a Float64Array store cost order 50-100 ns; against a ~2 us
 * primitive that is a few percent, which a reader is entitled to know about. We
 * report it rather than subtracting it -- subtracting would be a correction the
 * paper cannot defend, and the raw numbers are the measurement.
 */
function measureTimerOverheadUs(samples) {
  const n = samples || 200000;
  const buf = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const t0 = process.hrtime.bigint();
    const t1 = process.hrtime.bigint();
    buf[i] = Number(t1 - t0) / 1000;
  }
  buf.sort();
  return buf[Math.floor(n * 0.5)];
}

function percentile(sortedUs, q) {
  if (sortedUs.length === 0) return NaN;
  // Nearest-rank; with >= 1e5 samples the choice of interpolation rule is far
  // below the run-to-run spread, and nearest-rank never invents a value that
  // was not observed.
  const idx = Math.min(sortedUs.length - 1, Math.max(0, Math.ceil(q * sortedUs.length) - 1));
  return sortedUs[idx];
}

/**
 * Time `fn` for `iterations`, discarding the first `warmup` fraction.
 * `sink` accumulates a value derived from each result so V8 cannot eliminate
 * the call as dead code.
 */
function timeStage(fn, iterations, warmupFraction) {
  const durations = new Float64Array(iterations);
  let sink = 0;

  // Explicit JIT warmup before the recorded loop, on top of the discarded
  // warmup fraction: the first few thousand calls run in the interpreter and
  // would otherwise dominate the p99.
  const jitIterations = Math.min(20000, Math.max(1000, Math.floor(iterations * 0.05)));
  for (let i = 0; i < jitIterations; i += 1) sink += fn(i) ? 1 : 0;

  for (let i = 0; i < iterations; i += 1) {
    const t0 = process.hrtime.bigint();
    const value = fn(i);
    const t1 = process.hrtime.bigint();
    durations[i] = Number(t1 - t0) / 1000; // microseconds
    sink += value ? 1 : 0;
  }

  const discard = Math.floor(iterations * warmupFraction);
  const kept = durations.subarray(discard);
  let total = 0;
  for (let i = 0; i < kept.length; i += 1) total += kept[i];
  const sorted = Float64Array.from(kept).sort();

  return {
    iterations: kept.length,
    mean_us: total / kept.length,
    p50_us: percentile(sorted, 0.5),
    p99_us: percentile(sorted, 0.99),
    sink,
  };
}

// ---------------------------------------------------------------------------
// Stages
// ---------------------------------------------------------------------------

function base64UrlDecodeToJson(segment) {
  return JSON.parse(Buffer.from(segment, 'base64url').toString('utf8'));
}

function buildStages(algorithm, token) {
  const key = algorithm === 'HS256' ? HS_SECRET : RSA_PUBLIC_PEM;
  const dot1 = token.indexOf('.');
  const dot2 = token.indexOf('.', dot1 + 1);
  const signingInput = token.slice(0, dot2);
  const signingInputBuf = Buffer.from(signingInput, 'ascii');
  const signatureBuf = Buffer.from(token.slice(dot2 + 1), 'base64url');
  // Same byte length as the real signing input, but no JWT structure: this is
  // what primitive_raw operates on.
  const rawBuf = crypto.randomBytes(signingInputBuf.length);

  // Pre-computed reference values so primitive_raw still does a real comparison
  // (a verification that always fails could take a different code path).
  const rawHmac = algorithm === 'HS256'
    ? crypto.createHmac('sha256', HS_KEYOBJECT).update(rawBuf).digest()
    : null;
  const rawSignature = algorithm === 'RS256'
    ? crypto.sign('RSA-SHA256', rawBuf, RSA.privateKey)
    : null;

  return {
    full_verify: () => {
      // Exactly what the service does in S4/S5/S6.
      const claims = jwt.verify(token, key, { algorithms: [algorithm] });
      return claims.sub.length > 0;
    },

    decode_only: () => {
      // Structural parsing with no signature check whatsoever.
      const header = base64UrlDecodeToJson(token.slice(0, dot1));
      const payload = base64UrlDecodeToJson(token.slice(dot1 + 1, dot2));
      return header.alg.length + payload.sub.length > 0;
    },

    primitive_preparsed: algorithm === 'HS256'
      ? () => {
        const mac = crypto.createHmac('sha256', HS_KEYOBJECT).update(signingInput).digest();
        return crypto.timingSafeEqual(mac, signatureBuf);
      }
      : () => crypto.verify('RSA-SHA256', signingInputBuf, RSA_PUBLIC_KEYOBJECT, signatureBuf),

    primitive_raw: algorithm === 'HS256'
      ? () => {
        const mac = crypto.createHmac('sha256', HS_KEYOBJECT).update(rawBuf).digest();
        return crypto.timingSafeEqual(mac, rawHmac);
      }
      : () => crypto.verify('RSA-SHA256', rawBuf, RSA_PUBLIC_KEYOBJECT, rawSignature),
  };
}

const STAGE_ORDER = ['full_verify', 'decode_only', 'primitive_preparsed', 'primitive_raw'];

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  const args = parseArgs(process.argv);
  const outPath = args.out || defaultOutPath();
  fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });

  const timerOverheadUs = measureTimerOverheadUs();
  console.log(`node ${process.version} | iterations=${args.iterations} `
    + `warmup=${args.warmup} | timer overhead (p50) = ${timerOverheadUs.toFixed(3)} us/sample`);
  console.log('This overhead is NOT subtracted from the reported figures.');
  console.log('');

  const rows = [];
  for (const algorithm of args.algorithms) {
    for (const kb of args.payloadKb) {
      const token = makeToken(algorithm, kb);
      const encodedPayloadKb = token.split('.')[1].length / 1024;
      const stages = buildStages(algorithm, token);
      for (const stage of STAGE_ORDER) {
        const r = timeStage(stages[stage], args.iterations, args.warmup);
        rows.push({
          algorithm,
          stage,
          payload_kb: kb,
          iterations: r.iterations,
          mean_us: r.mean_us,
          p50_us: r.p50_us,
          p99_us: r.p99_us,
        });
        console.log(
          `${algorithm.padEnd(6)} ${stage.padEnd(20)} `
          + `payload=${kb}KB (encoded ${encodedPayloadKb.toFixed(2)}KB) `
          + `n=${r.iterations} mean=${r.mean_us.toFixed(3)}us `
          + `p50=${r.p50_us.toFixed(3)}us p99=${r.p99_us.toFixed(3)}us`,
        );
      }
    }
  }

  const header = 'algorithm,stage,payload_kb,iterations,mean_us,p50_us,p99_us';
  const body = rows.map((r) => [
    r.algorithm, r.stage, r.payload_kb, r.iterations,
    r.mean_us.toFixed(6), r.p50_us.toFixed(6), r.p99_us.toFixed(6),
  ].join(','));
  fs.writeFileSync(outPath, `${[header].concat(body).join('\n')}\n`, 'utf8');
  console.log(`\nwrote ${rows.length} rows to ${outPath}`);
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error(`error: ${err.message}`);
    process.exit(1);
  }
}

module.exports = { makeToken, buildStages, timeStage, STAGE_ORDER };
