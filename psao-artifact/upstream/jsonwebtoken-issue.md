<!--
DRAFT — not filed. Target: https://github.com/auth0/node-jsonwebtoken/issues
Review before submitting. See the note at the bottom on whether this should go
through the security channel instead.
-->

**Title:** `verify()` with a string secret pays a failed `createPublicKey()` on every call (4x–52x overhead, HS*)

---

### Summary

When `secretOrPublicKey` is anything other than a `KeyObject`, `verify()` resolves
it by trying `createPublicKey()` **first** and falling back to `createSecretKey()`
in the `catch`. For an HMAC secret the first call can never succeed, so every
verification constructs and discards an OpenSSL parse failure.

The conversion this is a fallback for costs **0.69 µs**. The failed probe that
precedes it costs **17.6 µs** on Node 26 and **400 µs** on Node 18 — where it is
**97% of the entire `verify()` call**.

Passing a pre-parsed `KeyObject` avoids it entirely, so there is a clean
workaround; this is about the default path that the documented string-secret
usage takes.

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

`node v26.6.0, openssl 3.6.4, jsonwebtoken 9.0.3` (macOS arm64):

```
jwt.verify, string secret             29.51 us/call
jwt.verify, KeyObject secret           7.26 us/call
createPublicKey(secret) [throws]      17.60 us/call
createSecretKey(Buffer.from(s))        0.69 us/call
```

`node v18.20.8, openssl 3.0.16, jsonwebtoken 9.0.3` (node:18.20.8-alpine, same machine):

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
    secretOrPublicKey = createPublicKey(secretOrPublicKey);   // always throws for an HMAC secret
  } catch (_) {
    try {
      secretOrPublicKey = createSecretKey(/* ... */);
```

Independently confirmed by `node --cpu-prof` over 200k iterations, which attributes
self-time by frame with no differencing involved:

| runtime | `createPublicKey` self-time |
|---|---|
| node:18.20.8-alpine | **94.7%** |
| node:26.6.0-alpine | 57.9% |

### Why the magnitude varies so much

The probe's cost tracks the bundled OpenSSL, not Node or V8. Measured across four
container runtimes, 10 process invocations each, medians with bootstrap CIs:

| runtime | OpenSSL | V8 | failed probe |
|---|---|---|---|
| node:18.20.8-alpine | 3.0.16 | 10.2 | 373.79 µs [371.5, 375.8] |
| node:20-alpine | 3.0.19 | 11.3 | 420.62 µs [419.5, 422.6] |
| node:26.6.0-alpine | 3.5.7 | 14 | 22.94 µs [22.8, 23.3] |
| node:26.6.0-bookworm | 3.5.7 | 14 | 16.58 µs [16.4, 17.9] |

Node 18 and Node 20 are different V8 majors sharing the OpenSSL 3.0 series and
both pay ~400 µs; OpenSSL 3.5 pays ~20 µs. `createPublicKey` on a *valid* PEM moves
the same way (115.8 µs → 12.1 µs), so this looks like general OpenSSL 3.0 key-parsing
cost rather than anything specific to the error path.

Everything else in `verify()` is stable across all four runtimes — KeyObject verify
spans 1.26x, HMAC 1.47x, decode 1.70x. Only the probe spans 25x.

This matters because `node:18-alpine` is a very common base image, and the overhead
there is roughly 50x the actual verification.

### Suggested fix

Dispatch on `header.alg` before probing, so an `HS*` token with an ordinary string
secret goes straight to `createSecretKey()`.

### ⚠️ The obvious version of that fix is an authentication bypass

Worth stating explicitly, because it is not obvious and I nearly shipped it.

**The wasted probe is load-bearing security.** Given a service configured with an
RSA *public key* and an attacker-supplied `alg:HS256` token HMAC'd with that public
key, current `jsonwebtoken` rejects it — because `createPublicKey(pem)` **succeeds**,
yields a `KeyObject` of `type: 'public'`, and the check at
[L148](https://github.com/auth0/node-jsonwebtoken/blob/master/verify.js#L148)
refuses `HS*` against a non-secret key.

Skipping the probe whenever `alg` is `HS*` removes that defence. I built and tested
it: the forged token is **accepted**. (Pinning `algorithms` still defends, but the
bypass lands whenever a caller omits it.)

A safe narrowing is to take the fast path only when the secret is a string that
cannot be asymmetric key material:

```js
const symmetric = typeof header.alg === 'string' && header.alg.startsWith('HS')
  && typeof secretOrPublicKey === 'string'
  && secretOrPublicKey.indexOf('-----BEGIN') === -1
  && secretOrPublicKey.trim().charAt(0) !== '{';
```

Anything that could be PEM or JWK still takes the original path, so the confusion
defence is untouched. With that patch, `verify()` goes 29.51 µs → 7.21 µs — within
1.2 µs of full pre-parsing — and the confusion attack is still rejected, with all
legitimate HS256/RS256/KeyObject cases still passing.

I make no claim that this narrowing is exhaustive; that judgement is yours. My
point is narrower: **any fix here has to keep that rejection, and the natural
one does not.**

### Environment

- `jsonwebtoken` 9.0.3 (current latest)
- Node v18.20.8 / v20.20.2 / v26.6.0
- macOS 26.5 arm64 host; containers via Docker Desktop, arm64 only
- x86_64 not yet tested

### What I am not claiming

- Not a vulnerability in current code. Current behaviour is correct and safe; this
  is a performance report with a security constraint attached to the fix.
- Measured on one machine, arm64 only. The cross-runtime *ordering* is consistent
  and the effect sizes are large, but absolute figures are from one host.
- I have not benchmarked `sign()`, which has similar key-resolution logic.
- Happy to open a PR with the narrowing and the algorithm-confusion regression test
  if that is useful.

<!--
BEFORE FILING — judgement call for the author:

This discusses how an algorithm-confusion defence currently works and how a
plausible patch would break it. Current code is NOT vulnerable, so a public issue
is defensible and arguably protective: it pre-empts someone contributing the naive
"optimisation" as a performance PR.

If you would rather not reason about that in public, Auth0 has a responsible
disclosure programme and you could send the security half there first, keeping the
public issue to the performance finding alone.

Supporting data, all reproducible:
  data/runs/2026-09-17T08-42-17Z-keypath-mechanism/       host, 15 invocations
  data/runs/2026-09-17T08-57-13Z-keypath-runtime-matrix/  4 runtimes, 10 each
  bench/keypath-security-check.js                         the bypass demonstration
  bench/keypath-patch.js                                  both patches
-->
