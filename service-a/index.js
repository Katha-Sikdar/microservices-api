// service-a — product endpoint, instrumented for PSAO.
//
// The PSAO controller and the open-loop ramp both read psao_* metrics from this
// process. eventloop-metrics.js is vendored from
// psao-artifact/instrumentation/eventloop-metrics.js so that the Docker build
// context (this directory) is self-contained; keep the two copies in sync.
//
// Metrics are served on a SEPARATE port (9464), not on 3000: port 3000 is the
// thing being saturated by the ramp, and scraping it would make the scrape
// compete with the load under test.
//
// ---------------------------------------------------------------------------
// WHY THERE IS AN AUTH MODE
// ---------------------------------------------------------------------------
// Scenarios S1-S3 are defined as the request path WITHOUT application-level JWT
// validation; S4-S9 are defined as the same path WITH it. The original testbed
// switched between the two by commenting the JWT block out of this file and
// rebuilding, which means S1-S3 and S4-S5 were measured on DIFFERENT IMAGES.
// Any difference in Express version, base image layer or build date then sits
// inside the very comparison the elbow figure is making.
//
// PSAO_AUTH_MODE removes that confound: one image, one build, one digest in
// run_metadata.json across every scenario, with the mode recorded per run.
//
//   PSAO_AUTH_MODE=jwt   (default)  verify a bearer token -- S4..S9
//   PSAO_AUTH_MODE=none              serve the payload unconditionally -- S1..S3
//
// The mode is resolved ONCE, at startup, and selects which handler is
// registered. It is deliberately not a branch inside the handler: a per-request
// `if` on a hot path that is being measured at millisecond resolution is
// exactly the kind of thing that ends up in a reviewer's question.

const express = require('express');
const jwt = require('jsonwebtoken');
const { createEventLoopMetrics } = require('./eventloop-metrics');

const app = express();
const port = Number(process.env.PORT || 3000);

// This secret key MUST match the one you use to create the token
const JWT_SECRET = process.env.JWT_SECRET || 'your-super-secret-key-that-is-long';

// ---------------------------------------------------------------------------
// ALGORITHM SELECTION
// ---------------------------------------------------------------------------
// PSAO_JWT_ALG picks the algorithm and, with it, the key material:
//
//   HS256 (default)  symmetric; verified with JWT_SECRET.
//   RS256            asymmetric; verified with the PUBLIC key only. The service
//                    never holds the private key -- that is the whole point of
//                    RS256 as the deployable offload path, and it is why the
//                    sidecar can be handed the same public key without widening
//                    the blast radius the way an inline `oct` JWKS does.
//
// Selected once at startup, like PSAO_AUTH_MODE, so the two algorithms differ by
// configuration rather than by a fork of this file. The verify histogram is
// labelled with whichever is in force (timeVerify's first argument), so an
// HS256 run and an RS256 run are distinguishable in the same Prometheus series.
//
// The public key is supplied as a PEM: PSAO_JWT_PUBLIC_KEY inline, or
// PSAO_JWT_PUBLIC_KEY_FILE as a path. A file is preferable in a real deployment
// (it keeps the key out of the process environment and lets Kubernetes rotate it
// as a mounted Secret); the inline form exists so a single `kubectl set env`
// can flip the service for a measurement.
const JWT_ALGORITHM = (process.env.PSAO_JWT_ALG || 'HS256').toUpperCase();
if (JWT_ALGORITHM !== 'HS256' && JWT_ALGORITHM !== 'RS256') {
  console.error(`PSAO_JWT_ALG must be 'HS256' or 'RS256', got '${JWT_ALGORITHM}'`);
  process.exit(1);
}

// Resolved once, outside the handler. jwt.verify() accepts a PEM string and
// re-parses it into a key object on EVERY call, which would put key parsing
// inside the measured verification cost and inflate RS256 by far more than the
// signature check itself. Pre-parsing with crypto.createPublicKey is what makes
// the RS256 figure a signature-verification measurement rather than a
// key-parsing one.
// PSAO_JWT_KEYFORM selects how the key is handed to jwt.verify():
//
//   preparsed (default)  a crypto KeyObject, parsed once at startup.
//   string               the raw secret / PEM string, re-parsed by the library
//                        on EVERY call. This is what the submitted paper's
//                        service did, and it is retained so the difference can
//                        be measured rather than argued about.
//
// It is not a stylistic choice. Measured in this container: 415 us per call with
// a string secret against 9.6 us with a pre-parsed KeyObject -- a 43x difference
// with identical cryptography, because jsonwebtoken converts the string to a key
// on every single invocation. Keep the default unless you are reproducing the
// original measurement.
const JWT_KEYFORM = (process.env.PSAO_JWT_KEYFORM || 'preparsed').toLowerCase();
if (JWT_KEYFORM !== 'preparsed' && JWT_KEYFORM !== 'string') {
  console.error(`PSAO_JWT_KEYFORM must be 'preparsed' or 'string', got '${JWT_KEYFORM}'`);
  process.exit(1);
}

let JWT_VERIFY_KEY = JWT_SECRET;
if (JWT_ALGORITHM === 'HS256' && JWT_KEYFORM === 'preparsed') {
  JWT_VERIFY_KEY = require('node:crypto').createSecretKey(Buffer.from(JWT_SECRET));
}
if (JWT_ALGORITHM === 'RS256') {
  const fs = require('node:fs');
  const crypto = require('node:crypto');
  const pem = process.env.PSAO_JWT_PUBLIC_KEY
    || (process.env.PSAO_JWT_PUBLIC_KEY_FILE
        && fs.readFileSync(process.env.PSAO_JWT_PUBLIC_KEY_FILE, 'utf8'));
  if (!pem) {
    console.error('PSAO_JWT_ALG=RS256 requires PSAO_JWT_PUBLIC_KEY or '
      + 'PSAO_JWT_PUBLIC_KEY_FILE (a PEM public key)');
    process.exit(1);
  }
  try {
    JWT_VERIFY_KEY = JWT_KEYFORM === 'string' ? pem : crypto.createPublicKey(pem);
  } catch (err) {
    console.error(`PSAO_JWT_PUBLIC_KEY is not a valid PEM public key: ${err.message}`);
    process.exit(1);
  }
}

