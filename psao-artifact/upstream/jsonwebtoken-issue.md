<!-- FILED 2026-09-17 as https://github.com/auth0/node-jsonwebtoken/issues/1046
     This file is the text as submitted. Edit only to track upstream replies. -->

**Title:** `verify()` resolves a string secret by attempting `createPublicKey()` first, costing 4x–52x on the HS* path

---

### Summary

When `secretOrPublicKey` is not already a `KeyObject`, `verify()` resolves it by
calling `createPublicKey()` first and falling back to `createSecretKey()` in the
`catch`. For an HMAC string secret the first call cannot succeed, so every
verification constructs and discards an OpenSSL parse failure.

The conversion it falls back to costs **0.69 µs**. The attempt that precedes it
costs **17.6 µs** on Node 26 and **400 µs** on Node 18, where it is **97% of the
entire `verify()` call**.

Passing a pre-parsed `KeyObject` avoids this completely, so there is a clean
workaround. This report is about the cost on the documented string-secret path.

### Reproduction

```js
const crypto = require('crypto');
const jwt = require('jsonwebtoken');

const SECRET = 'a-shared-secret-of-reasonable-length';
const KEYOBJ = crypto.createSecretKey(Buffer.from(SECRET));
const token = jwt.sign({ sub: 'u' }, SECRET, { algorithm: 'HS256', expiresIn: '1h' });
const N = 20000;

function bench(label, fn) {
  for (let i = 0; i < N; i++) fn();                     // warm
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < N; i++) fn();
  console.log(label.padEnd(34),
    (Number(process.hrtime.bigint() - t0) / 1000 / N).toFixed(2).padStart(8), 'us/call');
}

bench('jwt.verify, string secret',        () => jwt.verify(token, SECRET, { algorithms: ['HS256'] }));
bench('jwt.verify, KeyObject secret',     () => jwt.verify(token, KEYOBJ, { algorithms: ['HS256'] }));
bench('createPublicKey(secret) [throws]', () => { try { crypto.createPublicKey(SECRET); } catch (_) {} });
bench('createSecretKey(Buffer.from(s))',  () => crypto.createSecretKey(Buffer.from(SECRET)));
```

`node v26.6.0, openssl 3.6.4, jsonwebtoken 9.0.3` — macOS arm64:

```
jwt.verify, string secret             29.51 us/call
jwt.verify, KeyObject secret           7.26 us/call
createPublicKey(secret) [throws]      17.60 us/call
createSecretKey(Buffer.from(s))        0.69 us/call
```

`node v18.20.8, openssl 3.0.16, jsonwebtoken 9.0.3` — `node:18.20.8-alpine`, same machine:

```
jwt.verify, string secret            412.18 us/call
jwt.verify, KeyObject secret           7.86 us/call
createPublicKey(secret) [throws]     400.85 us/call
createSecretKey(Buffer.from(s))        1.73 us/call
```

### Root cause