// The header Istio's RequestAuthentication writes the VERIFIED claims into,
// via jwtRules[].outputPayloadToHeader. Its presence is what tells the handler
// that the sidecar has already checked the signature. See the block above
// productsWithJwt for why trusting it is safe here and what makes it unsafe.
const SIDECAR_PAYLOAD_HEADER =
  (process.env.PSAO_SIDECAR_PAYLOAD_HEADER || 'x-psao-jwt-payload').toLowerCase();

const AUTH_MODE = (process.env.PSAO_AUTH_MODE || 'jwt').toLowerCase();
if (AUTH_MODE !== 'jwt' && AUTH_MODE !== 'none') {
  console.error(`PSAO_AUTH_MODE must be 'jwt' or 'none', got '${AUTH_MODE}'`);
  process.exit(1);
}

const metrics = createEventLoopMetrics();

const products = [
  { id: 1, name: 'Laptop' },
  { id: 2, name: 'Keyboard' },
  { id: 3, name: 'Mouse' }
];

// Mounted before the routes so the duration histogram covers the whole handler.
app.use(metrics.middleware);

/**
 * S4..S9: the application-layer check, with PSAO's offload path.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS HANDLER TRUSTS A HEADER, AND WHEN THAT WOULD BE WRONG
 * ---------------------------------------------------------------------------
 * PSAO relocates *verification*; it does not remove it. When the controller
 * applies its RequestAuthentication, the sidecar verifies the JWT signature
 * before the request is ever proxied to this process, and writes the verified
 * claims into SIDECAR_PAYLOAD_HEADER. Repeating jwt.verify() here would mean
 * verification is DUPLICATED rather than MOVED -- the cost would stay on the
 * event loop and the entire premise of the experiment would be unmeasurable.
 * So when the header is present, this handler reads the claims and does not
 * re-check the signature.
 *
 * That is only sound because of two properties, and it is worth being explicit
 * that the security of this service now rests on them:
 *
 *   1. Envoy OVERWRITES this header on every request. A client that sends its
 *      own x-psao-jwt-payload cannot have it reach this process while the
 *      policy is applied -- the filter replaces it with the value derived from
 *      the token it verified, or removes it when there is no valid token. The
 *      AuthorizationPolicy the controller applies alongside
 *      (requestPrincipals: ["*"]) independently rejects any request that did
 *      not produce a verified principal.
 *
 *   2. Nothing else can reach port 3000. PeerAuthentication STRICT means the
 *      only traffic the application sees has come through its own sidecar. If
 *      mTLS were dropped to PERMISSIVE, or the pod were exposed directly, a
 *      client could reach this handler without traversing the filter and forge
 *      the header freely. **The mTLS posture is load-bearing for this code
 *      path, not merely for confidentiality.**
 *
 * If you take either property away, this branch becomes an authentication
 * bypass. experiments/set_mesh_posture.sh --verify checks both halves of
 * property 2, and is why it refuses to accept a 200 as evidence.
 *
 * The verification histogram labels the two paths differently ('HS256' vs
 * 'sidecar') so a trace shows the cost moving rather than merely shrinking.
 */
function productsWithJwt(req, res) {
  const forwarded = req.headers[SIDECAR_PAYLOAD_HEADER];

  if (forwarded) {
    // Offloaded: the sidecar has already established authenticity. All that is
    // left is reading the claims, which is a base64 decode and a JSON parse --
    // the work PSAO claims to leave behind on the event loop.
    try {
      metrics.timeVerify('sidecar', () =>
        JSON.parse(Buffer.from(forwarded, 'base64url').toString('utf8')));
    } catch (err) {
      // A malformed payload header means the sidecar is misconfigured, not that
      // the client is unauthorised. Fail closed rather than falling back to
      // local verification, which would silently hide the misconfiguration.
      return res.sendStatus(500);
    }
    return res.json(products);
  }

  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Format is "Bearer TOKEN"

  if (token == null) {
    return res.sendStatus(401); // 401 Unauthorized if no token is present
  }

  // Synchronous verify, wrapped in timeVerify so the verification call is timed
  // in isolation from the rest of the handler. The callback form would put the
  // call behind a continuation and make the isolated timing meaningless.
  try {
    metrics.timeVerify(JWT_ALGORITHM,
      () => jwt.verify(token, JWT_VERIFY_KEY, { algorithms: [JWT_ALGORITHM] }));
  } catch (err) {
    return res.sendStatus(403); // 403 Forbidden if token is invalid or expired
  }
  return res.json(products);
}

/**
 * S1..S3: no application-layer validation at all. Any Authorization header is
 * ignored rather than rejected, so a stray token in a load script cannot turn
 * this into a different measurement.
 */
function productsWithoutJwt(req, res) {
  return res.json(products);
}

app.get('/products', AUTH_MODE === 'jwt' ? productsWithJwt : productsWithoutJwt);

app.listen(port, () => {
  console.log(`service-a listening at http://localhost:${port} `
    + `(PSAO_AUTH_MODE=${AUTH_MODE}, alg=${JWT_ALGORITHM}, keyform=${JWT_KEYFORM}, `
    + `sidecar payload header=${SIDECAR_PAYLOAD_HEADER})`);
});

metrics.startMetricsServer();