[`verify.js` L120–127](https://github.com/auth0/node-jsonwebtoken/blob/master/verify.js#L120-L127):

```js
if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
  try {
    secretOrPublicKey = createPublicKey(secretOrPublicKey);   // cannot succeed for an HMAC secret
  } catch (_) {
    try {
      secretOrPublicKey = createSecretKey(/* ... */);
```

Confirmed independently with `node --cpu-prof` over 200k iterations, which
attributes self-time per frame with no differencing involved:

| runtime | `createPublicKey` self-time |
|---|---|
| `node:18.20.8-alpine` | **94.7%** |
| `node:26.6.0-alpine` | 57.9% |

### Why the magnitude varies so widely

The cost tracks the bundled OpenSSL rather than Node or V8. Four container
runtimes, 10 process invocations each, medians with bootstrap 95% CIs:

| runtime | OpenSSL | V8 | failed attempt |
|---|---|---|---|
| `node:18.20.8-alpine` | 3.0.16 | 10.2 | 373.79 µs [371.5, 375.8] |
| `node:20-alpine` | 3.0.19 | 11.3 | 420.62 µs [419.5, 422.6] |
| `node:26.6.0-alpine` | 3.5.7 | 14 | 22.94 µs [22.8, 23.3] |
| `node:26.6.0-bookworm` | 3.5.7 | 14 | 16.58 µs [16.4, 17.9] |

Node 18 and Node 20 are different V8 majors sharing the OpenSSL 3.0 series and
both pay ~400 µs; OpenSSL 3.5 pays ~20 µs. `createPublicKey()` on a *valid* PEM
moves the same way (115.8 µs → 12.1 µs), so this looks like general OpenSSL 3.0
key-parsing cost rather than anything specific to the failure path.

Everything else in `verify()` is stable across all four: `KeyObject` verify spans
1.26x, HMAC 1.47x, decode 1.70x. Only this attempt spans 25x.

`node:18-alpine` remains a very common base image, and the overhead there is
roughly 50x the cost of the verification itself.

### Proposed patch

Resolve a plain string secret directly when the token's `alg` is `HS*`:

```diff
     if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
-      try {
-        secretOrPublicKey = createPublicKey(secretOrPublicKey);
-      } catch (_) {
-        try {
-          secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
+      var isPlainStringSecret = typeof secretOrPublicKey === 'string'
+        && secretOrPublicKey.indexOf('-----BEGIN') === -1
+        && secretOrPublicKey.trim().charAt(0) !== '{';
+
+      if (typeof header.alg === 'string' && header.alg.startsWith('HS') && isPlainStringSecret) {
+        try {
+          secretOrPublicKey = createSecretKey(Buffer.from(secretOrPublicKey));
         } catch (_) {
           return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
         }
+      } else {
+        try {
+          secretOrPublicKey = createPublicKey(secretOrPublicKey);
+        } catch (_) {
+          try {
+            secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
+          } catch (_) {
+            return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
+          }
+        }
       }
     }
```

With this applied, `verify()` goes **29.51 µs → 7.21 µs** on Node 26 — within
1.2 µs of passing a `KeyObject` directly — with no change required in calling code.

### A constraint on any fix here

The attempt is not purely wasteful, and I think this is the important part of the
report.

`createPublicKey()` *succeeding* on asymmetric key material is what produces a
`KeyObject` whose `type` the algorithm/key-type check at
[L148](https://github.com/auth0/node-jsonwebtoken/blob/master/verify.js#L148)
depends on. Any change that dispatches on `header.alg` while relaxing what the
key material may be would alter which inputs reach that check, and the check is
what keeps symmetric and asymmetric material from being interchanged.

That is why the guard above is narrow rather than simply `alg.startsWith('HS')`:
the fast path is restricted to string secrets that cannot be PEM or JWK, so
anything that might be asymmetric still resolves exactly as it does today.

I verified that this narrowing preserves the check, and that a variant without
the material restriction does not. I would rather not spell out the second half
in a public issue — happy to share the detail privately if it helps review.

### Tests

Four assertions, in the project's mocha/chai style, covering both the invariant
and the absence of regression. They pass against `master` and against the patch,
and the first fails against a version of the patch lacking the material
restriction — so it constrains the change rather than merely describing it.

I expect the existing suite already covers key-type confusion; if so, the useful
contribution may be to confirm those tests still pass rather than to add new
ones. Happy either way.

### Environment

- `jsonwebtoken` 9.0.3 (current latest, published 2026-07-08)
- Node v18.20.8 / v20.20.2 / v26.6.0
- macOS 26.5 arm64 host; containers via Docker Desktop, **arm64 only**
- x86_64 not yet tested

### What I am not claiming

- **Not a vulnerability.** Current behaviour is correct. This is a performance
  report, with a note about what a fix must preserve.
- One machine, one architecture. The cross-runtime ordering is consistent and
  the effect sizes are large, but absolute figures come from a single host.
- `sign()` has similar key-resolution logic; I have not benchmarked it.
- Glad to open a PR with the patch and tests if that would be useful.
